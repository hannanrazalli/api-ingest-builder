from datetime import date
from typing import Literal

from pydantic import Field

from backend.models import Model


class GenerationOptions(Model):
    endpoint: int = Field(default=0, ge=0)
    mode: Literal["snippet", "daily", "backfill", "chunking", "ndjson", "full_ingestion"] = (
        "snippet"
    )
    params: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    start_date: date = date(2026, 1, 1)
    end_date: date = date(2026, 1, 2)
    chunk_days: int = Field(default=1, gt=0, le=3650)
    flatten: bool = False
    full_ingestion: bool = False
    skip_existing: bool = False
    cursor_next_path: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_.]*$")


class GenerateRequest(GenerationOptions):
    job_id: str
