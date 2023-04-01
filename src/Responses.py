from abc import ABC, abstractmethod
from flask import jsonify, request
from typing import Any, Dict, Tuple, Union
from Logger import Logger
from werkzeug.local import LocalProxy


class Response(ABC):
    def __init__(self, status_code: int, message: str):
        self._status_code = status_code
        self._message = message

    @abstractmethod
    def json(self):
        """Retruns message in json format"""
        pass


class OKResponse(Response):
    def __init__(self, data: Dict[str, Any], request: LocalProxy, status_code: int = 200, message: str = 'OK'):
        super().__init__(status_code, message)
        self._data = data
        self._request = request

    @property
    def json(self) -> Dict[Any, Any]:
        return jsonify({'status_code': self._status_code,
                        'message': self._message,
                        **self._data})

    def log(self, logger: Logger, **kwargs) -> None:
        """Logs statistics messages"""
        args = kwargs
        if self._request.args.get('method'):
            args['method'] = self._request.args.get('method')
        if self._request.files.getlist('file[]'):
            args['number_of_sent_files'] = len(self._request.files.getlist('file[]'))
        if self._request.args.getlist('pid[]'):
            args['number_of_requested_structures'] = len(self._request.args.getlist('pid[]'))
        if self._request.args.getlist('cid[]'):
            args['number_of_requested_structures'] = len(self._request.args.getlist('cid[]'))
        if self._request.args.get('structure_id'):
            args['structure_id'] = self._request.args.get('structure_id')
        if self._request.args.get('pH'):
            args['pH'] = self._request.args.get('pH')
        if 'get_info' in self._request.path:
            args['number_of_molecules'] = self._data['Number of molecules']
            args['number_of_atoms'] = self._data['Number of atoms']
            args['number_of_individual_atoms'] = self._data['Number of individual atoms']
        if 'suitable_methods' in self._request.path:
            args['suitable_methods'] = self._data['suitable_methods']
        logger.log_statistics_message(self._request.remote_addr, endpoint_name=self._request.path, **args)


class ErrorResponse(Response):
    def __init__(self, message: str, status_code: int = 404, request: LocalProxy = request):
        super().__init__(status_code, message)
        self._request = request

    @property
    def json(self) -> Tuple[Dict[str, Union[str, int]], int]:
        return {'status_code': self._status_code,
                'message': self._message}, self._status_code

    def log(self, logger: Logger) -> None:
        """Logs error messages"""
        logger.log_error_message(self._request.remote_addr, endpoint_name=self._request.path,
                                 error_message=self._message, status_code=self._status_code)
