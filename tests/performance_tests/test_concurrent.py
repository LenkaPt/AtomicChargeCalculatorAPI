import requests
import time
import os
from pathlib import Path
import concurrent.futures
from datetime import date

def calc_file(identifier, ip, method, params):
    charges = requests.get(f'http://{ip}/calculate_charges',
                           params={'structure_id': identifier,
                                   'method': method,
                                   'parameters': params})
    return charges


def api(folder_path, ip, method, params):
    identifiers = []
    folder = Path(folder_path)
    for file in folder.iterdir():
        filename = Path(file).name
        identifier = requests.post(f'http://{ip}/send_files',
                                   files={'file[]': open(file)}).json()['structure_ids'][filename[:-4]]
        identifiers.append(identifier)

    i = 0
    start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as executor:
        for charge in executor.map(lambda p: calc_file(p, ip, method, params), identifiers):
            i += 1
            if charge.json()['message'] != "OK":
                raise ValueError(f'{charge.json()["status_code"]} - {charge.json()["message"]}')

    stop = time.perf_counter()
    return {'calculation': stop - start}
