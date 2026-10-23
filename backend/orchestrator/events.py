import asyncio

from backend.cache.store import Store
from backend.models import Event


class EventBus:
    """SQLite is the durable event bus: no subscriber queues or dropped events."""

    def __init__(self, store: Store, secrets=()):
        self.store = store
        self.secrets = secrets

    def emit(self, event: Event) -> int:
        def redact(value):
            if isinstance(value, str):
                for secret in self.secrets:
                    if secret:
                        value = value.replace(secret, "[REDACTED]")
                return value
            if isinstance(value, dict):
                return {key: redact(item) for key, item in value.items()}
            return value

        return self.store.append_event(Event.model_validate(redact(event.model_dump())))

    async def stream(self, job_id: str, after: int = 0):
        while True:
            for sequence, event in self.store.events(job_id, after):
                after = sequence
                yield f"id: {sequence}\nevent: agent\ndata: {event.model_dump_json()}\n\n"
            job = self.store.job(job_id)
            if job and job.status in {"success", "error"}:
                yield "event: done\ndata: {}\n\n"
                return
            yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)
