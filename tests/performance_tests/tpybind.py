import chargefw2_python
from pathlib import Path
import time
import argparse

def all_in_one(path_to_file, method, parameters):
    start = time.perf_counter()
    molecules = chargefw2_python.Molecules(path_to_file)
    stop_load = time.perf_counter()

    # chargefw2_python.get_suitable_methods(molecules)
    charges_eem = chargefw2_python.calculate_charges(molecules, method, parameters)
    stop_calc = time.perf_counter()
    # return stop_load - start, stop_calc - start, charges_eem
    return {'loading_time': stop_load - start, 'calculation': stop_calc - start, 'charges': charges_eem}


def sequentially(path_to_folder, method, parameters):
    folder = Path(path_to_folder)
    loading_time = 0
    calc_time = 0
    files_count = 0
    start = time.perf_counter()
    for file in folder.iterdir():
        file = str(file)
        # print(file)
        files_count += 1
        start_loading = time.perf_counter()
        molecules = chargefw2_python.Molecules(file)
        stop_loading = time.perf_counter()

        charges = chargefw2_python.calculate_charges(molecules, method, parameters)
        # print(charges)
        stop_calculate = time.perf_counter()
        loading_time += stop_loading - start_loading
        calc_time += stop_calculate - start_loading
    stop = time.perf_counter()
    # return loading_time, stop - start, files_count
    return {'loading_time': loading_time, 'calculation': stop - start, 'files_number': files_count}


# TODO dodelat concurrentni
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--method', help='Computational method')
    parser.add_argument('--parameters', help='Parameters for method')
    parser.add_argument('--file', help='Path to file containing your strucutre')
    parser.add_argument('--folder', help='Path to folder with files')

    args = parser.parse_args()

    calc1 = all_in_one(args.file, args.method, args.parameters)['calculation']
    print(f'Allin1: calc - {calc1}')

    loading, calc, _ = pybind_sequentially(args.folder, args.method, args.parameters)
    print(f'Seq: calc - {calc}')



