import pytest
from device_firmware_gen.firmware_gen import FirmwareGenerator, DeviceRegNode, DeviceGroupNode
from register_mapper import Register, Group, RegisterMapGenerator


def _tree(rm):
    gen = FirmwareGenerator(rm)
    gen._build_device_tree()
    return gen


# ---------------------------------------------------------------------------
# Flat register maps
# ---------------------------------------------------------------------------

class TestFlatTree:
    def test_simple_rm_count(self, simple_rm):
        gen = _tree(simple_rm)
        assert len(gen._device_tree) == 3

    def test_simple_rm_all_reg_nodes(self, simple_rm):
        gen = _tree(simple_rm)
        assert all(isinstance(n, DeviceRegNode) for n in gen._device_tree)

    def test_simple_rm_names(self, simple_rm):
        gen = _tree(simple_rm)
        names = {n.name for n in gen._device_tree}
        assert names == {"status", "control", "config"}

    def test_bank_reg_is_bank_true(self, banked_rm):
        gen = _tree(banked_rm)
        assert len(gen._device_tree) == 1
        assert gen._device_tree[0].is_bank is True

    def test_bank_size_preserved(self, banked_rm):
        gen = _tree(banked_rm)
        assert gen._device_tree[0].bank_size == 4

    def test_single_reg_is_bank_false(self, simple_rm):
        gen = _tree(simple_rm)
        for node in gen._device_tree:
            assert node.is_bank is False


# ---------------------------------------------------------------------------
# Grouped maps
# ---------------------------------------------------------------------------

class TestGroupTree:
    def test_grouped_rm_single_top_node(self, grouped_rm):
        gen = _tree(grouped_rm)
        assert len(gen._device_tree) == 1

    def test_grouped_rm_produces_group_node(self, grouped_rm):
        gen = _tree(grouped_rm)
        assert isinstance(gen._device_tree[0], DeviceGroupNode)

    def test_group_node_count(self, grouped_rm):
        gen = _tree(grouped_rm)
        assert gen._device_tree[0].count == 2

    def test_group_node_name(self, grouped_rm):
        gen = _tree(grouped_rm)
        assert gen._device_tree[0].name == "periph"

    def test_group_children_count(self, grouped_rm):
        gen = _tree(grouped_rm)
        node = gen._device_tree[0]
        assert len(node.children) == 2

    def test_group_children_are_reg_nodes(self, grouped_rm):
        gen = _tree(grouped_rm)
        node = gen._device_tree[0]
        assert all(isinstance(c, DeviceRegNode) for c in node.children)

    def test_group_children_names(self, grouped_rm):
        gen = _tree(grouped_rm)
        node = gen._device_tree[0]
        child_names = {c.name for c in node.children}
        assert child_names == {"enable", "value"}


# ---------------------------------------------------------------------------
# Nested groups
# ---------------------------------------------------------------------------

class TestNestedGroups:
    @pytest.fixture
    def nested_rm(self):
        rm = RegisterMapGenerator("nested_mod", [], word_width=32)
        outer = Group("outer", count=1)
        inner = Group("inner", count=1)
        inner.add(Register("r", rw="r", type="unsigned", width=8))
        outer.add(inner)
        rm.add(outer)
        rm.generate()
        return rm

    def test_nested_group_produces_group_node(self, nested_rm):
        gen = _tree(nested_rm)
        assert len(gen._device_tree) == 1
        assert isinstance(gen._device_tree[0], DeviceGroupNode)

    def test_nested_group_child_is_group_node(self, nested_rm):
        gen = _tree(nested_rm)
        outer = gen._device_tree[0]
        assert len(outer.children) == 1
        assert isinstance(outer.children[0], DeviceGroupNode)

    def test_nested_group_leaf_is_reg_node(self, nested_rm):
        gen = _tree(nested_rm)
        outer = gen._device_tree[0]
        inner = outer.children[0]
        assert len(inner.children) == 1
        assert isinstance(inner.children[0], DeviceRegNode)
