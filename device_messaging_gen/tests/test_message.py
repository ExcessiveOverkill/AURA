"""Tests for Message, MessageGroup, and MessagingGenerator flatten/naming logic."""

from device_messaging_gen import Message, MessageGroup, MessageSeverity, MessagingGenerator


def _make_gen():
    return MessagingGenerator("drive", [
        MessageGroup("system", [
            Message("clock_fault",  MessageSeverity.ERROR,   desc="Clock failure"),
            Message("init_failed",  MessageSeverity.CRITICAL),
            MessageGroup("power", [
                Message("low_voltage",  MessageSeverity.WARNING, delay_us=5000),
                Message("overvoltage",  MessageSeverity.ERROR),
            ]),
        ]),
        MessageGroup("communication", [
            Message("timeout",         MessageSeverity.ERROR),
            Message("checksum_error",  MessageSeverity.WARNING),
        ]),
        Message("watchdog", MessageSeverity.CRITICAL),
    ])


def test_flatten_count():
    gen = _make_gen()
    gen._flatten()
    assert len(gen._flat) == 7


def test_flatten_ids_sequential():
    gen = _make_gen()
    gen._flatten()
    for i, msg in enumerate(gen._flat):
        assert msg._id == i


def test_flatten_group_paths():
    gen = _make_gen()
    gen._flatten()
    paths = [msg._group_path for msg in gen._flat]
    assert paths[0] == ["system"]
    assert paths[1] == ["system"]
    assert paths[2] == ["system", "power"]
    assert paths[3] == ["system", "power"]
    assert paths[4] == ["communication"]
    assert paths[5] == ["communication"]
    assert paths[6] == []


def test_flatten_order():
    gen = _make_gen()
    gen._flatten()
    names = [msg.name for msg in gen._flat]
    assert names == [
        "clock_fault", "init_failed", "low_voltage",
        "overvoltage", "timeout", "checksum_error", "watchdog",
    ]


def test_enum_member_names():
    gen = _make_gen()
    gen._flatten()
    assert gen._enum_member(gen._flat[0]) == "SYSTEM__CLOCK_FAULT"
    assert gen._enum_member(gen._flat[1]) == "SYSTEM__INIT_FAILED"
    assert gen._enum_member(gen._flat[2]) == "SYSTEM__POWER__LOW_VOLTAGE"
    assert gen._enum_member(gen._flat[3]) == "SYSTEM__POWER__OVERVOLTAGE"
    assert gen._enum_member(gen._flat[4]) == "COMMUNICATION__TIMEOUT"
    assert gen._enum_member(gen._flat[6]) == "WATCHDOG"


def test_packed_values():
    gen = _make_gen()
    gen._flatten()
    # ERROR=3, id=0 → 0x30000000
    assert (int(gen._flat[0].severity) << 28) | gen._flat[0]._id == 0x30000000
    # CRITICAL=4, id=1 → 0x40000001
    assert (int(gen._flat[1].severity) << 28) | gen._flat[1]._id == 0x40000001
    # WARNING=2, id=2 → 0x20000002
    assert (int(gen._flat[2].severity) << 28) | gen._flat[2]._id == 0x20000002


def test_delays():
    gen = _make_gen()
    gen._flatten()
    assert gen._flat[2].delay_us == 5000   # low_voltage
    assert gen._flat[0].delay_us == 0      # clock_fault


def test_struct_type_names():
    gen = _make_gen()
    assert gen._struct_type([])                    == "_DriveMsg"
    assert gen._struct_type(["system"])            == "_DriveMsg_System"
    assert gen._struct_type(["system", "power"])   == "_DriveMsg_System_Power"
    assert gen._struct_type(["communication"])     == "_DriveMsg_Communication"


def test_pascal_conversion():
    gen = _make_gen()
    assert gen._pascal("drive")      == "Drive"
    assert gen._pascal("my_module")  == "MyModule"
    assert gen._pascal("system")     == "System"


def test_naming_helpers():
    gen = _make_gen()
    assert gen._id_type()     == "DriveMessageId"
    assert gen._sev_type()    == "DriveMessageSeverity"
    assert gen._cmd_type()    == "DriveMsgCommand"
    assert gen._class_name()  == "DriveMessaging"
    assert gen._iface_type()  == "DriveMsgRegIface"
    assert gen._count_macro() == "DRIVE_MESSAGE_COUNT"
    assert gen._values_name() == "drive_message_values"
    assert gen._delays_name() == "drive_message_delays"
    assert gen._accessor_name() == "drive_msgs"


def test_top_level_message_no_path():
    gen = _make_gen()
    gen._flatten()
    watchdog = gen._flat[6]
    assert watchdog.name == "watchdog"
    assert watchdog._group_path == []
    assert gen._enum_member(watchdog) == "WATCHDOG"


def test_flatten_is_idempotent():
    gen = _make_gen()
    gen._flatten()
    first_ids = [m._id for m in gen._flat]
    gen._flatten()
    second_ids = [m._id for m in gen._flat]
    assert first_ids == second_ids


def test_group_nodes_built():
    gen = _make_gen()
    gen._flatten()
    # Expect exactly 3 unique group segments: system, power, communication
    assert len(gen._group_nodes) == 3
    names = [n for n, _ in gen._group_nodes]
    assert "system" in names
    assert "power" in names
    assert "communication" in names


def test_group_node_parents():
    gen = _make_gen()
    gen._flatten()
    # "system" and "communication" are root-level, "power" is child of "system"
    node_map = {name: parent for name, parent in gen._group_nodes}
    assert node_map["system"] == -1
    assert node_map["communication"] == -1
    # power's parent is the index of "system"
    system_idx = next(i for i, (n, _) in enumerate(gen._group_nodes) if n == "system")
    assert node_map["power"] == system_idx


def test_group_idx_on_messages():
    gen = _make_gen()
    gen._flatten()
    system_idx = gen._group_path_to_idx[("system",)]
    power_idx  = gen._group_path_to_idx[("system", "power")]
    comm_idx   = gen._group_path_to_idx[("communication",)]
    assert gen._flat[0]._group_idx == system_idx   # clock_fault
    assert gen._flat[1]._group_idx == system_idx   # init_failed
    assert gen._flat[2]._group_idx == power_idx    # low_voltage
    assert gen._flat[3]._group_idx == power_idx    # overvoltage
    assert gen._flat[4]._group_idx == comm_idx     # timeout
    assert gen._flat[5]._group_idx == comm_idx     # checksum_error
    assert gen._flat[6]._group_idx == -1           # watchdog (top-level)


def test_no_duplicate_group_strings():
    gen = _make_gen()
    gen._flatten()
    # Unique strings — none should be a concatenation of others with a dot
    node_names = [n for n, _ in gen._group_nodes]
    for name in node_names:
        assert "." not in name  # segments only, never "system.power"


# ------------------------------------------------------------------
# Instanced groups
# ------------------------------------------------------------------

def _make_instanced_gen():
    """2 messages × 3 motor instances + 1 top-level message = 7 total."""
    return MessagingGenerator("drive", [
        MessageGroup("motor", [
            Message("fault",    MessageSeverity.ERROR),
            Message("overtemp", MessageSeverity.WARNING),
        ], count=3),
        Message("watchdog", MessageSeverity.CRITICAL),
    ])


def _make_nested_instanced_gen():
    """Instanced group with a nested sub-group: 2 messages × 2 instances = 4 total."""
    return MessagingGenerator("drive", [
        MessageGroup("motor", [
            Message("fault", MessageSeverity.ERROR),
            MessageGroup("system", [
                Message("init_failed", MessageSeverity.CRITICAL),
            ]),
        ], count=2),
    ])


def test_instanced_flat_count():
    gen = _make_instanced_gen()
    gen._flatten()
    assert len(gen._flat) == 7  # 3*2 + 1


def test_instanced_sequential_ids():
    gen = _make_instanced_gen()
    gen._flatten()
    for i, msg in enumerate(gen._flat):
        assert msg._id == i


def test_instanced_enum_names():
    gen = _make_instanced_gen()
    gen._flatten()
    names = [gen._enum_member(m) for m in gen._flat]
    assert names[0] == "MOTOR_0__FAULT"
    assert names[1] == "MOTOR_0__OVERTEMP"
    assert names[2] == "MOTOR_1__FAULT"
    assert names[3] == "MOTOR_1__OVERTEMP"
    assert names[4] == "MOTOR_2__FAULT"
    assert names[5] == "MOTOR_2__OVERTEMP"
    assert names[6] == "WATCHDOG"


def test_instanced_string_ids_instance0():
    gen = _make_instanced_gen()
    gen._flatten()
    # Instance 0 messages: string_id == own id
    assert gen._flat[0]._string_id == 0  # fault_0
    assert gen._flat[1]._string_id == 1  # overtemp_0


def test_instanced_string_ids_other_instances():
    gen = _make_instanced_gen()
    gen._flatten()
    # Instance 1 and 2 point back to instance 0
    assert gen._flat[2]._string_id == 0  # fault_1  -> fault_0
    assert gen._flat[3]._string_id == 1  # overtemp_1 -> overtemp_0
    assert gen._flat[4]._string_id == 0  # fault_2  -> fault_0
    assert gen._flat[5]._string_id == 1  # overtemp_2 -> overtemp_0


def test_instanced_non_instanced_string_id():
    gen = _make_instanced_gen()
    gen._flatten()
    assert gen._flat[6]._string_id == 6  # watchdog: canonical


def test_instanced_unique_count():
    gen = _make_instanced_gen()
    gen._flatten()
    assert gen._unique_count == 3  # fault, overtemp, watchdog


def test_instanced_group_nodes_not_duplicated():
    gen = _make_instanced_gen()
    gen._flatten()
    # Only one "motor" group node — not one per instance
    node_names = [n for n, _ in gen._group_nodes]
    assert node_names.count("motor") == 1
    assert len(gen._group_nodes) == 1


def test_instanced_group_idx_all_same():
    gen = _make_instanced_gen()
    gen._flatten()
    motor_idx = gen._group_path_to_idx[("motor",)]
    # All motor messages share the same group index
    for msg in gen._flat[:6]:
        assert msg._group_idx == motor_idx
    # watchdog is top-level
    assert gen._flat[6]._group_idx == -1


def test_instanced_nested_flat_count():
    gen = _make_nested_instanced_gen()
    gen._flatten()
    assert len(gen._flat) == 4  # 2 messages * 2 instances


def test_instanced_nested_enum_names():
    gen = _make_nested_instanced_gen()
    gen._flatten()
    names = [gen._enum_member(m) for m in gen._flat]
    assert "MOTOR_0__FAULT" in names
    assert "MOTOR_0__SYSTEM__INIT_FAILED" in names
    assert "MOTOR_1__FAULT" in names
    assert "MOTOR_1__SYSTEM__INIT_FAILED" in names


def test_instanced_nested_group_nodes():
    gen = _make_nested_instanced_gen()
    gen._flatten()
    # "motor" and "system" nodes — not "motor_0", "motor_1"
    node_names = [n for n, _ in gen._group_nodes]
    assert "motor" in node_names
    assert "system" in node_names
    assert len(gen._group_nodes) == 2
    assert not any("_0" in n or "_1" in n for n in node_names)


def test_instanced_idempotent():
    gen = _make_instanced_gen()
    gen._flatten()
    first_ids = [m._id for m in gen._flat]
    gen._flatten()
    second_ids = [m._id for m in gen._flat]
    assert first_ids == second_ids
