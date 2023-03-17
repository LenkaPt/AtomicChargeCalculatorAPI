from flask import Flask, render_template, request, send_from_directory, jsonify
from flask_restx import Api, Resource, reqparse
from werkzeug.datastructures import FileStorage
from typing import Dict, TextIO, Any, Union, List, Tuple
from multiprocessing import Process, Manager, Queue
from multiprocessing.managers import BaseManager
import tempfile
import os
import csv
import json
import chargefw2_python
import requests
import subprocess
import time
from datetime import date
from threading import Timer, Thread
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import configparser
import pathlib
import logging
from logging.handlers import QueueHandler
from abc import ABC, abstractmethod
import heapq
from queue import PriorityQueue

config = configparser.ConfigParser()
config.read('api.ini')
app = Flask(__name__)
if config['limits']['on'] == 'True':
    app.config['MAX_CONTENT_LENGTH'] = int(config['limits']['file_size'])
api = Api(app,
          title='Atomic Charge Calculator II - API',
          description='Atomic Charge Calculator II is software tool '
                      'designated for calculation of partial atomic charges.\n'
                      '<br>'
                      '<a href="http://78.128.250.156/documentation">Documentation</a>')


# limiter = Limiter(
#     app,
#     key_func=get_remote_address,
#     default_limits=["200 per day", "50 per hour"]
# )


@app.route('/documentation')
def documentation():
    """Documentation"""
    return send_from_directory('.', 'Documentation.pdf')


# namespace for sending files - for documentation
send_files = api.namespace('send_files',
                           description='Send file containing structure '
                                       'of your interest and obtain '
                                       'structure identifier used for further '
                                       'operation with your structure\n'
                                       'Please be aware, that it is '
                                       'possible to upload only files '
                                       'of max size 10 MB.')

# namespace for getting structure through PDB ID
pid = api.namespace('pdb_id',
                    description='Specify PDB ID of structure of your '
                                'interest and obtain structure identifier used '
                                'for further operation with your structure.')

# namespace for getting compound through Pubchem CID
cid = api.namespace('pubchem_cid',
                    description='Specify Pubchem CID of compound of your '
                                'interest and obtain structure identifier used for '
                                'further operation with your structure.')

remove_file = api.namespace('remove_file',
                            description='Remove file specified by id')

# namespace for get_info about molecules root
get_info = api.namespace('get_info',
                         description='Get info about your structure.')

# namespace for adding hydrogens to structure
hydrogens = api.namespace('add_hydrogens',
                          description='WIP: Might not work as expected - works just fo structures in .pdb format! '
                                      'Add hydrogens to your structure.')

# namespace for available_method root - for documentation
avail_methods = api.namespace('available_methods',
                              description='Get available methods provided by Atomic Charge Calculator '
                                          'for calculation of partial atomic charges')

# namespace for available parameters route - for documentation
avail_params = api.namespace('available_parameters',
                             description='Get available parameters for specific method')

# namespace for suitable methods
suitable_methods = api.namespace('suitable_methods',
                                 description='Find out all methods suitable '
                                             'for your structure.')

calculate_charges = api.namespace('calculate_charges',
                                  description='Calculate partial atomic charges.')

get_calculation_results = api.namespace('get_calculation_results',
                                        description='Get results from calculation of partial atomic charges')

get_limits = api.namespace('get_limits',
                           description='Get info about limits, your files.')


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
    def json(self):
        return jsonify({'status_code': self._status_code,
                        'message': self._message,
                        **self._data})


class ErrorResponse(Response):
    def __init__(self, message: str, status_code: int = 404):
        super().__init__(status_code, message)

    @property
    def json(self):
        return {'status_code': self._status_code,
                'message': self._message}, self._status_code


class Structure:
    def __init__(self, structure_id: str = None):
        if structure_id not in file_manager:
            raise ValueError(f'Structure ID {structure_id} does not exists.')
        self._structure_id = structure_id

    def get_structure_file(self):
        if self._structure_id in file_manager:
            return file_manager[self._structure_id]
        return None

    def get_molecules(self, read_hetatm: bool = True, ignore_water: bool = False):
        path_to_file = self.get_structure_file()
        if path_to_file is None:
            raise ValueError(f'Structure ID {self._structure_id} does not exist.')
        try:
            return chargefw2_python.Molecules(path_to_file, read_hetatm, ignore_water)
        except RuntimeError as e:
            raise ValueError(e)

    def get_parameters_without_suffix(self, params):
        new_params = []
        for par in params:
            new_params.append(pathlib.Path(par).stem)
        return new_params

    def format_methods(self, methods):
        result_format = []
        for item in methods:
            params = item[1]
            if params:
                params = self.get_parameters_without_suffix(params)
            else:
                params = None
            result_format.append({'method': item[0], 'parameters': params})
        return result_format

    def get_suitable_methods(self, read_hetatm: bool = True, ignore_water: bool = False):
        """Returns suitable methods for particular dataset"""
        molecules = self.get_molecules(read_hetatm, ignore_water)
        return self.format_methods(chargefw2_python.get_suitable_methods(molecules))

    def is_method_suitable(self, method, suitable_methods=None, read_hetatm: bool = True, ignore_water: bool = False):
        if not suitable_methods:
            suitable_methods = self.get_suitable_methods(read_hetatm, ignore_water)
        for item in suitable_methods:
            if item['method'] == method:
                return True
        return False

    def get_pdb_input_file(self) -> str:
        """Returns input file in pdb format (pdb2pqr can process only pdb files)"""
        input_file = self.get_structure_file()
        if not input_file:
            raise ValueError(f'Structure ID {self._structure_id} does not exist.')
        # cif format convert to pdb using gemmi convert
        if input_file.endswith('.cif'):
            try:
                subprocess.run(['gemmi', 'convert', f'{input_file}', f'{input_file[:-4]}.pdb'], check=True)
            except subprocess.CalledProcessError:
                raise ValueError(f'Error converting from .cif to .pdb using gemmi convert.')
            input_file = input_file[:-4] + '.pdb'
        if not input_file.endswith('pdb'):
            raise ValueError(f'{self._structure_id} is not in .pdb or .cif format')
        return input_file


def calculate_time(func):
    def inner(*args, **kwargs):
        with open(config['paths']['log_time'], mode='a') as file:
            file.write(f'---STARTING---{func.__qualname__}\n')
            file.write(f'{time.asctime(time.localtime(time.time()))}\n')

        start = time.perf_counter()
        returned_value = func(*args, **kwargs)
        end = time.perf_counter()

        with open(config['paths']['log_time'], mode='a') as file:
            file.write(f'{date.today().strftime("%d/%m/%Y")}, '
                       f'{time.strftime("%H:%M:%S", time.localtime())} - '
                       f'{func.__qualname__} - {end - start}\n')
            file.write(f'---ENDING---{func.__qualname__}\n')

        # return value from function
        return returned_value

    return inner


class LevelFilter(logging.Filter):
    def __init__(self, level):
        self.__level = level

    def filter(self, logRecord):
        return logRecord.levelno == self.__level


class Logger:
    def __init__(self, type, level, queue=None):
        if type == 'error':
            self._logger = self.get_error_logger(level=level)
        elif type == 'statistics':
            self._logger = self.get_statistics_logger(level=level)
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

    def get_error_logger(self, file=(config['paths']['log_error']), level=logging.ERROR):
        return self.setup_logger('error_logger', file, level)

    def get_statistics_logger(self, file=(config['paths']['save_statistics_file']), level=logging.INFO):
        return self.setup_logger('collect_statistics_logger', file, level)

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



def logging_process(queue):
    error_logger = Logger('error', level=logging.ERROR)
    stat_logger = Logger('statistics', level=logging.INFO)
    for message in iter(queue.get, None):
        error_logger.handle(message)
        stat_logger.handle(message)
        print(f'Logger queue: {queue.qsize()}')


manager = Manager()
queue = manager.Queue()
log_process = Process(target=lambda: logging_process(queue))
log_process.start()
simple_logger = Logger('simple', logging.INFO, queue)



@avail_methods.route('')
class AvailableMethodsEndpoint(Resource):
    def get(self):
        """Returns list of methods available for calculation of partial atomic charges"""
        simple_logger.log_statistics_message(request.remote_addr, endpoint_name='available_methods')
        return OKResponse({'available_methods': chargefw2_python.get_available_methods()}).json


@avail_params.route('')
@api.doc(params={'method': {'description': 'Calculation method', 'type': 'string', 'required': True, 'in': 'query'}},
         responses={404: 'Method not specified',
                    400: 'Method not available',
                    200: 'OK'})
class AvailableParametersEndpoint(Resource):
    def get(self):
        """Returns list of available parameters for specific method"""
        method = request.args.get('method')
        if not method:
            simple_logger.log_error_message(request.remote_addr,
                                            'available_parameters',
                                            'User did not specify method')
            return ErrorResponse(f'You have not specified method. '
                                 f'Add to URL following, please: ?method=your_chosen_method').json

        if method not in chargefw2_python.get_available_methods():
            simple_logger.log_error_message(request.remote_addr,
                                            'available_parameters',
                                            f'User wanted to use method {method} that is not available')
            return ErrorResponse(f'Method {method} is not available.', status_code=400).json

        simple_logger.log_statistics_message(request.remote_addr, endpoint_name='available_parameters', method=method)
        return OKResponse({'parameters': chargefw2_python.get_available_parameters(method)}).json


def valid_suffix(files: TextIO) -> bool:
    for file in files:
        if not file.filename.endswith(('sdf', 'pdb', 'mol2', 'cif')):
            return False
    return True


def save_file_identifiers(identifiers: Dict[str, str]) -> None:
    if request.remote_addr not in user_id_manager:
        user_id_manager[request.remote_addr] = manager.list()
    for identifier, path_to_file in identifiers.items():
        file_manager[identifier] = path_to_file
        user_id_manager[request.remote_addr].append(identifier)
        # {user: [id1, id2]}


# TODO not good - just one file (action='append' not working with files)
file_parser = api.parser()
file_parser.add_argument('file[]', location='files', type=FileStorage, required=True)


@send_files.route('')
@api.doc(responses={404: 'No file sent',
                    400: 'Unsupported format',
                    413: 'File is too large',
                    200: 'OK'})
@api.expect(file_parser)
class SendFilesEndpoint(Resource):
    # decorators = [limiter.shared_limit("100/hour", scope="upload")]
    def post(self):
        """Send files in pdb, sdf or cif format"""
        files = request.files.getlist('file[]')

        if not files:
            simple_logger.log_error_message(request.remote_addr,
                                            'send_files',
                                            f'User did not send a file')
            return ErrorResponse(f'No file sent. Add to URL following, please: ?file[]=path_to_file').json

        if not valid_suffix(files):
            simple_logger.log_error_message(request.remote_addr,
                                            f'send_files',
                                            f'User sent file in unsupported format')
            return ErrorResponse(f'Unsupported format. Send only .sdf, .mol2, .cif and .pdb files.',
                                 status_code=400).json

        tmpdir = tempfile.mkdtemp(dir=config['paths']['save_user_files'])
        # tmpdir = tempfile.mkdtemp()
        identifiers_plus_filepath = {}
        identifiers_plus_filenames = {}
        all_uploaded = True
        for file in files:
            path_to_file = os.path.join(tmpdir, file.filename)
            file.save(path_to_file)

            # user has limited space
            file_size = pathlib.Path(path_to_file).stat().st_size
            if limitations_on and request.remote_addr in used_space:
                if file_size + used_space[request.remote_addr] > int(config['limits']['granted_space']):
                    all_uploaded = False
                    break
            if limitations_on:
                used_space[request.remote_addr] = used_space.get(request.remote_addr, 0) + file_size

            # convert formats (different new lines)
            subprocess.run(['dos2unix', path_to_file])

            identifier = os.path.basename(tempfile.NamedTemporaryFile(prefix=file.filename.rsplit('.')[0]).name)
            identifiers_plus_filepath[identifier] = path_to_file
            identifiers_plus_filenames[file.filename.rsplit('.')[0]] = identifier

        save_file_identifiers(identifiers_plus_filepath)

        simple_logger.log_statistics_message(request.remote_addr,
                                             endpoint_name='send_files',
                                             number_of_sent_files=len(files))

        if all_uploaded:
            return OKResponse({'structure_ids': identifiers_plus_filenames}).json
        # some ids were uploaded, but not all because the limited disk space
        elif not all_uploaded and identifiers_plus_filenames:
            return jsonify({'message': 'You have exceeded the grounded disk space',
                            'status_code': 413,
                            'successfully_uploaded_structure_ids': identifiers_plus_filenames})
        else:
            return ErrorResponse('You have exceeded the grounded disk space', 413).json


def write_file(path_to_file, r):
    file_size = 0
    with open(path_to_file, 'wb') as fd:
        for chunk in r.iter_content(chunk_size=128):
            fd.write(chunk)
            file_size += len(chunk)
            if config['limits']['on'] == 'True':
                if file_size > int(config['limits']['file_size']):
                    return False
    return True


# parser for query arguments
pid_parser = reqparse.RequestParser()
pid_parser.add_argument('pid[]', type=str, help='PDB ID', action='append', required=True)


@pid.route('')
@api.doc(responses={404: 'No PDB iD specified or PDB ID does not exist',
                    200: 'OK',
                    400: 'File bigger than 10 Mb'})
@api.expect(pid_parser)
class PdbID(Resource):
    # decorators = [limiter.shared_limit("100/hour", scope="upload")]
    def post(self):
        """Specify PDB ID of your structure."""
        pdb_identifiers = request.args.getlist('pid[]')

        if not pdb_identifiers:
            simple_logger.log_error_message(request.remote_addr,
                                            'pdb_id',
                                            'User did not specify pdb ID')
            return ErrorResponse('No pdb id specified. Add to URL following, please: ?pid[]=pdb_id').json

        tmpdir = tempfile.mkdtemp(dir=config['paths']['save_user_files'])
        identifiers_plus_filepath = {}
        identifiers_plus_filename = {}
        all_uploaded = True
        for pdb_id in pdb_identifiers:
            r = requests.get('https://files.rcsb.org/download/' + pdb_id + '.cif', stream=True)
            try:
                r.raise_for_status()
            except requests.exceptions.HTTPError as e:
                simple_logger.log_error_message(request.remote_addr,
                                                'pdb_id',
                                                f'{e}',
                                                status_code=r.status_code)
                return ErrorResponse(f'{e}', r.status_code).json

            # save requested pdb structure
            path_to_file = os.path.join(tmpdir, pdb_id + '.cif')
            successfully_written_file = write_file(path_to_file, r)
            if not successfully_written_file:
                simple_logger.log_error_message(request.remote_addr,
                                                'pdb_id',
                                                'User wanted to upload file bigger than 10 Mb')
                return ErrorResponse(f'Not possible to upload {pdb_id}. It is bigger than 10 Mb.', 400).json

            # user has limited space
            file_size = pathlib.Path(path_to_file).stat().st_size
            if limitations_on and request.remote_addr in used_space:
                if file_size + used_space[request.remote_addr] > int(config['limits']['granted_space']):
                    all_uploaded = False
                    break
            if limitations_on:
                used_space[request.remote_addr] = used_space.get(request.remote_addr, 0) + file_size

            identifier = os.path.basename(tempfile.NamedTemporaryFile(prefix=pdb_id).name)
            identifiers_plus_filepath[identifier] = path_to_file
            identifiers_plus_filename[pdb_id] = identifier

        save_file_identifiers(identifiers_plus_filepath)

        simple_logger.log_statistics_message(request.remote_addr,
                                             endpoint_name='pdb_id',
                                             number_of_requested_structures=len(pdb_identifiers))

        if all_uploaded:
            return OKResponse({'structure_ids': identifiers_plus_filename}).json
        # some ids were uploaded, but not all because the limited disk space
        elif not all_uploaded and identifiers_plus_filepath:
            return jsonify({'message': 'You have exceeded the grounded disk space',
                            'status_code': 413,
                            'successfully_uploaded_structure_ids': identifiers_plus_filenames})
        else:
            return ErrorResponse('You have exceeded the grounded disk space', 413).json


# parser for query arguments
pubchem_parser = reqparse.RequestParser()
pubchem_parser.add_argument('cid[]', type=int, help='Compound CID', action='append', required=True)


@cid.route('')
@api.doc(responses={404: 'No Pubchem compound ID specified or compound ID does not exist',
                    200: 'OK',
                    400: 'File bigger than 10 Mb'})
@api.expect(pubchem_parser)
class PubchemCID(Resource):
    # decorators = [limiter.shared_limit("100/hour", scope="upload")]
    def post(self):
        """Specify Pubchem CID of your structure."""
        cid_identifiers = request.args.getlist('cid[]')

        if not cid_identifiers:
            simple_logger.log_error_message(request.remote_addr,
                                            'pubchem_id',
                                            'User did not specify pubchem cid')
            return ErrorResponse('No pubchem cid specified. Add to URL following, please: ?cid[]=pubchem_cid').json

        tmpdir = tempfile.mkdtemp(dir=config['paths']['save_user_files'])
        identifiers_plus_filepath = {}
        identifiers_plus_filenames = {}
        all_uploaded = True
        for cid in cid_identifiers:
            r = requests.get('https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/CID/' +
                             cid +
                             '/record/SDF/?record_type=3d&response_type=save&response_basename=Conformer3D_CID_' +
                             cid, stream=True)
            try:
                r.raise_for_status()
            except requests.exceptions.HTTPError as e:
                simple_logger.log_error_message(request.remote_addr,
                                                'pubchem_cid',
                                                f'{e}',
                                                status_code=r.status_code)
                return ErrorResponse(f'{e}', r.status_code).json

            # save requested cid compound
            path_to_file = os.path.join(tmpdir, cid + '.sdf')
            successfully_written_file = write_file(path_to_file, r)
            if not successfully_written_file:
                simple_logger.log_error_message(request.remote_addr,
                                                'cid',
                                                'User wanted to upload file bigger than 10 Mb')
                return ErrorResponse(f'Not possible to upload {cid}. It is bigger than 10 Mb.', 400).json

            # user has limited space
            file_size = pathlib.Path(path_to_file).stat().st_size
            if limitations_on and request.remote_addr in used_space:
                if file_size + used_space[request.remote_addr] > int(config['limits']['granted_space']):
                    all_uploaded = False
                    break
            if limitations_on:
                used_space[request.remote_addr] = used_space.get(request.remote_addr, 0) + file_size

            identifier = os.path.basename(tempfile.NamedTemporaryFile(prefix=cid).name)
            identifiers_plus_filepath[identifier] = path_to_file
            identifiers_plus_filenames[cid] = identifier

        save_file_identifiers(identifiers_plus_filepath)

        simple_logger.log_statistics_message(request.remote_addr,
                                             endpoint_name='pubchem_cid',
                                             number_of_requested_structures=len(cid_identifiers))

        if all_uploaded:
            return OKResponse({'structure_ids': identifiers_plus_filenames}).json
        # some ids were uploaded, but not all because the limited disk space
        elif not all_uploaded and identifiers_plus_filenames:
            return jsonify({'message': 'You have exceeded the grounded disk space',
                            'status_code': 413,
                            'successfully_uploaded_structure_ids': identifiers_plus_filenames})
        else:
            return ErrorResponse('You have exceeded the grounded disk space', 413).json


remove_file_parser = reqparse.RequestParser()
remove_file_parser.add_argument('structure_id',
                                type=str,
                                help='Obtained structure identifier of your structure',
                                required=True)


@api.doc(responses={404: 'Structure ID not specified',
                    400: 'Structure ID does not exist / Structure not in correct format',
                    200: 'OK'})
@api.expect(remove_file_parser)
@remove_file.route('')
class RemoveFile(Resource):
    def post(self):
        """Remove file specified by structure_id"""
        structure_id = request.args.get('structure_id')
        if not structure_id:
            simple_logger.log_error_message(request.remote_addr,
                                            'remove_file',
                                            'User did not specify structure id')
            return ErrorResponse(f'You have not specified structure ID obtained after uploading your file. '
                                 f'Add to URL following, please: ?structure_id=obtained_structure_id').json
        try:
            structure = Structure(structure_id)
        except ValueError as e:
            simple_logger.log_error_message(request.remote_addr,
                                            'remove_file',
                                            'User specified id that does not exist',
                                            structure_id=structure_id)
            return ErrorResponse(f'Structure ID {structure_id} does not exist.', 400).json

        if structure_id not in user_id_manager[request.remote_addr]:
            simple_logger.log_error_message(request.remote_addr,
                                            'remove_file',
                                            'User wanted to remove file that is not his.')
            return ErrorResponse(f'You are not allowed to remove {structure_id}. It is not your structure.').json

        path_to_file = pathlib.Path(structure.get_structure_file())

        # remove from file_manager and user_id_manager
        del file_manager[structure_id]
        delete_id_from_user(structure_id)

        # release space
        file_size = path_to_file.stat().st_size
        if limitations_on:
            if used_space[request.remote_addr] - file_size <= 0:
                del used_space[request.remote_addr]
            else:
                used_space[request.remote_addr] = used_space[request.remote_addr] - file_size

        os.remove(path_to_file)
        path_to_file.parent.rmdir()
        simple_logger.log_statistics_message(request.remote_addr,
                                             endpoint_name='remove_file',
                                             structure_id=structure_id,
                                             user=request.remote_addr,
                                             removed_successfully=True)
        return OKResponse({structure_id: 'removed'}).json


def convert_pqr_to_pdb(pqr_file: str, pdb_file: str) -> None:
    """Converts .pqr to .pdb format - using open babel"""
    try:
        subprocess.run(['obabel', f'-ipqr', f'{pqr_file}', f'-opdb', f'-O{pdb_file}'], check=True)
    except subprocess.CalledProcessError:
        raise ValueError('Error converting from .pqr to .pdb format using openbabel.')


# parser for query arguments
hydro_parser = reqparse.RequestParser()
hydro_parser.add_argument('structure_id',
                          type=str,
                          help='Obtained structure identifier of your structure',
                          required=True)
hydro_parser.add_argument('pH',
                          type=str,
                          help='Specify pH parameter if you would like '
                               'to add hydrogens under specific pH.\n'
                               'Default: 7.0')
hydro_parser.add_argument('noopt',
                          type=bool,
                          help='Use in case that you would not like to '
                               'optimize hydrogen bonds.\n'
                               'Default: True')


@hydrogens.route('')
@api.doc(responses={404: 'Structure ID not specified',
                    400: 'Structure ID does not exist / Structure not in correct format',
                    405: 'Error in using pdb2pqr / openbabel',
                    200: 'OK'})
@api.expect(hydro_parser)
class AddHydrogens(Resource):
    def post(self):
        """WIP: Might not work as expected - works just for structures in .pdb format!
        Add hydrogens to your structure represented by an structure identifier"""
        structure_id = request.args.get('structure_id')
        if not structure_id:
            simple_logger.log_error_message(request.remote_addr,
                                            'add_hydrogens',
                                            'User did not specify structure id')
            return ErrorResponse(f'You have not specified structure ID obtained after uploading your file. '
                                 f'Add to URL following, please: ?structure_id=obtained_structure_id').json

        ph = request.args.get('pH')
        if not ph:
            ph = float(config['pH']['default'])

        try:
            structure = Structure(structure_id)
            input_file = structure.get_pdb_input_file()
        except ValueError as e:
            simple_logger.log_error_message(request.remote_addr,
                                            'add_hydrogens',
                                            f'{str(e)}')
            return ErrorResponse(f'{str(e)}', status_code=400).json
        output_pqr_file = os.path.join(tempfile.mkdtemp(dir=config['paths']['save_user_files']), 'result.pqr')
        output_pdb_file = output_pqr_file[:-4] + '.pdb'

        # hydrogen bond optimalization
        noopt = request.args.get('noopt')

        if not noopt:
            try:
                subprocess.run(['pdb2pqr30', f'--noopt', f'--pH', f'{ph}', f'{input_file}', f'{output_pqr_file}'],
                               check=True)
            except subprocess.CalledProcessError as e:
                simple_logger.log_error_message(request.remote_addr,
                                                'add_hydrogens',
                                                'Error occurred when using pdb2pqr30',
                                                structure_id=structure_id)
                return ErrorResponse(f'Error occurred when using pdb2pqr30 on structure {structure_id}',
                                     status_code=405).json
        else:
            try:
                subprocess.run(['pdb2pqr30', f'--pH', f'{ph}', f'{input_file}', f'{output_pqr_file}'], check=True)
            except subprocess.CalledProcessError as e:
                simple_logger.log_error_message(request.remote_addr,
                                                'add_hydrogens',
                                                'Error occurred when using pdb2pqr30',
                                                structure_id=structure_id)
                return ErrorResponse(f'Error occurred when using pdb2pqr30 on structure {structure_id}',
                                     status_code=405).json

        output_identifier = os.path.basename(tempfile.NamedTemporaryFile(prefix='hydro').name)
        try:
            convert_pqr_to_pdb(output_pqr_file, output_pdb_file)
        except ValueError as e:
            simple_logger.log_error_message(request.remote_addr,
                                            'add_hydrogens',
                                            f'{str(e)}')
            return ErrorResponse(f'{str(e)}', status_code=405).json
        save_file_identifiers({output_identifier: output_pdb_file})

        simple_logger.log_statistics_message(request.remote_addr,
                                             endpoint_name='add_hydrogens',
                                             ph=ph,
                                             noopt=noopt)
        return OKResponse({'structure_id': output_identifier}).json


def get_read_hetatm_value(read_hetatm: Union[None, str]) -> bool:
    """Get boolean value - if user wants to read hetatoms from input pdb/mmcif file"""
    if read_hetatm:
        read_hetatm = read_hetatm.lower()
    return read_hetatm != 'false'  # default: True


def get_ignore_water_value(ignore_water: Union[None, str]) -> bool:
    """Get boolean value - if user wants to ignore water read hetatoms
    from input pdb/mmcif file"""
    if ignore_water:
        ignore_water = ignore_water.lower()
    return ignore_water == 'true'  # default False


def get_dict_atoms_count(atoms_list_count):
    """Get dictionary of atoms count - atom as key, count as value"""
    result = {}
    for atom_count in atoms_list_count:
        atom, count = atom_count
        result[atom] = count
    return result


# parser for query arguments
info_parser = reqparse.RequestParser()
info_parser.add_argument('structure_id',
                         type=str,
                         help='Obtained structure identifier of your structure',
                         required=True)
info_parser.add_argument('read_hetatm',
                         type=bool,
                         help='Use in case that you would like to read '
                              'not only the protein, but also ligands.\n'
                              'Default: True')
info_parser.add_argument('ignore_water',
                         type=bool,
                         help='Use in case that you would like to ignore '
                              'water molecules.\n'
                              'Default: False')


@get_info.route('')
@api.doc(responses={404: 'Structure ID not specified',
                    400: 'Structure ID does not exist or input file is not correct',
                    200: 'OK'})
@api.expect(info_parser)
class GetInfo(Resource):
    def get(self):
        """Get info about your molecule."""
        structure_id = request.args.get('structure_id')
        read_hetatm = request.args.get('read_hetatm')
        ignore_water = request.args.get('ignore_water')
        if not structure_id:
            simple_logger.log_error_message(request.remote_addr,
                                            'get_info',
                                            'User did not specify structure id')
            return ErrorResponse(f'You have not specified structure ID obtained after uploading your file. '
                                 f'Add to URL following, please: ?structure_id=obtained_structure_id').json

        read_hetatm = get_read_hetatm_value(read_hetatm)  # default: True
        ignore_water = get_ignore_water_value(ignore_water)  # default False

        try:
            structure = Structure(structure_id)
            molecules = structure.get_molecules(read_hetatm, ignore_water)
        except ValueError as e:
            simple_logger.log_error_message(request.remote_addr,
                                            'get_info',
                                            f'{str(e)}')
            return ErrorResponse(str(e), status_code=400).json

        molecules_count, atom_count, atoms_list_count = chargefw2_python.get_info(molecules)
        atoms_dict_count = get_dict_atoms_count(atoms_list_count)

        simple_logger.log_statistics_message(request.remote_addr,
                                             endpoint_name='get_info',
                                             number_of_molecules=molecules_count,
                                             number_of_atoms=atom_count,
                                             number_of_individdual_atoms=atoms_dict_count)

        return OKResponse({'Number of molecules': molecules_count,
                           'Number of atoms': atom_count,
                           'Number of individual atoms': atoms_dict_count}).json



# parser for query arguments
suit_parser = reqparse.RequestParser()
suit_parser.add_argument('structure_id',
                         type=str,
                         help='Obtained structure identifier of your structure',
                         required=True)
suit_parser.add_argument('read_hetatm',
                         type=bool,
                         help='Use in case that you would like to read '
                              'not only the protein, but also ligands.\n'
                              'Default: True')
suit_parser.add_argument('ignore_water',
                         type=bool,
                         help='Use in case that you would like to ignore '
                              'water molecules.\n'
                              'Default: False')


@suitable_methods.route('')
@api.doc(responses={404: 'Structure ID not specified',
                    400: 'Structure ID does not exist or input file is not correct',
                    200: 'OK'})
@api.expect(suit_parser)
class SuitableMethods(Resource):
    def get(self):
        """Get calculation methods suitable for your molecule."""
        structure_id = request.args.get('structure_id')
        read_hetatm = request.args.get('read_hetatm')
        ignore_water = request.args.get('ignore_water')
        if not structure_id:
            simple_logger.log_error_message(request.remote_addr,
                                            'suitable_methods',
                                            'User did not specify structure id')
            return ErrorResponse(f'You have not specified structure ID obtained after uploading your file. '
                                 f'Add to URL following, please: ?structure_id=obtained_structure_id').json

        read_hetatm = get_read_hetatm_value(read_hetatm)  # default: True
        ignore_water = get_ignore_water_value(ignore_water)  # default False

        try:
            structure = Structure(structure_id)
            suitable_methods = structure.get_suitable_methods(read_hetatm, ignore_water)
        except ValueError as e:
            simple_logger.log_error_message(request.remote_addr,
                                            'suitable_methods',
                                            f'{str(e)}')
            return ErrorResponse(str(e), status_code=400).json

        simple_logger.log_statistics_message(request.remote_addr,
                                             endpoint_name='suitable_methods',
                                             suitable_methods=suitable_methods)
        return OKResponse({'suitable_methods': suitable_methods}).json


class CalculationTask:
    def __init__(self, priority, calculation_id, user_id, molecules, method, parameters):
        self._priority = priority
        self._calculation_id = calculation_id
        self._user_id = user_id
        self._molecules = molecules
        self._method = method
        self._parameters = parameters

    @property
    def priority(self):
        return self._priority

    @property
    def calculation_id(self):
        return self._calculation_id

    @property
    def user_id(self):
        return self._user_id

    def get_molecules(self):
        return self._molecules

    def get_method(self):
        return self._method

    def get_parameters(self):
        return self._parameters

    def __lt__(self, other):
        return self._priority < other.priority

    def __gt__(self, other):
        return self._priority > other.priority


priority_queue = PriorityQueue()


@calculate_time
def round_charges(charges):
    rounded_charges = []
    for key in charges.keys():
        tmp = {}
        tmp[key] = list(map(lambda x: round(x, 4), charges[key]))
        rounded_charges.append(tmp)
    return rounded_charges


calc_results = manager.dict()


class CalculationResult:
    def __init__(self, calc_time, charges, method, parameters):
        self._calc_time = calc_time
        self._charges = charges
        self._method = method
        self._parameters = parameters

    @property
    def calc_time(self):
        return self._calc_time

    def get_charges(self):
        return self._charges

    @property
    def method(self):
        return self._method

    @property
    def parameters(self):
        return self._parameters



def calc_charges(molecules, method, parameters, calculation_id):
    calc_start = time.perf_counter()
    charges = chargefw2_python.calculate_charges(molecules, method, parameters)
    calc_end = time.perf_counter()

    if config['limits']['on'] == 'True':
        if calc_end - calc_start > float(config['limits']['calc_time']):
            add_long_calc(long_calculations, request.remote_addr)

    rounded_charges = round_charges(charges)
    result_of_calculation = CalculationResult(round(calc_end - calc_start, 2), rounded_charges, method, parameters)
    return result_of_calculation


priorities = manager.dict()  # {user_id: number_of_calculations_in_queue}


calc_parser = reqparse.RequestParser()
calc_parser.add_argument('structure_id',
                         type=str,
                         help='Obtained structure identifier of your structure',
                         required=True)
calc_parser.add_argument('method',
                         type=str,
                         help='Calculation method.')
calc_parser.add_argument('parameters',
                         type=str,
                         help='Parameters set by specific method')
calc_parser.add_argument('read_hetatm',
                         type=bool,
                         help='Use in case that you would like to read '
                              'not only the protein, but also ligands.\n'
                              'Default: True')
calc_parser.add_argument('ignore_water',
                         type=bool,
                         help='Use in case that you would like to ignore '
                              'water molecules.\n'
                              'Default: False')


@calculate_charges.route('')
@api.doc(responses={404: 'Structure ID not specified',
                    400: 'Structure ID does not exist/'
                         'input file is not correct/'
                         'method is not available/'
                         'method is not suitable for dataset/'
                         'wrong or incompatible parameters',
                    200: 'OK'})
@api.expect(calc_parser)
class CalculateCharges(Resource):
    @calculate_time
    def get(self):
        structure_id = request.args.get('structure_id')
        method = request.args.get('method')
        parameters = request.args.get('parameters')

        read_hetatm = request.args.get('read_hetatm')
        ignore_water = request.args.get('ignore_water')

        read_hetatm = get_read_hetatm_value(read_hetatm)  # default: True
        ignore_water = get_ignore_water_value(ignore_water)  # default False

        if not structure_id:
            simple_logger.log_error_message(request.remote_addr,
                                            'calculate_charges',
                                            'User did not specify structure id')
            return ErrorResponse(f'You have not specified structure ID obtained after uploading your file. '
                                 f'Add to URL following, please: ?structure_id=obtained_structure_id').json

        try:
            structure = Structure(structure_id)
            suitable_methods = structure.get_suitable_methods(read_hetatm, ignore_water)
        except ValueError as e:
            simple_logger.log_error_message(request.remote_addr, 'calculate_charges', str(e))
            return ErrorResponse(str(e), 400).json

        if method:
            # method is not available
            if method not in chargefw2_python.get_available_methods():
                simple_logger.log_error_message(request.remote_addr,
                                                'calculate_charges',
                                                'User wanted to use method that is not available',
                                                method=method)
                return ErrorResponse(f'Method {method} is not available.', status_code=400).json

            if parameters and parameters not in chargefw2_python.get_available_parameters(method):
                simple_logger.log_error_message(request.remote_addr,
                                                'calculate_charges',
                                                f'Parameters {parameters} are not available for method {method}')
                return ErrorResponse(f'Parameters {parameters} are not available for method {method}').json

        if not method:
            method = suitable_methods[0]['method']
            if not suitable_methods[0]['parameters']:
                parameters = None
            else:
                parameters = suitable_methods[0]['parameters'][0]

        try:
            molecules = structure.get_molecules(read_hetatm, ignore_water)
        except ValueError as e:
            simple_logger.log_error_message(request.remote_addr,
                                            'calculate_charges',
                                            str(e))
            return ErrorResponse(str(e)).json

        # try:
        if config['limits']['on'] == 'True':
            if request.remote_addr in long_calculations and long_calculations[request.remote_addr] >= int(
                    config['limits']['max_long_calc']):
                simple_logger.log_error_message(request.remote_addr,
                                                'calculate_charges',
                                                'User has too many time demanding calculations per day')
                return ErrorResponse(
                    f'You can perform only {config["limits"]["max_long_calc"]} time demanding calculations per day.').json

        calculation_id = pathlib.Path((tempfile.NamedTemporaryFile(prefix=structure_id).name)).name
        calc_results[calculation_id] = None

        try:
            results = calc_charges(molecules, method, parameters, calculation_id)
        except RuntimeError as e:
            simple_logger.log_error_message(request.remote_addr,
                                            'calculate_charges',
                                            str(e))
            return ErrorResponse(str(e)).json

        suffix = structure.get_structure_file()[-3:]
        molecules_count, atom_count, atoms_list_count = chargefw2_python.get_info(molecules)
        simple_logger.log_statistics_message(request.remote_addr,
                                             endpoint_name='calculate_charges',
                                             suffix=suffix,
                                             number_of_molecules=molecules_count,
                                             number_of_atoms=atom_count,
                                             method=method,
                                             parameters=parameters)
        return OKResponse(
            {'charges': results.get_charges(), 'method': results.method, 'parameters': results.parameters}).json


def calculation_process():
    print('Before popping')
    for calc_task in iter(priority_queue.get, None):
        print('I have a task')
        # try:
        result = calc_charges(calc_task.get_molecules(), calc_task.get_method, calc_task.get_parameters,
                              calc_task.calculation_id)

        users_calculations_in_queue = priorities[request.remote_addr]
        if users_calculations_in_queue == 1:
            del priorities[request.remote_addr]
        priorities[request.remote_addr] = users_calculations_in_queue - 1

        calc_results[calculation_id] = {'charges': result.get_charges(),
                                        'method': result.method,
                                        'parameters': result.parameters}
        # except RuntimeError as e:
        #     calc_results[calculation_id] = e


process_running_calculations = Process(target=calculation_process)
process_running_calculations.start()

get_calc_results_parser = reqparse.RequestParser()
get_calc_results_parser.add_argument('calculation_id',
                                     type=str,
                                     help='Obtained calculation identifier',
                                     required=True)


@get_calculation_results.route('')
@api.expect(get_calc_results_parser)
class GetCalculationResults(Resource):
    def get(self):
        calc_id = request.args.get('calculation_id')
        if not calc_id:
            return ErrorResponse(f'You have not specified calculation ID obtained after calculation request. '
                                 f'Add to URL following, please: ?calculation_id=obtained_calculation_id').json
        if not calc_id in calc_results:
            return ErrorResponse('Calculation ID does not exist.').json
        if not calc_results[calc_id]:
            # print(calc_results[calc_id])
            return ErrorResponse(f'The calculation has not yet been completed.').json

        charges = calc_results[calc_id]['charges']
        method = calc_results[calc_id]['method']
        parameters = calc_results[calc_id]['parameters']
        # remove charges from calc_results
        del calc_results[calc_id]
        return OKResponse({'charges': charges, 'method': method, 'parameters': parameters}).json


class Limits:
    def __init__(self, user):
        self._user = user

    def get_users_files_info(self):
        """Returns id, file name and info when the file was lastly modified for particular use"""
        files_info = []
        ids = user_id_manager[self._user]
        for id in ids:
            path_to_file = pathlib.Path(file_manager[id])
            file_name = path_to_file.name
            files_info.append(f'ID: {id}, '
                              f'name of file: {file_name}, '
                              f'file was last modified before {round(time.time() - path_to_file.stat().st_mtime, 2)}s.')
        return '\n'.join(files_info)

    def get_limits(self):
        if config['limits']['on'] == 'True':
            file_size = int(config['limits']['file_size'])
            max_long_calc = int(config['limits']['max_long_calc'])
            # self._user = request.remote_addr
            if self._user in long_calculations:
                curr_user_has_long_calc = long_calculations[self._user]
            else:
                curr_user_has_long_calc = 0
            if self._user in user_id_manager:
                files_info = self.get_users_files_info()
            else:
                files_info = 'Currently you have no uploaded structures - no ids.'
            return jsonify({'Max file size': file_size,
                            'Max allowed long calculations': max_long_calc,
                            'You are allowed to have long calculations': max_long_calc - curr_user_has_long_calc,
                            'Your files': files_info,
                            'Removing files': f'Files that was not modified '
                                              f'for more than {int(config["remove_tmp"]["older_than"])}s '
                                              f'are removed once every {int(config["remove_tmp"]["every_x_seconds"])}s.',
                            'Granted space': int(config['limits']['granted_space']),
                            'Your used space': used_space.get(self._user, 0)})
        return jsonify({'message': 'No restrictions turned on'})


@get_limits.route('')
class GetLimitsEndpoint(Resource):
    def get(self):
        limits = Limits(request.remote_addr)
        return limits.get_limits()


def add_long_calc(dict, user_add):
    """Add long calculation to user"""
    dict[user_add] = dict.get(user_add, 0) + 1


def increase_limit():
    to_delete = []
    for user in long_calculations:
        if long_calculations[user] > 1:
            long_calculations[user] -= 1
        else:
            to_delete.append(user)
    for user in to_delete:
        del long_calculations[user]


class RepeatTimer(Timer):
    def run(self):
        while not self.finished.wait(self.interval):
            self.function(*self.args, **self.kwargs)


limitations_on = False

# limits in api.ini are enabled
if config['limits']['on'] == 'True':
    limitations_on = True
    long_calculations = manager.dict()
    used_space = manager.dict()
    del_timer = RepeatTimer(float(config['limits']['decrease_restriction']), increase_limit)
    del_timer.start()

file_manager = manager.dict()  # id: path_to_file
user_id_manager = manager.dict()  # {user:[id1, id2]}


def delete_id_from_user(identifier):
    for user in user_id_manager:
        if identifier in user_id_manager[user]:
            user_id_manager[user].remove(identifier)
            if len(user_id_manager[user]) == 0:
                del user_id_manager[user]
            break


def delete_old_records():
    removed = []  # TODO testing purposes
    identifiers = file_manager.keys()
    for identifier in identifiers:
        path_to_id = pathlib.Path(file_manager[identifier])
        file_is_old = time.time() - path_to_id.stat().st_mtime
        if file_is_old > float(config['remove_tmp']['older_than']):
            removed.append(file_manager[identifier])  # TODO testing purposes
            # delete id and path_to structure from file_manager
            del file_manager[identifier]
            # delete id from ids of user
            delete_id_from_user(identifier)
            with open(config['remove_tmp']['log'], mode='a') as output:
                output.write(f'{date.today().strftime("%d/%m/%Y")}, '
                             f'{time.strftime("%H:%M:%S", time.localtime())} '
                             f'Removing {path_to_id}, '
                             f'File was last modified before {round(file_is_old, 2)}s.\n')
            os.remove(path_to_id)
            path_to_id.parent.rmdir()
    return removed  # TODO testing purposes


# Remove file manager and tmp files repeatedly
remove_tmp = RepeatTimer(float(config['remove_tmp']['every_x_seconds']), delete_old_records)
remove_tmp.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0')

