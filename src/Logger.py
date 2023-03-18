import logging
from logging.handlers import QueueHandler

class LevelFilter(logging.Filter):
    def __init__(self, level):
        self.__level = level

    def filter(self, logRecord):
        return logRecord.levelno == self.__level


class Logger:
    def __init__(self, type, level, queue=None, file=None):
        if type == 'error':
            self._logger = self.get_error_logger(level=level, file=file)
        elif type == 'statistics':
            self._logger = self.get_statistics_logger(level=level, file=file)
        elif type == 'simple':
            self._logger = self.get_simple_logger(queue)
        else:
            raise ValueError('Wrong type of logger')

    def setup_logger(self, name, log_file, level):
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

    def get_error_logger(self, file, level=logging.ERROR):
        return self.setup_logger('error_logger', file, level)

    def get_statistics_logger(self, file, level=logging.INFO):
        return self.setup_logger('collect_statistics_logger',file, level)

    def get_simple_logger(self, queue):
        logger = logging.getLogger('api')
        # add a handler that uses the shared queue
        logger.addHandler(QueueHandler(queue))
        logger.setLevel(logging.INFO)
        return logger

    def log_statistics_message(self, remote_add, endpoint_name, **kwargs):
        result_message = []
        result_message.append(f'{remote_add}')
        result_message.append(f'endpoint_name={endpoint_name}')
        if kwargs:
            for key, value in kwargs.items():
                result_message.append(f'{key}={value}')
        message = ', '.join(result_message)
        self._logger.info(message)

    def log_error_message(self, remote_add, endpoint_name, error_message, **kwargs):
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
        self._logger.handle(message)