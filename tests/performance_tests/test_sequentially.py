import requests
import time
from pathlib import Path
import chargefw2_python
import subprocess


def api(folder_path, ip, method, parameters):
    folder = Path(folder_path)
    start_time = time.perf_counter()
    calc_time = 0
    for file in folder.iterdir():
        filename = Path(file).name
        id = requests.post(f'http://{ip}/send_files',
                           files={'file[]': open(file)}).json()['structure_ids'][filename[:-4]]
        start_calc = time.perf_counter()
        charges = requests.get(f'http://{ip}/calculate_charges',
                               params={'structure_id': id,
                                       'method': method,
                                       'parameters': parameters})
        end_calc = time.perf_counter()
        calc_time += end_calc - start_calc
        if charges.json()['status_code'] != 200:
            raise ValueError(f'{charges.json()["status_code"]} - {charges.json()["message"]}. File: {file}')

    end = time.perf_counter()
    return {'whole': end - start_time, 'calculation': calc_time}


def pybind(path_to_folder, method, parameters):
    folder = Path(path_to_folder)
    loading_time = 0
    calc_time = 0
    files_count = 0
    start = time.perf_counter()
    for file in folder.iterdir():
        file = str(file)
        files_count += 1
        start_loading = time.perf_counter()
        molecules = chargefw2_python.Molecules(file)
        stop_loading = time.perf_counter()

        charges = chargefw2_python.calculate_charges(molecules, method, parameters)
        stop_calculate = time.perf_counter()
        loading_time += stop_loading - start_loading
        calc_time += stop_calculate - start_loading
    stop = time.perf_counter()
    return {'loading_time': loading_time, 'calculation': stop - start, 'files_number': files_count}


def chargefw2(path_to_folder, method, path_to_parameters, chg_out_dir):
    folder = Path(path_to_folder)
    files_count = 0
    start = time.perf_counter()
    for file in folder.iterdir():
        files_count += 1
        subprocess.run(
            ['chargefw2', '--mode', 'charges', '--input-file', file, '--method', method, '--chg-out-dir', chg_out_dir,
             '--par-file', path_to_parameters])
    stop = time.perf_counter()
    return {'calculation': stop - start}