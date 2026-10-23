from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.models import Event


def test_recorded_replay_contract_and_no_traversal(store):
    with TestClient(create_app(store.path)) as client:
        response = client.get("/api/demo-events/office_full")
        assert response.status_code == 200
        events = [Event.model_validate(e) for e in response.json()["events"]]
        assert len({e.agent for e in events}) == 11
        assert any(e.agent == "repair" and e.state == "working" for e in events)
        assert response.json()["saved_tokens"] == 500
        assert client.get("/api/demo-events/not-a-recording").status_code == 404
        assert client.get("/api/demo-events/..%2Fsecret").status_code == 404
