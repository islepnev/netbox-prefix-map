import pytest
from app.webapp import build_prefix_tree

@pytest.fixture
def mock_prefixes():
    return [
        {"prefix": "10.0.0.0/16", "children": 3},
        {"prefix": "10.0.1.0/24", "children": 0},
        {"prefix": "10.0.2.0/24", "children": 0},
        {"prefix": "10.0.3.0/24", "children": 0},
        {"prefix": "192.168.0.0/16", "children": 1},
        {"prefix": "192.168.1.0/24", "children": 0}
    ]

def test_build_prefix_tree(mock_prefixes):
    result = build_prefix_tree(mock_prefixes)
    expected_tree = {
        "10.0.0.0/16": {
            "10.0.1.0/24": {},
            "10.0.2.0/24": {},
            "10.0.3.0/24": {}
        },
        "192.168.0.0/16": {
            "192.168.1.0/24": {}
        }
    }
    assert result == expected_tree
