import logging


def redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, dict):
        return {redact(key, secrets): redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    return value


class SecretFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self.secrets = set()

    def filter(self, record):
        record.msg = redact(record.getMessage(), self.secrets)
        record.args = ()
        return True


FILTER = SecretFilter()


def register_secrets(*secrets):
    FILTER.secrets.update(secret for secret in secrets if secret)
    logger = logging.getLogger("httpx")
    if FILTER not in logger.filters:
        logger.addFilter(FILTER)
