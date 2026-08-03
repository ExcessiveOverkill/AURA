import os
import sys
import shutil

import pytest

_ROOT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, _ROOT_DIR)

from register_mapper import RegisterMapGenerator, Register, Group
from device_firmware_gen import FirmwareGenerator
from cpp_writer import CppWriter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_rm():
    rm = RegisterMapGenerator("test_mod", [], word_width=32)
    rm.add(Register("status",  rw="r",  type="unsigned", width=8))
    rm.add(Register("control", rw="w",  type="unsigned", width=8))
    rm.add(Register("config",  rw="rw", type="unsigned", width=16))
    rm.generate()
    return rm


@pytest.fixture
def banked_rm():
    rm = RegisterMapGenerator("bank_mod", [], word_width=32)
    rm.add(Register("channel", rw="r", type="unsigned", width=8, bank_size=4))
    rm.generate()
    return rm


@pytest.fixture
def grouped_rm():
    rm = RegisterMapGenerator("group_mod", [], word_width=32)
    g = Group("periph", count=2)
    g.add(Register("enable", rw="r", type="bool"))
    g.add(Register("value", rw="w", type="unsigned", width=16))
    rm.add(g)
    rm.generate()
    return rm


@pytest.fixture
def nested_counted_rm():
    rm = RegisterMapGenerator("nested_counted_mod", [], word_width=32)
    outer = Group("outer", count=2)
    inner = Group("inner", count=3)
    inner.add(Register("leaf", rw="rw", type="unsigned", width=8))
    outer.add(inner)
    rm.add(outer)
    rm.generate()
    return rm


@pytest.fixture
def multiword_rm():
    rm = RegisterMapGenerator("mw_mod", [], word_width=32)
    rm.add(Register("big_val", rw="r", type="unsigned", width=64))
    rm.generate()
    return rm


@pytest.fixture
def min_access_rm():
    """8-bit word, 32-bit minimum access (min_access_words=4).
    A 32-bit register (4 words) should NOT need buffers; a 64-bit (8 words) should."""
    rm = RegisterMapGenerator("maw_mod", [], word_width=8, min_access_words=4)
    rm.add(Register("small", rw="r", type="unsigned", width=32, start_address=0x00))
    rm.add(Register("large", rw="r", type="unsigned", width=64, start_address=0x04))
    rm.generate()
    return rm


@pytest.fixture
def enum_rm():
    rm = RegisterMapGenerator("enum_mod", [], word_width=32)
    rm.add(Register("mode", rw="r", type="unsigned", width=8,
                    enum={"IDLE": 0, "RUN": 1, "SLEEP": 2}))
    rm.generate()
    return rm


@pytest.fixture
def bitfield_rm():
    rm = RegisterMapGenerator("bf_mod", [], word_width=32)
    en = Register("enabled", rw="r", type="bool")
    lvl = Register("level", rw="r", type="unsigned", width=4)
    rm.add(Register("ctrl", rw="r", type="unsigned", width=8, bit_field=[en, lvl]))
    rm.generate()
    return rm


@pytest.fixture
def json_rm():
    path = os.path.join(os.path.dirname(__file__), "../../register_mapper/test.json")
    return RegisterMapGenerator.fromJSON(path)


@pytest.fixture
def out_dir(tmp_path):
    d = tmp_path / "output"
    d.mkdir()
    return str(d)


@pytest.fixture
def compiler():
    cc = shutil.which("g++") or shutil.which("clang++")
    if cc is None:
        pytest.skip("No C++ compiler found")
    return cc
