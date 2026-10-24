import ast
import io
import json
import pprint
import subprocess
import sys
import tokenize
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from backend.models import Spec
from backend.models.generation import GenerationOptions
from backend.security.ssrf import validate_url

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


def format_code(code):
    # Split long literal strings before Ruff; user values are never executable syntax.
    for token in reversed(list(tokenize.generate_tokens(io.StringIO(code).readline))):
        if token.type == tokenize.STRING and token.start[0] == token.end[0]:
            try:
                value = ast.literal_eval(token.string)
            except (ValueError, SyntaxError):
                continue
            if isinstance(value, str) and len(token.string) > 65:
                lines = code.splitlines(keepends=True)
                replacement = (
                    "(\n"
                    + "\n".join(repr(value[i : i + 55]) for i in range(0, len(value), 55))
                    + "\n)"
                )
                line = lines[token.start[0] - 1]
                lines[token.start[0] - 1] = (
                    line[: token.start[1]] + replacement + line[token.end[1] :]
                )
                code = "".join(lines)
    for arguments in (["check", "--select", "I,F401", "--fix", "--exit-zero"], ["format"]):
        result = subprocess.run(
            [sys.executable, "-m", "ruff", *arguments, "--stdin-filename", "generated.py", "-"],
            input=code,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode:
            raise ValueError("Generated code formatting failed")
        code = result.stdout
    ast.parse(code)
    return code


def sample_preview(sample, record_path):
    """Match generated dotted-key flattening on a small recorded sample."""
    records = sample
    if record_path:
        for part in record_path.split("."):
            if isinstance(records, dict):
                records = records.get(part)
            elif isinstance(records, list) and part.isdigit():
                index = int(part)
                records = records[index] if index < len(records) else None
            else:
                return None
    records = records if isinstance(records, list) else [records]

    def flatten(value, prefix="", output=None):
        output = {} if output is None else output
        if isinstance(value, dict):
            for key, item in value.items():
                flatten(item, f"{prefix}.{key}" if prefix else str(key), output)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                flatten(item, f"{prefix}.{index}" if prefix else str(index), output)
        else:
            output[prefix or "value"] = value
        return output

    return "\n".join(json.dumps(flatten(row), ensure_ascii=False) for row in records[:3])


class Generator:
    def render(self, spec: Spec, options: GenerationOptions, profile=None):
        spec = Spec.model_validate(spec.model_dump())
        if options.endpoint >= len(spec.endpoints):
            raise ValueError("Select an existing endpoint")
        endpoint = spec.endpoints[options.endpoint]
        dates = endpoint.date_params
        if endpoint.method != "GET" or spec.auth.type == "unsupported":
            raise ValueError("Generation supports GET with no auth, API key or bearer only")
        validate_url(str(spec.base_url))
        if endpoint.path.startswith("//") or any(
            c in endpoint.path for c in ("\\", "?", "#", "\r", "\n")
        ):
            raise ValueError("Unsafe endpoint path")
        if options.mode == "backfill" and not dates:
            raise ValueError("Backfill requires documented date parameters")
        if options.mode == "backfill" and options.start_date is None:
            raise ValueError("Choose a start date for backfill")
        if options.start_date and options.end_date and options.end_date < options.start_date:
            raise ValueError("End date must be on or after start date")
        flatten = options.flatten
        if flatten and (profile is None or not profile.nested):
            raise ValueError("Flattening is offered only for a profiled nested response")
        if (
            endpoint.pagination
            and endpoint.pagination.type == "cursor"
            and not options.cursor_next_path
        ):
            raise ValueError("Supply the documented response cursor path; it is never guessed")
        params, path_params, headers = {}, {}, dict(spec.default_headers)
        if any(key.lower() not in {"accept", "content-type", "user-agent"} for key in headers):
            raise ValueError("Credential headers must use the authentication env variable")
        names = {p.name for p in endpoint.params}
        if options.params.keys() - names:
            raise ValueError("An input parameter is not declared by this specification")
        secret_names = {spec.auth.header_name, spec.auth.query_name, "Authorization"} - {None}
        if secret_names.intersection(options.params):
            raise ValueError("Supply API credentials through environment variables only")
        path = endpoint.path
        snippet_dates = {}
        if dates:
            if options.mode == "backfill" and options.start_date:
                for name, value in [
                    (dates.start, options.start_date),
                    (dates.end, options.end_date or options.start_date),
                ]:
                    if name:
                        dt = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
                        if name == dates.end and dates.format in {"unix", "unix_ms"}:
                            dt += timedelta(days=1) - timedelta(seconds=1)
                        snippet_dates[name] = (
                            int(dt.timestamp()) * (1000 if dates.format == "unix_ms" else 1)
                            if dates.format in {"unix", "unix_ms"}
                            else dt.strftime(dates.strftime or "%Y-%m-%d")
                        )
        for param in endpoint.params:
            if param.name in secret_names:
                continue
            value = options.params.get(param.name)
            if param.name in snippet_dates and options.mode in {
                "backfill",
                "daily",
                "full_ingestion",
            }:
                value = snippet_dates[param.name]
            elif value is None and param.required:
                value = param.default
            if value is None and param.required and dates and param.name in {
                dates.start,
                dates.end,
            }:
                today = datetime.combine(datetime.now(UTC).date(), datetime.min.time(), tzinfo=UTC)
                if param.name == dates.end and dates.format in {"unix", "unix_ms"}:
                    today += timedelta(days=1) - timedelta(seconds=1)
                value = (
                    int(today.timestamp()) * (1000 if dates.format == "unix_ms" else 1)
                    if dates.format in {"unix", "unix_ms"}
                    else today.strftime(dates.strftime or "%Y-%m-%d")
                )
            if value is None and param.required:
                raise ValueError(f"Supply required parameter: {param.name}")
            if value is None:
                continue
            if param.allowed_values and value not in param.allowed_values:
                raise ValueError(f"Parameter outside its documented allowed values: {param.name}")
            if param.location == "path":
                path_params[param.name] = value
                path = path.replace("{" + param.name + "}", quote(str(value), safe=""))
            elif param.location == "header":
                raise ValueError(
                    "Custom header parameters need an explicit reviewed header configuration"
                )
            elif param.location == "body":
                raise ValueError("GET body parameters are unsupported")
            else:
                params[param.name] = value
        if "{" in path or "}" in path:
            raise ValueError("Fill every required path parameter")
        chunk_days = min(options.chunk_days, endpoint.max_range_days or options.chunk_days)
        if options.full_ingestion and options.mode in {"daily", "full_ingestion"}:
            if not options.bucket_name:
                raise ValueError("Enter an S3 bucket name for full S3 ingestion")
            if not options.table_name:
                raise ValueError("Enter a table name for full S3 ingestion")
        if options.mode == "full_ingestion" and not options.bucket_name:
            raise ValueError("Enter an S3 bucket name for full S3 ingestion")
        if options.mode == "full_ingestion" and not options.table_name:
            raise ValueError("Enter a table name for full S3 ingestion")
        if options.mode == "full_ingestion" and options.run_target == "airflow":
            raise ValueError("Use Daily with Airflow to generate a scheduled S3 task")
        env = Environment(
            loader=FileSystemLoader(TEMPLATES),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )
        env.filters["py"] = lambda value: pprint.pformat(value, width=70, sort_dicts=True)
        mode_template = options.mode
        if options.mode == "full_ingestion":
            mode_template = "full_ingestion_local"
        if options.mode == "backfill":
            if options.run_target != "local":
                raise ValueError("Backfill is generated for local Python only")
            mode_template = "backfill_s3" if options.full_ingestion else "backfill"
        if options.mode == "daily":
            mode_template = "daily_s3" if options.full_ingestion else "daily"
        if options.mode == "daily" and options.run_target == "airflow":
            mode_template = "daily_airflow_s3" if options.full_ingestion else "daily_airflow"
        code = env.get_template(mode_template + ".py.j2").render(
            spec=spec,
            endpoint=endpoint,
            options=options,
            flatten=flatten,
            full=options.full_ingestion or options.mode == "full_ingestion",
            output_format=options.output_format,
            run_target=options.run_target,
            bucket_name=options.bucket_name,
            main_folder=options.main_folder,
            table_name=options.table_name or spec.name,
            base_url=str(spec.base_url).rstrip("/"),
            source_url=str(endpoint.source_url),
            url=str(spec.base_url).rstrip("/") + path,
            headers=headers,
            params=params,
            snippet_params=params,
            path_params=path_params,
            record_path=endpoint.record_path or (profile.record_path if profile else None),
            pagination=endpoint.pagination.model_dump() if endpoint.pagination else None,
            date_params=dates.model_dump() if dates else None,
            chunk_days=chunk_days,
            interval=spec.rate_limit.per_seconds / spec.rate_limit.requests
            if spec.rate_limit
            else 0,
        )
        return format_code(code)

    async def run(self, ctx, spec, options, profile=None):
        async with ctx.step("generator", "Render deterministic Python code") as progress:
            code = self.render(spec, options, profile)
            progress("Validated template fields and Python syntax; zero LLM calls")
            return code
