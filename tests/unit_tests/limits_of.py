import requests
import pytest
from pathlib import Path


def send_file(file, url):
    return requests.post(f'http://{url}/send_files',
                         files={'file[]': open(file)})


def test_send_file(url, valid_file, invalid_format, big_file):
    assert 'OK' in send_file(valid_file, url).json()['message']
    assert 'unsupported format' in send_file(invalid_format, url).json()['message']
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
    ('hgkcgyargy', 'Not Found for url'),
    (None, 'No pdb id specified')
])
def test_pdb_id(structure_id, expected, url, valid_pdb_id, big_molecule_pdb_id):
    assert 'OK' in pdb_id(valid_pdb_id, url).json()['message']
    assert 'OK' in pdb_id(big_molecule_pdb_id, url).json()['message']
    response = pdb_id(structure_id, url).json()
    assert expected in response['message']


def get_limits(url):
    return requests.get(f'http://{url}/get_limits')


def test_get_limits(url):
    response = get_limits(url).json()
    assert 'No restrictions turned on' in response['message']


def test_space_not_limited(url, granted_space, valid_file):
    response_send_file = send_file(valid_file, url).json()['message']
    file_size = Path(valid_file).stat().st_size
    crowded_space = file_size
    while float(granted_space) >= crowded_space:
        response_send_file = send_file(valid_file, url).json()['message']
        crowded_space += file_size
    # user is not limited by space
    assert response_send_file == 'OK'
