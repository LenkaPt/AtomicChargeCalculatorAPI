from flask import Flask, render_template, request, send_file, jsonify, send_from_directory
from flask_restx import Api, Resource, reqparse
from werkzeug.datastructures import FileStorage
from typing import Dict, TextIO, Any, Union, List, Tuple
from multiprocessing import Process, Manager, Queue
import tempfile
import os
import chargefw2_python
import requests
import subprocess
import time
from datetime import date
from threading import Timer, Thread
import configparser
import pathlib
import logging
from io import BytesIO
from zipfile import ZipFile

from Responses import OKResponse, ErrorResponse
from Structures import Structure, Method
from Logger import Logger
from File import File

config = configparser.ConfigParser()
config.read('/home/api_dev/api_dev/utils/api.ini')
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


def logging_process(queue):
    error_logger = Logger('error', file=config['paths']['log_error'], level=logging.ERROR)
    stat_logger = Logger('statistics', file=config['paths']['save_statistics_file'], level=logging.INFO)
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
        available_methods = chargefw2_python.get_available_methods()
        return OKResponse({'available_methods': available_methods}).json


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

        try:
            parameters = Method(method).get_available_parameters()
        except ValueError as e:
            simple_logger.log_error_message(request.remote_addr,
                                            'available_parameters',
                                            f'User wanted to use method {method} that is not available')
            return ErrorResponse(str(e), status_code=400).json

        simple_logger.log_statistics_message(request.remote_addr, endpoint_name='available_parameters', method=method)
        return OKResponse({'parameters': parameters}).json


def save_file_identifiers(identifiers: Dict[str, str]) -> None:
    if request.remote_addr not in user_id_manager:
        user_id_manager[request.remote_addr] = manager.list()
    for identifier, path_to_file in identifiers.items():
        file_manager[identifier] = path_to_file
        user_id_manager[request.remote_addr].append(identifier)
        # {user: [id1, id2]}


def user_has_no_space(file, user):
    if limitations_on and user in used_space:
        if file.get_size() + used_space[user] > int(config['limits']['granted_space']):
            return True
    if limitations_on:
        used_space[user] = used_space.get(user, 0) + file.get_size()
    return False


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

        uploaded_files = {}
        user_response = {}
        all_uploaded = True
        tmpdir = tempfile.mkdtemp(dir=config['paths']['save_user_files'])
        for file in files:
            file = File(file, tmpdir)

            if not file.has_valid_suffix():
                simple_logger.log_error_message(request.remote_addr,
                                                f'send_files',
                                                f'User sent file in unsupported format')
                return ErrorResponse(f'Unsupported format. Send only .sdf, .mol2, .cif and .pdb files.',
                                     status_code=400).json

            # user has limited space
            if user_has_no_space(file, request.remote_addr):
                all_uploaded = False
                break

            file.save()
            file.convert_line_endings_to_unix_style()
            uploaded_files[file.get_id()] = file.get_path()
            user_response[file.get_filename()] = file.get_id()

        save_file_identifiers(uploaded_files)
        simple_logger.log_statistics_message(request.remote_addr,
                                             endpoint_name='send_files',
                                             number_of_sent_files=len(files))

        if all_uploaded:
            return OKResponse({'structure_ids': user_response}).json
        # some ids were uploaded, but not all because the limited disk space
        elif not all_uploaded and user_response:
            return jsonify({'message': 'You have exceeded the grounded disk space',
                            'status_code': 413,
                            'successfully_uploaded_structure_ids': user_response})
        else:
            return ErrorResponse('You have exceeded the grounded disk space', 413).json


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
        uploaded_files = {}
        user_response = {}
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
            file = File(os.path.join(f'{pdb_id}.cif'), tmpdir)
            successfully_written_file = file.write_file(r, config)
            if not successfully_written_file:
                simple_logger.log_error_message(request.remote_addr,
                                                'pdb_id',
                                                'User wanted to upload file bigger than 10 Mb')
                return ErrorResponse(f'Not possible to upload {pdb_id}. It is bigger than 10 Mb.', 400).json

            # user has limited space
            if user_has_no_space(file, request.remote_addr):
                all_uploaded = False
                break

            uploaded_files[file.get_id()] = file.get_path()
            user_response[file.get_filename()] = file.get_id()

        save_file_identifiers(uploaded_files)
        simple_logger.log_statistics_message(request.remote_addr,
                                             endpoint_name='pdb_id',
                                             number_of_requested_structures=len(pdb_identifiers))

        if all_uploaded:
            return OKResponse({'structure_ids': user_response}).json
        # some ids were uploaded, but not all because the limited disk space
        elif not all_uploaded and user_response:
            return jsonify({'message': 'You have exceeded the grounded disk space',
                            'status_code': 413,
                            'successfully_uploaded_structure_ids': user_response})
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
        uploaded_files = {}
        user_response = {}
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
            file = File(os.path.join(f'{cid}.sdf'), tmpdir)
            successfully_written_file = file.write_file(r, config)
            if not successfully_written_file:
                simple_logger.log_error_message(request.remote_addr,
                                                'cid',
                                                'User wanted to upload file bigger than 10 Mb')
                return ErrorResponse(f'Not possible to upload {cid}. It is bigger than 10 Mb.', 400).json

            # user has limited space
            if user_has_no_space(file, request.remote_addr):
                all_uploaded = False
                break

            uploaded_files[file.get_id()] = file.get_path()
            user_response[file.get_filename()] = file.get_id()

        save_file_identifiers(uploaded_files)

        simple_logger.log_statistics_message(request.remote_addr,
                                             endpoint_name='pubchem_cid',
                                             number_of_requested_structures=len(cid_identifiers))

        if all_uploaded:
            return OKResponse({'structure_ids': user_response}).json
        # some ids were uploaded, but not all because the limited disk space
        elif not all_uploaded and user_response:
            return jsonify({'message': 'You have exceeded the grounded disk space',
                            'status_code': 413,
                            'successfully_uploaded_structure_ids': user_response})
        else:
            return ErrorResponse('You have exceeded the grounded disk space', 413).json


def release_space(file_size, user):
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
            structure = Structure(structure_id, file_manager)
        except ValueError:
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
        file = File(str(pathlib.Path(path_to_file.name)), path_to_file.parent)

        # remove from file_manager and user_id_manager
        del file_manager[structure_id]
        delete_id_from_user(structure_id)
        # release space
        release_space(file.get_size(), request.remote_addr)
        file.remove()
        simple_logger.log_statistics_message(request.remote_addr,
                                             endpoint_name='remove_file',
                                             structure_id=structure_id,
                                             user=request.remote_addr,
                                             removed_successfully=True)
        return OKResponse({structure_id: 'removed'}).json


def convert_pqr_to_pdb(pqr_file: os.PathLike, pdb_file: os.PathLike) -> None:
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
            structure = Structure(structure_id, file_manager)
            input_file = structure.get_pdb_input_file()
        except ValueError as e:
            simple_logger.log_error_message(request.remote_addr,
                                            'add_hydrogens',
                                            f'{str(e)}')
            return ErrorResponse(f'{str(e)}', status_code=400).json

        output_dir = tempfile.mkdtemp(dir=config['paths']['save_user_files'])
        pqr_file = File(structure_id + '.pqr', output_dir)
        path_to_pqr = pathlib.Path(pqr_file.get_path())
        pdb_file = File(structure_id + 'pdb', output_dir)
        path_to_pdb = pathlib.Path(pdb_file.get_path())

        # hydrogen bond optimalization
        noopt = request.args.get('noopt')

        if not noopt:
            try:
                subprocess.run(['pdb2pqr30', f'--noopt', f'--pH', f'{ph}', f'{input_file}', f'{path_to_pqr}'],
                               check=True)
            except subprocess.CalledProcessError:
                simple_logger.log_error_message(request.remote_addr,
                                                'add_hydrogens',
                                                'Error occurred when using pdb2pqr30',
                                                structure_id=structure_id)
                return ErrorResponse(f'Error occurred when using pdb2pqr30 on structure {structure_id}',
                                     status_code=405).json
        else:
            try:
                subprocess.run(['pdb2pqr30', f'--pH', f'{ph}', f'{input_file}', f'{path_to_pqr}'], check=True)
            except subprocess.CalledProcessError:
                simple_logger.log_error_message(request.remote_addr,
                                                'add_hydrogens',
                                                'Error occurred when using pdb2pqr30',
                                                structure_id=structure_id)
                return ErrorResponse(f'Error occurred when using pdb2pqr30 on structure {structure_id}',
                                     status_code=405).json

        pdb_file_id = pdb_file.get_id()
        try:
            convert_pqr_to_pdb(path_to_pqr, path_to_pdb)
        except ValueError as e:
            simple_logger.log_error_message(request.remote_addr,
                                            'add_hydrogens',
                                            f'{str(e)}')
            return ErrorResponse(f'{str(e)}', status_code=405).json
        save_file_identifiers({pdb_file_id: path_to_pdb})

        simple_logger.log_statistics_message(request.remote_addr,
                                             endpoint_name='add_hydrogens',
                                             ph=ph,
                                             noopt=noopt)
        return OKResponse({'structure_id': pdb_file_id}).json


def create_zip_file(folder):
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
                    400: 'Structure ID does not exist / Structure not in correct format'})
@api.expect(file_parser)
class StructureFile(Resource):
    def get(self):
        structure_id = request.args.get('structure_id')
        if not structure_id:
            simple_logger.log_error_message(request.remote_addr,
                                            'get_structure_file',
                                            'User did not specify structure id')
            return ErrorResponse(
                f'You have not specified structure ID obtained after uploading/adding hydrogens to your file. '
                f'Add to URL following, please: ?structure_id=obtained_structure_id').json
        try:
            file = Structure(structure_id, file_manager).get_structure_file()
        except ValueError as e:
            simple_logger.log_error_message(request.remote_addr,
                                            'get_structure_file',
                                            'Structure id does not exist',
                                            structure_id=structure_id)
            return ErrorResponse(str(e), 400).json

        zip_file = create_zip_file(pathlib.Path(file).parent)
        return send_file(zip_file, download_name='structures.zip', as_attachment=True)


def get_bool_value(original: Union[None, str]) -> bool:
    """Get boolean value - set to default if parameters not specified"""
    if original:
        original = original.lower()
    return original == 'true'


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

        read_hetatm = get_bool_value(read_hetatm)  # default: True
        ignore_water = get_bool_value(ignore_water)  # default False

        try:
            structure = Structure(structure_id, file_manager)
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

        read_hetatm = get_bool_value(read_hetatm)  # default: True
        ignore_water = get_bool_value(ignore_water)  # default False

        try:
            structure = Structure(structure_id, file_manager)
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


@calculate_time
def round_charges(charges):
    rounded_charges = []
    for key in charges.keys():
        tmp = {}
        tmp[key] = list(map(lambda x: round(x, 4), charges[key]))
        rounded_charges.append(tmp)
    return rounded_charges


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



def calculate_charges(molecules, method, parameters):
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
    def get(self):
        structure_id = request.args.get('structure_id')
        method = request.args.get('method')
        parameters = request.args.get('parameters')

        read_hetatm = request.args.get('read_hetatm')
        ignore_water = request.args.get('ignore_water')

        read_hetatm = get_bool_value(read_hetatm)  # default: True
        ignore_water = get_bool_value(ignore_water)  # default False

        if not structure_id:
            simple_logger.log_error_message(request.remote_addr,
                                            'calculate_charges',
                                            'User did not specify structure id')
            return ErrorResponse(f'You have not specified structure ID obtained after uploading your file. '
                                 f'Add to URL following, please: ?structure_id=obtained_structure_id').json

        try:
            structure = Structure(structure_id, file_manager)
            # suitable_methods = structure.get_suitable_methods(read_hetatm, ignore_water)
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

        try:
            result = calculate_charges(molecules, method, parameters)
        except RuntimeError as e:
            simple_logger.log_error_message(request.remote_addr,
                                            'calculate_charges',
                                            str(e))
            return ErrorResponse(str(e)).json

        if config['limits']['on'] == 'True':
            if result.calc_time > float(config['limits']['calc_time']):
                add_long_calc(long_calculations, request.remote_addr)

        suffix = structure.get_structure_file()[-3:]
        molecules_count, atom_count, atoms_list_count = chargefw2_python.get_info(molecules)
        simple_logger.log_statistics_message(request.remote_addr,
                                             endpoint_name='calculate_charges',
                                             suffix=suffix,
                                             number_of_molecules=molecules_count,
                                             number_of_atoms=atom_count,
                                             method=method,
                                             parameters=parameters,
                                             time=result.calc_time)
        return OKResponse(
            {'charges': result.get_charges(), 'method': result.method, 'parameters': result.parameters}).json

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

