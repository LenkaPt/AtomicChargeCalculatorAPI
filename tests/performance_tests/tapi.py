import requests
import time
import os
from pathlib import Path
import concurrent.futures
from datetime import date
import threading
import argparse

# eem, EEM_00_NEEMP_ccd2016_npa

def all_in_one(file, ip, method, parameters):
    start_with_sending = time.perf_counter()
    identifier = requests.post(f'http://{ip}/send_files',
                         files={'file[]': open(file)}).json()['structure_ids'][file[:-4]]

    start_calculation = time.perf_counter()
    mcharges = requests.get(f'http://{ip}/calculate_charges',
                        params={'structure_id': identifier,
                                'method': method,
                                'parameters': parameters})
    end = time.perf_counter()
    if mcharges.json()['status_code'] != 200:
        raise ValueError(f'{mcharges.json()["status_code"]} - {mcharges.json()["message"]}')
    # return end - start_with_sending, end - start_calculation, mcharges.json()
    return {'whole': end - start_with_sending, 'calculation': end - start_calculation, 'charges': mcharges.json()['charges']}


def sequentially(folder_path, ip, method, parameters):
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
    # return end - start_time, calc_time
    return {'whole': end - start_time, 'calculation': calc_time}



def calc_file(file, ip, method, parameters):
    filename = Path(file).name
    identifier = requests.post(f'http://{ip}/send_files',
                       files={'file[]': open(file)}).json()['structure_ids'][filename[:-4]]
    charges = requests.get(f'http://{ip}/calculate_charges',
                           params={'structure_id': identifier,
                                   'method': method,
                                   'parameters': parameters})
    return charges


def concurrently(folder_path, ip, method, parameters):
    files = []
    folder = Path(folder_path)
    for file in folder.iterdir():
        files.append(file)

    start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        for charge in executor.map(calc_file, files, ip, method, parameters):
            if charge.json()['message'] != "OK":
                raise ValueError(f'{charge.json()["status_code"]} - {charge.json()["message"]}')

    stop = time.perf_counter()
    return {'calculation': stop - start}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-ip', help='IP adress of server')
    parser.add_argument('--method', help='Computational method')
    parser.add_argument('--parameters', help='Parameters for method')
    parser.add_argument('--file', help='Path to file containing your strucutre')
    parser.add_argument('--folder', help='Path to folder with files')

    args = parser.parse_args()

    calc1 = all_in_one(args.file, args.ip, args.method, args.parameters)['calculation']
    print(f'Allin1: calc - {calc1}')

    calc2 = sequentially(args.folder, args.ip, args.method, args.parameters)['calculation']
    print(f'Seq: calc - {calc2}')

    time = concurrently(args.folder, args.ip, args.method, args.parameters)['calculation']
    print(f'Conc: calc: {time}')




