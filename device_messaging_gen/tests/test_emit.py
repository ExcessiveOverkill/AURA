"""Tests for generated C++ file contents."""

import os
import tempfile

from device_messaging_gen import Message, MessageGroup, MessageSeverity, MessagingGenerator


def _make_gen():
    return MessagingGenerator("drive", [
        MessageGroup("system", [
            Message("clock_fault",  MessageSeverity.ERROR,   desc="Clock failure"),
            MessageGroup("power", [
                Message("low_voltage", MessageSeverity.WARNING, delay_us=5000),
                Message("overvoltage", MessageSeverity.ERROR),
            ]),
        ]),
        MessageGroup("communication", [
            Message("timeout",        MessageSeverity.ERROR),
            Message("checksum_error", MessageSeverity.WARNING),
        ]),
        Message("watchdog", MessageSeverity.CRITICAL, desc="Watchdog timeout"),
    ])


def _generate(gen=None):
    if gen is None:
        gen = _make_gen()
    with tempfile.TemporaryDirectory() as d:
        gen.generate(d)
        return {
            fname: open(os.path.join(d, fname), encoding="utf-8").read()
            for fname in os.listdir(d)
        }


# ------------------------------------------------------------------
# types header
# ------------------------------------------------------------------

def test_types_pragma_once():
    f = _generate()["msg_types.hpp"]
    assert "#pragma once" in f


def test_types_message_count():
    f = _generate()["msg_types.hpp"]
    assert "MESSAGE_COUNT = 6" in f


def test_types_message_id_enum():
    f = _generate()["msg_types.hpp"]
    assert "enum class MessageId" in f
    assert "SYSTEM__CLOCK_FAULT = 0" in f
    assert "SYSTEM__POWER__LOW_VOLTAGE = 1" in f
    assert "SYSTEM__POWER__OVERVOLTAGE = 2" in f
    assert "COMMUNICATION__TIMEOUT = 3" in f
    assert "COMMUNICATION__CHECKSUM_ERROR = 4" in f
    assert "WATCHDOG = 5" in f


def test_types_severity_enum():
    f = _generate()["msg_types.hpp"]
    assert "enum class MessageSeverity" in f
    assert "NONE = 0" in f
    assert "CRITICAL = 4" in f


def test_types_command_enum():
    f = _generate()["msg_types.hpp"]
    assert "enum class MsgCommand" in f
    assert "RESET_SELECTED_TIME = 1" in f
    assert "RESET_SELECTED_PAYLOAD = 2" in f
    assert "RESET_SELECTED_HIT_COUNT = 3" in f
    assert "RESET_SELECTED = 4" in f
    assert "RESET_ALL_TIME = 5" in f
    assert "RESET_ALL_PAYLOAD = 6" in f
    assert "RESET_ALL_HIT_COUNT = 7" in f
    assert "RESET_ALL = 8" in f
    assert "RECALC_SEVERITY = 9" in f


def test_types_reg_iface_struct():
    f = _generate()["msg_types.hpp"]
    assert "MsgRegIface" in f
    assert "uint16_t* count;" in f
    assert "uint16_t* active_severity;" in f
    assert "uint16_t* cmd;" in f
    assert "uint16_t* control;" in f
    assert "uint32_t* time_lower;" in f
    assert "uint32_t* time_upper;" in f
    assert "uint32_t* payload;" in f
    assert "uint16_t* hit_count;" in f


def test_types_string_declarations():
    f = _generate()["msg_types.hpp"]
    assert "msg_get_name(" in f
    assert "msg_get_desc(" in f
    assert "msg_get_severity(" in f
    assert "severity_label(" in f
    # Old full-path group function must be gone
    assert "msg_get_group(" not in f


def test_types_msg_get_time_macro():
    f = _generate()["msg_types.hpp"]
    assert "MSG_GET_TIME_US" in f
    assert "#ifndef MSG_GET_TIME_US" in f


def test_types_accessor_structs():
    f = _generate()["msg_types.hpp"]
    # Struct type names
    assert "struct _Msg_System_Power" in f
    assert "struct _Msg_System" in f
    assert "struct _Msg_Communication" in f
    assert "struct _Msg " in f or "struct _Msg{" in f or "_Msg {" in f
    # Leaf ID members
    assert "static constexpr MessageId clock_fault" in f
    assert "static constexpr MessageId low_voltage" in f
    assert "static constexpr MessageId watchdog" in f
    # Nested group members
    assert "static constexpr _Msg_System_Power power{};" in f
    assert "static constexpr _Msg_System system{};" in f
    # Global accessor instance
    assert "msgs" in f
    assert "inline constexpr" in f


# ------------------------------------------------------------------
# strings cpp
# ------------------------------------------------------------------

def test_strings_message_values():
    f = _generate()["msg_strings.cpp"]
    assert "message_values" in f
    # ERROR(3)<<28 | 0 = 0x30000000
    assert "0x30000000u" in f


def test_strings_delays():
    f = _generate()["msg_strings.cpp"]
    assert "message_delays" in f
    assert "5000u" in f


def test_strings_name_table():
    f = _generate()["msg_strings.cpp"]
    assert '"clock_fault"' in f
    assert '"low_voltage"' in f
    assert '"watchdog"' in f


def test_strings_desc_table():
    f = _generate()["msg_strings.cpp"]
    assert '"Clock failure"' in f
    assert '"Watchdog timeout"' in f


def test_strings_group_table():
    f = _generate()["msg_strings.cpp"]
    # Group node table — one entry per unique segment, not per message
    assert 'msg_group_nodes' in f
    assert '"system"' in f
    assert '"power"' in f
    assert '"communication"' in f
    # Must NOT contain the concatenated "system.power" path
    assert '"system.power"' not in f
    # Per-message index array
    assert 'msg_group_idx' in f


def test_group_node_count():
    f = _generate()["msg_types.hpp"]
    # 3 unique groups: system, power (child of system), communication
    assert "GROUP_COUNT = 3" in f


def test_group_node_struct():
    f = _generate()["msg_types.hpp"]
    assert "GroupNode" in f
    assert "const char* name;" in f
    assert "int8_t      parent;" in f


def test_group_accessors_declared():
    f = _generate()["msg_types.hpp"]
    assert "msg_get_group_idx(" in f
    assert "group_name(" in f
    assert "group_parent(" in f
    # Old full-path function must be gone
    assert "msg_get_group(" not in f


def test_group_accessors_defined():
    f = _generate()["msg_strings.cpp"]
    assert "msg_get_group_idx(" in f
    assert "group_name(" in f
    assert "group_parent(" in f


def test_strings_severity_labels():
    f = _generate()["msg_strings.cpp"]
    assert '"none"' in f
    assert '"warning"' in f
    assert '"critical"' in f


def test_strings_accessor_functions():
    f = _generate()["msg_strings.cpp"]
    assert "msg_get_name(" in f
    assert "msg_get_desc(" in f
    assert "msg_get_severity(" in f
    assert "severity_label(" in f
    assert "msg_get_group_idx(" in f
    assert "group_name(" in f
    assert "group_parent(" in f
    # Old full-path function must be gone
    assert "msg_get_group(" not in f


# ------------------------------------------------------------------
# class header
# ------------------------------------------------------------------

def test_header_class_declaration():
    f = _generate()["msg.hpp"]
    assert "struct Messaging" in f
    assert "void init();" in f
    assert "void set_register_interface(" in f


def test_header_logging_methods():
    f = _generate()["msg.hpp"]
    assert "MessageSeverity add(MessageId" in f
    assert "log_persistent_active(" in f
    assert "log_persistent_inactive(" in f


def test_header_clear_methods():
    f = _generate()["msg.hpp"]
    assert "void clear_time(MessageId" in f
    assert "void clear_payload(MessageId" in f
    assert "void clear_hit_count(MessageId" in f
    assert "void clear(MessageId" in f
    assert "void clear_all_times();" in f
    assert "void clear_all_payloads();" in f
    assert "void clear_all_hit_counts();" in f
    assert "void clear_all();" in f


def test_header_severity():
    f = _generate()["msg.hpp"]
    assert "void recalc_severity();" in f


def test_header_query_methods():
    f = _generate()["msg.hpp"]
    assert "get_active_severity()" in f
    assert "bool is_active(MessageId" in f
    assert "get_last_active_time(" in f
    assert "get_last_payload(" in f
    assert "get_hit_count(" in f


def test_header_comm_update():
    f = _generate()["msg.hpp"]
    assert "void comm_update();" in f


def test_header_private_members():
    f = _generate()["msg.hpp"]
    assert "private:" in f
    assert "_active_times" in f
    assert "_ok_times" in f
    assert "_payloads" in f
    assert "_hit_counts" in f
    assert "_has_regs" in f


# ------------------------------------------------------------------
# class implementation
# ------------------------------------------------------------------

def test_impl_init():
    f = _generate()["msg.cpp"]
    assert "Messaging::init()" in f
    assert "memset" in f


def test_impl_add():
    f = _generate()["msg.cpp"]
    assert "Messaging::add(" in f
    assert "MSG_GET_TIME_US()" in f
    assert "_hit_counts" in f
    assert "_payloads" in f


def test_impl_persistent():
    f = _generate()["msg.cpp"]
    assert "log_persistent_active(" in f
    assert "log_persistent_inactive(" in f
    assert "message_delays" in f


def test_impl_clear():
    f = _generate()["msg.cpp"]
    # Field helpers exist
    assert "_clear_time(" in f
    assert "_clear_payload(" in f
    assert "_clear_hit_count(" in f
    assert "_clear_one(" in f
    # Public clears exist
    assert "Messaging::clear_time(" in f
    assert "Messaging::clear_payload(" in f
    assert "Messaging::clear_hit_count(" in f
    assert "Messaging::clear(" in f
    assert "Messaging::clear_all_times()" in f
    assert "Messaging::clear_all_payloads()" in f
    assert "Messaging::clear_all_hit_counts()" in f
    assert "Messaging::clear_all()" in f
    # No auto severity recalc inside clear/clear_all
    # (recalc_severity is only called from recalc_severity() and comm_update RECALC_SEVERITY)
    assert "Messaging::recalc_severity()" in f


def test_impl_is_active():
    f = _generate()["msg.cpp"]
    assert "Messaging::is_active(" in f
    assert "_active_times[idx] > _ok_times[idx]" in f


def test_impl_no_auto_recalc_in_clear():
    f = _generate()["msg.cpp"]
    # Find the clear() function body — it should call _clear_one but NOT _recalc_severity
    clear_fn = f[f.index("Messaging::clear("):]
    clear_body = clear_fn[:clear_fn.index("Messaging::clear_a")]
    assert "_recalc_severity" not in clear_body


def test_impl_comm_update():
    f = _generate()["msg.cpp"]
    assert "Messaging::comm_update()" in f
    assert "RESET_SELECTED_TIME" in f
    assert "RESET_SELECTED_PAYLOAD" in f
    assert "RESET_SELECTED_HIT_COUNT" in f
    assert "RESET_SELECTED" in f
    assert "RESET_ALL_TIME" in f
    assert "RESET_ALL_PAYLOAD" in f
    assert "RESET_ALL_HIT_COUNT" in f
    assert "RESET_ALL" in f
    assert "RECALC_SEVERITY" in f
    assert "time_lower" in f
    assert "time_upper" in f
    assert "hit_count" in f


def test_impl_set_register_interface():
    f = _generate()["msg.cpp"]
    assert "set_register_interface(" in f
    assert "_has_regs = true" in f


# ------------------------------------------------------------------
# Module name variation — file names are fixed; module only affects
# the device name used inside generated content (e.g. class impl).
# ------------------------------------------------------------------

def test_custom_module_name():
    gen = MessagingGenerator("motor_ctrl", [
        Message("fault", MessageSeverity.ERROR),
    ])
    files = _generate(gen)
    # File names are fixed regardless of module name
    assert "msg_types.hpp" in files
    assert "msg_strings.cpp" in files
    assert "msg.hpp" in files
    assert "msg.cpp" in files
    types = files["msg_types.hpp"]
    # All type names are fixed too
    assert "MessageId" in types
    assert "msgs" in types
    assert "MESSAGE_COUNT" in types


# ------------------------------------------------------------------
# Instanced groups
# ------------------------------------------------------------------

def _make_instanced_gen():
    """3 motor instances × 2 messages + 1 top-level = 7 total, 3 unique."""
    return MessagingGenerator("drive", [
        MessageGroup("motor", [
            Message("fault",    MessageSeverity.ERROR,   desc="Motor fault"),
            Message("overtemp", MessageSeverity.WARNING, delay_us=1000),
        ], count=3),
        Message("watchdog", MessageSeverity.CRITICAL, desc="Watchdog"),
    ])


def _make_nested_instanced_gen():
    """Instanced group with a nested sub-group."""
    return MessagingGenerator("drive", [
        MessageGroup("motor", [
            Message("fault", MessageSeverity.ERROR),
            MessageGroup("system", [
                Message("init_failed", MessageSeverity.CRITICAL),
            ]),
        ], count=2),
    ])


def test_instanced_enum_members():
    f = _generate(_make_instanced_gen())["msg_types.hpp"]
    assert "MOTOR_0__FAULT = 0" in f
    assert "MOTOR_0__OVERTEMP = 1" in f
    assert "MOTOR_1__FAULT = 2" in f
    assert "MOTOR_1__OVERTEMP = 3" in f
    assert "MOTOR_2__FAULT = 4" in f
    assert "MOTOR_2__OVERTEMP = 5" in f
    assert "WATCHDOG = 6" in f


def test_instanced_message_count():
    f = _generate(_make_instanced_gen())["msg_types.hpp"]
    assert "MESSAGE_COUNT = 7" in f


def test_instanced_unique_count_constant():
    f = _generate(_make_instanced_gen())["msg_types.hpp"]
    assert "UNIQUE_MSG_COUNT = 3" in f


def test_instanced_no_unique_count_when_not_instanced():
    f = _generate()["msg_types.hpp"]
    assert "UNIQUE_MSG_COUNT" not in f


def test_instanced_string_id_array():
    f = _generate(_make_instanced_gen())["msg_strings.cpp"]
    assert "_msg_string_id" in f
    # 7-element array: [0,1,0,1,0,1,2]
    assert "0,  // MOTOR_0__FAULT" in f
    assert "1,  // MOTOR_0__OVERTEMP" in f
    assert "0,  // MOTOR_1__FAULT" in f
    assert "2,  // WATCHDOG" in f


def test_instanced_name_table_deduplicated():
    f = _generate(_make_instanced_gen())["msg_strings.cpp"]
    # Only 3 unique names; "fault" appears exactly once as a string literal
    assert f.count('"fault"') == 1
    assert f.count('"overtemp"') == 1
    assert f.count('"watchdog"') == 1


def test_instanced_desc_table_deduplicated():
    f = _generate(_make_instanced_gen())["msg_strings.cpp"]
    assert f.count('"Motor fault"') == 1
    assert f.count('"Watchdog"') == 1


def test_instanced_name_table_uses_unique_count():
    f = _generate(_make_instanced_gen())["msg_strings.cpp"]
    assert "UNIQUE_MSG_COUNT" in f


def test_instanced_string_id_accessor_indirection():
    f = _generate(_make_instanced_gen())["msg_strings.cpp"]
    # Accessor must use the string_id lookup
    assert "_msg_string_id[uint16_t(id)]" in f


def test_instanced_delays_full_size():
    f = _generate(_make_instanced_gen())["msg_strings.cpp"]
    # Delays are full-size (not deduplicated) — 7 entries, 1000u appears 3 times
    assert f.count("1000u") == 3


def test_instanced_group_node_not_duplicated():
    f = _generate(_make_instanced_gen())["msg_strings.cpp"]
    # Only one "motor" group node entry
    assert f.count('"motor"') == 1


def test_instanced_accessor_array_in_types():
    f = _generate(_make_instanced_gen())["msg_types.hpp"]
    # Root struct has a C-style array for the instanced group
    assert "_Msg_Motor motor[3]" in f


def test_instanced_struct_type_emitted():
    f = _generate(_make_instanced_gen())["msg_types.hpp"]
    assert "struct _Msg_Motor" in f


def test_instanced_struct_non_static_members():
    f = _generate(_make_instanced_gen())["msg_types.hpp"]
    # Members inside _Msg_Motor must NOT be static constexpr
    # Find the struct body
    start = f.index("struct _Msg_Motor {")
    end = f.index("};", start)
    body = f[start:end]
    assert "static constexpr" not in body


def test_instanced_array_initializer_values():
    f = _generate(_make_instanced_gen())["msg_types.hpp"]
    assert "MessageId(0)" in f
    assert "MessageId(2)" in f
    assert "MessageId(4)" in f


def test_nested_instanced_enum_members():
    f = _generate(_make_nested_instanced_gen())["msg_types.hpp"]
    assert "MOTOR_0__FAULT" in f
    assert "MOTOR_0__SYSTEM__INIT_FAILED" in f
    assert "MOTOR_1__FAULT" in f
    assert "MOTOR_1__SYSTEM__INIT_FAILED" in f


def test_nested_instanced_sub_struct():
    f = _generate(_make_nested_instanced_gen())["msg_types.hpp"]
    assert "struct _Msg_Motor_System" in f
    assert "struct _Msg_Motor" in f


def test_nested_instanced_group_nodes_canonical():
    f = _generate(_make_nested_instanced_gen())["msg_strings.cpp"]
    # "motor" and "system" nodes, not "motor_0"/"motor_1"
    assert '"motor"' in f
    assert '"system"' in f
    assert '"motor_0"' not in f
    assert '"motor_1"' not in f
