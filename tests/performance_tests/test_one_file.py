import requests
import time
import chargefw2_python
import subprocess
import argparse

def api(path_to_file, ip, method, parameters):
    start_with_sending = time.perf_counter()
    identifier = requests.post(f'http://{ip}/send_files',
                               files={'file[]': open(path_to_file)}).json()['structure_ids'][path_to_file[:-4]]

    start_calculation = time.perf_counter()
    mcharges = requests.get(f'http://{ip}/calculate_charges',
                            params={'structure_id': identifier,
                                    'method': method,
                                    'parameters': parameters})
    end = time.perf_counter()
    if mcharges.json()['status_code'] != 200:
        raise ValueError(f'{mcharges.json()["status_code"]} - {mcharges.json()["message"]}')
    return {'whole': end - start_with_sending, 'calculation': end - start_calculation,
            'charges': mcharges.json()['charges']}


def pybind(path_to_file, method, parameters):
    start = time.perf_counter()
    molecules = chargefw2_python.Molecules(path_to_file)
    stop_load = time.perf_counter()

    charges_eem = chargefw2_python.calculate_charges(molecules, method, parameters)
    stop_calc = time.perf_counter()
    return {'loading_time': stop_load - start, 'calculation': stop_calc - start, 'charges': charges_eem}


def chargefw2(path_to_file, method, path_to_parameters, chg_out_dir):
    start = time.perf_counter()
    subprocess.run(['chargefw2', '--mode', 'charges', '--input-file', path_to_file, '--method', method, '--chg-out-dir',
                    chg_out_dir, '--par-file', path_to_parameters])
    stop = time.perf_counter()
    return {'calculation': stop - start}


def main(count, file, ip, method, parameters, parameters_file, chg_out_dir):
    api_total = 0
    pybind_total = 0
    chargefw2_total = 0
    for i in range(count):
        api_total += api(file, ip, method, parameters)['calculation']
        pybind_total += pybind(file, method, parameters)['calculation']
        chargefw2_total += chargefw2(file, method, parameters_file, chg_out_dir)['calculation']

    return api_total/count, pybind_total/count, chargefw2_total/count


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--count', help='How many times does the test repeats?')
    parser.add_argument('-ip', help='IP adress of server')
    parser.add_argument('--method', help='Computational method')
    parser.add_argument('--parameters', help='Parameters for method')
    parser.add_argument('--file', help='Path to file containing your structure')
    parser.add_argument('--parameters_file', help='Path to parameters for method')
    parser.add_argument('--chg_out_dir', help='Output directory for result from chargefw2')

    args = parser.parse_args()

    calc_api, calc_pybind, calc_chargefw2 = main(int(args.count), args.file, args.ip, args.method, args.parameters, args.parameters_file, args.chg_out_dir)
    print(f'API: {calc_api}')

    print(f'Pybind: {calc_pybind}')

    print(f'ChargeFW2: {calc_chargefw2}')
