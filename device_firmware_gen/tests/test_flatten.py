import pytest
from device_firmware_gen import FirmwareGenerator


def _flatten(rm):
    gen = FirmwareGenerator(rm)
    gen._flatten()
    return gen


# ---------------------------------------------------------------------------
# Element count
# ---------------------------------------------------------------------------

class TestElementCount:
    def test_simple_rm_three_elements(self, simple_rm):
        gen = _flatten(simple_rm)
        assert len(gen._elements) == 3

    def test_banked_rm_four_elements(self, banked_rm):
        gen = _flatten(banked_rm)
        # bank_size=4 → 4 elements
        assert len(gen._elements) == 4

    def test_grouped_rm_expands_count(self, grouped_rm):
        gen = _flatten(grouped_rm)
        # group count=2, 2 registers each → 4 elements
        assert len(gen._elements) == 4

    def test_multiword_one_element(self, multiword_rm):
        gen = _flatten(multiword_rm)
        assert len(gen._elements) == 1


# ---------------------------------------------------------------------------
# Slot count
# ---------------------------------------------------------------------------

class TestSlotCount:
    def test_simple_rm_slots_equals_total_words(self, simple_rm):
        gen = _flatten(simple_rm)
        expected = sum(e.valid_words for e in gen._elements)
        assert len(gen._slots) == expected

    def test_multiword_slots_equals_valid_words(self, multiword_rm):
        gen = _flatten(multiword_rm)
        # 64-bit / 32-bit word = 2 valid words
        assert len(gen._slots) == 2

    def test_banked_rm_slot_count(self, banked_rm):
        gen = _flatten(banked_rm)
        # bank_size=4, each single-word → 4 slots
        assert len(gen._slots) == 4


# ---------------------------------------------------------------------------
# Address ordering
# ---------------------------------------------------------------------------

class TestAddressOrder:
    def test_elements_sorted_by_address(self, simple_rm):
        gen = _flatten(simple_rm)
        addresses = [e.base_address for e in gen._elements]
        assert addresses == sorted(addresses)

    def test_slot_addresses_are_contiguous_for_multiword(self, multiword_rm):
        gen = _flatten(multiword_rm)
        addresses = sorted(gen._slots.keys())
        assert addresses == list(range(addresses[0], addresses[0] + len(addresses)))


# ---------------------------------------------------------------------------
# words_per_reg
# ---------------------------------------------------------------------------

class TestWordsPerReg:
    def test_single_word_reg(self, simple_rm):
        gen = _flatten(simple_rm)
        for elem in gen._elements:
            assert elem.words_per_reg == 1

    def test_multiword_64bit_at_32bit(self, multiword_rm):
        gen = _flatten(multiword_rm)
        assert gen._elements[0].words_per_reg == 2

    def test_max_words_per_reg_updated(self, multiword_rm):
        gen = _flatten(multiword_rm)
        assert gen._max_words_per_reg == 2


# ---------------------------------------------------------------------------
# max_address
# ---------------------------------------------------------------------------

class TestMaxAddress:
    def test_max_address_set(self, simple_rm):
        gen = _flatten(simple_rm)
        assert gen._max_address >= 0

    def test_max_address_equals_highest_slot(self, simple_rm):
        gen = _flatten(simple_rm)
        if gen._slots:
            assert gen._max_address == max(gen._slots.keys())

    def test_max_address_multiword(self, multiword_rm):
        gen = _flatten(multiword_rm)
        # Two words at address 0 and 1 → max_address = 1
        assert gen._max_address == 1


# ---------------------------------------------------------------------------
# Device tree
# ---------------------------------------------------------------------------

class TestDeviceTree:
    def test_flat_rm_produces_reg_nodes(self, simple_rm):
        from device_firmware_gen.firmware_gen import DeviceRegNode
        gen = FirmwareGenerator(simple_rm)
        gen._build_device_tree()
        assert all(isinstance(n, DeviceRegNode) for n in gen._device_tree)

    def test_grouped_rm_produces_group_node(self, grouped_rm):
        from device_firmware_gen.firmware_gen import DeviceGroupNode
        gen = FirmwareGenerator(grouped_rm)
        gen._build_device_tree()
        assert any(isinstance(n, DeviceGroupNode) for n in gen._device_tree)

    def test_group_node_count(self, grouped_rm):
        from device_firmware_gen.firmware_gen import DeviceGroupNode
        gen = FirmwareGenerator(grouped_rm)
        gen._build_device_tree()
        group_nodes = [n for n in gen._device_tree if isinstance(n, DeviceGroupNode)]
        assert group_nodes[0].count == 2

    def test_bank_reg_is_bank(self, banked_rm):
        from device_firmware_gen.firmware_gen import DeviceRegNode
        gen = FirmwareGenerator(banked_rm)
        gen._build_device_tree()
        node = gen._device_tree[0]
        assert isinstance(node, DeviceRegNode)
        assert node.is_bank is True

    def test_group_children_populated(self, grouped_rm):
        from device_firmware_gen.firmware_gen import DeviceGroupNode
        gen = FirmwareGenerator(grouped_rm)
        gen._build_device_tree()
        group = next(n for n in gen._device_tree if isinstance(n, DeviceGroupNode))
        assert len(group.children) > 0
