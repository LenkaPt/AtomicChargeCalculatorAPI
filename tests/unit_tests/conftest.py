import pytest


def pytest_addoption(parser):
    parser.addoption(
        '--url', action='store', help='Base URL for the API tests'
    )
    parser.addoption(
        '--valid_id', action='store', help='ID of correct file'
    )
    parser.addoption(
        '--invalid_id', action='store', help='ID of file in invalid format'
    )
    parser.addoption(
        '--sdf_id', action='store', help='ID of file in sdf format'
    )
    parser.addoption(
        '--valid_file', action='store', help='File in valid format'
    )
    parser.addoption(
        '--invalid_format', action='store', help='File in not supported format'
    )
    parser.addoption(
        '--big_file', action='store', help='File larger than 10 Mb'
    )
    parser.addoption(
        '--max_long_calc', action='store', help='How many long calculations is allowed to user'
    )
    parser.addoption(
        '--granted_space', action='store', help='Space granted for user'
    )


@pytest.fixture(scope='module')
def url(request):
    url = request.config.getoption('--url')
    return url


@pytest.fixture(scope='module')
def valid_id(request):
    valid_id = request.config.getoption('--valid_id')
    return valid_id


@pytest.fixture(scope='module')
def invalid_id(request):
    invalid_id = request.config.getoption('--invalid_id')
    return invalid_id


@pytest.fixture(scope='module')
def sdf_id(request):
    sdf_id = request.config.getoption('--sdf_id')
    return sdf_id


@pytest.fixture(scope='module')
def valid_file(request):
    valid_file = request.config.getoption('--valid_file')
    return valid_file


@pytest.fixture(scope='module')
def invalid_format(request):
    invalid_format = request.config.getoption('--invalid_format')
    return invalid_format


@pytest.fixture(scope='module')
def big_file(request):
    big_file = request.config.getoption('--big_file')
    return big_file


@pytest.fixture(scope='module')
def max_long_calc(request):
    max_long_calc = request.config.getoption('--max_long_calc')
    return max_long_calc


@pytest.fixture(scope='module')
def granted_space(request):
    granted_space = request.config.getoption('--granted_space')
    return granted_space
