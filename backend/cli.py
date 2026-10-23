import argparse
import asyncio
import json
import os

from backend.cache.store import Store
from backend.models.research import ResearchRequest
from backend.orchestrator.research import ResearchPipeline
from backend.settings import effective_settings, public_settings


def main():
    parser = argparse.ArgumentParser(description="Research a REST API using the app settings layer")
    parser.add_argument("url")
    parser.add_argument("--demo", action="store_true", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--api-key-env", help="Optional target-API credential variable (not an LLM key)"
    )
    parser.add_argument(
        "--api-key-host", help="Explicit hostname authorized for the target API key"
    )
    args = parser.parse_args()
    if args.api_key_env and (
        not args.api_key_host
        or args.api_key_env.startswith(("LLM_", "OPENAI_", "ANTHROPIC_", "CODEX_"))
    ):
        parser.error(
            "Target API credentials require an explicit "
            "host and cannot reuse provider credential variables"
        )
    store = Store(os.getenv("DATABASE_PATH", "data/app.sqlite3"))
    request = ResearchRequest(
        url=args.url,
        force=args.force,
        demo=args.demo,
        api_key=os.getenv(args.api_key_env) if args.api_key_env else None,
        api_key_host=args.api_key_host,
    )
    result = asyncio.run(ResearchPipeline(store).run(request))
    print(
        json.dumps(
            {
                "job_id": result.job.id,
                "status": result.status,
                "cache_hit": result.cache_hit,
                "usage": result.job.model_dump(mode="json"),
                "usage_label": public_settings(effective_settings(store))["usage_label"],
                "warnings": result.warnings,
            },
            indent=2,
        )
    )
    return 1 if result.status in {"error", "budget_blocked"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
