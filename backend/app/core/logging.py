import logging


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # The OpenAI SDK logs every HTTP request at INFO through httpx.
    logging.getLogger("httpx").setLevel(logging.WARNING)
