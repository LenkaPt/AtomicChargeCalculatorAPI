from abc import ABC, abstractmethod
from flask import jsonify
from typing import Any, Dict, Tuple, Union


class Response(ABC):
    def __init__(self, status_code: int, message: str):
        self._status_code = status_code
        self._message = message

    @abstractmethod
    def json(self):
        pass


class OKResponse(Response):
    def __init__(self, data, status_code: int = 200, message: str = 'OK'):
        super().__init__(status_code, message)
        self._data = data

    @property
    def json(self) -> Dict[Any, Any]:
        return jsonify({'status_code': self._status_code,
                        'message': self._message,
                        **self._data})


class ErrorResponse(Response):
    def __init__(self, message: str, status_code: int = 404):
        super().__init__(status_code, message)

    @property
    def json(self) -> Tuple[Dict[str, Union[str, int]], int]:
        return {'status_code': self._status_code,
                'message': self._message}, self._status_code
