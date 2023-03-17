import tapi
import tpybind
import tchargefw2
from datetime import date
import concurrent.futures
import threading
import argparse
import time

def get_calc_time(count, func, *args):
    calc_time = 0
    for _ in range(count):
            calc_time += func(*args)['calculation']
    return round(calc_time/count, 2)


def all_in_one(count, file, ip, method, parameters, parameters_file, chg_out_dir):
    api = get_calc_time(count, tapi.all_in_one, file, ip, method, parameters)
    pybind = get_calc_time(count, tpybind.all_in_one, file, method, parameters)
    chargefw2 = get_calc_time(count, tchargefw2.all_in_one, file, method, parameters_file, chg_out_dir)
    return api, pybind, chargefw2


def results_summary_all_in_one(api, pybind, chargefw2):
    return f'All molecules in one file:\n' \
           f'Calculation via API: {api}\n' \
           f'Calculation via pybind: {pybind}\n' \
           f'Calculation via chargefw2: {chargefw2}\n\n'


def sequentially(count, folder, ip, method, parameters, path_to_parameters, chg_out_dir):
    api = get_calc_time(count, tapi.sequentially, folder, ip, method, parameters)
    pybind = get_calc_time(count, tpybind.sequentially, folder, method, parameters)
    chargefw2 = get_calc_time(count, tchargefw2.sequentially, folder, method, path_to_parameters, chg_out_dir)
    return api, pybind, chargefw2


def results_summary_sequentially(api, pybind, chargefw2):
    return f'Molecules sequentially:\n' \
           f'Calculation via API: {api}\n' \
           f'Calculation via pybind: {pybind}\n' \
           f'Calculation via chargefw2: {chargefw2}\n\n'


def concurently(count, folder, ip, method, parameters):
    api = get_calc_time(count, tapi.concurrently, folder, ip, method, parameters)
    return api


def results_summary_concurently(api):
    return f'Molecules concurently:\n' \
           f'Calculation via API: {api}\n\n'


def main(count, output_file, file, folder, ip, method, parameters, parameters_file, chg_out_dir):
    # All molecules in one file
    api1, pybind1, chargefw21 = all_in_one(count, file, ip, method, parameters, parameters_file, chg_out_dir)

    # Molecules sequentially
    # api2, pybind2, chargefw22 = sequentially(count, folder, ip, method, parameters, parameters_file, chg_out_dir)

    # concurently
    # api3 = concurently(count, folder, ip, method, parameters)

    with open(output_file, mode='a') as output:
        output.write(f'Count: {count}\n')
        output.write(f'{date.today().strftime("%d/%m/%Y")}, {time.strftime("%H:%M:%S", time.localtime())}\n')

        output.write(results_summary_all_in_one(api1, pybind1, chargefw21))
        # output.write('-------------------------------------------------------\n')

        # output.write(results_summary_sequentially(api2, pybind2, chargefw22))

        # output.write('--------------------------------------------------------\n')
        # output.write(results_summary_concurently(api3))
        output.write('||||||||||||||||||||||||||||||||||||||||||||||||||||||||||\n\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--count', help='How many times does the test repeats?')
    parser.add_argument('--output_file', help='Path to output file containing results')
    parser.add_argument('--ip', help='IP adress of server')
    parser.add_argument('--method', help='Computational method')
    parser.add_argument('--parameters', help='Parameters for method')
    parser.add_argument('--file', help='Path to file containing your strucutre')
    parser.add_argument('--folder', help='Path to folder with files')
    parser.add_argument('--parameters_file', help='Path to parameters for method')
    parser.add_argument('--chg_out_dir', help='Output directory for result from chargefw2')

    args = parser.parse_args()

    try:
        main(args.count, args.output_file, args.file, args.folder, args.ip, args.method, args.parameters,
             args.parameters_file, args.chg_out_dir)
    except ValueError as e:
        with open(output_file, mode='a') as output:
            output.write(f'{date.today().strftime("%d/%m/%Y")}, {time.strftime("%H:%M:%S", time.localtime())}\n')
            output.write(e)
        raise ValueError(e)



