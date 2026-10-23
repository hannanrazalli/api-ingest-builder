from typing import Literal

from pydantic import Field

from backend.models import Model


class ConvertRequest(Model):
    sql: str = Field(min_length=1, max_length=30000)
    dialect: str = Field(default="spark", max_length=40)
    target: Literal["pyspark", "pandas", "both"] = "both"
    allow_llm: bool = False


class FragmentResult(Model):
    sql_expression: str = Field(max_length=4000)


class ExplainRequest(Model):
    text: str = Field(min_length=1, max_length=20000)
    language: Literal["Malay", "English"] = "Malay"
    detail: Literal["short", "detailed"] = "short"


class Explanation(Model):
    language: Literal["Malay", "English"]
    summary: str = Field(max_length=1200)
    steps: list[str] = Field(max_length=15)
    concepts: list[str] = Field(max_length=15)


class VerifyRequest(ConvertRequest):
    tables: dict[str, list[dict[str, str | int | float | bool | None]]] = Field(
        default_factory=dict
    )
