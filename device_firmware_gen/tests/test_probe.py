"""
Exhaustive behavioral tests for the generated register comm interface.

Each test fixture compiles the host shim once (module scope) and launches a
fresh subprocess per test function.  The Python side drives every register in
the map via the binary protocol and independently verifies permissions, values,
bank/group isolation, multi-word coherence, and the C++ accessor verify pass.
"""

import os
import shutil
import subprocess
import sys
from collections import defaultdict

import pytest

from register_mapper import RegisterMapGenerator, Register, Group
from device_firmware_gen import FirmwareGenerator
from device_firmware_gen.reg_probe import RegProbe, RegStatus


# ---------------------------------------------------------------------------
# Compile helper
# ---------------------------------------------------------------------------

def _compile_host(compiler: str, rm, tmp_dir: str):
    """Generate + compile the host shim.  Returns (binary_path, gen)."""
    gen     = FirmwareGenerator(rm, interfaces="shell")
    out_dir = os.path.join(tmp_dir, "out")
    os.makedirs(out_dir, exist_ok=True)
    gen.generate(out_dir)

    binary = os.path.join(tmp_dir, "reg_test")
    if os.name == "nt":
        binary += ".exe"

    srcs = [
        os.path.join(out_dir, "reg_storage.cpp"),
        os.path.join(out_dir, "reg_comm.cpp"),
        os.path.join(out_dir, "reg_verify.cpp"),
        os.path.join(out_dir, "reg_meta.cpp"),
        os.path.join(out_dir, "reg_host.cpp"),
    ]
    result = subprocess.run(
        [compiler, "-std=c++17", "-DAURA_HOST_TEST", "-I", out_dir] + srcs + ["-o", binary],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Host-shim compilation failed:\n{result.stderr}"
    return binary, gen


def _compiler():
    cc = shutil.which("g++") or shutil.which("clang++")
    if cc is None:
        pytest.skip("No C++ compiler found")
    return cc


# ---------------------------------------------------------------------------
# Module-scoped binaries (compile once, reuse across tests)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def _simple_bin(tmp_path_factory):
    rm = RegisterMapGenerator("test_mod", [], word_width=32)
    rm.add(Register("status",  rw="r",  type="unsigned", width=8))
    rm.add(Register("control", rw="w",  type="unsigned", width=8))
    rm.add(Register("config",  rw="rw", type="unsigned", width=16))
    rm.generate()
    return _compile_host(_compiler(), rm, str(tmp_path_factory.mktemp("simple")))


@pytest.fixture(scope="module")
def _banked_bin(tmp_path_factory):
    rm = RegisterMapGenerator("bank_mod", [], word_width=32)
    rm.add(Register("channel", rw="rw", type="unsigned", width=8, bank_size=4))
    rm.generate()
    return _compile_host(_compiler(), rm, str(tmp_path_factory.mktemp("banked")))


@pytest.fixture(scope="module")
def _grouped_bin(tmp_path_factory):
    rm = RegisterMapGenerator("group_mod", [], word_width=32)
    g  = Group("periph", count=2)
    g.add(Register("enable", rw="r",  type="bool"))
    g.add(Register("value",  rw="rw", type="unsigned", width=16))
    rm.add(g)
    rm.generate()
    return _compile_host(_compiler(), rm, str(tmp_path_factory.mktemp("grouped")))


@pytest.fixture(scope="module")
def _multiword_bin(tmp_path_factory):
    rm = RegisterMapGenerator("mw_mod", [], word_width=32)
    rm.add(Register("big_val", rw="rw", type="unsigned", width=64))
    rm.generate()
    return _compile_host(_compiler(), rm, str(tmp_path_factory.mktemp("multiword")))


@pytest.fixture(scope="module")
def _bitfield_bin(tmp_path_factory):
    rm = RegisterMapGenerator("bf_mod", [], word_width=32)
    en  = Register("enabled", rw="rw", type="bool")
    lvl = Register("level",   rw="rw", type="unsigned", width=4)
    rm.add(Register("ctrl", rw="rw", type="unsigned", width=8, bit_field=[en, lvl]))
    rm.generate()
    return _compile_host(_compiler(), rm, str(tmp_path_factory.mktemp("bitfield")))


@pytest.fixture(scope="module")
def _enum_bin(tmp_path_factory):
    rm = RegisterMapGenerator("enum_mod", [], word_width=32)
    rm.add(Register("mode", rw="rw", type="unsigned", width=8,
                    enum={"IDLE": 0, "RUN": 1, "SLEEP": 2}))
    rm.generate()
    return _compile_host(_compiler(), rm, str(tmp_path_factory.mktemp("enum")))


@pytest.fixture(scope="module")
def _min_access_bin(tmp_path_factory):
    """8-bit word bus, 32-bit minimum atomic access.
    'small' is 32-bit (4 words == min_access_words) → no buffers.
    'large' is 64-bit (8 words > min_access_words) → buffers."""
    rm = RegisterMapGenerator("maw_mod", [], word_width=8, min_access_words=4)
    rm.add(Register("small", rw="rw", type="unsigned", width=32, start_address=0x00))
    rm.add(Register("large", rw="rw", type="unsigned", width=64, start_address=0x04))
    rm.generate()
    return _compile_host(_compiler(), rm, str(tmp_path_factory.mktemp("min_access")))


# ---------------------------------------------------------------------------
# Function-scoped probes (fresh process per test)
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_probe(_simple_bin):
    binary, gen = _simple_bin
    with RegProbe(binary, gen._word_width // 8) as p:
        yield p, gen


@pytest.fixture
def banked_probe(_banked_bin):
    binary, gen = _banked_bin
    with RegProbe(binary, gen._word_width // 8) as p:
        yield p, gen


@pytest.fixture
def grouped_probe(_grouped_bin):
    binary, gen = _grouped_bin
    with RegProbe(binary, gen._word_width // 8) as p:
        yield p, gen


@pytest.fixture
def multiword_probe(_multiword_bin):
    binary, gen = _multiword_bin
    with RegProbe(binary, gen._word_width // 8) as p:
        yield p, gen


@pytest.fixture
def bitfield_probe(_bitfield_bin):
    binary, gen = _bitfield_bin
    with RegProbe(binary, gen._word_width // 8) as p:
        yield p, gen


@pytest.fixture
def enum_probe(_enum_bin):
    binary, gen = _enum_bin
    with RegProbe(binary, gen._word_width // 8) as p:
        yield p, gen


@pytest.fixture
def min_access_probe(_min_access_bin):
    binary, gen = _min_access_bin
    with RegProbe(binary, 1) as p:   # word_width=8 → 1 byte per word
        yield p, gen


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_read_only(gen):
    return [e for e in gen._elements if e.reg.rw == "r"]


def _all_write_only(gen):
    return [e for e in gen._elements if e.reg.rw == "w"]


def _all_rw(gen):
    return [e for e in gen._elements if e.reg.rw == "rw"]


def _word_mask(elem):
    """Max value that can be stored in a single word of this element."""
    bits = elem.last_word_used_bits or elem.words_per_reg * 32
    return (1 << min(bits, 32)) - 1


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

class TestPermissions:
    def test_write_to_read_only_rejected(self, simple_probe):
        probe, gen = simple_probe
        for elem in _all_read_only(gen):
            status = probe.write(elem.base_address, [0])
            assert status == RegStatus.BAD_ACCESS_READ_ONLY, \
                f"Expected BAD_ACCESS_READ_ONLY for r-only '{elem.qualified_name}', got {status.name}"

    def test_read_from_write_only_rejected(self, simple_probe):
        probe, gen = simple_probe
        for elem in _all_write_only(gen):
            status, _ = probe.read(elem.base_address)
            assert status == RegStatus.BAD_ACCESS_WRITE_ONLY, \
                f"Expected BAD_ACCESS_WRITE_ONLY for w-only '{elem.qualified_name}', got {status.name}"

    def test_read_from_read_only_ok(self, simple_probe):
        probe, gen = simple_probe
        probe.reset()
        for elem in _all_read_only(gen):
            status, _ = probe.read(elem.base_address)
            assert status == RegStatus.OK, \
                f"r-only read of '{elem.qualified_name}' returned {status.name}"

    def test_write_to_write_only_ok(self, simple_probe):
        probe, gen = simple_probe
        for elem in _all_write_only(gen):
            status = probe.write(elem.base_address, [0])
            assert status == RegStatus.OK, \
                f"w-only write to '{elem.qualified_name}' returned {status.name}"

    def test_read_write_both_ok(self, simple_probe):
        probe, gen = simple_probe
        probe.reset()
        for elem in _all_rw(gen):
            s_w = probe.write(elem.base_address, [1])
            s_r, _ = probe.read(elem.base_address)
            assert s_w == RegStatus.OK, f"rw write '{elem.qualified_name}' got {s_w.name}"
            assert s_r == RegStatus.OK, f"rw read  '{elem.qualified_name}' got {s_r.name}"

    def test_permissions_exhaustive_banked(self, banked_probe):
        probe, gen = banked_probe
        probe.reset()
        for elem in gen._elements:
            rw = elem.reg.rw
            if rw in ("r", "rw"):
                s, _ = probe.read(elem.base_address)
                assert s == RegStatus.OK
            if rw in ("w", "rw"):
                s = probe.write(elem.base_address, [0])
                assert s == RegStatus.OK
            if rw == "r":
                s = probe.write(elem.base_address, [0])
                assert s == RegStatus.BAD_ACCESS_READ_ONLY
            if rw == "w":
                s, _ = probe.read(elem.base_address)
                assert s == RegStatus.BAD_ACCESS_WRITE_ONLY


# ---------------------------------------------------------------------------
# Write-read roundtrip
# ---------------------------------------------------------------------------

class TestRoundtrip:
    def test_rw_registers_roundtrip(self, simple_probe):
        probe, gen = simple_probe
        probe.reset()
        for elem in _all_rw(gen):
            for wpr_i in range(elem.valid_words):
                addr = elem.base_address + wpr_i
                probe.write(addr, [1])
            status, words = probe.read(elem.base_address, elem.valid_words)
            assert status == RegStatus.OK
            for v in words:
                assert v != 0, f"'{elem.qualified_name}' read back 0 after writing 1"

    def test_rw_value_persists_across_reads(self, simple_probe):
        probe, gen = simple_probe
        probe.reset()
        for elem in _all_rw(gen):
            probe.write(elem.base_address, [0xAB])
            _, w1 = probe.read(elem.base_address)
            _, w2 = probe.read(elem.base_address)
            assert w1 == w2, f"'{elem.qualified_name}' gave different values on repeated reads"

    def test_write_zero_readable(self, simple_probe):
        probe, gen = simple_probe
        probe.reset()
        for elem in _all_rw(gen):
            probe.write(elem.base_address, [0xFF])
            probe.write(elem.base_address, [0x00])
            _, words = probe.read(elem.base_address)
            assert words[0] == 0, f"'{elem.qualified_name}' should read 0 after writing 0"

    def test_banked_rw_roundtrip(self, banked_probe):
        probe, gen = banked_probe
        probe.reset()
        for elem in gen._elements:
            if elem.reg.rw == "rw":
                probe.write(elem.base_address, [elem.bank_idx + 1])
        for elem in gen._elements:
            if elem.reg.rw == "rw":
                _, words = probe.read(elem.base_address)
                assert words[0] == elem.bank_idx + 1, \
                    f"Bank slot {elem.bank_idx} of '{elem.reg.name}' roundtrip failed"


# ---------------------------------------------------------------------------
# Reset behaviour
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_zeroes_rw_registers(self, simple_probe):
        probe, gen = simple_probe
        for elem in _all_rw(gen):
            probe.write(elem.base_address, [0xFF])
        probe.reset()
        for elem in _all_rw(gen):
            _, words = probe.read(elem.base_address)
            assert words[0] == 0, f"'{elem.qualified_name}' not zero after reset"

    def test_reset_zeroes_banked(self, banked_probe):
        probe, gen = banked_probe
        for elem in gen._elements:
            if elem.reg.rw in ("w", "rw"):
                probe.write(elem.base_address, [0xFF])
        probe.reset()
        for elem in gen._elements:
            if elem.reg.rw in ("r", "rw"):
                _, words = probe.read(elem.base_address)
                assert words[0] == 0

    def test_reset_after_reset_is_idempotent(self, simple_probe):
        probe, gen = simple_probe
        probe.reset()
        probe.reset()
        for elem in _all_rw(gen):
            _, words = probe.read(elem.base_address)
            assert words[0] == 0


# ---------------------------------------------------------------------------
# Bank isolation
# ---------------------------------------------------------------------------

class TestBankIsolation:
    def test_bank_slots_independent(self, banked_probe):
        """Writing to one bank slot must not affect any other slot."""
        probe, gen = banked_probe
        # Group elements by their Register object identity — all slots of the
        # same bank share the same reg object.
        banks = defaultdict(list)
        for elem in gen._elements:
            if elem.reg.bank_size > 1:
                banks[id(elem.reg)].append(elem)

        for elems in banks.values():
            elems.sort(key=lambda e: e.bank_idx)
            probe.reset()
            # Write distinct values to every slot
            for elem in elems:
                if elem.reg.rw in ("w", "rw"):
                    probe.write(elem.base_address, [elem.bank_idx + 1])
            # Verify every readable slot independently
            for elem in elems:
                if elem.reg.rw in ("r", "rw"):
                    _, words = probe.read(elem.base_address)
                    assert words[0] == elem.bank_idx + 1, (
                        f"Bank slot {elem.bank_idx} of '{elem.reg.name}' contaminated: "
                        f"expected {elem.bank_idx + 1}, got {words[0]}"
                    )

    def test_bank_slot_write_does_not_spill(self, banked_probe):
        """Writing max value to slot 0 must not affect slot 1."""
        probe, gen = banked_probe
        banks = defaultdict(list)
        for elem in gen._elements:
            if elem.reg.bank_size > 1:
                banks[id(elem.reg)].append(elem)

        for elems in banks.values():
            elems.sort(key=lambda e: e.bank_idx)
            if len(elems) < 2:
                continue
            probe.reset()
            probe.write(elems[0].base_address, [0xFF])
            _, w1 = probe.read(elems[1].base_address)
            assert w1[0] == 0, "Write to slot 0 spilled into slot 1"


# ---------------------------------------------------------------------------
# Group instance isolation
# ---------------------------------------------------------------------------

class TestGroupIsolation:
    def test_group_instances_have_distinct_addresses(self, grouped_probe):
        probe, gen = grouped_probe
        # Elements from count>1 groups share the same reg object but have
        # different ancestor instance indices → different base_addresses.
        by_reg = defaultdict(list)
        for elem in gen._elements:
            if any(cnt > 1 for _, cnt, _ in elem.ancestor_instances):
                by_reg[id(elem.reg)].append(elem)

        for elems in by_reg.values():
            addrs = [e.base_address for e in elems]
            assert len(set(addrs)) == len(addrs), \
                f"Group instances of '{elems[0].reg.name}' share addresses: {addrs}"

    def test_group_instances_are_independent(self, grouped_probe):
        """Writing to one group instance must not affect the other."""
        probe, gen = grouped_probe
        by_reg = defaultdict(list)
        for elem in gen._elements:
            if any(cnt > 1 for _, cnt, _ in elem.ancestor_instances):
                by_reg[id(elem.reg)].append(elem)

        for elems in by_reg.values():
            if elems[0].reg.rw not in ("rw",):
                continue
            probe.reset()
            for i, elem in enumerate(elems):
                probe.write(elem.base_address, [i + 1])
            for i, elem in enumerate(elems):
                _, words = probe.read(elem.base_address)
                assert words[0] == i + 1, (
                    f"Group instance {i} of '{elem.reg.name}' contaminated: "
                    f"expected {i + 1}, got {words[0]}"
                )


# ---------------------------------------------------------------------------
# Multi-word coherence
# ---------------------------------------------------------------------------

class TestMultiWord:
    def test_full_register_write_read(self, multiword_probe):
        """Full-register read/write (word_idx=0, count=valid_words) fast path."""
        probe, gen = multiword_probe
        probe.reset()
        for elem in gen._elements:
            if elem.valid_words < 2 or elem.reg.rw not in ("rw",):
                continue
            test_words = [0xAA + i for i in range(elem.valid_words)]
            s = probe.write(elem.base_address, test_words)
            assert s == RegStatus.OK
            s, got = probe.read(elem.base_address, elem.valid_words)
            assert s == RegStatus.OK
            assert got == test_words, f"Multi-word full roundtrip failed: {got} != {test_words}"

    def test_partial_write_not_committed_until_last_word(self, multiword_probe):
        """Partial write to word 0 alone must not commit to storage."""
        probe, gen = multiword_probe
        for elem in gen._elements:
            if elem.valid_words < 2 or elem.reg.rw not in ("rw",):
                continue
            probe.reset()
            # Write only word 0
            probe.write(elem.base_address, [0xAA])
            # Read full register — should still see zeros (write not committed)
            s, words = probe.read(elem.base_address, elem.valid_words)
            assert s == RegStatus.OK
            assert words[0] == 0, \
                "Partial write word-0 committed prematurely: storage should still be 0"

    def test_partial_write_commits_on_last_word(self, multiword_probe):
        """Partial write commits atomically when the last valid word is written."""
        probe, gen = multiword_probe
        for elem in gen._elements:
            if elem.valid_words < 2 or elem.reg.rw not in ("rw",):
                continue
            probe.reset()
            probe.write(elem.base_address, [0xAA])           # word 0 — staged
            probe.write(elem.base_address + elem.valid_words - 1, [0xBB])  # last — commit
            s, words = probe.read(elem.base_address, elem.valid_words)
            assert s == RegStatus.OK
            assert words[0] == 0xAA, f"Word 0 not committed: {words}"
            assert words[-1] == 0xBB, f"Last word not committed: {words}"

    def test_partial_read_uses_snapshot(self, multiword_probe):
        """Partial reads after a full write serve consistent data from the snapshot."""
        probe, gen = multiword_probe
        for elem in gen._elements:
            if elem.valid_words < 2 or elem.reg.rw not in ("rw",):
                continue
            probe.reset()
            test_words = [0x10 + i for i in range(elem.valid_words)]
            probe.write(elem.base_address, test_words)
            # Read word 0 (takes snapshot)
            _, w0 = probe.read(elem.base_address, 1)
            # Read remaining words (served from snapshot)
            for i in range(1, elem.valid_words):
                _, wi = probe.read(elem.base_address + i, 1)
                assert wi[0] == test_words[i], \
                    f"Word {i} from snapshot mismatch: {wi[0]} != {test_words[i]}"

    def test_overflow_rejected(self, multiword_probe):
        probe, gen = multiword_probe
        for elem in gen._elements:
            if elem.valid_words < 2:
                continue
            # Ask for one more word than exists
            s, _ = probe.read(elem.base_address, elem.valid_words + 1)
            assert s == RegStatus.REGISTER_OVERFLOW


# ---------------------------------------------------------------------------
# Address space
# ---------------------------------------------------------------------------

class TestAddressSpace:
    def test_valid_addresses_return_ok_or_permission_error(self, simple_probe):
        probe, gen = simple_probe
        probe.reset()
        valid = {e.base_address + wi
                 for e in gen._elements
                 for wi in range(e.valid_words)}
        for addr in valid:
            s, _ = probe.read(addr)
            assert s in (RegStatus.OK, RegStatus.BAD_ACCESS_WRITE_ONLY), \
                f"Valid addr 0x{addr:04X} returned unexpected {s.name}"

    def test_gap_addresses_return_bad_address(self, simple_probe):
        probe, gen = simple_probe
        valid = {e.base_address + wi
                 for e in gen._elements
                 for wi in range(e.valid_words)}
        max_addr = max(valid) if valid else 0
        for addr in range(max_addr + 1):
            if addr in valid:
                continue
            s, _ = probe.read(addr)
            assert s == RegStatus.BAD_ADDRESS, \
                f"Gap addr 0x{addr:04X} returned {s.name} instead of BAD_ADDRESS"

    def test_out_of_range_returns_error(self, simple_probe):
        probe, gen = simple_probe
        max_addr = max(e.base_address for e in gen._elements)
        s, _ = probe.read(max_addr + 100)
        assert s == RegStatus.BAD_ADDRESS_OUT_OF_RANGE

    def test_address_0xFFFF_out_of_range(self, simple_probe):
        probe, gen = simple_probe
        s, _ = probe.read(0xFFFF)
        assert s == RegStatus.BAD_ADDRESS_OUT_OF_RANGE


# ---------------------------------------------------------------------------
# Bits-above-width guard
# ---------------------------------------------------------------------------

class TestBitsAboveWidth:
    def test_write_bits_above_width_rejected(self, simple_probe):
        """Writing a value with bits above the register width is rejected."""
        probe, gen = simple_probe
        for elem in gen._elements:
            if elem.reg.rw not in ("w", "rw"):
                continue
            if elem.last_word_used_bits == 0:
                continue  # last word fully used — nothing to exceed
            overflow_val = 1 << elem.last_word_used_bits
            addr = elem.base_address + (elem.valid_words - 1)
            s = probe.write(addr, [overflow_val])
            assert s == RegStatus.BITS_ABOVE_WIDTH, (
                f"Expected BITS_ABOVE_WIDTH for '{elem.qualified_name}' "
                f"val=0x{overflow_val:X}, got {s.name}"
            )


# ---------------------------------------------------------------------------
# Accessor verify (C++ side)
# ---------------------------------------------------------------------------

class TestAccessorVerify:
    def test_simple_rm_accessor_verify(self, simple_probe):
        probe, _ = simple_probe
        probe.reset()
        assert probe.verify(), "C++ accessor verify failed for simple_rm"

    def test_banked_rm_accessor_verify(self, banked_probe):
        probe, _ = banked_probe
        probe.reset()
        assert probe.verify(), "C++ accessor verify failed for banked_rm"

    def test_grouped_rm_accessor_verify(self, grouped_probe):
        probe, _ = grouped_probe
        probe.reset()
        assert probe.verify(), "C++ accessor verify failed for grouped_rm"

    def test_multiword_rm_accessor_verify(self, multiword_probe):
        probe, _ = multiword_probe
        probe.reset()
        assert probe.verify(), "C++ accessor verify failed for multiword_rm"

    def test_bitfield_rm_accessor_verify(self, bitfield_probe):
        probe, _ = bitfield_probe
        probe.reset()
        assert probe.verify(), "C++ accessor verify failed for bitfield_rm"

    def test_enum_rm_accessor_verify(self, enum_probe):
        probe, _ = enum_probe
        probe.reset()
        assert probe.verify(), "C++ accessor verify failed for enum_rm"


# ---------------------------------------------------------------------------
# Atomic status codes — partial multi-word reads
# ---------------------------------------------------------------------------

class TestAtomicStatus:
    def test_first_word_partial_read_returns_ok_atomic_updated(self, multiword_probe):
        """Partial read of word 0 alone returns OK_ATOMIC_UPDATED (snapshot taken)."""
        probe, gen = multiword_probe
        for elem in gen._elements:
            if elem.valid_words < 2 or elem.reg.rw not in ("r", "rw"):
                continue
            probe.reset()
            status, _ = probe.read(elem.base_address, 1)
            assert status == RegStatus.OK_ATOMIC_UPDATED, (
                f"Expected OK_ATOMIC_UPDATED for partial word-0 read of "
                f"'{elem.qualified_name}', got {status.name}"
            )

    def test_subsequent_word_partial_read_returns_ok_atomic_buffered(self, multiword_probe):
        """After the snapshot read, subsequent words return OK_ATOMIC_BUFFERED."""
        probe, gen = multiword_probe
        for elem in gen._elements:
            if elem.valid_words < 2 or elem.reg.rw not in ("r", "rw"):
                continue
            probe.reset()
            probe.read(elem.base_address, 1)  # take snapshot
            for i in range(1, elem.valid_words):
                status, _ = probe.read(elem.base_address + i, 1)
                assert status == RegStatus.OK_ATOMIC_BUFFERED, (
                    f"Expected OK_ATOMIC_BUFFERED for word {i} of "
                    f"'{elem.qualified_name}', got {status.name}"
                )

    def test_full_register_read_returns_ok(self, multiword_probe):
        """Full-register read (word_idx=0, count=valid_words) returns plain OK."""
        probe, gen = multiword_probe
        for elem in gen._elements:
            if elem.valid_words < 2 or elem.reg.rw not in ("r", "rw"):
                continue
            probe.reset()
            status, _ = probe.read(elem.base_address, elem.valid_words)
            assert status == RegStatus.OK, (
                f"Expected OK for full-register read of '{elem.qualified_name}', "
                f"got {status.name}"
            )

    def test_single_word_read_returns_ok(self, simple_probe):
        """Single-word register reads always return plain OK."""
        probe, gen = simple_probe
        probe.reset()
        for elem in _all_read_only(gen) + _all_rw(gen):
            status, _ = probe.read(elem.base_address)
            assert status == RegStatus.OK, (
                f"Expected OK for single-word read of '{elem.qualified_name}', "
                f"got {status.name}"
            )


# ---------------------------------------------------------------------------
# word_width = 8 and 16 behavioral tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def _w8_bin(tmp_path_factory):
    rm = RegisterMapGenerator("w8_mod", [], word_width=8)
    rm.add(Register("status",  rw="r",  type="unsigned", width=8))
    rm.add(Register("control", rw="w",  type="unsigned", width=8))
    rm.add(Register("config",  rw="rw", type="unsigned", width=8))
    rm.add(Register("channel", rw="rw", type="unsigned", width=8, bank_size=4))
    rm.generate()
    return _compile_host(_compiler(), rm, str(tmp_path_factory.mktemp("w8")))


@pytest.fixture(scope="module")
def _w16_bin(tmp_path_factory):
    rm = RegisterMapGenerator("w16_mod", [], word_width=16)
    rm.add(Register("status",  rw="r",  type="unsigned", width=16))
    rm.add(Register("control", rw="w",  type="unsigned", width=16))
    rm.add(Register("config",  rw="rw", type="unsigned", width=16))
    rm.add(Register("channel", rw="rw", type="unsigned", width=16, bank_size=4))
    rm.generate()
    return _compile_host(_compiler(), rm, str(tmp_path_factory.mktemp("w16")))


@pytest.fixture
def w8_probe(_w8_bin):
    binary, gen = _w8_bin
    with RegProbe(binary, 1) as p:
        yield p, gen


@pytest.fixture
def w16_probe(_w16_bin):
    binary, gen = _w16_bin
    with RegProbe(binary, 2) as p:
        yield p, gen


class TestWordWidth8:
    def test_permissions(self, w8_probe):
        probe, gen = w8_probe
        for elem in _all_read_only(gen):
            s = probe.write(elem.base_address, [0])
            assert s == RegStatus.BAD_ACCESS_READ_ONLY
        for elem in _all_write_only(gen):
            s, _ = probe.read(elem.base_address)
            assert s == RegStatus.BAD_ACCESS_WRITE_ONLY

    def test_roundtrip(self, w8_probe):
        probe, gen = w8_probe
        probe.reset()
        for elem in _all_rw(gen):
            if elem.reg.bank_size > 1:
                continue
            s = probe.write(elem.base_address, [0xAB])
            assert s == RegStatus.OK
            s, words = probe.read(elem.base_address)
            assert s == RegStatus.OK
            assert words[0] == 0xAB

    def test_bank_isolation(self, w8_probe):
        probe, gen = w8_probe
        banks = defaultdict(list)
        for elem in gen._elements:
            if elem.reg.bank_size > 1:
                banks[id(elem.reg)].append(elem)
        for elems in banks.values():
            if elems[0].reg.rw not in ("rw",):
                continue
            probe.reset()
            for i, elem in enumerate(elems):
                probe.write(elem.base_address, [i + 1])
            for i, elem in enumerate(elems):
                _, words = probe.read(elem.base_address)
                assert words[0] == i + 1

    def test_reset(self, w8_probe):
        probe, gen = w8_probe
        for elem in _all_rw(gen):
            probe.write(elem.base_address, [0xFF])
        probe.reset()
        for elem in _all_rw(gen):
            _, words = probe.read(elem.base_address)
            assert words[0] == 0

    def test_accessor_verify(self, w8_probe):
        probe, _ = w8_probe
        probe.reset()
        assert probe.verify()


class TestWordWidth16:
    def test_permissions(self, w16_probe):
        probe, gen = w16_probe
        for elem in _all_read_only(gen):
            s = probe.write(elem.base_address, [0])
            assert s == RegStatus.BAD_ACCESS_READ_ONLY
        for elem in _all_write_only(gen):
            s, _ = probe.read(elem.base_address)
            assert s == RegStatus.BAD_ACCESS_WRITE_ONLY

    def test_roundtrip(self, w16_probe):
        probe, gen = w16_probe
        probe.reset()
        for elem in _all_rw(gen):
            if elem.reg.bank_size > 1:
                continue
            s = probe.write(elem.base_address, [0xABCD])
            assert s == RegStatus.OK
            s, words = probe.read(elem.base_address)
            assert s == RegStatus.OK
            assert words[0] == 0xABCD

    def test_bank_isolation(self, w16_probe):
        probe, gen = w16_probe
        banks = defaultdict(list)
        for elem in gen._elements:
            if elem.reg.bank_size > 1:
                banks[id(elem.reg)].append(elem)
        for elems in banks.values():
            if elems[0].reg.rw not in ("rw",):
                continue
            probe.reset()
            for i, elem in enumerate(elems):
                probe.write(elem.base_address, [i + 1])
            for i, elem in enumerate(elems):
                _, words = probe.read(elem.base_address)
                assert words[0] == i + 1

    def test_reset(self, w16_probe):
        probe, gen = w16_probe
        for elem in _all_rw(gen):
            probe.write(elem.base_address, [0xFFFF])
        probe.reset()
        for elem in _all_rw(gen):
            _, words = probe.read(elem.base_address)
            assert words[0] == 0

    def test_accessor_verify(self, w16_probe):
        probe, _ = w16_probe
        probe.reset()
        assert probe.verify()


# ---------------------------------------------------------------------------
# AURA_HOST_TEST guard
# ---------------------------------------------------------------------------

class TestHostTestGuard:
    def test_compilation_fails_without_flag(self, tmp_path):
        """_reg_host.cpp must not compile without -DAURA_HOST_TEST."""
        cc = shutil.which("g++") or shutil.which("clang++")
        if cc is None:
            pytest.skip("No C++ compiler found")

        rm = RegisterMapGenerator("guard_mod", [], word_width=32)
        rm.add(Register("val", rw="rw", type="unsigned", width=8))
        rm.generate()
        out = str(tmp_path / "out")
        os.makedirs(out)
        gen = FirmwareGenerator(rm, interfaces="shell")
        gen.generate(out)
        host_src = os.path.join(out, "reg_host.cpp")

        result = subprocess.run(
            [cc, "-std=c++17", "-c", "-I", out, host_src, "-o", os.devnull],
            capture_output=True, text=True,
        )
        assert result.returncode != 0, (
            "Expected compilation to fail without -DAURA_HOST_TEST but it succeeded"
        )
        assert "AURA_HOST_TEST" in result.stderr or "error" in result.stderr.lower()


# ---------------------------------------------------------------------------
# Range check and default value fixtures
# ---------------------------------------------------------------------------

import struct as _struct


def _float_bits(v: float) -> int:
    """Pack a Python float as a 32-bit IEEE 754 little-endian integer."""
    return _struct.unpack("<I", _struct.pack("<f", v))[0]


def _double_words(v: float):
    """Return (lo_word, hi_word) for a 64-bit IEEE 754 double."""
    lo, hi = _struct.unpack("<II", _struct.pack("<d", v))
    return lo, hi


@pytest.fixture(scope="module")
def _range_bin(tmp_path_factory):
    rm = RegisterMapGenerator("range_mod", [], word_width=32)
    # unsigned 32-bit: min=10, max=200
    rm.add(Register("u32_range", rw="rw", type="unsigned", width=32,
                    min_val=10, max_val=200))
    # signed 32-bit: min=-50, max=50
    rm.add(Register("s32_range", rw="rw", type="signed", width=32,
                    min_val=-50, max_val=50))
    # float 32-bit: min=-1.0, max=1.0
    rm.add(Register("f32_range", rw="rw", type="float", width=32,
                    min_val=-1.0, max_val=1.0))
    # unsigned 64-bit (2 words): min=0, max=0xFFFF
    rm.add(Register("u64_range", rw="rw", type="unsigned", width=64,
                    min_val=0, max_val=0xFFFF))
    # signed 8-bit (sub-word): min=-50, max=50
    rm.add(Register("s8_range",  rw="rw", type="signed", width=8,
                    min_val=-50, max_val=50))
    rm.generate()
    return _compile_host(_compiler(), rm, str(tmp_path_factory.mktemp("range")))


@pytest.fixture(scope="module")
def _default_bin(tmp_path_factory):
    rm = RegisterMapGenerator("def_mod", [], word_width=32)
    rm.add(Register("u32_def",  rw="rw", type="unsigned", width=32, default_val=42))
    rm.add(Register("s32_def",  rw="rw", type="signed",   width=32, default_val=-7))
    rm.add(Register("u64_def",  rw="rw", type="unsigned", width=64,
                    default_val=0x0000000200000001))
    rm.add(Register("no_def",   rw="rw", type="unsigned", width=8))
    rm.generate()
    return _compile_host(_compiler(), rm, str(tmp_path_factory.mktemp("default")))


@pytest.fixture
def range_probe(_range_bin):
    binary, gen = _range_bin
    with RegProbe(binary, gen._word_width // 8) as p:
        yield p, gen


@pytest.fixture
def default_probe(_default_bin):
    binary, gen = _default_bin
    with RegProbe(binary, gen._word_width // 8) as p:
        yield p, gen


# ---------------------------------------------------------------------------
# Range enforcement
# ---------------------------------------------------------------------------

class TestRangeCheck:
    def _elem(self, gen, name):
        return next(e for e in gen._elements if e.reg.name == name)

    def test_unsigned_within_range_accepted(self, range_probe):
        probe, gen = range_probe
        e = self._elem(gen, "u32_range")
        assert probe.write(e.base_address, [10])  == RegStatus.OK
        assert probe.write(e.base_address, [100]) == RegStatus.OK
        assert probe.write(e.base_address, [200]) == RegStatus.OK

    def test_unsigned_at_boundary_accepted(self, range_probe):
        probe, gen = range_probe
        e = self._elem(gen, "u32_range")
        assert probe.write(e.base_address, [10])  == RegStatus.OK
        assert probe.write(e.base_address, [200]) == RegStatus.OK

    def test_unsigned_below_min_rejected(self, range_probe):
        probe, gen = range_probe
        e = self._elem(gen, "u32_range")
        assert probe.write(e.base_address, [9]) == RegStatus.OUT_OF_RANGE

    def test_unsigned_above_max_rejected(self, range_probe):
        probe, gen = range_probe
        e = self._elem(gen, "u32_range")
        assert probe.write(e.base_address, [201]) == RegStatus.OUT_OF_RANGE

    def test_signed32_positive_within_range_accepted(self, range_probe):
        probe, gen = range_probe
        e = self._elem(gen, "s32_range")
        assert probe.write(e.base_address, [50])  == RegStatus.OK
        assert probe.write(e.base_address, [0])   == RegStatus.OK

    def test_signed32_negative_within_range_accepted(self, range_probe):
        probe, gen = range_probe
        e = self._elem(gen, "s32_range")
        # -50 as 32-bit two's complement = 0xFFFFFFCE
        neg50 = (1 << 32) + (-50)
        assert probe.write(e.base_address, [neg50]) == RegStatus.OK

    def test_signed32_above_max_rejected(self, range_probe):
        probe, gen = range_probe
        e = self._elem(gen, "s32_range")
        assert probe.write(e.base_address, [51]) == RegStatus.OUT_OF_RANGE

    def test_signed32_below_min_rejected(self, range_probe):
        probe, gen = range_probe
        e = self._elem(gen, "s32_range")
        neg51 = (1 << 32) + (-51)
        assert probe.write(e.base_address, [neg51]) == RegStatus.OUT_OF_RANGE

    def test_float_within_range_accepted(self, range_probe):
        probe, gen = range_probe
        e = self._elem(gen, "f32_range")
        assert probe.write(e.base_address, [_float_bits(0.0)])  == RegStatus.OK
        assert probe.write(e.base_address, [_float_bits(-1.0)]) == RegStatus.OK
        assert probe.write(e.base_address, [_float_bits(1.0)])  == RegStatus.OK

    def test_float_above_max_rejected(self, range_probe):
        probe, gen = range_probe
        e = self._elem(gen, "f32_range")
        assert probe.write(e.base_address, [_float_bits(1.5)]) == RegStatus.OUT_OF_RANGE

    def test_float_below_min_rejected(self, range_probe):
        probe, gen = range_probe
        e = self._elem(gen, "f32_range")
        assert probe.write(e.base_address, [_float_bits(-2.0)]) == RegStatus.OUT_OF_RANGE

    def test_multiword_unsigned_within_range_accepted(self, range_probe):
        probe, gen = range_probe
        e = self._elem(gen, "u64_range")
        assert probe.write(e.base_address, [0, 0])       == RegStatus.OK
        assert probe.write(e.base_address, [0xFFFF, 0])  == RegStatus.OK

    def test_multiword_unsigned_above_max_rejected(self, range_probe):
        probe, gen = range_probe
        e = self._elem(gen, "u64_range")
        # 0x10000 > max=0xFFFF
        assert probe.write(e.base_address, [0x10000, 0]) == RegStatus.OUT_OF_RANGE

    def test_multiword_unsigned_nonzero_hi_word_rejected(self, range_probe):
        probe, gen = range_probe
        e = self._elem(gen, "u64_range")
        # Any nonzero hi word puts value far above max=0xFFFF
        assert probe.write(e.base_address, [0, 1]) == RegStatus.OUT_OF_RANGE

    def test_signed8_subword_negative_within_range_accepted(self, range_probe):
        """8-bit signed in 32-bit word: sign bit is at position 7, not 31."""
        probe, gen = range_probe
        e = self._elem(gen, "s8_range")
        neg50_byte = (1 << 8) + (-50)  # 0xCE = 206
        assert probe.write(e.base_address, [neg50_byte]) == RegStatus.OK

    def test_signed8_subword_below_min_rejected(self, range_probe):
        probe, gen = range_probe
        e = self._elem(gen, "s8_range")
        neg51_byte = (1 << 8) + (-51)  # 0xCD = 205
        assert probe.write(e.base_address, [neg51_byte]) == RegStatus.OUT_OF_RANGE

    def test_signed8_subword_above_max_rejected(self, range_probe):
        probe, gen = range_probe
        e = self._elem(gen, "s8_range")
        assert probe.write(e.base_address, [51]) == RegStatus.OUT_OF_RANGE

    def test_range_check_does_not_block_read(self, range_probe):
        """Range constraints apply only to writes, never reads."""
        probe, gen = range_probe
        probe.reset()
        for e in gen._elements:
            if e.reg.rw in ("r", "rw"):
                s, _ = probe.read(e.base_address, e.valid_words)
                assert s in (RegStatus.OK, RegStatus.OK_ATOMIC_UPDATED,
                             RegStatus.OK_ATOMIC_BUFFERED)

    def test_range_register_accessor_verify(self, range_probe):
        probe, _ = range_probe
        probe.reset()
        assert probe.verify()


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------

class TestDefaultValues:
    def _elem(self, gen, name):
        return next(e for e in gen._elements if e.reg.name == name)

    def test_unsigned_default_restored_after_reset(self, default_probe):
        probe, gen = default_probe
        e = self._elem(gen, "u32_def")
        probe.write(e.base_address, [0xFF])
        probe.reset()
        _, words = probe.read(e.base_address)
        assert words[0] == 42

    def test_signed_default_restored_after_reset(self, default_probe):
        """Signed -7 stored as 32-bit two's complement 0xFFFFFFF9."""
        probe, gen = default_probe
        e = self._elem(gen, "s32_def")
        probe.write(e.base_address, [0])
        probe.reset()
        _, words = probe.read(e.base_address)
        assert words[0] == (1 << 32) + (-7)  # 0xFFFFFFF9

    def test_multiword_default_restored_after_reset(self, default_probe):
        """64-bit default 0x0000000200000001 → word[0]=1, word[1]=2."""
        probe, gen = default_probe
        e = self._elem(gen, "u64_def")
        probe.write(e.base_address, [0, 0])
        probe.reset()
        _, words = probe.read(e.base_address, e.valid_words)
        assert words[0] == 0x00000001
        assert words[1] == 0x00000002

    def test_no_default_reads_zero_after_reset(self, default_probe):
        probe, gen = default_probe
        e = self._elem(gen, "no_def")
        probe.write(e.base_address, [0xFF])
        probe.reset()
        _, words = probe.read(e.base_address)
        assert words[0] == 0

    def test_default_not_overwritten_by_prior_write(self, default_probe):
        """Writing a non-default value then resetting must restore the default."""
        probe, gen = default_probe
        e = self._elem(gen, "u32_def")
        probe.write(e.base_address, [99])
        _, w_before = probe.read(e.base_address)
        assert w_before[0] == 99
        probe.reset()
        _, w_after = probe.read(e.base_address)
        assert w_after[0] == 42

    def test_double_reset_is_idempotent(self, default_probe):
        probe, gen = default_probe
        probe.reset()
        probe.reset()
        e = self._elem(gen, "u32_def")
        _, words = probe.read(e.base_address)
        assert words[0] == 42

    def test_default_register_accessor_verify(self, default_probe):
        probe, _ = default_probe
        probe.reset()
        assert probe.verify()


# ---------------------------------------------------------------------------
# min_access_words — buffer suppression for registers within the minimum
# atomic access width
# ---------------------------------------------------------------------------

class TestMinAccessWords:
    def _elem(self, gen, name):
        return next(e for e in gen._elements if e.reg.name == name)

    def test_small_reg_partial_read_returns_plain_ok(self, min_access_probe):
        """32-bit register (== min_access_words) has no buffers: partial word-0
        read must return OK, not OK_ATOMIC_UPDATED."""
        probe, gen = min_access_probe
        probe.reset()
        e = self._elem(gen, "small")
        status, _ = probe.read(e.base_address, 1)
        assert status == RegStatus.OK, (
            f"Expected OK (no buffers) for 'small', got {status.name}"
        )

    def test_large_reg_partial_read_returns_atomic_updated(self, min_access_probe):
        """64-bit register (> min_access_words) has buffers: partial word-0
        read must return OK_ATOMIC_UPDATED."""
        probe, gen = min_access_probe
        probe.reset()
        e = self._elem(gen, "large")
        status, _ = probe.read(e.base_address, 1)
        assert status == RegStatus.OK_ATOMIC_UPDATED, (
            f"Expected OK_ATOMIC_UPDATED (buffered) for 'large', got {status.name}"
        )

    def test_large_reg_subsequent_words_return_atomic_buffered(self, min_access_probe):
        """After the snapshot read on 'large', remaining words return OK_ATOMIC_BUFFERED."""
        probe, gen = min_access_probe
        probe.reset()
        e = self._elem(gen, "large")
        probe.read(e.base_address, 1)  # take snapshot
        for i in range(1, e.valid_words):
            status, _ = probe.read(e.base_address + i, 1)
            assert status == RegStatus.OK_ATOMIC_BUFFERED, (
                f"Expected OK_ATOMIC_BUFFERED for word {i} of 'large', got {status.name}"
            )

    def test_small_reg_full_read_returns_ok(self, min_access_probe):
        """Full read of 'small' (all 4 words at once) returns plain OK."""
        probe, gen = min_access_probe
        probe.reset()
        e = self._elem(gen, "small")
        status, _ = probe.read(e.base_address, e.valid_words)
        assert status == RegStatus.OK

    def test_small_reg_roundtrip(self, min_access_probe):
        probe, gen = min_access_probe
        probe.reset()
        e = self._elem(gen, "small")
        probe.write(e.base_address, [0xAB, 0xCD, 0xEF, 0x12])
        status, words = probe.read(e.base_address, e.valid_words)
        assert status == RegStatus.OK
        assert words == [0xAB, 0xCD, 0xEF, 0x12]

    def test_large_reg_full_roundtrip(self, min_access_probe):
        probe, gen = min_access_probe
        probe.reset()
        e = self._elem(gen, "large")
        test_words = [0x10 + i for i in range(e.valid_words)]
        probe.write(e.base_address, test_words)
        status, words = probe.read(e.base_address, e.valid_words)
        assert status == RegStatus.OK
        assert words == test_words

    def test_accessor_verify(self, min_access_probe):
        probe, _ = min_access_probe
        probe.reset()
        assert probe.verify(), "C++ accessor verify failed for min_access_rm"
