import logging


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"))
        logger.addHandler(h)
        logger.setLevel(level)
    return logger
