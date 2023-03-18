import chargefw2_python
import pathlib
import subprocess

class Structure:
    def __init__(self, structure_id: str, file_manager):
        if structure_id not in file_manager:
            raise ValueError(f'Structure ID {structure_id} does not exists.')
        self._structure_id = structure_id
        self._file_manager = file_manager

    def set_file_manager(self, file_manager):
        self._file_manager = file_manager

    def get_structure_file(self):
        if self._structure_id in self._file_manager:
            return self._file_manager[self._structure_id]
        return None

    def get_molecules(self, read_hetatm: bool = True, ignore_water: bool = False):
        path_to_file = self.get_structure_file()
        if path_to_file is None:
            raise ValueError(f'Structure ID {self._structure_id} does not exist.')
        try:
            return chargefw2_python.Molecules(path_to_file, read_hetatm, ignore_water)
        except RuntimeError as e:
            raise ValueError(e)

    def get_parameters_without_suffix(self, params):
        new_params = []
        for par in params:
            new_params.append(pathlib.Path(par).stem)
        return new_params

    def format_methods(self, methods):
        result_format = []
        for item in methods:
            params = item[1]
            if params:
                params = self.get_parameters_without_suffix(params)
            else:
                params = None
            result_format.append({'method': item[0], 'parameters': params})
        return result_format

    def get_suitable_methods(self, read_hetatm: bool = True, ignore_water: bool = False):
        """Returns suitable methods for particular dataset"""
        molecules = self.get_molecules(read_hetatm, ignore_water)
        return self.format_methods(chargefw2_python.get_suitable_methods(molecules))

    def is_method_suitable(self, method, suitable_methods=None, read_hetatm: bool = True, ignore_water: bool = False):
        if not suitable_methods:
            suitable_methods = self.get_suitable_methods(read_hetatm, ignore_water)
        for item in suitable_methods:
            if item['method'] == method:
                return True
        return False

    def get_pdb_input_file(self) -> str:
        """Returns input file in pdb format (pdb2pqr can process only pdb files)"""
        input_file = self.get_structure_file()
        if not input_file:
            raise ValueError(f'Structure ID {self._structure_id} does not exist.')
        # cif format convert to pdb using gemmi convert
        if input_file.endswith('.cif'):
            try:
                subprocess.run(['gemmi', 'convert', f'{input_file}', f'{input_file[:-4]}.pdb'], check=True)
            except subprocess.CalledProcessError:
                raise ValueError(f'Error converting from .cif to .pdb using gemmi convert.')
            input_file = input_file[:-4] + '.pdb'
        if not input_file.endswith('pdb'):
            raise ValueError(f'{self._structure_id} is not in .pdb or .cif format')
        return input_file