"""Bounded offline comparison. Never executes generated/LLM Python."""

import asyncio
import json
import sys

from backend.converter.compiler import identifier, parse, plan


async def verify(request):
    if len(request.tables) > 5 or any(len(rows) > 100 for rows in request.tables.values()):
        raise ValueError("Verification allows five tables with at most 100 rows each")
    if any(len(row) > 30 for rows in request.tables.values() for row in rows):
        raise ValueError("Verification allows at most 30 columns")
    for name in request.tables:
        identifier(name)
    compiled = plan(parse(request.sql, request.dialect))
    payload = json.dumps(
        {"sql": request.sql, "dialect": request.dialect, "plan": compiled, "tables": request.tables}
    )
    if len(payload) > 100000:
        raise ValueError("Verification sample is too large")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "backend.converter.verify_worker",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(payload.encode()), timeout=10)
        if process.returncode or len(stdout) > 20000:
            raise ValueError("Verification failed; check sample column names and types")
        return json.loads(stdout)
    except TimeoutError:
        raise ValueError("Verification timed out") from None
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
