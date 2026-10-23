from contextlib import asynccontextmanager

from backend.cost_guard import BudgetExceeded
from backend.models import Event


class AgentContext:
    def __init__(self, store, job, bus):
        self.store, self.job, self.bus = store, job, bus

    def emit(self, agent, state, task, **fields):
        self.bus.emit(Event(job_id=self.job.id, agent=agent, state=state, task=task, **fields))

    @asynccontextmanager
    async def step(self, agent, task):
        self.emit(agent, "walking", task)
        self.emit(agent, "working", task)
        try:
            yield lambda text: self.emit(agent, "working", text)
        except BudgetExceeded:
            self.emit(agent, "waiting", "Cost Guard requires explicit budget approval")
            raise
        except Exception:
            self.emit(agent, "error", "Step failed; inspect the safe job warning")
            raise
        else:
            self.emit(agent, "success", task + " complete")

    def skipped(self, agent, task):
        self.emit(agent, "sleeping", task)
