from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


def load_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture
def master_utf8() -> bytes:
    return load_fixture("master_utf8.csv")


@pytest.fixture
def master_cp932() -> bytes:
    return load_fixture("master_cp932.csv")


@pytest.fixture
def sf_export() -> bytes:
    return load_fixture("salesforce_export.csv")
