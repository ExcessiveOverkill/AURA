import pytest
from register_mapper import Register, Group


# ---------------------------------------------------------------------------
# Init validation
# ---------------------------------------------------------------------------

class TestGroupInit:
    def test_invalid_start_address_negative(self):
        with pytest.raises(ValueError, match="Invalid start_address"):
            Group("g", start_address=-2)    # allow -1 for auto-assign, but not other negative values

    def test_invalid_start_address_too_large(self):
        with pytest.raises(ValueError, match="Invalid start_address"):
            Group("g", start_address=0x10000)

    def test_invalid_alignment_not_power_of_2(self):
        with pytest.raises(ValueError, match="Invalid alignment"):
            Group("g", alignment=3)

    def test_invalid_count_zero(self):
        with pytest.raises(ValueError, match="Invalid count"):
            Group("g", count=0)

    def test_invalid_count_too_large(self):
        with pytest.raises(ValueError, match="Invalid count"):
            Group("g", count=0x10000)

    def test_valid_construction(self):
        g = Group("g", count=2, start_address=0x10, desc="test", alignment=4)
        assert g.name == "g"
        assert g.count == 2
        assert g.start_address == 0x10
        assert g.desc == "test"
        assert g.alignment == 4


# ---------------------------------------------------------------------------
# add()
# ---------------------------------------------------------------------------

class TestGroupAdd:
    def test_add_register(self):
        g = Group("g")
        g.add(Register("r1", "r"))
        assert "r1" in g.contents

    def test_add_subgroup(self):
        g = Group("g")
        sub = Group("sub")
        sub.add(Register("r1", "r"))
        g.add(sub)
        assert "sub" in g.contents

    def test_duplicate_name_raises(self):
        g = Group("g")
        g.add(Register("r1", "r"))
        with pytest.raises(ValueError, match="already exists"):
            g.add(Register("r1", "r"))

    def test_invalid_item_raises(self):
        g = Group("g")
        with pytest.raises(ValueError, match="Invalid item"):
            g.add("not_a_register")

    def test_add_after_generate_raises(self):
        g = Group("g", start_address=0, alignment=4)
        g.add(Register("r1", "r", start_address=0x0))
        g.generate()
        with pytest.raises(ValueError, match="already generated"):
            g.add(Register("r2", "r"))


# ---------------------------------------------------------------------------
# generate() — address placement
# ---------------------------------------------------------------------------

class TestGroupGenerate:
    def test_fixed_address_registers_placed_correctly(self):
        g = Group("g", start_address=0, alignment=4)
        g.add(Register("r1", "r", start_address=0x0))
        g.add(Register("r2", "r", start_address=0x1))
        g.generate()
        assert g.map["registers"]["r1"]["address_offset"] == 0x0
        assert g.map["registers"]["r2"]["address_offset"] == 0x1

    def test_auto_assign_no_overlap(self):
        g = Group("g", start_address=0)
        g.add(Register("r1", "r"))
        g.add(Register("r2", "r"))
        g.generate()
        assert g.map["registers"]["r1"]["address_offset"] != g.map["registers"]["r2"]["address_offset"]

    def test_address_collision_raises(self):
        g = Group("g", start_address=0, alignment=4)
        g.add(Register("r1", "r", start_address=0x0))
        g.add(Register("r2", "r", start_address=0x0))
        with pytest.raises(ValueError, match="addresses are already in use"):
            g.generate()

    def test_registers_appear_in_map(self):
        g = Group("g", start_address=0)
        g.add(Register("r1", "r"))
        g.generate()
        assert "r1" in g.map["registers"]

    def test_subgroup_appears_in_map(self):
        outer = Group("outer", start_address=0)
        inner = Group("inner", start_address=0x0, alignment=2)
        inner.add(Register("r1", "r", start_address=0x0))
        outer.add(inner)
        outer.generate()
        assert "inner" in outer.map["groups"]

    def test_generated_flag_set(self):
        g = Group("g", start_address=0)
        g.add(Register("r1", "r"))
        g.generate()
        assert g.generated is True


# ---------------------------------------------------------------------------
# generate() — alignment
# ---------------------------------------------------------------------------

class TestGroupAlignment:
    def test_auto_alignment_power_of_2(self):
        g = Group("g", start_address=0)
        g.add(Register("r1", "r", start_address=0x0))
        g.add(Register("r2", "r", start_address=0x1))
        g.add(Register("r3", "r", start_address=0x2))
        g.generate()
        alignment = g.map["alignment"]
        assert alignment >= 1
        assert (alignment & (alignment - 1)) == 0  # power of 2
        assert alignment >= 3  # large enough to fit 3 entries

    def test_explicit_alignment_preserved(self):
        g = Group("g", start_address=0, alignment=8)
        g.add(Register("r1", "r", start_address=0x0))
        g.generate()
        assert g.map["alignment"] == 8

    def test_explicit_alignment_too_small_raises(self):
        g = Group("g", start_address=0, alignment=2)
        g.add(Register("r1", "r", start_address=0x0))
        g.add(Register("r2", "r", start_address=0x1))
        g.add(Register("r3", "r", start_address=0x2))
        with pytest.raises(ValueError):
            g.generate()


# ---------------------------------------------------------------------------
# generate() — count / used_addresses
# ---------------------------------------------------------------------------

class TestGroupCount:
    def test_used_addresses_count_x_alignment(self):
        g = Group("g", start_address=0, alignment=4, count=3)
        g.add(Register("r1", "r", start_address=0x0))
        g.generate()
        assert list(g.used_addresses) == list(range(0, 4 * 3))

    def test_used_addresses_auto_align_count(self):
        g = Group("g", start_address=0, count=2)
        g.add(Register("r1", "r", start_address=0x0))
        g.generate()
        assert len(g.used_addresses) == g.alignment * 2


# ---------------------------------------------------------------------------
# post_assign_address_offset
# ---------------------------------------------------------------------------

class TestGroupPostAssign:
    def test_updates_address_offset_in_map(self):
        g = Group("g")
        g.add(Register("r1", "r"))
        g.generate()
        g.post_assign_address_offset(0x40)
        assert g.map["address_offset"] == 0x40

    def test_updates_used_addresses(self):
        g = Group("g", alignment=4)
        g.add(Register("r1", "r"))
        g.generate()
        g.post_assign_address_offset(0x10)
        assert 0x10 in g.used_addresses


# ---------------------------------------------------------------------------
# __getattr__ traversal
# ---------------------------------------------------------------------------

class TestGroupGetattr:
    def test_access_register_by_name(self):
        g = Group("g", start_address=0)
        g.add(Register("r1", "r"))
        g.generate()
        assert g.r1 is not None

    def test_unknown_attr_raises(self):
        g = Group("g", start_address=0)
        g.add(Register("r1", "r"))
        g.generate()
        with pytest.raises(AttributeError):
            _ = g.nonexistent
