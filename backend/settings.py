import os

from backend.cache.store import Store
from backend.models import Settings

ENV_FIELDS = {
    "LLM_PROVIDER": "provider",
    "LLM_API_KEY": "api_key",
    "LLM_BASE_URL": "base_url",
    "MODEL_FAST": "model_fast",
    "MODEL_SMART": "model_smart",
    "MAX_LLM_CALLS": "max_llm_calls",
    "MAX_INPUT_TOKENS": "max_input_tokens",
    "MAX_OUTPUT_TOKENS": "max_output_tokens",
}


def effective_settings(store: Store) -> Settings:
    values = store.settings().model_dump()
    for env, field in ENV_FIELDS.items():
        if os.environ.get(env):
            values[field] = os.environ[env]
    return Settings.model_validate(values)


def public_settings(settings: Settings) -> dict:
    value = settings.model_dump(mode="json", exclude={"api_key"})
    value["api_key_masked"] = "********" if settings.api_key.get_secret_value() else ""
    value["has_api_key"] = bool(settings.api_key.get_secret_value())
    value["demo_mode"] = settings.demo_mode or not value["has_api_key"]
    value["env_overrides"] = [field for env, field in ENV_FIELDS.items() if os.environ.get(env)]
    return value
