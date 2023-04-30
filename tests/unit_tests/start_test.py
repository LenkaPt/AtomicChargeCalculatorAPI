import subprocess
import requests
import argparse
import configparser
from pathlib import Path


config = configparser.ConfigParser()
config.read('default_tests_values.ini')
default_valid_file = config['files']['valid_file']
default_invalid_file = config['files']['invalid_file']
default_file_in_invalid_format = config['files']['file_in_invalid_format']
default_big_file = config['files']['big_file']
default_valid_pdb_id = config['ids']['valid_pdb_id']
default_big_molecule_pdb_id = config['ids']['big_molecule_pdb_id']
default_pdb_id_for_long_calculation = config['ids']['pdb_id_for_long_calculation']
default_url = config['urls']['url']
default_cid = config['ids']['cid']
default_limit_file = config['limit_file']['default']

config.read(default_limit_file)
default_max_long_calc = config['limits']['max_long_calc']
default_granted_space = config['limits']['granted_space']

parser = argparse.ArgumentParser()
parser.add_argument('--api_url', help='url adress of API', default=default_url)
parser.add_argument('--valid_file', help='File in valid format', default=default_valid_file)
parser.add_argument('--invalid_file', help='File in invalid format', default=default_invalid_file)
parser.add_argument('--cid', help='ID of structure in Pubchem database', default=default_cid)
parser.add_argument('--file_in_invalid_format', help='File in not supported format',
                    default=default_file_in_invalid_format)
parser.add_argument('--big_file', help='File larger than 10 Mb', default=default_big_file)
parser.add_argument('--valid_pdb_id', help='Existing PDB ID of molecule that can be upload to API',
                    default=default_valid_pdb_id)
parser.add_argument('--big_molecule_pdb_id',
                    help='Existing PDB ID of molecule that is larger than limit for uploading files to API',
                    default=default_big_molecule_pdb_id)
parser.add_argument('--pdb_id_for_long_calculation',
                    help='Existing PDB ID of molecule that can be upload to API but its calculation should be consider as long',
                    default=default_pdb_id_for_long_calculation)
parser.add_argument('--max_long_calc', help='How many long calculations is allowed to user',
                    default=default_max_long_calc)
parser.add_argument('--granted_space', help='Space granted for user', default=default_granted_space)
args = parser.parse_args()

url = args.api_url
valid_file = args.valid_file
invalid_file = args.invalid_file
cid = args.cid
file_in_invalid_format = args.file_in_invalid_format
big_file = args.big_file
valid_pdb_id = args.valid_pdb_id
big_molecule_pdb_id = args.big_molecule_pdb_id
pdb_id_for_long_calculation = args.pdb_id_for_long_calculation
max_long_calc = args.max_long_calc
granted_space = args.granted_space

valid_id = requests.post(f'http://{url}/send_files',
                         files={'file[]': open(valid_file)}).json()['structure_ids'][Path(valid_file).stem]
invalid_id = requests.post(f'http://{url}/send_files',
                           files={'file[]': open(invalid_file)}).json()['structure_ids'][Path(invalid_file).stem]
sdf_id = requests.post(f'http://{url}/pubchem_cid', params={'cid[]': cid}).json()['structure_ids'][cid]
subprocess.run(['pytest', '--url', url,
                '--valid_id', valid_id,
                '--invalid_id', invalid_id,
                '--sdf_id', sdf_id,
                '--valid_file', valid_file,
                '--invalid_format', file_in_invalid_format,
                '--big_file', default_big_file,
                '--max_long_calc', max_long_calc,
                '--granted_space', granted_space,
                '--valid_pdb_id', valid_pdb_id,
                '--big_molecule_pdb_id', big_molecule_pdb_id,
                '--pdb_id_for_long_calculation', pdb_id_for_long_calculation,
                'limits_of.py'])
