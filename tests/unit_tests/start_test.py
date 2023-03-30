import subprocess
import requests
import argparse
import configparser

default_valid_file = '1ner.pdb'
default_invalid_file = '6a5j.pdb'
default_file_in_invalid_format = 'text.txt'
default_big_file = '4wfb.pdb'
default_url = '78.128.250.156:8080/'
default_cid = '1'
default_limit_file = 'api.ini'

config = configparser.ConfigParser()
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
max_long_calc = args.max_long_calc
granted_space = args.granted_space

valid_id = requests.post(f'http://{url}/send_files',
                         files={'file[]': open(valid_file)}).json()['structure_ids'][valid_file[:-4]]
invalid_id = requests.post(f'http://{url}/send_files',
                           files={'file[]': open(invalid_file)}).json()['structure_ids'][invalid_file[:-4]]
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
                'test.py', 'limits_of.py'])
