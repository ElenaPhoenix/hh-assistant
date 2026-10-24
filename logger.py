import logging
import os
from logging.handlers import RotatingFileHandler

DATA_DIR = "data"


def setup_logger():
    """Настраивает запись логов в файл и в консоль."""
    os.makedirs(DATA_DIR, exist_ok=True)
    log_file = os.path.join(DATA_DIR, "app.log")

    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    logger = logging.getLogger("hh_assistant")
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger


# Создаем глобальный объект
log = setup_logger()
