import sys
import os
import shutil

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "../../..")))


@pytest.fixture
def compiler():
    cc = shutil.which("g++") or shutil.which("clang++")
    if cc is None:
        pytest.skip("No C++ compiler found")
    return cc
