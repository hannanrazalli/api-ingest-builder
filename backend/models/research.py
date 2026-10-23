from typing import Literal

from pydantic import Field, SecretStr

from backend.models import Auth, Endpoint, Job, Model, Param, RateLimit, Spec

Scalar = str | int | float | bool | None


class WireParam(Param):
    default: Scalar = None
    allowed_values: list[str | int | float | bool] | None = None


class WireEndpoint(Endpoint):
    params: list[WireParam] = Field(default_factory=list)


class Header(Model):
    name: str
    value: str


class Extraction(Model):
    name: str
    base_url: str
    auth: Auth = Field(default_factory=Auth)
    headers: list[Header] = Field(default_factory=list)
    endpoints: list[WireEndpoint]
    rate_limit: RateLimit | None = None
    unsupported_reason: str | None = None


class Document(Model):
    source_url: str
    markdown: str


class Chunk(Document):
    score: float = 0


class Profile(Model):
    nesting_depth: int = 0
    nested: bool = False
    record_path: str | None = None
    arrays_of_objects: list[str] = Field(default_factory=list)
    primary_keys: list[str] = Field(default_factory=list)
    date_fields: list[str] = Field(default_factory=list)


class ResearchRequest(Model):
    url: str = Field(min_length=1, max_length=2000)
    force: bool = False
    demo: bool | None = None
    api_key: SecretStr | None = None
    api_key_host: str | None = None


class ResearchResult(Model):
    job: Job
    status: Literal["ready", "unverified", "not_found", "unsupported", "budget_blocked", "error"]
    spec: Spec | None = None
    profile: Profile | None = None
    warnings: list[str] = Field(default_factory=list)
    cache_hit: bool = False
    demo: bool = False
