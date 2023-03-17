import requests
import pytest

ip = '78.128.250.156:8080'

def available_methods():
    return requests.get(f'http://{ip}/available_methods')


def test_available_methods():
    response = available_methods().json()
    assert 'eem' in response['available_methods']


def available_parameters(method):
    return requests.get(f'http://{ip}/available_parameters',
                        params={'method': method})


@pytest.mark.parametrize('method, expected', [
    ('eem', 'OK'),
    ('aam', 'Method aam is not available.')
])
def test_available_parameters(method, expected):
    response = available_parameters(method).json()
    assert response['message'] == expected


def send_file(file):
    return requests.post(f'http://{ip}/send_files',
                         files={'file[]': open(file)})


valid_file_identifier = send_file('./../../1ner.pdb').json()['structure_ids']['1ner']
invalid_file_identifier = send_file('./../../code/6a5j.pdb').json()['structure_ids']['6a5j']

def suitable_methods(structure_id):
    return requests.get(f'http://{ip}/suitable_methods',
                        params={'structure_id': [structure_id]})


@pytest.mark.parametrize('structure_id, expected', [
    (valid_file_identifier, 'OK'),
    (invalid_file_identifier, 'No molecules were loaded'),
    (None, 'not specified structure ID'),
    ('jhskhk', 'Structure ID jhskhk does not exist')
])
def test_suitable_methods(structure_id, expected):
    response = suitable_methods(structure_id).json()
    assert expected in response['message']


def calculate_charges(structure_id, method, parameters):
    return requests.get(f'http://{ip}/calculate_charges',
                        params={'structure_id': structure_id,
                                'method': method,
                                'parameters': parameters})

# testy pro produkci
# @pytest.mark.parametrize('structure_id, method, parameters, expected', [
#     (valid_file_identifier, 'denr', 'DENR_00_from_QEq', 'OK'),
#     (valid_file_identifier, None, None, 'You have not specified calculation method'),
#     (valid_file_identifier, 'dgjybgcakgr', 'DENR_00_from_QEq', 'Method dgjybgcakgr is not available'),
#     (valid_file_identifier, 'eem', None, 'Method eem requires parameters'),
#     (valid_file_identifier, 'denr', 'EEM_00_NEEMP_ccd2016_npa', 'Parameters EEM_00_NEEMP_ccd2016_npa are not available'),
#     (valid_file_identifier, 'eqeq', 'gdfnxrg', 'Parameters gdfnxrg are not available'),
#     (valid_file_identifier, 'eqeq', 'DENR_00_from_QEq', 'Parameters DENR_00_from_QEq are not available'),
#     (valid_file_identifier, 'eem', 'EEM_00_NEEMP_ccd2016_npa', 'OK'),
#     (valid_file_identifier, 'abeem', 'ABEEM_00_original', "Selected parameters doesn't cover the whole molecule set"),
#     (invalid_file_identifier, 'eem', None, 'No molecules were loaded'),
#     (None, None, None, 'not specified structure ID'),
#     ('jhskhk', None, None, 'Structure ID jhskhk does not exist'),
# ])
# def test_calculate_charges(structure_id, method, parameters, expected):
#     response = calculate_charges(structure_id, method, parameters).json()
#     assert expected in response['message']

@pytest.mark.parametrize('structure_id, method, parameters, expected', [
    (valid_file_identifier, 'denr', 'DENR_00_from_QEq', 'OK'),
    (valid_file_identifier, None, None, 'OK'),
    (valid_file_identifier, 'dgjybgcakgr', 'DENR_00_from_QEq', 'Method dgjybgcakgr is not available'),
    (valid_file_identifier, 'eem', None, 'Method eem requires parameters'),
    (valid_file_identifier, 'denr', 'EEM_00_NEEMP_ccd2016_npa', 'not available for method'),
    (valid_file_identifier, 'eqeq', 'gdfnxrg', 'not available for method'),
    (valid_file_identifier, 'eqeq', 'DENR_00_from_QEq', 'not available for method'),
    (valid_file_identifier, 'eem', 'EEM_00_NEEMP_ccd2016_npa', 'OK'),
    (valid_file_identifier, 'abeem', 'ABEEM_00_original', "Selected parameters doesn't cover the whole molecule set"),
    (invalid_file_identifier, 'eem', None, 'No molecules were loaded'),
    (None, None, None, 'not specified structure ID'),
    ('jhskhk', None, None, 'Structure ID jhskhk does not exist'),
])
def test_calculate_charges(structure_id, method, parameters, expected):
    response = calculate_charges(structure_id, method, parameters).json()
    assert expected in response['message']

# valid_calc_id = calculate_charges(valid_file_identifier, 'denr', 'DENR_00_from_QEq').json()['calculation_id']
#
# def get_calculated_results(calculation_id):
#     return requests.get(f'http://{ip}/get_calculation_results', params={'calculation_id': calculation_id})
#
# @pytest.mark.parametrize('calculation_id, expected',[
#     ('1', 'Calculation ID does not exist'),
#     (valid_calc_id, 'OK'),
#     (None, 'You have not specified calculation ID obtained after calculation request'),
#     (valid_calc_id, 'Calculation ID does not exist'),    # id should be remove from system after user picks results up
# ])
# def test_get_calculated_results(calculation_id, expected):
#     response = get_calculated_results(calculation_id).json()
#     assert expected in response['message']


def pdb_id(identifier):
    return requests.post(f'http://{ip}/pdb_id', params={'pid[]': identifier})


def cid(identifier):
    return requests.post(f'http://{ip}/pubchem_cid', params={'cid[]': identifier})

sdf_identifier = cid('1').json()['structure_ids']['1']

@pytest.mark.parametrize('structure_id, expected', [
    ('1', 'OK'),
    ('hgkcgyargy', 'BadRequest'),
    (None, 'No pubchem cid specified')
])
def test_cid(structure_id, expected):
    response = cid(structure_id).json()
    assert expected in response['message']


def add_hydrogens(identifier):
    return requests.post(f'http://{ip}/add_hydrogens', params={'structure_id': identifier})


@pytest.mark.parametrize('structure_id, expected', [
    (valid_file_identifier, 'OK'),
    (sdf_identifier, 'not in .pdb or .cif format'),
    (invalid_file_identifier, 'Error occurred when using pdb2pqr30')
])
def test_add_hydrogens(structure_id, expected):
    response = add_hydrogens(structure_id).json()
    assert expected in response['message']



def get_info(identifier):
    return requests.get(f'http://{ip}/get_info', params={'structure_id': identifier})


@pytest.mark.parametrize('structure_id, expected', [
    (valid_file_identifier, "OK"),
    ('jsjsj', "does not exist")
])
def test_get_info(structure_id, expected):
    response= get_info(structure_id).json()
    assert expected in response["message"]


def remove_file(identifier):
    return requests.post(f'http://{ip}/remove_file', params={'structure_id': identifier})


@pytest.mark.parametrize('structure_id, expected', [
    (valid_file_identifier, 'OK')
])
def test_remove_file(structure_id, expected):
    get_info_json = get_info(structure_id).json()
    assert expected in get_info_json['message']
    remove_file_json = remove_file(structure_id).json()
    assert expected in remove_file_json['message']
    get_info_after_removing = get_info(structure_id).json()
    assert expected not in get_info_after_removing['message']
