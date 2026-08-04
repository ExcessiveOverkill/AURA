import struct

import pytest
from device_firmware_gen import FirmwareGenerator
from register_mapper import Register, RegisterMapGenerator


@pytest.fixture
def gen(simple_rm):
    return FirmwareGenerator(simple_rm)


def _gen_for(reg_type, rw="r", width=None, word_width=32):
    rm = RegisterMapGenerator("m", [], word_width=word_width)
    kwargs = {"rw": rw, "type": reg_type}
    if width is not None:
        kwargs["width"] = width
    rm.add(Register("r", **kwargs))
    rm.generate()
    g = FirmwareGenerator(rm)
    reg = rm.base_group.contents["r"]
    return g, reg


# ---------------------------------------------------------------------------
# _to_pascal
# ---------------------------------------------------------------------------

class TestToPascal:
    def test_single_word(self, gen):
        assert gen._to_pascal("status") == "Status"

    def test_snake_case(self, gen):
        assert gen._to_pascal("big_value") == "BigValue"

    def test_three_parts(self, gen):
        assert gen._to_pascal("a_b_c") == "ABC"

    def test_already_capitalized(self, gen):
        assert gen._to_pascal("Foo") == "Foo"

    def test_empty_string(self, gen):
        assert gen._to_pascal("") == ""


# ---------------------------------------------------------------------------
# _struct_type
# ---------------------------------------------------------------------------

class TestStructType:
    def test_single_part(self, gen):
        assert gen._struct_type("ctrl") == "Ctrl_t"

    def test_multi_part(self, gen):
        assert gen._struct_type("group", "reg") == "GroupReg_t"

    def test_snake_parts(self, gen):
        assert gen._struct_type("my_group", "my_reg") == "MyGroupMyReg_t"

    def test_trailing_t(self, gen):
        assert gen._struct_type("foo").endswith("_t")


# ---------------------------------------------------------------------------
# _rw_to_access
# ---------------------------------------------------------------------------

class TestRwToAccess:
    def test_read(self, gen):
        assert gen._rw_to_access("r") == "RegAccess::READ"

    def test_write(self, gen):
        assert gen._rw_to_access("w") == "RegAccess::WRITE"

    def test_read_write(self, gen):
        assert gen._rw_to_access("rw") == "RegAccess::READ_WRITE"


# ---------------------------------------------------------------------------
# _word_encode
# ---------------------------------------------------------------------------

class TestWordEncode:
    def test_unsigned_zero(self):
        g, reg = _gen_for("unsigned", width=8)
        assert g._word_encode(reg, 0) == 0

    def test_unsigned_value(self):
        g, reg = _gen_for("unsigned", width=8)
        assert g._word_encode(reg, 5) == 5

    def test_unsigned_masked(self):
        # Value larger than word width (32 bits) gets masked
        g, reg = _gen_for("unsigned", width=8)
        assert g._word_encode(reg, 0x1_0000_0001) == 1

    def test_bool_true(self):
        g, reg = _gen_for("bool")
        assert g._word_encode(reg, True) == 1

    def test_bool_false(self):
        g, reg = _gen_for("bool")
        assert g._word_encode(reg, False) == 0

    def test_signed_positive(self):
        g, reg = _gen_for("signed", width=8)
        assert g._word_encode(reg, 10) == 10

    def test_signed_negative(self):
        g, reg = _gen_for("signed", width=8)
        # -1 & 0xFFFFFFFF == 0xFFFFFFFF
        assert g._word_encode(reg, -1) == 0xFFFFFFFF

    def test_float_ieee754_one(self):
        g, reg = _gen_for("float")
        expected = struct.unpack("<I", struct.pack("<f", 1.0))[0]
        assert g._word_encode(reg, 1.0) == expected

    def test_float_ieee754_zero(self):
        g, reg = _gen_for("float")
        assert g._word_encode(reg, 0.0) == 0

    def test_none_returns_zero(self):
        g, reg = _gen_for("unsigned", width=8)
        assert g._word_encode(reg, None) == 0

    def test_double_returns_zero(self):
        # double at word_width=32 has no special handling → returns 0
        g, reg = _gen_for("double")
        assert g._word_encode(reg, 1.0) == 0


# ---------------------------------------------------------------------------
# _ns, _prefix, _filepath
# ---------------------------------------------------------------------------

class TestNsAndPrefix:
    def test_ns_format(self, gen):
        assert gen._ns() == "Regs"

    def test_ns_contains_module_name(self, gen):
        # Namespace is now fixed — does not contain the module name
        assert gen._ns() == "Regs"

    def test_filepath_construction(self, gen):
        result = gen._filepath("/out", "foo.hpp")
        import os
        assert result == os.path.join("/out", "foo.hpp")

    def test_module_name_normalised(self):
        # Module name normalisation is internal; _ns() is always "Regs"
        rm = RegisterMapGenerator("My-Module Name", [], word_width=32)
        rm.add(Register("r", rw="r", type="unsigned", width=8))
        rm.generate()
        g = FirmwareGenerator(rm)
        assert g._ns() == "Regs"
