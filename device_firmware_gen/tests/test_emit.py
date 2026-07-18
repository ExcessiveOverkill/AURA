import os
import pytest
from device_firmware_gen import FirmwareGenerator
from register_mapper import RegisterMapGenerator, Register


def _gen(rm, out_dir):
    gen = FirmwareGenerator(rm, interfaces="shell")
    gen.generate(out_dir)
    return gen


def _read(out_dir, suffix):
    path = os.path.join(out_dir, suffix)
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Types header
# ---------------------------------------------------------------------------

class TestTypesHeader:
    def test_pragma_once(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "#pragma once" in _read(out_dir,"reg_types.hpp")

    def test_word_typedef_uint32(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_types.hpp")
        assert "using word_t" in content
        assert "uint32_t" in content

    def test_word_typedef_uint8(self, tmp_path, out_dir):
        rm = RegisterMapGenerator("tiny_mod", [], word_width=8)
        rm.add(Register("r", rw="r", type="unsigned", width=8))
        rm.generate()
        _gen(rm, out_dir)
        content = _read(out_dir, "reg_types.hpp")
        assert "using word_t = uint8_t" in content

    def test_word_typedef_uint16(self, tmp_path, out_dir):
        rm = RegisterMapGenerator("sm_mod", [], word_width=16)
        rm.add(Register("r", rw="r", type="unsigned", width=8))
        rm.generate()
        _gen(rm, out_dir)
        content = _read(out_dir, "reg_types.hpp")
        assert "using word_t = uint16_t" in content

    def test_reg_status_ok(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_types.hpp")
        assert "OK" in content

    def test_reg_status_bad_address(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "BAD_ADDRESS" in _read(out_dir,"reg_types.hpp")

    def test_reg_status_register_overflow(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "REGISTER_OVERFLOW" in _read(out_dir,"reg_types.hpp")

    def test_reg_status_out_of_range(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "OUT_OF_RANGE" in _read(out_dir,"reg_types.hpp")

    def test_reg_access_read(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "READ" in _read(out_dir,"reg_types.hpp")

    def test_reg_access_write(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "WRITE" in _read(out_dir,"reg_types.hpp")

    def test_reg_access_read_write(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "READ_WRITE" in _read(out_dir,"reg_types.hpp")

    def test_enum_class_for_enum_reg(self, enum_rm, out_dir):
        _gen(enum_rm, out_dir)
        content = _read(out_dir,"reg_types.hpp")
        assert "mode_e" in content

    def test_enum_values_in_header(self, enum_rm, out_dir):
        _gen(enum_rm, out_dir)
        content = _read(out_dir,"reg_types.hpp")
        assert "IDLE" in content
        assert "RUN" in content
        assert "SLEEP" in content

    def test_no_enum_when_no_enum_regs(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_types.hpp")
        # Should say no enum entries
        assert "No registers with enum" in content

    def test_namespace_wraps_content(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_types.hpp")
        assert "namespace regs" in content

    def test_generated_header_comment(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "do not edit" in _read(out_dir,"reg_types.hpp")


# ---------------------------------------------------------------------------
# Storage header
# ---------------------------------------------------------------------------

class TestStorageHeader:
    def test_pragma_once(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "#pragma once" in _read(out_dir,"reg_storage.hpp")

    def test_includes_types_header(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "reg_types.hpp" in _read(out_dir,"reg_storage.hpp")

    def test_reg_map_t_struct(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "RegMap_t" in _read(out_dir,"reg_storage.hpp")

    def test_extern_regs_declaration(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "extern RegMap_t regs" in _read(out_dir,"reg_storage.hpp")

    def test_single_word_value_member(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "word_t value = 0" in _read(out_dir,"reg_storage.hpp")

    def test_bank_entries_array(self, banked_rm, out_dir):
        _gen(banked_rm, out_dir)
        assert "entries[4]" in _read(out_dir,"reg_storage.hpp")

    def test_multiword_words_array(self, multiword_rm, out_dir):
        _gen(multiword_rm, out_dir)
        assert "words[" in _read(out_dir,"reg_storage.hpp")

    def test_namespace_wraps_content(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "namespace regs" in _read(out_dir,"reg_storage.hpp")


# ---------------------------------------------------------------------------
# Storage source
# ---------------------------------------------------------------------------

class TestStorageSource:
    def test_includes_storage_header(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "reg_storage.hpp" in _read(out_dir,"reg_storage.cpp")

    def test_reg_map_definition(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "RegMap_t regs" in _read(out_dir,"reg_storage.cpp")

    def test_zero_initialised(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "= {}" in _read(out_dir,"reg_storage.cpp")


# ---------------------------------------------------------------------------
# Device header
# ---------------------------------------------------------------------------

class TestDeviceHeader:
    def test_pragma_once(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "#pragma once" in _read(out_dir,"reg_device.hpp")

    def test_getter_for_read_register(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "get_status" in _read(out_dir,"reg_device.hpp")

    def test_setter_for_write_register(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "set_control" in _read(out_dir,"reg_device.hpp")

    def test_setter_for_read_only(self, simple_rm, out_dir):
        # Device always gets direct write access regardless of host rw setting
        _gen(simple_rm, out_dir)
        assert "set_status" in _read(out_dir,"reg_device.hpp")

    def test_getter_for_write_only(self, simple_rm, out_dir):
        # Device always gets direct read access regardless of host rw setting
        _gen(simple_rm, out_dir)
        assert "get_control" in _read(out_dir,"reg_device.hpp")

    def test_accessors_are_inline(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "inline" in _read(out_dir,"reg_device.hpp")

    def test_bank_getter_takes_index(self, banked_rm, out_dir):
        _gen(banked_rm, out_dir)
        assert "uint8_t idx" in _read(out_dir,"reg_device.hpp")

    def test_bitfield_getter(self, bitfield_rm, out_dir):
        _gen(bitfield_rm, out_dir)
        content = _read(out_dir,"reg_device.hpp")
        assert "get_ctrl_enabled" in content

    def test_bitfield_setter(self, tmp_path):
        # Write-only ctrl register with write-only bitfields
        rm = RegisterMapGenerator("wbf_mod", [], word_width=32)
        en = Register("enabled", rw="w", type="bool")
        lvl = Register("level", rw="w", type="unsigned", width=4)
        rm.add(Register("ctrl", rw="w", type="unsigned", width=8, bit_field=[en, lvl]))
        rm.generate()
        out = str(tmp_path / "out")
        os.makedirs(out)
        FirmwareGenerator(rm).generate(out)
        content = open(os.path.join(out, "reg_device.hpp"), encoding="utf-8").read()
        assert "set_ctrl_level" in content

    def test_grouped_count_gt1_comment_only(self, grouped_rm, out_dir):
        # Groups with count > 1 get a comment, not expanded accessors
        _gen(grouped_rm, out_dir)
        content = _read(out_dir,"reg_device.hpp")
        assert "periph" in content
        assert "count=2" in content

    def test_multiword_bulk_accessor(self, multiword_rm, out_dir):
        _gen(multiword_rm, out_dir)
        content = _read(out_dir,"reg_device.hpp")
        # Multi-word register gets a word_t* bulk interface
        assert "big_val" in content


# ---------------------------------------------------------------------------
# Comm header
# ---------------------------------------------------------------------------

class TestCommHeader:
    def test_pragma_once(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "#pragma once" in _read(out_dir,"reg_comm.hpp")

    def test_reg_read_declaration(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "reg_read(" in _read(out_dir,"reg_comm.hpp")

    def test_reg_write_declaration(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "reg_write(" in _read(out_dir,"reg_comm.hpp")

    def test_reg_reset_declaration(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "reg_reset" in _read(out_dir,"reg_comm.hpp")

    def test_reg_info_struct(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "RegInfo" in _read(out_dir,"reg_comm.hpp")

    def test_reg_addr_slot_struct(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "RegAddrSlot" in _read(out_dir,"reg_comm.hpp")

    def test_includes_types_header(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "reg_types.hpp" in _read(out_dir,"reg_comm.hpp")

    def test_reg_status_return_type(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_comm.hpp")
        assert "RegStatus" in content


# ---------------------------------------------------------------------------
# Comm source
# ---------------------------------------------------------------------------

class TestCommSource:
    def test_includes_comm_header(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "reg_comm.hpp" in _read(out_dir,"reg_comm.cpp")

    def test_includes_storage_header(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "reg_storage.hpp" in _read(out_dir,"reg_comm.cpp")

    def test_address_table_present(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_comm.cpp")
        assert "reg_table" in content

    def test_reg_info_table_present(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "RegInfo" in _read(out_dir,"reg_comm.cpp")

    def test_reg_reset_uses_memset(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "memset" in _read(out_dir,"reg_comm.cpp")

    def test_reg_reset_function_body(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "reg_reset" in _read(out_dir,"reg_comm.cpp")

    def test_multiword_buffers_present(self, multiword_rm, out_dir):
        _gen(multiword_rm, out_dir)
        content = _read(out_dir,"reg_comm.cpp")
        # Multi-word registers need read/write buffers
        assert "rd_buf" in content or "read_buf" in content or "buf" in content

    def test_multiword_read_uses_memcpy(self, multiword_rm, out_dir):
        _gen(multiword_rm, out_dir)
        assert "memcpy" in _read(out_dir,"reg_comm.cpp")

    def test_multiword_write_uses_memcpy(self, multiword_rm, out_dir):
        _gen(multiword_rm, out_dir)
        content = _read(out_dir,"reg_comm.cpp")
        assert content.count("memcpy") >= 2

    def test_full_register_read_path_present(self, multiword_rm, out_dir):
        _gen(multiword_rm, out_dir)
        content = _read(out_dir,"reg_comm.cpp")
        assert "slot.word_idx == 0 && count == info.valid_words" in content

    def test_full_register_write_path_present(self, multiword_rm, out_dir):
        _gen(multiword_rm, out_dir)
        content = _read(out_dir,"reg_comm.cpp")
        assert content.count("slot.word_idx == 0 && count == info.valid_words") == 2

    def test_critical_macros_in_types_header(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_types.hpp")
        assert "REG_ENTER_CRITICAL" in content
        assert "REG_EXIT_CRITICAL" in content

    def test_critical_macros_used_in_comm_source(self, multiword_rm, out_dir):
        _gen(multiword_rm, out_dir)
        content = _read(out_dir,"reg_comm.cpp")
        assert "REG_ENTER_CRITICAL" in content
        assert "REG_EXIT_CRITICAL" in content

    def test_namespace_wraps_content(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "namespace regs" in _read(out_dir,"reg_comm.cpp")


# ---------------------------------------------------------------------------
# Accessor verify source
# ---------------------------------------------------------------------------

class TestVerifySource:
    def test_do_not_edit_comment(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "do not edit" in _read(out_dir,"reg_verify.cpp")

    def test_includes_device_header(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "reg_device.hpp" in _read(out_dir,"reg_verify.cpp")

    def test_includes_comm_header(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "reg_comm.hpp" in _read(out_dir,"reg_verify.cpp")

    def test_verify_function_declaration(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "int reg_verify()" in _read(out_dir,"reg_verify.cpp")

    def test_verify_assert_macro_present(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_verify.cpp")
        assert "REG_VERIFY_ASSERT" in content

    def test_returns_zero_on_success(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "return 0;" in _read(out_dir,"reg_verify.cpp")

    def test_rw_register_has_set_and_get(self, simple_rm, out_dir):
        # simple_rm has config as rw — verify emits both set_config and get_config
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_verify.cpp")
        assert "set_config" in content
        assert "get_config" in content

    def test_write_only_register_has_set_and_get(self, simple_rm, out_dir):
        # Device always gets both accessors — verify exercises both
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_verify.cpp")
        assert "set_control" in content
        assert "get_control" in content

    def test_read_only_register_has_get_and_set(self, simple_rm, out_dir):
        # Device always gets both accessors — verify exercises both
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_verify.cpp")
        assert "get_status" in content
        assert "set_status" in content

    def test_bitfield_accessors_in_verify(self, bitfield_rm, out_dir):
        _gen(bitfield_rm, out_dir)
        content = _read(out_dir,"reg_verify.cpp")
        assert "get_ctrl_enabled" in content or "set_ctrl_enabled" in content

    def test_reg_reset_called_per_register(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_verify.cpp")
        assert content.count("reg_reset()") >= 1


# ---------------------------------------------------------------------------
# Host shim source
# ---------------------------------------------------------------------------

class TestHostShim:
    def test_do_not_edit_comment(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "do not edit" in _read(out_dir,"reg_host.cpp")

    def test_host_test_guard_present(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_host.cpp")
        assert "#ifndef AURA_HOST_TEST" in content
        assert "error" in content  # #  error "..." directive

    def test_includes_comm_header(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "reg_comm.hpp" in _read(out_dir,"reg_host.cpp")

    def test_includes_storage_header(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "reg_storage.hpp" in _read(out_dir,"reg_host.cpp")

    def test_cmd_constants_present(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_host.cpp")
        for cmd in ("CMD_READ", "CMD_WRITE", "CMD_RESET", "CMD_VERIFY"):
            assert cmd in content

    def test_main_function_present(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "int main()" in _read(out_dir,"reg_host.cpp")

    def test_windows_binary_mode_present(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_host.cpp")
        assert "_setmode" in content
        assert "_O_BINARY" in content

    def test_vector_used_for_io_buffers(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "std::vector" in _read(out_dir,"reg_host.cpp")

    def test_forward_declaration_verify(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "reg_verify" in _read(out_dir,"reg_host.cpp")

    def test_atomic_statuses_send_data(self, simple_rm, out_dir):
        # Data must be sent for OK (0), OK_ATOMIC_BUFFERED (1), OK_ATOMIC_UPDATED (2)
        _gen(simple_rm, out_dir)
        assert "s <= 2" in _read(out_dir,"reg_host.cpp")

    def test_fflush_stdout_present(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "fflush(stdout)" in _read(out_dir,"reg_host.cpp")


# ---------------------------------------------------------------------------
# Comm header — RegType enum and RegInfo.type field
# ---------------------------------------------------------------------------

class TestCommHeaderRegType:
    def test_reg_type_enum_emitted(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_comm.hpp")
        assert "RegType" in content

    def test_reg_type_unsigned_value(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "UNSIGNED" in _read(out_dir,"reg_comm.hpp")

    def test_reg_type_signed_value(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "SIGNED" in _read(out_dir,"reg_comm.hpp")

    def test_reg_type_float_value(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "FLOAT" in _read(out_dir,"reg_comm.hpp")

    def test_reg_type_double_value(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "DOUBLE" in _read(out_dir,"reg_comm.hpp")

    def test_reg_info_has_type_field(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_comm.hpp")
        assert "RegType" in content and "type;" in content

    def test_default_val_pointer_in_reg_info(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_comm.hpp")
        assert "const word_t*" in content and "default_val" in content

    def test_min_val_pointer_in_reg_info(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "min_val" in _read(out_dir,"reg_comm.hpp")

    def test_max_val_pointer_in_reg_info(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "max_val" in _read(out_dir,"reg_comm.hpp")


# ---------------------------------------------------------------------------
# Comm source — default/range arrays, comparators, range-check dispatch
# ---------------------------------------------------------------------------

def _range_rm(tmp_path):
    """Register map with one register of each type that has min/max and a default."""
    rm = RegisterMapGenerator("rng_mod", [], word_width=32)
    rm.add(Register("u32r", rw="rw", type="unsigned", width=32,
                    min_val=10, max_val=200, default_val=100))
    rm.add(Register("s32r", rw="rw", type="signed",   width=32,
                    min_val=-50, max_val=50, default_val=-5))
    rm.add(Register("f32r", rw="rw", type="float",    width=32,
                    min_val=-1.0, max_val=1.0, default_val=0.5))
    rm.add(Register("u64r", rw="rw", type="unsigned", width=64,
                    min_val=0, max_val=0xFFFF, default_val=1))
    rm.generate()
    return rm


class TestRangeDefaultEmit:
    def test_default_array_emitted_for_register_with_default(self, tmp_path):
        rm = _range_rm(tmp_path)
        out = str(tmp_path / "out"); os.makedirs(out, exist_ok=True)
        _gen(rm, out)
        content = _read(out,"reg_comm.cpp")
        assert "_default[" in content

    def test_min_array_emitted_for_register_with_range(self, tmp_path):
        rm = _range_rm(tmp_path)
        out = str(tmp_path / "out"); os.makedirs(out, exist_ok=True)
        _gen(rm, out)
        content = _read(out,"reg_comm.cpp")
        assert "_min[" in content

    def test_max_array_emitted_for_register_with_range(self, tmp_path):
        rm = _range_rm(tmp_path)
        out = str(tmp_path / "out"); os.makedirs(out, exist_ok=True)
        _gen(rm, out)
        content = _read(out,"reg_comm.cpp")
        assert "_max[" in content

    def test_no_default_array_when_no_default(self, simple_rm, out_dir):
        """simple_rm has no defaults — no _default[] arrays should be emitted."""
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_comm.cpp")
        assert "_default[" not in content

    def test_no_min_max_array_when_no_range(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_comm.cpp")
        assert "_min[" not in content
        assert "_max[" not in content

    def test_default_ptr_is_nullptr_when_no_default(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_comm.cpp")
        assert "nullptr" in content

    def test_reg_cmp_le_emitted(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "reg_cmp_le(" in _read(out_dir,"reg_comm.cpp")

    def test_reg_cmp_le_signed_emitted(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "reg_cmp_le_signed(" in _read(out_dir,"reg_comm.cpp")

    def test_reg_cmp_le_float_emitted(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "reg_cmp_le_float(" in _read(out_dir,"reg_comm.cpp")

    def test_reg_cmp_le_double_emitted(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        assert "reg_cmp_le_double(" in _read(out_dir,"reg_comm.cpp")

    def test_range_check_uses_switch_on_type(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_comm.cpp")
        assert "switch (info.type)" in content

    def test_range_check_dispatches_signed(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_comm.cpp")
        assert "RegType::SIGNED" in content and "reg_cmp_le_signed" in content

    def test_range_check_dispatches_float(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_comm.cpp")
        assert "RegType::FLOAT" in content and "reg_cmp_le_float" in content

    def test_range_check_dispatches_double(self, simple_rm, out_dir):
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_comm.cpp")
        assert "RegType::DOUBLE" in content and "reg_cmp_le_double" in content

    def test_reset_uses_memcpy_for_default(self, tmp_path):
        rm = _range_rm(tmp_path)
        out = str(tmp_path / "out"); os.makedirs(out, exist_ok=True)
        _gen(rm, out)
        content = _read(out,"reg_comm.cpp")
        assert "memcpy(info.storage, info.default_val" in content

    def test_multiword_default_encodes_both_words(self, tmp_path):
        """64-bit default=1 → [0x1u, 0x0u] — both words must appear in the array."""
        rm = RegisterMapGenerator("mwd_mod", [], word_width=32)
        rm.add(Register("big", rw="rw", type="unsigned", width=64, default_val=1))
        rm.generate()
        out = str(tmp_path / "out"); os.makedirs(out, exist_ok=True)
        _gen(rm, out)
        content = _read(out,"reg_comm.cpp")
        # Array should be { 0x1u, 0x0u }
        assert "0x1u" in content and "0x0u" in content

    def test_signed_default_encodes_as_two_complement(self, tmp_path):
        """-7 encoded as 32-bit two's complement: 0xFFFFFFF9."""
        rm = RegisterMapGenerator("sgn_mod", [], word_width=32)
        rm.add(Register("s", rw="rw", type="signed", width=32, default_val=-7))
        rm.generate()
        out = str(tmp_path / "out"); os.makedirs(out, exist_ok=True)
        _gen(rm, out)
        content = _read(out,"reg_comm.cpp")
        assert "0xFFFFFFF9u" in content

    def test_signed_min_encodes_as_two_complement(self, tmp_path):
        """-50 in 8-bit signed encodes as 0xCE (not 32-bit 0xFFFFFFCE)."""
        rm = RegisterMapGenerator("s8m_mod", [], word_width=32)
        rm.add(Register("s8", rw="rw", type="signed", width=8,
                        min_val=-50, max_val=50))
        rm.generate()
        out = str(tmp_path / "out"); os.makedirs(out, exist_ok=True)
        _gen(rm, out)
        content = _read(out,"reg_comm.cpp")
        # -50 in 8-bit = 0xCE; must NOT extend to full 32-bit 0xFFFFFFCE
        assert "0xCEu" in content
        assert "0xFFFFFFCEu" not in content

    def test_last_word_bits_passed_to_signed_comparator(self, simple_rm, out_dir):
        """The generated switch must pass info.last_word_bits to reg_cmp_le_signed."""
        _gen(simple_rm, out_dir)
        content = _read(out_dir,"reg_comm.cpp")
        assert "info.last_word_bits" in content
