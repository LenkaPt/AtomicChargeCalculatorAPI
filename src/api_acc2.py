from flask import Flask, render_template, request, send_file, jsonify
from flask_restx import Api, Resource, reqparse
from werkzeug.datastructures import FileStorage
from typing import Dict, Any, Union, List, Tuple, Callable
from multiprocessing import Process, Manager
import tempfile
import os
import chargefw2_python
import requests
import subprocess
import time
from datetime import date
import configparser
import pathlib
import logging
from io import BytesIO
from zipfile import ZipFile

from Responses import OKResponse, ErrorResponse
from Structures import Structure, Method, CalculationResult
from Logger import Logger, logging_process
from File import File
from remove_old_files import RepeatTimer, delete_id_from_user, delete_old_records

config = configparser.ConfigParser()
config.read('/home/api_acc2/api_acc2/utils/api.ini')
app = Flask(__name__)
if config['limits']['on'] == 'True':
    app.config['MAX_CONTENT_LENGTH'] = int(config['limits']['file_size'])
api = Api(app,
          title='Atomic Charge Calculator II - API',
          description='Atomic Charge Calculator II is software tool '
                      'designated for calculation of partial atomic charges.\n'
                      '<br>'
                      '<a href="http://78.128.250.156/documentation">Documentation</a>')


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
                          description='Add hydrogens to your structure.')

get_structure_file = api.namespace('get_structure_file',
                                   description='Get structure file saved under specific ID.')

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

calc_charges = api.namespace('calculate_charges',
                             description='Calculate partial atomic charges.')

get_calculation_results = api.namespace('get_calculation_results',
                                        description='Get results from calculation of partial atomic charges')

get_limits = api.namespace('get_limits',
                           description='Get info about limits, your files.')


def calculate_time(func: Callable) -> Callable:
    """Decorator for time measurement of function run"""
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


manager = Manager()
queue = manager.Queue()
log_process = Process(target=lambda: logging_process(queue, config['paths']['log_error'],
                                                     config['paths']['save_statistics_file']))
log_process.start()
simple_logger = Logger('simple', logging.INFO, queue)


@avail_methods.route('')
class AvailableMethodsEndpoint(Resource):
    def get(self) -> Dict[str, Union[List[str], int]]:
        """Returns list of methods available for calculation of partial atomic charges"""
        available_methods = chargefw2_python.get_available_methods()
        response = OKResponse(data={'available_methods': available_methods}, request=request)
        response.log(simple_logger)
        return response.json


@avail_params.route('')
@api.doc(params={'method': {'description': 'Calculation method', 'type': 'string', 'required': True, 'in': 'query'}},
         responses={404: 'Method not specified',
                    400: 'Method not available',
                    200: 'OK'})
class AvailableParametersEndpoint(Resource):
    def get(self) -> Union[Tuple[Dict[str, Union[str, int]], int], Dict[str, Union[List[str], int]]]:
        """Returns list of available parameters for specific method"""
        method = request.args.get('method')
        if not method:
            response = ErrorResponse(message=f'Method not specified', request=request)
            response.log(simple_logger)
            return response.json

        try:
            parameters = Method(method).get_available_parameters()
        except ValueError as e:
            response = ErrorResponse(str(e), status_code=400, request=request)
            response.log(simple_logger)
            return response.json

        response = OKResponse(data={'parameters': parameters}, request=request)
        response.log(simple_logger)
        return response.json


def save_file_identifiers(identifiers: Dict[str, Union[str, os.PathLike]]) -> None:
    """Assignes identifier of file to specific user and saves identifier and path to the file"""
    if request.remote_addr not in user_id_manager:
        user_id_manager[request.remote_addr] = manager.list()
    for identifier, path_to_file in identifiers.items():
        file_manager[identifier] = path_to_file
        user_id_manager[request.remote_addr].append(identifier)
        # {user: [id1, id2]}


def user_has_no_space(file: File, user: str) -> bool:
    """Determines wheter specific user has some space available on disk"""
    if limitations_on and user in used_space:
        if file.get_size() + used_space[user] > int(config['limits']['granted_space']):
            return True
    if limitations_on:
        used_space[user] = used_space.get(user, 0) + file.get_size()
    return False


def generate_tmp_directory() -> os.PathLike:
    """Generates directory for saving uploaded files"""
    return tempfile.mkdtemp(dir=config['paths']['save_user_files'])


file_parser = api.parser()
file_parser.add_argument('file[]', location='files', type=FileStorage, required=True)
@send_files.route('')
@api.doc(responses={404: 'No file sent',
                    400: 'Unsupported format',
                    413: 'File is too large',
                    429: 'The grounded disk space was exceeded',
                    200: 'OK'})
@api.expect(file_parser)
class SendFilesEndpoint(Resource):
    def post(self) -> Union[Tuple[Dict[str, Union[str, int]], int], Dict[str, Any]]:
        """Send files in pdb, sdf or cif format"""
        files = request.files.getlist('file[]')
        if not files:
            response = ErrorResponse(message=f'No file sent', request=request)
            response.log(simple_logger)
            return response.json

        uploaded_files = {}
        user_response = {}
        all_uploaded = True
        tmpdir = generate_tmp_directory()
        for file in files:
            file = File(file, tmpdir)

            if not file.has_valid_suffix():
                response = ErrorResponse(message=f'File is in unsupported format. '
                                                 f'Send only .sdf, .mol2, .cif and .pdb files.',
                                         status_code=400,
                                         request=request)
                response.log(simple_logger)
                return response.json

            file.save()
            # user has limited space
            if user_has_no_space(file, request.remote_addr):
                all_uploaded = False
                break

            file.convert_line_endings_to_unix_style()
            uploaded_files[file.get_id()] = file.get_path()
            user_response[file.get_filename()[:-4]] = file.get_id()

        save_file_identifiers(uploaded_files)

        if all_uploaded:
            response = OKResponse(data={'structure_ids': user_response}, request=request)
            response.log(simple_logger)
            return response.json
        # some ids were uploaded, but not all because the limited disk space
        elif not all_uploaded and user_response:
            return jsonify({'message': 'You have exceeded the grounded disk space',
                            'status_code': 429,
                            'successfully_uploaded_structure_ids': user_response})
        else:
            response = ErrorResponse(message='Grounted disk space exceeded', status_code=413, request=request)
            response.log(simple_logger)
            return response.json


def send_request(url: str)  -> Dict[str, Any]:
    """Sends request to specific url"""
    successfull = True
    error_message = None
    r = requests.get(url, stream=True)
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        successfull = False
        error_message = e
    return {'successfull': successfull, 'response': r, 'error_message': error_message}


def send_pdb_request(pdb_id: str) -> Dict[str, Any]:
    """Sends request to PDB database"""
    url = 'https://files.rcsb.org/download/' + pdb_id + '.cif'
    response = send_request(url)
    return response


# parser for query arguments
pid_parser = reqparse.RequestParser()
pid_parser.add_argument('pid[]', type=str, help='PDB ID', action='append', required=True)
@pid.route('')
@api.doc(responses={404: 'No PDB iD specified or PDB ID does not exist',
                    200: 'OK',
                    413: 'File bigger than 10 Mb',
                    429: 'The grounded disk space was exceeded'})
@api.expect(pid_parser)
class PdbID(Resource):
    def post(self) -> Union[Tuple[Dict[str, Union[str, int]], int], Dict[str, Any]]:
        """Specify PDB ID of your structure."""
        pdb_identifiers = request.args.getlist('pid[]')
        if not pdb_identifiers:
            response = ErrorResponse(message='No pdb id specified.', request=request)
            response.log(simple_logger)
            return response.json

        tmpdir = generate_tmp_directory()
        uploaded_files = {}
        user_response = {}
        all_uploaded = True
        for pdb_id in pdb_identifiers:
            # get file from pdb
            request_response = send_pdb_request(pdb_id)
            if not request_response['successfull']:
                error_message = request_response['error_message']
                response = ErrorResponse(message=f'{error_message}',
                                         status_code=request_response['response'].status_code,
                                         request=request)
                response.log(simple_logger)
                return response.json

            # save requested pdb structure
            file = File(os.path.join(f'{pdb_id}.cif'), tmpdir)
            successfully_written_file = file.write_file(request_response['response'], config)
            if not successfully_written_file:
                response = ErrorResponse(message=f'Not possible to upload {pdb_id}. It is bigger than 10 Mb.',
                                         status_code=413,
                                         request=request)
                response.log(simple_logger)
                return response.json

            # user has limited space
            if user_has_no_space(file, request.remote_addr):
                all_uploaded = False
                break

            uploaded_files[file.get_id()] = file.get_path()
            user_response[file.get_filename()[:-4]] = file.get_id()

        save_file_identifiers(uploaded_files)

        if all_uploaded:
            response = OKResponse(data={'structure_ids': user_response}, request=request)
            response.log(simple_logger)
            return response.json
        # some ids were uploaded, but not all because the limited disk space
        elif not all_uploaded and user_response:
            return jsonify({'message': 'You have exceeded the grounded disk space',
                            'status_code': 429,
                            'successfully_uploaded_structure_ids': user_response})
        else:
            response = ErrorResponse(message='Grounted disk space exceeded', status_code=413, request=request)
            response.log(simple_logger)
            return response.json


def send_pubchem_request(cid: str) -> Dict[str, Any]:
    """Sends request to PubChem database"""
    url = f'https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/CID/{cid}' \
          f'/record/SDF/?record_type=3d&response_type=save&response_basename=Conformer3D_CID_{cid}'
    response = send_request(url)
    return response


# parser for query arguments
pubchem_parser = reqparse.RequestParser()
pubchem_parser.add_argument('cid[]', type=int, help='Compound CID', action='append', required=True)
@cid.route('')
@api.doc(responses={404: 'No Pubchem compound ID specified or compound ID does not exist',
                    200: 'OK',
                    413: 'File bigger than 10 Mb',
                    429: 'The grounded disk space was exceeded'})
@api.expect(pubchem_parser)
class PubchemCID(Resource):
    def post(self) -> Union[Tuple[Dict[str, Union[str, int]], int], Dict[str, Any]]:
        """Specify Pubchem CID of your structure."""
        cid_identifiers = request.args.getlist('cid[]')
        if not cid_identifiers:
            response = ErrorResponse(message='No pubchem cid specified.', request=request)
            response.log(simple_logger)
            return response.json

        tmpdir = generate_tmp_directory()
        uploaded_files = {}
        user_response = {}
        all_uploaded = True
        for cid in cid_identifiers:
            # get file from pubchem
            request_response = send_pubchem_request(cid)
            if not request_response['successfull']:
                error_message = request_response['error_message']
                response = ErrorResponse(message=f'{error_message}',
                                         status_code=request_response['response'].status_code,
                                         request=request)
                response.log(simple_logger)
                return response.json

            # save requested cid compound
            file = File(os.path.join(f'{cid}.sdf'), tmpdir)
            successfully_written_file = file.write_file(request_response['response'], config)
            if not successfully_written_file:
                response = ErrorResponse(message=f'Not possible to upload {cid}. It is bigger than 10 Mb.',
                                         status_code=413,
                                         request=request)
                response.log(simple_logger)
                return response.json

            # user has limited space
            if user_has_no_space(file, request.remote_addr):
                all_uploaded = False
                break

            uploaded_files[file.get_id()] = file.get_path()
            user_response[file.get_filename()[:-4]] = file.get_id()

        save_file_identifiers(uploaded_files)

        if all_uploaded:
            response = OKResponse(data={'structure_ids': user_response}, request=request)
            response.log(simple_logger)
            return response.json
        # some ids were uploaded, but not all because the limited disk space
        elif not all_uploaded and user_response:
            return jsonify({'message': 'You have exceeded the grounded disk space',
                            'status_code': 429,
                            'successfully_uploaded_structure_ids': user_response})
        else:
            response = ErrorResponse(message='Grounted disk space exceeded', status_code=413, request=request)
            response.log(simple_logger)
            return response.json


def release_space(file_size: float, user: str) -> None:
    """Release space on disk for specific user"""
    if limitations_on:
        if used_space[user] - file_size <= 0:
            del used_space[user]
        else:
            used_space[user] = used_space[user] - file_size


remove_file_parser = reqparse.RequestParser()
remove_file_parser.add_argument('structure_id',
                                type=str,
                                help='Obtained structure identifier of your structure',
                                required=True)
@api.doc(responses={404: 'Structure ID not specified',
                    400: 'Structure ID does not exist',
                    403: 'Not allowed to remove the structure',
                    200: 'OK'})
@api.expect(remove_file_parser)
@remove_file.route('')
class RemoveFile(Resource):
    def post(self) -> Union[Tuple[Dict[str, Union[str, int]], int], Dict[str, Any]]:
        """Remove file specified by structure_id"""
        structure_id = request.args.get('structure_id')
        if not structure_id:
            response = ErrorResponse(message=f'Structure ID not specified', request=request)
            response.log(simple_logger)
            return response.json
        try:
            structure = Structure(structure_id, file_manager)
        except ValueError:
            response = ErrorResponse(message=f'Structure ID {structure_id} does not exist.',
                                     status_code=400,
                                     request=request)
            response = response
            return response.json

        if structure_id not in user_id_manager[request.remote_addr]:
            response = ErrorResponse(message=f'It is not allowed to remove {structure_id}.',
                                     status_code=403,
                                     request=request)
            response.log(simple_logger)
            return response.json

        path_to_file = pathlib.Path(structure.get_structure_file())
        file = File(str(pathlib.Path(path_to_file.name)), path_to_file.parent)

        # remove from file_manager and user_id_manager
        del file_manager[structure_id]
        delete_id_from_user(structure_id, user_id_manager)
        # release space
        release_space(file.get_size(), request.remote_addr)
        file.remove()

        response = OKResponse(data={structure_id: 'removed'}, request=request)
        response.log(simple_logger)
        return response.json


def convert_pqr_to_pdb(pqr_file: os.PathLike, pdb_file: os.PathLike) -> None:
    """Converts .pqr to .pdb format - using open babel"""
    try:
        subprocess.run(['obabel', f'-ipqr', f'{pqr_file}', f'-opdb', f'-O{pdb_file}'], check=True)
    except subprocess.CalledProcessError:
        raise ValueError('Error converting from .pqr to .pdb format using openbabel.')


def run_pqr(noopt: bool, ph: str, input_file: os.PathLike, path_to_pqr: os.PathLike) -> bool:
    """Add hydrogens using pdb2pqr"""
    successfull = True
    try:
        if noopt:
            subprocess.run(['pdb2pqr30', f'--noopt', f'--pH', f'{ph}', f'{input_file}', f'{path_to_pqr}'], check=True)
        else:
            subprocess.run(['pdb2pqr30', f'--pH', f'{ph}', f'{input_file}', f'{path_to_pqr}'], check=True)
    except subprocess.CalledProcessError:
        successfull = False
    return successfull


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
    def post(self) -> Union[Tuple[Dict[str, Union[str, int]], int], Dict[str, Union[str, int]]]:
        """Add hydrogens to your structure represented by an structure identifier"""
        structure_id = request.args.get('structure_id')
        if not structure_id:
            response = ErrorResponse(message=f'Structure ID not specified', request=request)
            response.log(simple_logger)
            return response.json

        ph = request.args.get('pH')
        if not ph:
            ph = float(config['pH']['default'])

        try:
            structure = Structure(structure_id, file_manager)
            input_file = structure.get_pdb_input_file()
        except ValueError as e:
            response = ErrorResponse(f'{str(e)}', status_code=400, request=request)
            response.log(simple_logger)
            return response.json

        output_dir = generate_tmp_directory()
        pqr_file = File(structure_id + '.pqr', output_dir)
        path_to_pqr = pathlib.Path(pqr_file.get_path())
        pdb_file = File(structure_id + 'pdb', output_dir)
        path_to_pdb = pathlib.Path(pdb_file.get_path())

        # hydrogen bond optimalization
        noopt = request.args.get('noopt')

        successful = run_pqr(noopt, ph, input_file, path_to_pqr)
        if not successful:
            response = ErrorResponse(f'Error occurred when using pdb2pqr30 on structure {structure_id}',
                                     status_code=405,
                                     request=request)
            response.log(simple_logger)
            return response.json

        pdb_file_id = pdb_file.get_id()
        try:
            convert_pqr_to_pdb(path_to_pqr, path_to_pdb)
        except ValueError as e:
            response = ErrorResponse(f'{str(e)}', status_code=405, request=request)
            response.log(simple_logger)
            return response.json
        save_file_identifiers({pdb_file_id: path_to_pdb})

        response = OKResponse(data={'structure_id': pdb_file_id}, request=request)
        response.log(simple_logger)
        return response.json


def create_zip_file(folder: pathlib.Path) -> BytesIO:
    """Returns zip file"""
    stream = BytesIO()
    with ZipFile(stream, 'w') as zf:
        for file in folder.glob('*'):
            zf.write(file, file.name)
    stream.seek(0)
    return stream


# parser for query arguments
file_parser = reqparse.RequestParser()
file_parser.add_argument('structure_id',
                         type=str,
                         help='Obtained structure identifier of your structure',
                         required=True)
@get_structure_file.route('')
@api.doc(responses={404: 'Structure ID not specified',
                    400: 'Structure ID does not exist'})
@api.expect(file_parser)
class StructureFile(Resource):
    """Allows to download the structure specified by structure ID"""
    def get(self):
        structure_id = request.args.get('structure_id')
        if not structure_id:
            response = ErrorResponse(message=f'Structure ID not specified', request=request)
            response.log(simple_logger)
            return response.json
        try:
            file = Structure(structure_id, file_manager).get_structure_file()
        except ValueError as e:
            response = ErrorResponse(str(e), 400, request)
            response.log(simple_logger)
            return response.json

        zip_file = create_zip_file(pathlib.Path(file).parent)
        return send_file(zip_file, download_name='structures.zip', as_attachment=True)


def get_bool_value(original: Union[None, str]) -> bool:
    """Get boolean value - set to default if parameters not specified"""
    if original:
        original = original.lower()
    return original == 'true'


def get_individual_atoms_count(atoms_count: List[Tuple[str, int]]) -> Dict[str, int]:
    """Get dictionary of atoms count - atom as key, count as value"""
    result = {}
    for atom_count in atoms_count:
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
    def get(self) -> Union[Tuple[Dict[str, Union[str, int]], int], Dict[str, Any]]:
        """Get info about your molecule."""
        structure_id = request.args.get('structure_id')
        read_hetatm = request.args.get('read_hetatm')
        ignore_water = request.args.get('ignore_water')
        if not structure_id:
            response = ErrorResponse(message=f'Structure ID not specified', request=request)
            response.log(simple_logger)
            return response.json

        read_hetatm = get_bool_value(read_hetatm)  # default: True
        ignore_water = get_bool_value(ignore_water)  # default False

        try:
            structure = Structure(structure_id, file_manager)
            molecules = structure.get_molecules(read_hetatm, ignore_water)
        except ValueError as e:
            response = ErrorResponse(str(e), status_code=400, request=request)
            response.log(simple_logger)
            return response.json

        molecules_count, atom_count, atoms_count = chargefw2_python.get_info(molecules)
        individual_atoms_count = get_individual_atoms_count(atoms_count)

        response = OKResponse(data={'Number of molecules': molecules_count,
                                    'Number of atoms': atom_count,
                                    'Number of individual atoms': individual_atoms_count},
                              request=request)
        response.log(simple_logger)
        return response.json


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
    def get(self) -> Union[Tuple[Dict[str, Union[str, int]], int], Dict[str, List[Dict[str, List[str]]]]]:
        """Get calculation methods suitable for your molecule."""
        structure_id = request.args.get('structure_id')
        read_hetatm = request.args.get('read_hetatm')
        ignore_water = request.args.get('ignore_water')
        if not structure_id:
            response = ErrorResponse(message=f'Structure ID not specified', request=request)
            response.log(simple_logger)
            return response.json

        read_hetatm = get_bool_value(read_hetatm)  # default: True
        ignore_water = get_bool_value(ignore_water)  # default False

        try:
            structure = Structure(structure_id, file_manager)
            suitable_methods = structure.get_suitable_methods(read_hetatm, ignore_water)
        except ValueError as e:
            response = ErrorResponse(str(e), status_code=400, request=request)
            response.log(simple_logger)
            return response.json

        response = OKResponse(data={'suitable_methods': suitable_methods}, request=request)
        response.log(simple_logger)
        return response.json


@calculate_time
def round_charges(charges: Dict[str, Union[str, List[str]]]) -> Dict[str, Union[str, List[str]]]:
    """Rounds calculated charges"""
    rounded_charges = {}
    for key in charges.keys():
        rounded_charges[key] = list(map(lambda x: round(x, 4), charges[key]))
    return rounded_charges


def calculate_charges(molecules: chargefw2_python.Molecules, method: str, parameters: str) -> CalculationResult:
    """Function calculates charges"""
    calc_start = time.perf_counter()
    charges = chargefw2_python.calculate_charges(molecules, method, parameters)
    calc_end = time.perf_counter()

    rounded_charges = round_charges(charges)
    result_of_calculation = CalculationResult(round(calc_end - calc_start, 2), rounded_charges, method, parameters)
    return result_of_calculation


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
calc_parser.add_argument('generate_mol2',
                         type=bool,
                         help='Use in case that you want to generate charges '
                              'into mol2 format instead of returning list of charges.\n'
                              'Default: False')
@calc_charges.route('')
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
    def get(self) -> Union[Tuple[Dict[str, Union[str, int]], int], Dict[str, Any]]:
        """Calculates partial atomic charges"""
        structure_id = request.args.get('structure_id')
        method = request.args.get('method')
        parameters = request.args.get('parameters')

        read_hetatm = request.args.get('read_hetatm')
        ignore_water = request.args.get('ignore_water')
        generate_mol2 = request.args.get('generate_mol2')


        read_hetatm = get_bool_value(read_hetatm)  # default: True
        ignore_water = get_bool_value(ignore_water)  # default False
        generate_mol2 = get_bool_value(generate_mol2)  # default False

        if not structure_id:
            response = ErrorResponse(message=f'Structure ID not specified', request=request)
            response.log(simple_logger)
            return response.json

        try:
            structure = Structure(structure_id, file_manager)
        except ValueError as e:
            response = ErrorResponse(str(e), 400, request)
            response.log(simple_logger)
            return response.json

        if method:
            # method is not available
            if method not in chargefw2_python.get_available_methods():
                response = ErrorResponse(f'Method {method} is not available.', status_code=400, request=request)
                response.log(simple_logger)
                return response.json

        if not method:
            suitable_methods = structure.get_suitable_methods(read_hetatm, ignore_water)
            method = suitable_methods[0]['method']
            if not suitable_methods[0]['parameters']:
                parameters = None
            else:
                parameters = suitable_methods[0]['parameters'][0]

        try:
            molecules = structure.get_molecules(read_hetatm, ignore_water)
        except ValueError as e:
            response = ErrorResponse(str(e), request=request)
            response.log(simple_logger)
            return response.json

        if config['limits']['on'] == 'True':
            if request.remote_addr in long_calculations and \
                    long_calculations[request.remote_addr] >= int(config['limits']['max_long_calc']):
                response = ErrorResponse(message=f'It is allowed to perform only {config["limits"]["max_long_calc"]} '
                                                 f'time demanding calculations per day.',
                                         request=request)
                response.log(simple_logger)
                return response.json

        try:
            result = calculate_charges(molecules, method, parameters)
        except RuntimeError as e:
            response = ErrorResponse(str(e), request=request)
            response.log(simple_logger)
            return response.json

        if config['limits']['on'] == 'True':
            if result.calc_time > float(config['limits']['calc_time']):
                add_long_calc(long_calculations, request.remote_addr)

        suffix = structure.get_structure_file()[-3:]
        molecules_count, atom_count, atoms_list_count = chargefw2_python.get_info(molecules)

        response = OKResponse(data={'charges': result.get_charges(), 'method': result.method,
                                    'parameters': result.parameters},
                              request=request)
        if not request.args.get('method'):
            response.log(simple_logger,
                         time=result.calc_time,
                         suffix=suffix,
                         number_of_molecules=molecules_count,
                         number_of_atoms=atom_count,
                         method=method,
                         parameters=parameters)
        else:
            response.log(simple_logger,
                         time=result.calc_time,
                         suffix=suffix,
                         number_of_molecules=molecules_count,
                         number_of_atoms=atom_count)

        if generate_mol2:
            tmpdir = generate_tmp_directory()
            path = tmpdir + structure_id + '.mol2'
            chargefw2_python.save_mol2(molecules, result.get_charges(), path)
            return send_file(path, as_attachment=True)

        return response.json


class Limits:
    def __init__(self, user: str):
        self._user = user

    def get_users_files_info(self) -> str:
        """Returns id, file name and info when the file was lastly modified for particular use"""
        files_info = []
        ids = user_id_manager[self._user]
        for _id in ids:
            path_to_file = pathlib.Path(file_manager[_id])
            file_name = path_to_file.name
            files_info.append(f'ID: {_id}, '
                              f'name of file: {file_name}, '
                              f'file was last modified before {round(time.time() - path_to_file.stat().st_mtime, 2)}s.')
        return '\n'.join(files_info)

    def get_limits(self) -> Dict[str, Any]:
        """Returns info about current limits for the specific user"""
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
                                              f'are removed once every '
                                              f'{int(config["remove_tmp"]["every_x_seconds"])}s.',
                            'Granted space': int(config['limits']['granted_space']),
                            'Your used space': used_space.get(self._user, 0)})
        return jsonify({'message': 'No restrictions turned on'})


@get_limits.route('')
class GetLimitsEndpoint(Resource):
    def get(self) -> Dict[str, Any]:
        """Returns current limits for the user"""
        limits = Limits(request.remote_addr)
        return limits.get_limits()


def add_long_calc(long_calc: Dict[Any, Any], user_add: str) -> None:
    """Add long calculation to user"""
    long_calc[user_add] = long_calc.get(user_add, 0) + 1


def increase_limit() -> None:
    """Increase number of long calculation"""
    to_delete = []
    for user in long_calculations:
        if long_calculations[user] > 1:
            long_calculations[user] -= 1
        else:
            to_delete.append(user)
    for user in to_delete:
        del long_calculations[user]


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


# Remove file manager and tmp files repeatedly
remove_tmp = RepeatTimer(float(config['remove_tmp']['every_x_seconds']),
                         lambda: delete_old_records(file_manager, user_id_manager,
                                                    float(config['remove_tmp']['older_than']),
                                                    config['remove_tmp']['log']))
remove_tmp.start()


if __name__ == '__main__':
    app.run(host='0.0.0.0')
