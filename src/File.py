import subprocess
import pathlib
import os
import tempfile
from typing import Union, Any
from werkzeug.datastructures import FileStorage
from configparser import ConfigParser


class File:
    def __init__(self, file: Union[str, FileStorage], path_to_directory: Union[str, os.PathLike]):
        self._file = file
        if isinstance(file, str):
            self._filename = file
        else:
            self._filename = file.filename
        self._path_to_file = os.path.join(path_to_directory, self._filename)
        self._id = self.__generate_id()

    def has_valid_suffix(self) -> bool:
        """Returns if the file is in .sdf, .pdb, .mol2 or .cif format"""
        if not self._filename.endswith(('sdf', 'pdb', 'mol2', 'cif')):
            return False
        return True

    def get_size(self) -> int:
        """Returns size of file"""
        return pathlib.Path(self._path_to_file).stat().st_size

    def save(self) -> None:
        """Saves file"""
        self._file.save(self._path_to_file)

    def convert_line_endings_to_unix_style(self) -> None:
        """Converts line endings to unix style"""
        subprocess.run(['dos2unix', self._path_to_file])

    def __generate_id(self) -> str:
        """Generates id"""
        return pathlib.Path(tempfile.NamedTemporaryFile(prefix=self._filename.rsplit('.')[0]).name).name

    def get_id(self) -> str:
        """Returns id of file"""
        return self._id

    def get_filename(self) -> str:
        """Returns name of file"""
        return self._filename

    def get_path(self) -> Union[str, os.PathLike]:
        """Returns path to file"""
        return self._path_to_file

    def write_file(self, r: Any, config: ConfigParser) -> bool:
        """Writes file"""
        file_size = 0
        with open(self._path_to_file, 'wb') as fd:
            for chunk in r.iter_content(chunk_size=128):
                fd.write(chunk)
                file_size += len(chunk)
                if config['limits']['on'] == 'True':
                    if file_size > int(config['limits']['file_size']):
                        return False
        return True

    def remove(self) -> None:
        """Removes file"""
        os.remove(self._path_to_file)
        pathlib.Path(self._path_to_file).parent.rmdir()
