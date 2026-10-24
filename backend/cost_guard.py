from threading import Lock

from backend.models import Job, Settings, Usage


class BudgetExceeded(RuntimeError):
    pass


class CostGuard:
    """Reserve before I/O; failed requests retain reservations (fail closed)."""

    def __init__(self, settings: Settings, job: Job):
        self.settings = (
            settings.model_copy(update=job.budget_limits) if job.budget_limits else settings
        )
        self.job = job
        self.lock = Lock()

    def reserve(self, input_tokens: int, output_tokens: int):
        if min(input_tokens, output_tokens) < 0:
            raise ValueError("Token reservations cannot be negative")
        with self.lock:
            if (
                self.job.calls + 1 > self.settings.max_llm_calls
                or self.job.input_tokens + input_tokens > self.settings.max_input_tokens
                or self.job.output_tokens + output_tokens > self.settings.max_output_tokens
            ):
                self.job.budget_ready = False
                self.job.budget_required = {
                    "max_llm_calls": self.job.calls + 1,
                    "max_input_tokens": self.job.input_tokens + input_tokens,
                    "max_output_tokens": self.job.output_tokens + output_tokens,
                }
                self.job.status = "waiting"
                raise BudgetExceeded("LLM budget exceeded; explicit user override required")
            self.job.calls += 1
            self.job.input_tokens += input_tokens
            self.job.output_tokens += output_tokens

    def reserve_codex(self, prompt_chars: int):
        if prompt_chars < 0:
            raise ValueError("Prompt reservations cannot be negative")
        with self.lock:
            if (
                self.job.calls + 1 > self.settings.max_llm_calls
                or self.job.prompt_chars + prompt_chars > self.settings.max_prompt_chars
            ):
                self.job.budget_ready = False
                self.job.budget_required = {
                    "max_llm_calls": self.job.calls + 1,
                    "max_prompt_chars": self.job.prompt_chars + prompt_chars,
                }
                self.job.status = "waiting"
                raise BudgetExceeded(
                    "Codex call/character budget exceeded; explicit override required"
                )
            self.job.calls += 1
            self.job.prompt_chars += prompt_chars
            self.job.input_tokens = None
            self.job.output_tokens = None
            self.job.cached_tokens = None
            self.job.cost_usd = None

    def reconcile(self, reserved_input: int, reserved_output: int, usage: Usage):
        with self.lock:
            self.job.input_tokens += usage.input_tokens - reserved_input
            self.job.output_tokens += usage.output_tokens - reserved_output
            self.job.cached_tokens += usage.cached_tokens
            self.job.cost_usd += usage.cost_usd
