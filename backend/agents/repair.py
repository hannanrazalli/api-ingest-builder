import json

from backend.agents.extractor import to_spec
from backend.models.research import Extraction


class Repair:
    async def run(self, ctx, provider, spec, chunks, error, attempt):
        async with ctx.step("repair", "Repair the failed verification") as progress:
            progress("Use the fast model" if attempt == 0 else "Escalate to the smart model")
            text = json.dumps(
                {
                    "error": error,
                    "spec_slice": {
                        "base_url": str(spec.base_url),
                        "auth": spec.auth.model_dump(mode="json"),
                        "endpoints": [spec.endpoints[0].model_dump(mode="json")],
                    },
                    "evidence": chunks[0].model_dump(mode="json"),
                }
            )
            result = await provider.structured(
                "repair", text, Extraction, smart=attempt == 1, max_output=1000
            )
            return to_spec(result, chunks, spec.content_hash)
