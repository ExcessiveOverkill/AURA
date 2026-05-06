import pytest
from register_mapper import Register, Group, RegisterMapGenerator


# ---------------------------------------------------------------------------
# words_per_register is always a power of 2
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("width,word_width,expected_wpr", [
    (32,  32, 1),   # exactly 1 word
    (16,  32, 1),   # less than 1 word -> 1
    (1,   32, 1),   # 1 bit -> 1 word
    (33,  32, 2),   # just over 1 word -> 2
    (64,  32, 2),   # exactly 2 words
    (65,  32, 4),   # just over 2 words -> round up to 4
    (96,  32, 4),   # 3 raw words -> round up to 4
    (128, 32, 4),   # exactly 4 words
    (129, 32, 8),   # just over 4 words -> 8
    (32,   8, 4),   # 32-bit reg, 8-bit words -> 4 words
    (16,   8, 2),   # 16-bit reg, 8-bit words -> 2 words
    (1,    8, 1),   # 1-bit reg, 8-bit words -> 1 word
    (9,    8, 2),   # just over 1 byte -> 2 words
    (17,   8, 4),   # just over 2 bytes -> round up to 4
    (64,  16, 4),   # 64-bit reg, 16-bit words -> 4 words
])
def test_words_per_register_power_of_2(width, word_width, expected_wpr):
    r = Register("reg", "r", width=width)
    r.generate(word_width=word_width)
    assert r.map["words_per_register"] == expected_wpr
    wpr = r.map["words_per_register"]
    assert wpr >= 1
    assert (wpr & (wpr - 1)) == 0, f"words_per_register={wpr} is not a power of 2"


# ---------------------------------------------------------------------------
# used_addresses length = words_per_register * bank_size
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("width,word_width,bank_size,expected_addr_count", [
    (32,  32, 1, 1),
    (64,  32, 1, 2),
    (96,  32, 1, 4),   # 3 raw words -> padded to 4
    (32,  32, 4, 4),
    (64,  32, 4, 8),
    (32,   8, 1, 4),
    (32,   8, 3, 12),
])
def test_used_addresses_length(width, word_width, bank_size, expected_addr_count):
    r = Register("reg", "r", width=width, bank_size=bank_size)
    r.generate(word_width=word_width)
    assert len(r.used_addresses) == expected_addr_count


# ---------------------------------------------------------------------------
# Padding warning emitted only for top-level registers
# ---------------------------------------------------------------------------

def test_padding_warning_emitted_for_top_level(capsys):
    # 96-bit register at word_width=32: 3 raw words, padded to 4
    r = Register("reg", "r", width=96)
    r.generate(word_width=32)
    output = capsys.readouterr().out
    assert "padded" in output

def test_no_padding_warning_for_exact_power_of_2_width(capsys):
    # 64-bit register at word_width=32: exactly 2 words, no padding needed
    r = Register("reg", "r", width=64)
    r.generate(word_width=32)
    output = capsys.readouterr().out
    assert "padded" not in output

def test_no_padding_warning_for_sub_registers(capsys):
    # Sub-register with a width that would trigger padding if top-level,
    # but should be silent because it is a bit-field member
    field = Register("sub", type="unsigned", width=20)
    r = Register("reg", "r", width=64, bit_field=[field])
    r.generate(word_width=32)
    output = capsys.readouterr().out
    # The sub-register should not emit a padding warning
    assert "sub" not in output or "padded" not in output


# ---------------------------------------------------------------------------
# Bit fields spanning a word boundary
# ---------------------------------------------------------------------------

def test_bit_fields_span_word_boundary():
    """Two 20-bit sub-registers in a 64-bit register: second crosses the 32-bit boundary."""
    field1 = Register("lo", type="unsigned", width=20)  # bits 0-19
    field2 = Register("hi", type="unsigned", width=20)  # bits 20-39 (crosses 32-bit mark)
    r = Register("reg", "r", width=64, bit_field=[field1, field2])
    r.generate(word_width=32)
    assert r.map["bit_field"]["lo"]["starting_bit"] == 0
    assert r.map["bit_field"]["hi"]["starting_bit"] == 20

def test_bit_fields_auto_assign_fills_full_multiword_space():
    """Auto-assign should search the full padded bit space, not just one word."""
    # Fill the first word (bits 0-31) with two 16-bit fields, then one more
    field1 = Register("a", type="unsigned", width=16)
    field2 = Register("b", type="unsigned", width=16)
    field3 = Register("c", type="unsigned", width=16)  # must land in second word
    r = Register("reg", "r", width=64, bit_field=[field1, field2, field3])
    r.generate(word_width=32)
    assert r.map["bit_field"]["a"]["starting_bit"] == 0
    assert r.map["bit_field"]["b"]["starting_bit"] == 16
    assert r.map["bit_field"]["c"]["starting_bit"] == 32  # second word


# ---------------------------------------------------------------------------
# Multi-word bank auto-assign stride in a Group
# ---------------------------------------------------------------------------

def test_bank_64bit_auto_assign_stride():
    """A bank of 4 × 64-bit registers at word_width=32 should occupy 8 consecutive addresses."""
    rm = RegisterMapGenerator("mod", [], word_width=32)
    rm.add(Register("bank", "r", width=64, bank_size=4))
    rm.generate()
    reg_map = rm.map["base_group"]["registers"]["bank"]
    # words_per_register=2, bank_size=4 -> 8 addresses
    assert reg_map["words_per_register"] == 2
    assert reg_map["bank_size"] == 4

def test_multiword_register_auto_assigns_on_aligned_boundary():
    """A 64-bit register (2 words) must land at an even address when auto-assigned."""
    rm = RegisterMapGenerator("mod", [], word_width=32)
    rm.add(Register("r1", "r", width=32, start_address=0x0))  # occupies address 0
    rm.add(Register("wide", "r", width=64))                    # auto-assigned; must be even
    rm.generate()
    offset = rm.map["base_group"]["registers"]["wide"]["address_offset"]
    assert offset % 2 == 0  # aligned to words_per_register=2


# ---------------------------------------------------------------------------
# word_width propagates into the register map
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("word_width", [8, 16, 32, 64])
def test_word_width_stored_in_register_map(word_width):
    rm = RegisterMapGenerator("mod", [], word_width=word_width)
    rm.add(Register("r1", "r", width=word_width, start_address=0x0))
    rm.generate()
    assert rm.map["word_width"] == word_width
    assert rm.map["base_group"]["registers"]["r1"]["word_width"] == word_width


# ---------------------------------------------------------------------------
# word_width=8 regression: 32-bit register uses 4 addresses
# ---------------------------------------------------------------------------

def test_word_width_8_32bit_register_uses_4_addresses():
    r = Register("reg", "r", width=32)
    r.generate(word_width=8)
    assert r.map["words_per_register"] == 4
    assert len(r.used_addresses) == 4
