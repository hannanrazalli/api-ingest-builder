from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from backend.models import Model


class GenerationOptions(Model):
    endpoint: int = Field(default=0, ge=0)
    mode: Literal[
        "snippet", "daily", "backfill", "full_ingestion"
    ] = "snippet"
    run_target: Literal["local", "airflow"] = "local"
    output_format: Literal["json", "ndjson"] = "json"
    params: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    start_date: date | None = None
    end_date: date | None = None
    chunk_days: int = Field(default=1, gt=0, le=3650)
    flatten: bool = False
    full_ingestion: bool = False
    skip_existing: bool = False
    bucket_name: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
    main_folder: str = Field(default="raw", pattern=r"^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*$")
    table_name: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    cursor_next_path: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_.]*$")

    @model_validator(mode="after")
    def validate_mode(self):
        if self.mode == "backfill" and self.start_date is None:
            raise ValueError("Choose a start date for backfill")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date")
        return self


class GenerateRequest(GenerationOptions):
    job_id: str
