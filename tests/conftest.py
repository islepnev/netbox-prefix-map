import os
import sys
import tempfile

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

# Configure the app before anything imports app.webapp (it reads env at import time)
OUTPUT_DIR = tempfile.mkdtemp(prefix="prefix-map-test-")
os.environ['OUTPUT_DIR'] = OUTPUT_DIR
os.environ['CELL_SIZE'] = '12'
os.environ['BASE_PATH'] = '/prefix-map'
os.environ['NETBOX_API_URL'] = 'https://netbox.example.test'
os.environ.pop('WEBHOOK_SECRET', None)
os.environ.pop('NETBOX_API_TOKEN', None)

CELL_SIZE = 12


@pytest.fixture(scope="session")
def dataset():
    from tests.synthetic_data import build_dataset
    return build_dataset()


@pytest.fixture(scope="session")
def output_dir(dataset):
    """Run a full update against the synthetic dataset once per test session."""
    from app.cli import full_update
    from tests.synthetic_data import FakeNetboxManager
    assert full_update(mgr=FakeNetboxManager(dataset)) is True
    return OUTPUT_DIR


@pytest.fixture
def webapp(output_dir):
    import app.webapp as webapp
    return webapp


@pytest.fixture
def client(webapp):
    webapp.app.config['TESTING'] = True
    return webapp.app.test_client()
