import requests
import pytest


def available_methods(url):
    return requests.get(f'http://{url}/available_methods')


def test_available_methods(url):
    response = available_methods(url).json()
    assert 'eem' in response['available_methods']


def available_parameters(method, url):
    return requests.get(f'http://{url}/available_parameters',
                        params={'method': method})


@pytest.mark.parametrize('method, expected', [
    ('eem', 'OK'),
    ('aam', 'Method aam is not available.')
])
def test_available_parameters(method, expected, url):
    response = available_parameters(method, url).json()
    assert response['message'] == expected


def suitable_methods(structure_id, url):
    return requests.get(f'http://{url}/suitable_methods',
                        params={'structure_id': [structure_id]})


@pytest.mark.parametrize('structure_id, expected', [
    # (valid_id, 'OK'),
    # (invalid_id, 'No molecules were loaded'),
    (None, 'Structure ID not specified'),
    ('jhskhk', 'Structure ID jhskhk does not exist')
])
def test_suitable_methods(structure_id, expected, url, valid_id, invalid_id):
    assert 'OK' in suitable_methods(valid_id, url).json()['message']
    assert 'No molecules were loaded' in suitable_methods(invalid_id, url).json()['message']
    response = suitable_methods(structure_id, url).json()
    assert expected in response['message']


def calculate_charges(structure_id, method, parameters, url):
    return requests.get(f'http://{url}/calculate_charges',
                        params={'structure_id': structure_id,
                                'method': method,
                                'parameters': parameters})


@pytest.mark.parametrize('structure_id, method, parameters, expected', [
    (None, None, None, 'Structure ID not specified'),
    ('jhskhk', None, None, 'Structure ID jhskhk does not exist'),
])
def test_calculate_charges(structure_id, method, parameters, expected, url, valid_id, invalid_id):
    assert 'OK' in calculate_charges(valid_id, 'denr', 'DENR_00_from_QEq', url).json()['message']
    assert 'OK' in calculate_charges(valid_id, None, None, url).json()['message']
    assert 'Method dgjybgcakgr is not available' in \
           calculate_charges(valid_id, 'dgjybgcakgr', 'DENR_00_from_QEq', url).json()['message']
    assert 'Method eem requires parameters' in calculate_charges(valid_id, 'eem', None, url).json()['message']
    assert 'Invalid common parameters provided' in \
           calculate_charges(valid_id, 'denr', 'EEM_00_NEEMP_ccd2016_npa', url).json()['message']
    assert 'OK' in calculate_charges(valid_id, 'eqeq', 'gdfnxrg', url).json()['message']   # eqeq ignores parameters, because it does not require one
    assert 'OK' in calculate_charges(valid_id, 'eqeq', 'DENR_00_from_QEq', url).json()['message']  # eqeq ignores parameters, because it does not require one
    assert 'OK' in calculate_charges(valid_id, 'eem', 'EEM_00_NEEMP_ccd2016_npa', url).json()['message']
    assert "Selected parameters doesn't cover the whole molecule set" in \
           calculate_charges(valid_id, 'abeem', 'ABEEM_00_original', url).json()['message']
    assert 'No molecules were loaded' in calculate_charges(invalid_id, 'eem', None, url).json()['message']

    response = calculate_charges(structure_id, method, parameters, url).json()
    assert expected in response['message']


def cid(identifier, url):
    return requests.post(f'http://{url}/pubchem_cid', params={'cid[]': identifier})


@pytest.mark.parametrize('structure_id, expected', [
    ('1', 'OK'),
    ('hgkcgyargy', 'BadRequest'),
    (None, 'No pubchem cid specified')
])
def test_cid(structure_id, expected, url):
    response = cid(structure_id, url).json()
    assert expected in response['message']


def add_hydrogens(identifier, url):
    return requests.post(f'http://{url}/add_hydrogens', params={'structure_id': identifier})


def test_add_hydrogens(url, valid_id, invalid_id, sdf_id):
    assert 'OK' in add_hydrogens(valid_id, url).json()['message']
    assert 'not in .pdb or .cif format' in add_hydrogens(sdf_id, url).json()['message']
    assert 'Error occurred when using pdb2pqr30' in add_hydrogens(invalid_id, url).json()['message']



def get_info(identifier, url):
    return requests.get(f'http://{url}/get_info', params={'structure_id': identifier})


@pytest.mark.parametrize('structure_id, expected', [
    # (valid_file_identifier, "OK"),
    ('jsjsj', "does not exist")
])
def test_get_info(structure_id, expected, url, valid_id):
    assert 'OK' in get_info(valid_id, url).json()["message"]

    response= get_info(structure_id, url).json()
    assert expected in response["message"]


def remove_file(identifier, url):
    return requests.post(f'http://{url}/remove_file', params={'structure_id': identifier})


def test_remove_file(url, valid_id):
    assert 'OK' in get_info(valid_id, url).json()['message']
    assert 'OK' in remove_file(valid_id, url).json()['message']
    get_info_after_removing = get_info(valid_id, url).json()
    assert 'OK' not in get_info_after_removing['message']