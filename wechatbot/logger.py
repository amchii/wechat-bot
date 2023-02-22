import logging
from logging.handlers import RotatingFileHandler

from .settings import settings

verbose_formatter = logging.Formatter(
    "[%(levelname)s] [%(name)s] %(asctime)s %(filename)s %(process)d %(message)s"
)

logger = logging.getLogger("wechatbot")
logger.setLevel(settings.LOG_LEVEL.upper())
console_handler = logging.StreamHandler()
console_handler.setFormatter(verbose_formatter)
logger.addHandler(console_handler)

file_handler = RotatingFileHandler(
    settings.LOG_DIR.joinpath("wechatbot.log"),
    maxBytes=1024 * 1024,  # 1MB
    backupCount=10,
    encoding="utf-8",
)
file_handler.setFormatter(verbose_formatter)
logger.addHandler(file_handler)
