import subprocess
import time
from pathlib import Path
import argparse


def all_in_one(path_to_file, method, path_to_parameters, chg_out_dir):
    start = time.perf_counter()
    subprocess.run(['chargefw2', '--mode', 'charges', '--input-file', path_to_file, '--method', method, '--chg-out-dir', chg_out_dir, '--par-file', path_to_parameters])
    stop = time.perf_counter()
    return {'calculation': stop - start}


def sequentially(path_to_folder, method, path_to_parameters, chg_out_dir):
    folder = Path(path_to_folder)
    files_count = 0
    start = time.perf_counter()
    for file in folder.iterdir():
        # print(file)
        files_count += 1
        subprocess.run(['chargefw2', '--mode', 'charges', '--input-file', file, '--method', method, '--chg-out-dir', chg_out_dir, '--par-file', path_to_parameters])
    stop = time.perf_counter()
    return {'calculation': stop - start}

# conc?

# '/home/ubuntu/ChargeFW2/data/parameters/EEM_00_NEEMP_ccd2016_npa.json'

if __name__ == '__main__':
    # parser = argparse.ArgumentParser()
    # parser.add_argument('--method', help='Computational method')
    # parser.add_argument('--parameters_file', help='Path to parameters for method')
    # parser.add_argument('--file', help='Path to file containing your strucutre')
    # parser.add_argument('--folder', help='Path to folder with files')
    #
    # args = parser.parse_args()
    #
    # calc = all_in_one(args.file, args.method, args.parameters_file, '/home/ubuntu/api_testing/tmp')['calculation']
    calc = all_in_one('ideal_valid_all.sdf', 'eem', '/home/ubuntu/ChargeFW2/data/parameters/EEM_00_NEEMP_ccd2016_npa.json', '/home/ubuntu/api_testing/tmp')['calculation']
    print(f'Allin1: calc - {calc}')

    # calc = sequentially(args.folder, args.method, args.parameters_file)
    # print(f'Seq: calc - {calc}')
