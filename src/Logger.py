import logging
import os
from logging.handlers import QueueHandler
from multiprocessing import Queue
from typing import Union


def logging_process(queue: Queue, error_file: Union[os.PathLike, str], stat_file: Union[os.PathLike, str]) -> None:
    """Process of logging using queue"""
    error_logger = Logger('error', file=error_file, level=logging.ERROR)
    stat_logger = Logger('statistics', file=stat_file, level=logging.INFO)
    for message in iter(queue.get, None):
        error_logger.handle(message)
        stat_logger.handle(message)
        print(f'Logger queue: {queue.qsize()}')


class LevelFilter(logging.Filter):
    def __init__(self, level: int) -> None:
        self.__level = level

    def filter(self, logRecord: logging.LogRecord) -> bool:
        """Filtres record based on level"""
        return logRecord.levelno == self.__level


class Logger:
    def __init__(self, type: str, level: int, queue: Queue = None, file: os.PathLike = None):
        if type == 'error':
            self._logger = self.get_error_logger(level=level, file=file)
        elif type == 'statistics':
            self._logger = self.get_statistics_logger(level=level, file=file)
        elif type == 'simple':
            self._logger = self.get_simple_logger(queue)
        else:
            raise ValueError('Wrong type of logger')

    def setup_logger(self, name: str, log_file: os.PathLike, level: int) -> logging.Logger:
        """Setups logger"""
        formatter = logging.Formatter(f'%(asctime)s'
                                      f'%(process)d, '
                                      f'%(message)s')
        handler = logging.FileHandler(log_file)
        handler.setFormatter(formatter)

        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.addHandler(handler)
        logger.addFilter(LevelFilter(level))

        return logger

    def get_error_logger(self, file: os.PathLike, level: int = logging.ERROR) -> logging.Logger:
        """Returns logger for error messages"""
        return self.setup_logger('error_logger', file, level)

    def get_statistics_logger(self, file: os.PathLike, level=logging.INFO) -> logging.Logger:
        """Returns logger for statistics messages"""
        return self.setup_logger('collect_statistics_logger', file, level)

    def get_simple_logger(self, queue: Queue) -> logging.Logger:
        """Returns basic simple logger with QueueHandler"""
        logger = logging.getLogger('api')
        # add a handler that uses the shared queue
        logger.addHandler(QueueHandler(queue))
        logger.setLevel(logging.INFO)
        return logger

    def log_statistics_message(self, remote_add: str, endpoint_name: str, **kwargs) -> None:
        """Logs statistics messages"""
        result_message = []
        result_message.append(f'{remote_add}')
        result_message.append(f'endpoint_name={endpoint_name}')
        if kwargs:
            for key, value in kwargs.items():
                result_message.append(f'{key}={value}')
        message = ', '.join(result_message)
        self._logger.info(message)

    def log_error_message(self, remote_add: str, endpoint_name: str, error_message: str, **kwargs) -> None:
        """Logs error messages"""
        result_message = []
        result_message.append(f'{remote_add}')
        result_message.append(f'endpoint_name={endpoint_name}')
        result_message.append(f'error_message={error_message}')
        if kwargs:
            for key, value in kwargs.items():
                result_message.append(f'{key}={value}')
        message = ', '.join(result_message)
        self._logger.error(message)

    def handle(self, message):
        """Handles message"""
        self._logger.handle(message)
