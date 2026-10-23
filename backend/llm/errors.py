class ProviderError(RuntimeError):
    pass


class CodexCLIError(ProviderError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
