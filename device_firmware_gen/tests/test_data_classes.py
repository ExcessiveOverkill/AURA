import pytest
from device_firmware_gen.firmware_gen import (
    FirmwareGenerator, RegElement, AddrSlot,
    DeviceRegNode, DeviceGroupNode,
)


def _make_gen_and_flatten(rm):
    gen = FirmwareGenerator(rm)
    gen._flatten()
    return gen


def _make_gen_and_tree(rm):
    gen = FirmwareGenerator(rm)
    gen._build_device_tree()
    return gen


# ---------------------------------------------------------------------------
# RegElement properties
# ---------------------------------------------------------------------------

class TestRegElement:
    def test_single_word_not_multi_word(self, simple_rm):
        gen = _make_gen_and_flatten(simple_rm)
        elem = gen._elements[0]
        assert elem.words_per_reg == 1
        assert elem.is_multi_word is False

    def test_multi_word_is_multi_word(self, multiword_rm):
        gen = _make_gen_and_flatten(multiword_rm)
        elem = gen._elements[0]
        assert elem.is_multi_word is True

    def test_single_word_no_buffers(self, simple_rm):
        gen = _make_gen_and_flatten(simple_rm)
        assert gen._elements[0].needs_buffers is False

    def test_multi_word_needs_buffers(self, multiword_rm):
        gen = _make_gen_and_flatten(multiword_rm)
        assert gen._elements[0].needs_buffers is True

    def test_min_access_words_suppresses_buffers_for_small_reg(self, min_access_rm):
        # 32-bit register on 8-bit word bus with min_access_words=4: 4 words == min, no buffers
        gen = _make_gen_and_flatten(min_access_rm)
        small = next(e for e in gen._elements if e.reg.name == "small")
        assert small.words_per_reg == 4
        assert small.needs_buffers is False

    def test_min_access_words_keeps_buffers_for_large_reg(self, min_access_rm):
        # 64-bit register on 8-bit word bus with min_access_words=4: 8 words > min, needs buffers
        gen = _make_gen_and_flatten(min_access_rm)
        large = next(e for e in gen._elements if e.reg.name == "large")
        assert large.words_per_reg == 8
        assert large.needs_buffers is True

    def test_min_access_words_propagated_from_map(self, min_access_rm):
        gen = FirmwareGenerator(min_access_rm)
        assert gen._min_access_words == 4

    def test_qualified_name_flat(self, simple_rm):
        gen = _make_gen_and_flatten(simple_rm)
        names = {e.qualified_name for e in gen._elements}
        assert "status" in names
        assert "control" in names
        assert "config" in names

    def test_qualified_name_nested(self, grouped_rm):
        gen = _make_gen_and_flatten(grouped_rm)
        names = {e.qualified_name for e in gen._elements}
        # grouped registers have the group name prepended
        assert any("periph" in n for n in names)

    def test_bank_idx_increments(self, banked_rm):
        gen = _make_gen_and_flatten(banked_rm)
        indices = sorted(e.bank_idx for e in gen._elements)
        assert indices == [0, 1, 2, 3]


# ---------------------------------------------------------------------------
# AddrSlot
# ---------------------------------------------------------------------------

class TestAddrSlot:
    def test_base_slot_word_idx_zero(self, simple_rm):
        gen = _make_gen_and_flatten(simple_rm)
        for slot in gen._slots.values():
            assert slot.word_idx == 0  # all are single-word

    def test_multiword_subsequent_slot(self, multiword_rm):
        gen = _make_gen_and_flatten(multiword_rm)
        word_indices = sorted(s.word_idx for s in gen._slots.values())
        assert 0 in word_indices
        assert 1 in word_indices

    def test_slot_element_is_reg_element(self, simple_rm):
        gen = _make_gen_and_flatten(simple_rm)
        for slot in gen._slots.values():
            assert isinstance(slot.element, RegElement)


# ---------------------------------------------------------------------------
# DeviceRegNode
# ---------------------------------------------------------------------------

class TestDeviceRegNode:
    def test_single_reg_not_bank(self, simple_rm):
        gen = _make_gen_and_tree(simple_rm)
        for node in gen._device_tree:
            assert isinstance(node, DeviceRegNode)
            assert node.is_bank is False
            assert node.bank_size == 1

    def test_bank_reg_is_bank(self, banked_rm):
        gen = _make_gen_and_tree(banked_rm)
        assert len(gen._device_tree) == 1
        node = gen._device_tree[0]
        assert isinstance(node, DeviceRegNode)
        assert node.is_bank is True
        assert node.bank_size == 4

    def test_reg_node_name(self, simple_rm):
        gen = _make_gen_and_tree(simple_rm)
        names = {n.name for n in gen._device_tree}
        assert "status" in names
        assert "control" in names
        assert "config" in names


# ---------------------------------------------------------------------------
# DeviceGroupNode
# ---------------------------------------------------------------------------

class TestDeviceGroupNode:
    def test_group_node_produced(self, grouped_rm):
        gen = _make_gen_and_tree(grouped_rm)
        assert len(gen._device_tree) == 1
        node = gen._device_tree[0]
        assert isinstance(node, DeviceGroupNode)

    def test_group_node_count(self, grouped_rm):
        gen = _make_gen_and_tree(grouped_rm)
        node = gen._device_tree[0]
        assert node.count == 2

    def test_group_node_name(self, grouped_rm):
        gen = _make_gen_and_tree(grouped_rm)
        assert gen._device_tree[0].name == "periph"

    def test_group_node_children(self, grouped_rm):
        gen = _make_gen_and_tree(grouped_rm)
        node = gen._device_tree[0]
        assert len(node.children) == 2
        child_names = {c.name for c in node.children}
        assert "enable" in child_names
        assert "value" in child_names
