import pytest
from register_mapper import Register


# ---------------------------------------------------------------------------
# Init validation
# ---------------------------------------------------------------------------

class TestRegisterInit:
    def test_invalid_type(self):
        with pytest.raises(ValueError, match="Invalid type"):
            Register("r", "r", type="complex")

    def test_invalid_width_zero(self):
        with pytest.raises(ValueError, match="Invalid width"):
            Register("r", "r", width=0)

    def test_invalid_width_negative(self):
        with pytest.raises(ValueError, match="Invalid width"):
            Register("r", "r", width=-2)    # -1 is for auto, but negative values other than -1 are invalid

    def test_invalid_rw(self):
        with pytest.raises(ValueError, match="Invalid rw"):
            Register("r", "x")

    def test_invalid_bank_size_zero(self):
        with pytest.raises(ValueError, match="Invalid bank_size"):
            Register("r", "r", bank_size=0)

    def test_invalid_bank_size_too_large(self):
        with pytest.raises(ValueError, match="Invalid bank_size"):
            Register("r", "r", bank_size=0x10000)

    def test_invalid_start_address_negative(self):
        with pytest.raises(ValueError, match="Invalid start_address"):
            Register("r", "r", start_address=-2)    # -1 is for auto, but negative values other than -1 are invalid

    def test_invalid_start_address_too_large(self):
        with pytest.raises(ValueError, match="Invalid start_address"):
            Register("r", "r", start_address=0x10000)

    def test_invalid_bit_field_item(self):
        with pytest.raises(ValueError, match="Invalid sub_register"):
            Register("r", "r", bit_field=["not_a_register"])

    def test_invalid_enum_not_dict(self):
        with pytest.raises(ValueError, match="Invalid enum"):
            Register("r", "r", enum=[("A", 0)])

    def test_invalid_enum_on_non_unsigned(self):
        with pytest.raises(ValueError, match="Enum type must be unsigned"):
            Register("r", "r", type="signed", enum={"A": 0})

    def test_invalid_enum_name_type(self):
        with pytest.raises(ValueError, match="Invalid enum name"):
            Register("r", "r", enum={1: 0})

    def test_invalid_enum_value_type(self):
        with pytest.raises(ValueError, match="Invalid enum value"):
            Register("r", "r", enum={"A": "zero"})

    def test_invalid_enum_value_negative(self):
        with pytest.raises(ValueError, match="Invalid enum value"):
            Register("r", "r", enum={"A": -1})

    def test_invalid_enum_value_exceeds_width(self):
        with pytest.raises(ValueError, match="Enum value exceeds register width"):
            Register("r", "r", width=2, enum={"A": 4})

    def test_invalid_unit_type(self):
        with pytest.raises(ValueError, match="Invalid unit"):
            Register("r", "r", unit=123)

    def test_invalid_unsigned_min_out_of_range(self):
        with pytest.raises(ValueError, match="min value out of range"):
            Register("r", "r", type="unsigned", width=4, min_val=-1)

    def test_invalid_unsigned_max_out_of_range(self):
        with pytest.raises(ValueError, match="max value out of range"):
            Register("r", "r", type="unsigned", width=4, max_val=16)

    def test_invalid_unsigned_default_out_of_range(self):
        with pytest.raises(ValueError, match="default value out of range"):
            Register("r", "r", type="unsigned", width=4, default_val=16)
        with pytest.raises(ValueError, match="default value out of range"):
            Register("r", "r", type="unsigned", width=4, default_val=-1)

    def test_invalid_signed_min_out_of_range(self):
        with pytest.raises(ValueError, match="min value out of range"):
            Register("r", "r", type="signed", width=4, min_val=-9)

    def test_invalid_signed_max_out_of_range(self):
        with pytest.raises(ValueError, match="max value out of range"):
            Register("r", "r", type="signed", width=4, max_val=8)

    def test_invalid_signed_default_out_of_range(self):
        with pytest.raises(ValueError, match="default value out of range"):
            Register("r", "r", type="signed", width=4, default_val=8)
        with pytest.raises(ValueError, match="default value out of range"):
            Register("r", "r", type="signed", width=4, default_val=-9)

    def test_invalid_min_greater_than_max(self):
        with pytest.raises(ValueError, match="min value must be <= max value"):
            Register("r", "r", min_val=5, max_val=3)

    def test_invalid_default_less_than_min(self):
        with pytest.raises(ValueError, match="default value must be >= min value"):
            Register("r", "r", min_val=5, default_val=4)

    def test_invalid_default_greater_than_max(self):
        with pytest.raises(ValueError, match="default value must be <= max value"):
            Register("r", "r", max_val=5, default_val=6)

    def test_valid_unsigned_type(self):
        r = Register("ru", "r", type="unsigned")
        assert r.type == "unsigned"

    def test_valid_signed_type(self):
        r = Register("rs", "r", type="signed")
        assert r.type == "signed"

    def test_valid_bool_type(self):
        r = Register("rb", "r", type="bool")
        assert r.type == "bool"

    def test_valid_float_type(self):
        r = Register("rf", "r", type="float")
        assert r.type == "float"

    def test_valid_double_type(self):
        r = Register("rd", "r", type="double")
        assert r.type == "double"

    def test_invalid_bool_width(self):
        with pytest.raises(ValueError, match="Bool type must have width 1"):
            Register("rb", "r", type="bool", width=8)

    def test_invalid_float_width(self):
        with pytest.raises(ValueError, match="Float type must have width 32"):
            Register("rf", "r", type="float", width=16)

    def test_invalid_double_width(self):
        with pytest.raises(ValueError, match="Double type must have width 64"):
            Register("rd", "r", type="double", width=32)

    def test_valid_construction(self):
        r = Register("reg", "r", type="unsigned", width=16, start_address=0x10, desc="test", bank_size=2, enum={"ZERO": 0})
        assert r.name == "reg"
        assert r.rw == "r"
        assert r.type == "unsigned"
        assert r.width == 16
        assert r.start_address == 0x10
        assert r.desc == "test"
        assert r.bank_size == 2
        assert r.enum["ZERO"] == 0

    def test_rw_empty_string_allowed_at_init(self):
        # rw="" is valid at construction (sub-registers inherit rw at generate time)
        r = Register("r", rw="")
        assert r.rw == ""

    def test_rw_read_write_valid(self):
        r = Register("reg", rw="rw")
        assert r.rw == "rw"

    def test_rw_read_valid(self):
        r = Register("reg", rw="r")
        assert r.rw == "r"

    def test_rw_write_valid(self):
        r = Register("reg", rw="w")
        assert r.rw == "w"


# ---------------------------------------------------------------------------
# generate() — single register
# ---------------------------------------------------------------------------

class TestRegisterGenerate:
    def test_map_keys_present(self):
        r = Register("reg", "r", width=32)
        r.generate()
        for key in ("name", "address_offset", "type", "bank_size", "description",
                    "width", "word_width", "words_per_register", "starting_bit", "rw", "bit_field", "enum", "min", "max", "default", "unit"):
            assert key in r.map, f"Missing key: {key}"

    def test_enum_in_map(self):
        r = Register("reg", "r", width=8, enum={"OFF": 0, "ON": 1})
        r.generate()
        assert r.map["enum"]["OFF"] == 0
        assert r.map["enum"]["ON"] == 1

    def test_metadata_in_map(self):
        r = Register("reg", "r", width=8, min_val=1, max_val=7, default_val=3, unit="V")
        r.generate()
        assert r.map["min"] == 1
        assert r.map["max"] == 7
        assert r.map["default"] == 3
        assert r.map["unit"] == "V"

    def test_single_word_register(self):
        r = Register("reg", "r", width=32)
        r.generate(word_width=32)
        assert r.map["words_per_register"] == 1
        assert r.map["word_width"] == 32

    def test_used_addresses_no_start(self):
        r = Register("reg", "r", width=32)
        r.generate(word_width=32)
        assert list(r.used_addresses) == [0]

    def test_used_addresses_with_start(self):
        r = Register("reg", "r", width=32, start_address=0x5)
        r.generate(word_width=32)
        assert list(r.used_addresses) == [0x5]

    def test_rw_missing_raises(self):
        r = Register("reg", rw="")
        with pytest.raises(ValueError, match="rw must be set"):
            r.generate()

    def test_generate_sets_generated_flag(self):
        r = Register("reg", "r")
        r.generate()
        assert r.generated is True

    def test_starting_bit_is_zero_for_top_level(self):
        r = Register("reg", "r")
        r.generate()
        assert r.map["starting_bit"] == 0

    def test_empty_bit_field_in_map(self):
        r = Register("reg", "r")
        r.generate()
        assert r.map["bit_field"] == {}

    def test_sub_register_too_large_for_parent_raises(self):
        field = Register("sub", type="unsigned", width=16)
        r = Register("reg", "r", width=8, bit_field=[field])
        with pytest.raises(ValueError, match="space not available"):
            r.generate()
        
        field1 = Register("sub", type="unsigned", width=8)
        field2 = Register("sub2", type="unsigned", width=16)
        r = Register("reg", "r", width=16, bit_field=[field1, field2])
        with pytest.raises(ValueError, match="space not available"):
            r.generate()

        field = Register("sub", type="unsigned", width=8, start_address=4)
        r = Register("reg", "r", width=8, bit_field=[field])
        with pytest.raises(ValueError, match="too small"):
            r.generate()


# ---------------------------------------------------------------------------
# generate() — bank registers
# ---------------------------------------------------------------------------

class TestRegisterBank:
    def test_bank_used_addresses_no_start(self):
        r = Register("reg", "r", width=32, bank_size=4)
        r.generate(word_width=32)
        assert list(r.used_addresses) == [0, 1, 2, 3]

    def test_bank_used_addresses_with_start(self):
        r = Register("reg", "r", width=32, bank_size=3, start_address=0x10)
        r.generate(word_width=32)
        assert list(r.used_addresses) == [0x10, 0x11, 0x12]

    def test_bank_size_in_map(self):
        r = Register("reg", "r", bank_size=5)
        r.generate()
        assert r.map["bank_size"] == 5


# ---------------------------------------------------------------------------
# generate() — bit fields
# ---------------------------------------------------------------------------

class TestRegisterBitField:
    def test_fixed_bit_placement(self):
        field = Register("sub", type="unsigned", width=4, start_address=4)
        r = Register("reg", "r", width=8, bit_field=[field])
        r.generate()
        assert r.map["bit_field"]["sub"]["starting_bit"] == 4

    def test_auto_bit_placement_fills_from_zero(self):
        field1 = Register("sub1", type="unsigned", width=4)
        field2 = Register("sub2", type="unsigned", width=4)
        r = Register("reg", "r", width=8, bit_field=[field1, field2])
        r.generate()
        assert r.map["bit_field"]["sub1"]["starting_bit"] == 0
        assert r.map["bit_field"]["sub2"]["starting_bit"] == 4

    def test_rw_inherited_from_parent(self):
        field = Register("sub", type="unsigned", width=4)
        r = Register("reg", "r", bit_field=[field])
        r.generate()
        assert r.map["bit_field"]["sub"]["rw"] == "r"

    def test_bit_overlap_raises(self):
        field1 = Register("sub1", type="unsigned", width=4, start_address=0)
        field2 = Register("sub2", type="unsigned", width=4, start_address=2)  # overlaps field1 at bits 2-3
        r = Register("reg", "r", bit_field=[field1, field2])
        with pytest.raises(ValueError, match="bits are already in use"):
            r.generate()

    def test_sub_register_bank_raises(self):
        field = Register("sub", type="unsigned", width=4, bank_size=2)
        r = Register("reg", "r", bit_field=[field])
        with pytest.raises(ValueError, match="Sub-registers cannot be banks"):
            r.generate()

    def test_sub_register_sub_register_raises(self):
        sub_field = Register("subsub", type="unsigned", width=2)
        field = Register("sub", type="unsigned", width=4, bit_field=[sub_field])
        r = Register("reg", "r", bit_field=[field])
        with pytest.raises(ValueError, match="Sub-registers cannot have their own sub-registers"):
            r.generate()

    def test_sub_register_rw_mismatch_raises(self):
        field = Register("sub", "w", type="unsigned", width=4)
        r = Register("reg", "r", bit_field=[field])
        with pytest.raises(ValueError, match="rw must match"):
            r.generate()

    def test_sub_register_rw_parent_rw_allows_any_child_rw(self):
        # Parent rw="rw" permits child with any explicit rw — no ValueError raised.
        # The map always stores the parent's rw (sub-registers inherit parent rw).
        for child_rw in ("r", "w", "rw"):
            field = Register("sub", child_rw, type="unsigned", width=4)
            r = Register("reg", "rw", width=8, bit_field=[field])
            r.generate()  # must not raise
            assert r.map["bit_field"]["sub"]["rw"] == "rw"

    def test_sub_register_rw_strict_when_parent_not_rw(self):
        # Parent rw="r": child must also be "r"
        field = Register("sub", "w", type="unsigned", width=4)
        r = Register("reg", "r", bit_field=[field])
        with pytest.raises(ValueError, match="rw must match"):
            r.generate()

    def test_sub_register_address_offset_inherited(self):
        field = Register("sub", type="unsigned", width=4)
        r = Register("reg", "r", start_address=0xA, bit_field=[field])
        r.generate()
        assert r.map["bit_field"]["sub"]["address_offset"] == 0xA


# ---------------------------------------------------------------------------
# post_assign_address_offset
# ---------------------------------------------------------------------------

class TestPostAssignAddressOffset:
    def test_updates_map_address_offset(self):
        r = Register("reg", "r")
        r.generate()
        r.post_assign_address_offset(0x20)
        assert r.map["address_offset"] == 0x20

    def test_updates_used_addresses(self):
        r = Register("reg", "r", bank_size=3)
        r.generate(word_width=32)
        r.post_assign_address_offset(0x10)
        assert list(r.used_addresses) == [0x10, 0x11, 0x12]

    def test_sub_register_address_offset_updated(self):
        field = Register("sub", type="unsigned", width=4)
        r = Register("reg", "r", bit_field=[field])
        r.generate()
        r.post_assign_address_offset(0x30)
        assert r.map["bit_field"]["sub"]["address_offset"] == 0x30

    def test_raises_if_not_generated(self):
        r = Register("reg", "r")
        with pytest.raises(ValueError, match="generated"):
            r.post_assign_address_offset(0x0)


# ---------------------------------------------------------------------------
# __getattr__ traversal
# ---------------------------------------------------------------------------

class TestRegisterGetattr:
    def test_access_sub_register_by_name(self):
        field = Register("sub1", type="unsigned", width=4)
        r = Register("reg", "r", bit_field=[field])
        r.generate()
        assert r.sub1.width == 4

    def test_access_enum_by_name(self):
        r = Register("reg", "r", width=8, enum={"ENABLE": 1})
        r.generate()
        assert r.ENABLE == 1

    def test_access_metadata_by_name(self):
        r = Register("reg", "r", min_val=0, max_val=10, default_val=4, unit="V")
        r.generate()
        assert r.min == 0
        assert r.max == 10
        assert r.default_val == 4
        assert r.unit == "V"

    def test_unknown_attr_raises(self):
        r = Register("reg", "r")
        r.generate()
        with pytest.raises(AttributeError):
            _ = r.nonexistent
