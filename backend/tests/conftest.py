import pytest

from backend.cache.store import Store
from backend.settings import ENV_FIELDS


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    for name in ENV_FIELDS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "default.sqlite3"))


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.sqlite3")
