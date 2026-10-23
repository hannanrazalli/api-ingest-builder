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


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    import socket

    import httpx

    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must use recorded HTTP fixtures; real network is forbidden")

    async def forbidden_async(*args, **kwargs):
        forbidden()

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden_async)
