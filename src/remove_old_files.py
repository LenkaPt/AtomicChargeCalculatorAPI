import os
from threading import Timer
from typing import Dict, Union
import pathlib
import time
from datetime import date


def delete_id_from_user(identifier: str, user_id_manager: Dict[str, str]) -> None:
    for user in user_id_manager:
        if identifier in user_id_manager[user]:
            user_id_manager[user].remove(identifier)
            if len(user_id_manager[user]) == 0:
                del user_id_manager[user]
            break


def delete_old_records(file_manager: Dict[str, Union[str, os.PathLike]], user_id_manager: Dict[str, str],
                       config_older_than: float, log_file: Union[str, os.PathLike]) -> None:
    identifiers = file_manager.keys()
    for identifier in identifiers:
        path_to_id = pathlib.Path(file_manager[identifier])
        file_is_old = time.time() - path_to_id.stat().st_mtime
        if file_is_old > config_older_than:
            # delete id and path_to structure from file_manager
            del file_manager[identifier]
            # delete id from ids of user
            delete_id_from_user(identifier, user_id_manager)
            with open(log_file, mode='a') as output:
                output.write(f'{date.today().strftime("%d/%m/%Y")}, '
                             f'{time.strftime("%H:%M:%S", time.localtime())} '
                             f'Removing {path_to_id}, '
                             f'File was last modified before {round(file_is_old, 2)}s.\n')
            os.remove(path_to_id)
            path_to_id.parent.rmdir()


class RepeatTimer(Timer):
    def run(self) -> None:
        while not self.finished.wait(self.interval):
            self.function(*self.args, **self.kwargs)