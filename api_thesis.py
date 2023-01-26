from flask import Flask, render_template, request, send_from_directory, jsonify
from flask_restx import Api, Resource, reqparse
from werkzeug.datastructures import FileStorage
from typing import Dict, TextIO, Any, Union, List, Tuple
from multiprocessing import Process, Manager
import tempfile
import os
import csv
import json
import chargefw2_python
import requests
import subprocess
import time
from datetime import date
from threading import Timer
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import configparser
import pathlib
import shutil

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

get_limits = api.namespace('get_limits',
                           description='Get info about limits, your files.')


def json_ok(data):
    return jsonify({'status_code': 200,
                    'message': 'OK',
                    **data})


def json_error(message: str, status_code=404):
    return {'status_code': status_code,
            'message': message}, status_code


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


@calculate_time
def collect_statistics(endpoint_name, **kwargs):
    with open(config['paths']['save_statistics_file'], mode='a') as file:
        writer = csv.writer(file)

        args = list()
        for key, value in kwargs.items():
            connected = str(key) + '=' + str(value)
            args.append(connected)

        writer.writerow([request.remote_addr,
                         date.today().strftime("%d/%m/%Y"),
                         time.strftime("%H:%M:%S", time.localtime())] +
                        ['endpoint_name=' + endpoint_name] +
                        args)


def log_error(message, endpoint_name, **kwargs):
    with open(config['paths']['log_error'], mode='a') as file:
        file.write(f'{request.remote_addr}, '
                   f'{date.today().strftime("%d/%m/%Y")}, '
                   f'{time.strftime("%H:%M:%S", time.localtime())}, '
                   f'endpoint_name={endpoint_name}, '
                   f'error_message={message}')
        for key, value in kwargs.items():
            file.write(f', {key}={value}')
        file.write('\n')


@avail_methods.route('')
class AvailableMethods(Resource):
    def get(self):
        collect_statistics(endpoint_name='available_methods')
        """Returns list of methods available for calculation of partial atomic charges"""
        return json_ok({'available_methods': chargefw2_python.get_available_methods()})


@avail_params.route('')
@api.doc(params={'method': {'description': 'Calculation method', 'type': 'string', 'required': True, 'in': 'query'}},
         responses={404: 'Method not specified',
                    400: 'Method not available',
                    200: 'OK'})
class AvailableParameters(Resource):
    def get(self):
        """Returns list of available parameters for specific method"""
        method = request.args.get('method')
        if not method:
            log_error('User did not specify method', endpoint_name='available_parameters')
            return json_error(f'You have not specified method. '
                              f'Add to URL following, please: ?method=your_chosen_method')

        if method not in chargefw2_python.get_available_methods():
            log_error(f'User wanted to use method {method} that is not available',
                      endpoint_name='available_parameters')
            return json_error(f'Method {method} is not available.', status_code=400)

        collect_statistics(endpoint_name='available_parameters', method=method)
        return json_ok({'parameters': chargefw2_python.get_available_parameters(method)})


# @app.errorhandler(429)
# def ratelimit_handler(e):
#     return make_response(
#             jsonify(error="ratelimit exceeded")
#             , 429
#     )


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
    # while 'file_id' in file_manager or file_manager.get('file_id', 0) >= 1:
    #     time.sleep(0.01)
    # file_manager['file_id'] = file_manager.get('file_id', 0) + 1
    #
    # with open(config['paths']['save_file_identifiers_file'], mode='a') as file:
    #     writer = csv.writer(file)
    #     for identifier, path_to_file in identifiers.items():
    #         writer.writerow([identifier, path_to_file])
    #
    # file_manager['file_id'] = file_manager['file_id'] - 1
    # if file_manager['file_id'] == 0:
    #     del file_manager['file_id']


# TODO not good - just one file (action='append' not working with files)
file_parser = api.parser()
file_parser.add_argument('file[]', location='files', type=FileStorage, required=True)


@send_files.route('')
@api.doc(responses={404: 'No file sent',
                    400: 'Unsupported format',
                    413: 'File is too large',
                    200: 'OK'})
@api.expect(file_parser)
class SendFiles(Resource):
    # decorators = [limiter.shared_limit("100/hour", scope="upload")]
    def post(self):
        """Send files in pdb, sdf or cif format"""
        files = request.files.getlist('file[]')

        if not files:
            log_error('User did not send a file', endpoint_name='send_files')
            return json_error(f'No file sent. Add to URL following, please: ?file[]=path_to_file')

        if not valid_suffix(files):
            log_error(f'User sent file in unsupported format', endpoint_name='send_files')
            return json_error(f'Unsupported format. Send only .sdf, .mol2, .cif and .pdb files.', status_code=400)

        tmpdir = tempfile.mkdtemp(dir=config['paths']['save_user_files'])
        # tmpdir = tempfile.mkdtemp()
        identifiers_plus_filepath = {}
        identifiers_plus_filenames = {}
        for file in files:
            path_to_file = os.path.join(tmpdir, file.filename)
            file.save(path_to_file)
            # convert formats (different new lines)
            subprocess.run(['dos2unix', path_to_file])

            identifier = os.path.basename(tempfile.NamedTemporaryFile(prefix=file.filename.rsplit('.')[0]).name)
            identifiers_plus_filepath[identifier] = path_to_file
            identifiers_plus_filenames[file.filename.rsplit('.')[0]] = identifier

        save_file_identifiers(identifiers_plus_filepath)

        collect_statistics(endpoint_name='send_files', number_of_sent_files=len(files))

        return json_ok({'structure_ids': identifiers_plus_filenames})


def write_file(path_to_file, r):
    file_size = 0
    with open(path_to_file, 'wb') as fd:
        for chunk in r.iter_content(chunk_size=128):
            fd.write(chunk)
            file_size += len(chunk)
            if file_size > 10 * 1024 ** 2:
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
            log_error('User did not specify pdb ID', endpoint_name='pdb_id')
            return json_error('No pdb id specified. Add to URL following, please: ?pid[]=pdb_id')

        tmpdir = tempfile.mkdtemp(dir=config['paths']['save_user_files'])
        identifiers_plus_filepath = {}
        identifiers_plus_filename = {}
        for pdb_id in pdb_identifiers:
            r = requests.get('https://files.rcsb.org/download/' + pdb_id + '.cif', stream=True)
            try:
                r.raise_for_status()
            except requests.exceptions.HTTPError as e:
                log_error(f'{e}', endpoint_name='pdb_id', status_code=r.status_code)
                return json_error(f'{e}', r.status_code)

            # save requested pdb structure
            path_to_file = os.path.join(tmpdir, pdb_id + '.cif')
            successfully_written_file = write_file(path_to_file, r)
            if not successfully_written_file:
                log_error('User wanted to upload file bigger than 10 Mb', endpoint_name='pdb_id')
                return json_error(f'Not possible to upload {pdb_id}. It is bigger than 10 Mb.', 400)

            identifier = os.path.basename(tempfile.NamedTemporaryFile(prefix=pdb_id).name)
            identifiers_plus_filepath[identifier] = path_to_file
            identifiers_plus_filename[pdb_id] = identifier

        save_file_identifiers(identifiers_plus_filepath)

        collect_statistics(endpoint_name='pdb_id', number_of_requested_structures=len(pdb_identifiers))

        return json_ok({'structure_ids': identifiers_plus_filename})


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
            log_error('User did not specify pubchem cid', endpoint_name='pubchem_id')
            return json_error('No pubchem cid specified. Add to URL following, please: ?cid[]=pubchem_cid')

        tmpdir = tempfile.mkdtemp(dir=config['paths']['save_user_files'])
        identifiers_plus_filepath = {}
        identifiers_plus_filenames = {}
        for cid in cid_identifiers:
            r = requests.get('https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/CID/' +
                             cid +
                             '/record/SDF/?record_type=3d&response_type=save&response_basename=Conformer3D_CID_' +
                             cid, stream=True)
            try:
                r.raise_for_status()
            except requests.exceptions.HTTPError as e:
                log_error(f'{e}', endpoint_name='pubchem_cid', status_code=r.status_code)
                return json_error(f'{e}', r.status_code)

            # save requested cid compound
            path_to_file = os.path.join(tmpdir, cid + '.sdf')
            successfully_written_file = write_file(path_to_file, r)
            if not successfully_written_file:
                log_error('User wanted to upload file bigger than 10 Mb', endpoint_name='cid')
                return json_error(f'Not possible to upload {cid}. It is bigger than 10 Mb.', 400)

            identifier = os.path.basename(tempfile.NamedTemporaryFile(prefix=cid).name)
            identifiers_plus_filepath[identifier] = path_to_file
            identifiers_plus_filenames[cid] = identifier

        save_file_identifiers(identifiers_plus_filepath)

        collect_statistics(endpoint_name='pubchem_cid', number_of_requested_structures=len(cid_identifiers))

        return json_ok({'structure_ids': identifiers_plus_filenames})


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
        # TODO - kontrolovat, jestli to id je uživatelovo - až budu mít udělaný ten slovník {user:[id1, id2]}
        if not structure_id:
            log_error('User did not specify structure id', endpoint_name='add_hydrogens')
            return json_error(f'You have not specified structure ID obtained after uploading your file. '
                              f'Add to URL following, please: ?structure_id=obtained_structure_id')
        path_to_file = get_path_based_on_identifier(structure_id)
        if not path_to_file:
            log_error('User specified id that does not exist.', endpoint_name='remove_file', structure_id=structure_id)
            return json_error(f'Structure ID {structure_id} does not exist.', 400)
        path_to_file = pathlib.Path(path_to_file)
        file_size = path_to_file.stat().st_size

        # remove from file_manager
        del file_manager[structure_id]
        os.remove(path_to_file)
        path_to_file.parent.rmdir()
        return json_ok({structure_id: 'removed'})
        # TODO odečítat od omezující celkové hodnoty na omezení místa uživateli


@calculate_time
def get_path_based_on_identifier(structure_id: str):
    if structure_id in file_manager:
        return file_manager[structure_id]
    # with open(config['paths']['save_file_identifiers_file'], mode='r') as file:
    #     reader = csv.reader(file)
    #     for row in reader:
    #         if row[0] == structure_id:
    #             return row[1]
    return None


@calculate_time
def get_molecules(structure_id: str, read_hetatm: bool = True, ignore_water: bool = False):
    path_to_file = get_path_based_on_identifier(structure_id)
    if path_to_file is None:
        raise ValueError(f'Structure ID {structure_id} does not exist.')
    try:
        return chargefw2_python.Molecules(path_to_file, read_hetatm, ignore_water)
    except RuntimeError as e:
        raise ValueError(e)


def get_pdb_input_file(structure_id: str) -> str:
    """Returns input file in pdb format (pdb2pqr can process only pdb files)"""
    input_file = get_path_based_on_identifier(structure_id)
    if not input_file:
        raise ValueError(f'Structure ID {structure_id} does not exist.')
    # cif format convert to pdb using gemmi convert
    if input_file.endswith('.cif'):
        try:
            subprocess.run(['gemmi', 'convert', f'{input_file}', f'{input_file[:-4]}.pdb'], check=True)
        except subprocess.CalledProcessError:
            raise ValueError(f'Error converting from .cif to .pdb using gemmi convert.')
        input_file = input_file[:-4] + '.pdb'
    if not input_file.endswith('pdb'):
        raise ValueError(f'{structure_id} is not in .pdb or .cif format')
    return input_file


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
            log_error('User did not specify structure id', endpoint_name='add_hydrogens')
            return json_error(f'You have not specified structure ID obtained after uploading your file. '
                              f'Add to URL following, please: ?structure_id=obtained_structure_id')

        ph = request.args.get('pH')
        if not ph:
            ph = float(config['pH']['default'])

        try:
            input_file = get_pdb_input_file(structure_id)
        except ValueError as e:
            log_error(f'{str(e)}', endpoint_name='add_hydrogens')
            return json_error(f'{str(e)}', status_code=400)
        output_pqr_file = os.path.join(tempfile.mkdtemp(dir=config['paths']['save_user_files']), 'result.pqr')
        output_pdb_file = output_pqr_file[:-4] + '.pdb'

        # hydrogen bond optimalization
        noopt = request.args.get('noopt')

        if not noopt:
            try:
                subprocess.run(['pdb2pqr30', f'--noopt', f'--pH', f'{ph}', f'{input_file}', f'{output_pqr_file}'],
                               check=True)
            except subprocess.CalledProcessError:
                log_error('Error occurred when using pdb2pqr30', endpoint_name='add_hydrogens',
                          structure_id=structure_id)
                return json_error(f'Error occurred when using pdb2pqr30 on structure {structure_id}', status_code=405)
        else:
            try:
                subprocess.run(['pdb2pqr30', f'--pH', f'{ph}', f'{input_file}', f'{output_pqr_file}'], check=True)
            except subprocess.CalledProcessError:
                log_error('Error occurred when using pdb2pqr30', endpoint_name='add_hydrogens',
                          structure_id=structure_id)
                return json_error(f'Error occurred when using pdb2pqr30 on structure {structure_id}', status_code=405)

        output_identifier = os.path.basename(tempfile.NamedTemporaryFile(prefix='hydro').name)
        try:
            convert_pqr_to_pdb(output_pqr_file, output_pdb_file)
        except ValueError as e:
            log_error(f'{str(e)}', endpoint_name='add_hydrogens')
            return json_error(f'{str(e)}', status_code=405)
        save_file_identifiers({output_identifier: output_pdb_file})

        collect_statistics(endpoint_name='add_hydrogens', ph=ph, noopt=noopt)

        return json_ok({'structure_id': output_identifier})


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
            log_error('User did not specify structure id', endpoint_name='get_info')
            return json_error(f'You have not specified structure ID obtained after uploading your file. '
                              f'Add to URL following, please: ?structure_id=obtained_structure_id')

        read_hetatm = get_read_hetatm_value(read_hetatm)  # default: True
        ignore_water = get_ignore_water_value(ignore_water)  # default False

        try:
            molecules = get_molecules(structure_id, read_hetatm, ignore_water)
        except ValueError as e:
            log_error(str(e), endpoint_name='get_info')
            return json_error(str(e), status_code=400)

        molecules_count, atom_count, atoms_list_count = chargefw2_python.get_info(molecules)
        atoms_dict_count = get_dict_atoms_count(atoms_list_count)

        collect_statistics(endpoint_name='get_info', number_of_molecules=molecules_count,
                           number_of_atoms=atom_count, number_of_individdual_atoms=atoms_dict_count)

        return json_ok({'Number of molecules': molecules_count,
                        'Number of atoms': atom_count,
                        'Number of individual atoms': atoms_dict_count})


@calculate_time
def get_suitable_methods(structure_id: str, read_hetatm: bool, ignore_water: bool):
    """Returns suitable methods for particular dataset"""
    molecules = get_molecules(structure_id, read_hetatm, ignore_water)
    return chargefw2_python.get_suitable_methods(molecules)


def empty_brackets_to_null(dict):
    for key, value in dict.items():
        if not value:
            dict[key] = None
    return dict


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
            log_error('User did not specify structure id', endpoint_name='suitable_methods')
            return json_error(f'You have not specified structure ID obtained after uploading your file. '
                              f'Add to URL following, please: ?structure_id=obtained_structure_id')

        read_hetatm = get_read_hetatm_value(read_hetatm)  # default: True
        ignore_water = get_ignore_water_value(ignore_water)  # default False

        try:
            suitable_methods = get_suitable_methods(structure_id, read_hetatm, ignore_water)
            suitable_methods = empty_brackets_to_null(suitable_methods)
        except ValueError as e:
            log_error(str(e), endpoint_name='suitable_methods')
            return json_error(str(e), status_code=400)

        collect_statistics(endpoint_name='suitable_methods', suitable_methods=suitable_methods)

        return json_ok({'suitable_methods': suitable_methods})


@calculate_time
def get_calculated_charges(structure_id: str, method: str, parameter: str, read_hetatm: bool, ignore_water: bool):
    """Returns calculated charges of given set of molecules"""
    molecules = get_molecules(structure_id, read_hetatm, ignore_water)
    return chargefw2_python.calculate_charges(molecules, method, parameter)


@calculate_time
def round_charges(charges):
    rounded_charges = []
    for key in charges.keys():
        tmp = {}
        tmp[key] = list(map(lambda x: round(x, 4), charges[key]))
        rounded_charges.append(tmp)
    return rounded_charges


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
            log_error('User did not specify structure id', endpoint_name='calculate_charges')
            return json_error(f'You have not specified structure ID obtained after uploading your file. '
                              f'Add to URL following, please: ?structure_id=obtained_structure_id')

        try:
            molecules = get_molecules(structure_id, read_hetatm, ignore_water)
        except ValueError as e:
            return json_error(str(e), 400)

        # TODO debugging purposes
        with open(config['paths']['log_time'], mode='a') as file:
            file.write(f'{time.asctime(time.localtime(time.time()))} - '
                       f'Before getting suitable methods\n')

        # commented?
        try:
            suitable_methods = chargefw2_python.get_suitable_methods(molecules)
        except ValueError as e:
            return json_error(str(e), 400)

        # TODO debugging purposes
        with open(config['paths']['log_time'], mode='a') as file:
            file.write(f'{time.asctime(time.localtime(time.time()))} - '
                       f'After getting suitable methods\n')

        if method and method not in chargefw2_python.get_available_methods():
            log_error('User wanted to use method that is not available', endpoint_name='calculate_charges',
                      method=method)
            return json_error(f'Method {method} is not available.', status_code=400)

        # TODO debugging purposes
        with open(config['paths']['log_time'], mode='a') as file:
            file.write(f'{time.asctime(time.localtime(time.time()))} - '
                       f'After checking if method is in available methods\n')

        # commented
        try:
            if method and method not in suitable_methods:
                return json_error(f'Method {method} is not suitable for {structure_id}.', status_code=400)
        except ValueError as e:
            return json_error(str(e))

        # TODO debugging purposes
        with open(config['paths']['log_time'], mode='a') as file:
            file.write(f'{time.asctime(time.localtime(time.time()))} - '
                       f'After checking if method is in suitable methods\n')

        if method and not parameters:
            try:
                parameters = chargefw2_python.get_available_parameters(method)[0]
            except IndexError:
                # method does not requires any parameters
                parameters = None

        # wrong or not compatible parameters
        if method and parameters:
            if parameters not in chargefw2_python.get_available_parameters(method):
                log_error('Parameters are not available for method', endpoint_name='calculate_charges',
                          parameters=parameters, method=method)
                return json_error(f'Parameters {parameters} are not available for method {method}.', status_code=400)

            # TODO debugging purposes
        with open(config['paths']['log_time'], mode='a') as file:
            file.write(f'{time.asctime(time.localtime(time.time()))} - '
                       f'After cheking if parameters are in available parameters\n')

        # commented
        if not method:
            method = list(suitable_methods)[0]
            parameters = None  # if method does not require parameters
            if suitable_methods[method]:
                parameters = suitable_methods[method][0]

        try:
            if config['limits']['on'] == 'True':
                if request.remote_addr in long_calculations and long_calculations[request.remote_addr] >= int(
                        config['limits']['max_long_calc']):
                    log_error('User has too many time demanding calculations per day.')
                    return json_error(
                        f'You can perform only {config["limits"]["max_long_calc"]} time demanding calculations per day.')

            calc_start = time.perf_counter()
            charges = chargefw2_python.calculate_charges(molecules, method, parameters)
            calc_end = time.perf_counter()

            with open(config['paths']['log_time'], mode='a') as file:
                file.write(f'{time.asctime(time.localtime(time.time()))} - '
                           f'Calculation inside..debugging - {calc_end - calc_start}\n')

            # return ', '.join(charges.keys())
            if config['limits']['on'] == 'True':
                if calc_end - calc_start > float(config['limits']['calc_time']):
                    add_long_calc(long_calculations, request.remote_addr)

            rounded_charges = round_charges(charges)

            suffix = get_path_based_on_identifier(structure_id)[-3:]
            molecules_count, atom_count, atoms_list_count = chargefw2_python.get_info(molecules)
            collect_statistics('calculate_charges', suffix=suffix,
                               number_of_molecules=molecules_count,
                               number_of_atoms=atom_count, method=method,
                               parameters=parameters,
                               calculation_time=round(calc_end - calc_start, 2))
        except ValueError as e:
            log_error(str(e), endpoint_name='calculate_charges')
            return json_error(str(e))
        return json_ok({'charges': rounded_charges, 'method': method, 'parameters': parameters})


def get_users_files_info(user):
    """Returns id, file name and info when the file was lastly modified for particular use"""
    files_info = []
    ids = user_id_manager[user]
    for id in ids:
        path_to_file = pathlib.Path(file_manager[id])
        file_name = path_to_file.name
        files_info.append(f'ID: {id}, '
                          f'name of file: {file_name}, '
                          f'file was last modified before {round(time.time() - path_to_file.stat().st_mtime, 2)}s.')
    return '\n'.join(files_info)


@get_limits.route('')
class GetLimits(Resource):
    def get(self):
        if config['limits']['on'] == 'True':
            file_size = int(config['limits']['file_size'])
            max_long_calc = int(config['limits']['max_long_calc'])
            current_user = request.remote_addr
            if current_user in long_calculations:
                curr_user_has_long_calc = long_calculations[current_user]
            else:
                curr_user_has_long_calc = 0
            if current_user in user_id_manager:
                files_info = get_users_files_info(current_user)
            else:
                files_info = 'Currently you have no uploaded structures - no ids.'
            return jsonify({'Max file size': file_size,
                            'Max allowed long calculations': max_long_calc,
                            'You are allowed to have long calculations': max_long_calc - curr_user_has_long_calc,
                            'Your files': files_info,
                            'Removing files': f'Files that was not modified '
                                              f'for more than {int(config["remove_tmp"]["older_than"])}s '
                                              f'are removed once every {int(config["remove_tmp"]["every_x_seconds"])}s.'})
        return jsonify({'message': 'No restrictions turned on'})


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


manager = Manager()

# user can process only limited number of long
if config['limits']['on'] == 'True':
    long_calculations = manager.dict()
    used_space = manager.dict()
    del_timer = RepeatTimer(float(config['limits']['decrease_restriction']), increase_limit)
    del_timer.start()

file_manager = manager.dict()  # id: path_to_file
user_id_manager = manager.dict()  # {user:[id1, id2]} TODO remove - not using now


def delete_id_from_user(identifier):
    for user in user_id_manager:
        if identifier in user_id_manager[user]:
            user_id_manager[user].remove(identifier)
            if len(user_id_manager[user]) == 0:
                del user_id_manager[user]


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


# TODO just testing purposes
@app.route('/file_manager')
def file_manager_func():
    return '<br>'.join(file_manager.values())


# TODO just testing purposes
@app.route('/user_id_manager')
def user_id_manager_func():
    return '<br>'.join(user_id_manager[request.remote_addr])


if __name__ == '__main__':
    app.run(host='0.0.0.0')
