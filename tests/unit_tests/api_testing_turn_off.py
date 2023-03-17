import requests
import pytest
import api_testing

ip = '78.128.250.156:8080'

valid_file_identifier = api_testing.send_file('./../../1ner.pdb').json()['structure_ids']['1ner']
invalid_file_identifier = api_testing.send_file('./../../code/6a5j.pdb').json()['structure_ids']['6a5j']


@pytest.mark.parametrize('structure_id, expected', [
    ('./../../1ner.pdb', 'OK'),
    ('./../../test.txt', 'Unsupported format'),
    ('./../../4wfb.pdb', 'OK')
])
def test_send_file(structure_id, expected):
    response = api_testing.send_file(structure_id).json()
    assert expected in response['message']


def calculate_charges(structure_id, method, parameters):
    return requests.get(f'http://{ip}/calculate_charges',
                        params={'structure_id': structure_id,
                                'method': method,
                                'parameters': parameters})


#################################
# # TODO
# @pytest.mark.parametrize('structure_id, method, parameters, expected', [
#     (valid_file_identifier, 'denr', 'DENR_00_from_QEq', 'OK'),
#     (valid_file_identifier, None, None, 'not specified calculation method'),
#     (valid_file_identifier, 'dgjybgcakgr', 'DENR_00_from_QEq', 'Method dgjybgcakgr is not available'),
#     (valid_file_identifier, 'eem', None, 'Method eem requires parameters'),
#     (valid_file_identifier, 'denr', 'EEM_00_NEEMP_ccd2016_npa', 'Parameters EEM_00_NEEMP_ccd2016_npa are not available for method denr'),
#     (valid_file_identifier, 'eqeq', 'gdfnxrg', 'Parameters gdfnxrg are not available for method eqeq'),
#     (valid_file_identifier, 'eqeq', 'DENR_00_from_QEq', 'Parameters DENR_00_from_QEq are not available for method eqeq'),
#     (valid_file_identifier, 'eem', 'EEM_00_NEEMP_ccd2016_npa', 'OK'),
#     (invalid_file_identifier, 'eem', None, 'No molecules were loaded'),
#     (None, None, None, 'not specified structure ID'),
#     ('jhskhk', None, None, 'Structure ID jhskhk does not exist')
# ])
# def test_calculate_charges(structure_id, method, parameters, expected):
#     response = calculate_charges(structure_id, method, parameters).json()
#     assert expected in response['message']

#!!!!! (valid_file_identifier, 'eqeq', 'gdfnxrg', 'Parameters gdfnxrg are not available for method eqeq')
#!!!!! (valid_file_identifier, 'eqeq', 'DENR_00_from_QEq', 'Parameters DENR_00_from_QEq are not available for method eqeq')
#####################################################


@pytest.mark.parametrize('structure_id, expected', [
    ('1ner', 'OK'),
    ('4wfb', 'OK'),
    ('hgkcgyargy', 'Not Found for url'),
    (None, 'No pdb id specified')
])
def test_pdb_id(structure_id, expected):
    response = api_testing.pdb_id(structure_id).json()
    assert expected in response['message']


sdf_identifier = api_testing.cid('1').json()['structure_ids']['1']


def get_limits():
    return requests.get(f'http://{ip}/get_limits')

def test_get_limits():
    response = get_limits().json()
    assert 'No restrictions turned on' in response['message']
