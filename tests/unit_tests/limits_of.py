import requests
import pytest


def send_file(file, url):
    return requests.post(f'http://{url}/send_files',
                         files={'file[]': open(file)})


def test_send_file(url, valid_file, invalid_format, big_file):
    assert 'OK' in send_file(valid_file, url).json()['message']
    assert 'Unsupported format' in send_file(invalid_format, url).json()['message']
    assert 'OK' in send_file(big_file, url).json()['message']


def calculate_charges(structure_id, method, parameters, url):
    return requests.get(f'http://{url}/calculate_charges',
                        params={'structure_id': structure_id,
                                'method': method,
                                'parameters': parameters})


# def test_calculate_charges(structure_id, method, parameters, expected):
#     response = calculate_charges(structure_id, method, parameters).json()
#     assert expected in response['message']


def pdb_id(identifier, url):
    return requests.post(f'http://{url}/pdb_id', params={'pid[]': identifier})


@pytest.mark.parametrize('structure_id, expected', [
    ('1ner', 'OK'),
    ('4wfb', 'OK'),
    ('hgkcgyargy', 'Not Found for url'),
    (None, 'No pdb id specified')
])
def test_pdb_id(structure_id, expected, url):
    response = pdb_id(structure_id, url).json()
    assert expected in response['message']


def get_limits(url):
    return requests.get(f'http://{url}/get_limits')


def test_get_limits(url):
    response = get_limits(url).json()
    assert 'No restrictions turned on' in response['message']
