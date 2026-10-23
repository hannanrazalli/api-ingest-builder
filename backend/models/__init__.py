from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Auth(Model):
    required: bool = False
    type: Literal["header", "query", "bearer", "basic", "none", "unsupported"] = "none"
    header_name: str | None = None
    query_name: str | None = None
    env_var: str = Field(default="API_KEY", pattern=r"^[A-Z_][A-Z0-9_]*$")
    signup_url: HttpUrl | None = None

    @model_validator(mode="after")
    def supported(self):
        if self.type == "basic":
            object.__setattr__(self, "type", "unsupported")
        if self.required and self.type == "none":
            raise ValueError("Required authentication needs an authentication type")
        if self.type == "header" and not self.header_name:
            raise ValueError("Header authentication needs header_name")
        if self.type == "query" and not self.query_name:
            raise ValueError("Query authentication needs query_name")
        return self


class Param(Model):
    name: str = Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9_.-]+$")
    location: Literal["query", "path", "header", "body"] = "query"
    required: bool = False
    type: str = "string"
    default: Any = None
    description: str = ""
    allowed_values: list[Any] | None = None


class DateParams(Model):
    start: str
    end: str | None = None
    format: Literal["iso", "unix", "unix_ms", "custom"] = "iso"
    strftime: str | None = None

    @model_validator(mode="after")
    def custom_format(self):
        if self.format == "custom" and not self.strftime:
            raise ValueError("Custom dates require strftime")
        return self


class Pagination(Model):
    type: Literal["page", "offset", "cursor", "link_header"]
    param: str | None = None
    max_page_size: int | None = Field(default=None, gt=0)


class Endpoint(Model):
    path: str = Field(pattern=r"^/[^\r\n]*$")
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"] = "GET"
    description: str = ""
    source_url: HttpUrl
    verified: bool = False
    params: list[Param] = Field(default_factory=list)
    date_params: DateParams | None = None
    pagination: Pagination | None = None
    max_range_days: int | None = Field(default=None, gt=0)
    record_path: str | None = None
    response_sample_ref: str | None = None


class RateLimit(Model):
    requests: int = Field(gt=0)
    per_seconds: float = Field(gt=0)


class Spec(Model):
    name: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    base_url: HttpUrl
    docs_urls: list[HttpUrl]
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str
    auth: Auth = Field(default_factory=Auth)
    default_headers: dict[str, str] = Field(default_factory=dict)
    endpoints: list[Endpoint] = Field(default_factory=list)
    rate_limit: RateLimit | None = None
    unsupported_reason: str | None = None

    @model_validator(mode="after")
    def unsupported(self):
        if self.auth.type == "unsupported" and not self.unsupported_reason:
            object.__setattr__(self, "unsupported_reason", "Authentication is unsupported in MVP")
        return self


Agent = Literal[
    "orchestrator",
    "prober",
    "fetcher",
    "retriever",
    "extractor",
    "profiler",
    "verifier",
    "repair",
    "generator",
    "converter",
    "explainer",
]
State = Literal["idle", "walking", "working", "waiting", "success", "error", "sleeping"]


class Usage(Model):
    model: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0, ge=0, allow_inf_nan=False)


class Event(Model):
    job_id: str
    ts: float = Field(default_factory=lambda: datetime.now(UTC).timestamp(), ge=0)
    agent: Agent
    state: State
    task: str = Field(min_length=1, max_length=200)
    detail: str | None = Field(default=None, max_length=1000)
    llm: Usage | None = None
    cache_hit: bool | None = None


class Settings(Model):
    provider: Literal["openai", "anthropic", "compatible"] = "openai"
    api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    base_url: HttpUrl | None = None
    model_fast: str = ""
    model_smart: str = ""
    max_llm_calls: int = Field(default=3, ge=0)
    max_input_tokens: int = Field(default=20000, ge=0)
    max_output_tokens: int = Field(default=4000, ge=0)
    input_usd_per_million: float = Field(default=0, ge=0, allow_inf_nan=False)
    cached_usd_per_million: float = Field(default=0, ge=0, allow_inf_nan=False)
    output_usd_per_million: float = Field(default=0, ge=0, allow_inf_nan=False)
    onboarded: bool = False
    demo_mode: bool = False


class SettingsUpdate(Model):
    provider: Literal["openai", "anthropic", "compatible"] | None = None
    api_key: SecretStr | None = None
    base_url: HttpUrl | None = None
    model_fast: str | None = None
    model_smart: str | None = None
    input_usd_per_million: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cached_usd_per_million: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    output_usd_per_million: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_llm_calls: int | None = Field(default=None, ge=0)
    max_input_tokens: int | None = Field(default=None, ge=0)
    max_output_tokens: int | None = Field(default=None, ge=0)


class Job(Model):
    id: str
    status: Literal["pending", "running", "waiting", "success", "error"] = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0
