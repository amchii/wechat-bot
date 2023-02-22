import signal
import sys
import time
from collections import defaultdict
from typing import Callable, Dict, Set

from .logger import logger


class Signal:
    _signal_handlers: Dict[int, Set[Callable]] = defaultdict(set)
    signalled: bool = False
    signal_count: Dict[int, int] = defaultdict(int)

    @classmethod
    def register(cls, signum, func):
        if not cls.signalled:
            cls.signal()
        assert callable(func)
        cls._signal_handlers[signum].add(func)

    @classmethod
    def register_sigint(cls, func):
        logger.info(f"注册SIGINT信号处理程序: {func.__qualname__}")
        cls.register(signal.SIGINT, func)

    @classmethod
    def register_sigterm(cls, func):
        logger.info(f"注册SIGTERM信号处理程序: {func.__qualname__}")
        cls.register(signal.SIGTERM, func)

    @classmethod
    def register_shutdown(cls, func):
        cls.register_sigint(func)
        cls.register_sigterm(func)

    @classmethod
    def unregister(cls, signum, func):
        cls._signal_handlers[signum].remove(func)

    @classmethod
    def _handle(cls, signum):
        for _handler in cls._signal_handlers[signum]:
            try:
                _handler()
            except Exception as e:
                logger.error(f"信号{signal.strsignal(signum)}处理程序出现错误: {_handler}")
                logger.exception(e)

    @classmethod
    def gracefully_exit(cls, signum, frame):
        logger.info(f"接收到信号: {signal.strsignal(signum)}")
        cls.signal_count[signum] += 1
        if cls.signal_count[signum] > 1:
            sys.exit(1)
        # _handle内的处理程序都应该是同步的
        cls._handle(signum)
        time.sleep(1)
        sys.exit(0)

    @classmethod
    def signal(cls):
        signal.signal(signal.SIGINT, cls.gracefully_exit)
        signal.signal(signal.SIGTERM, cls.gracefully_exit)
        cls.signalled = True
