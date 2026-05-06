# device_messaging_gen

Optional, standalone module. Generates a C++ messaging/logging library. No compile-time dependency on `device_firmware_gen` — integration at runtime via pointer assignment.

Run `python device_messaging_gen/messaging_gen.py` to regenerate the example output in `device_messaging_gen/output/`.

---

## Python API

```python
from device_messaging_gen import Message, MessageGroup, MessageSeverity, MessagingGenerator

gen = MessagingGenerator(
    module_name="drive",
    messages=[
        MessageGroup("system", [
            Message("clock_fault", MessageSeverity.ERROR, desc="System clock failure"),
            MessageGroup("power", [
                Message("low_voltage", MessageSeverity.WARNING, delay_us=5000),
            ]),
        ]),
        Message("watchdog", MessageSeverity.CRITICAL, desc="Watchdog timeout"),
    ]
)
gen.generate("output/")   # writes 4 files
```

### `Message` fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Snake-case identifier |
| `severity` | `MessageSeverity` | `NONE/INFO/WARNING/ERROR/CRITICAL` |
| `desc` | str | Human-readable description (empty string default) |
| `delay_us` | int | Debounce delay in microseconds for persistent logging |

---

## Generated files

| File | Contents |
|------|---------|
| `<mod>_msg_types.hpp` | `MessageId` enum, `MessageSeverity` enum, `MsgCommand` enum, `MsgRegIface` struct, string accessor declarations, group node tree types, C++17 constexpr accessor structs |
| `<mod>_msg_strings.cpp` | `message_values[]`, `message_delays[]`, name/desc string tables in `.rodata`, compressed group node table, per-message group index array, all accessor function implementations |
| `<mod>_msg.hpp` | `<Mod>Messaging` class declaration |
| `<mod>_msg.cpp` | `<Mod>Messaging` class implementation |

---

## Compile-time ID accessors (C++17)

Messages are accessed via dot notation — resolves to a bare integer constant at compile time:

```cpp
messaging.add(drive_msgs.system.power.low_voltage, measured_voltage);
// expands to: messaging.add(DriveMessageId(2), measured_voltage)
```

---

## `<Mod>Messaging` class interface

```cpp
// Lifecycle
void init();
void set_register_interface(const DriveMsgRegIface& iface);  // optional

// Logging
DriveMessageSeverity add(DriveMessageId id, uint32_t payload = 0);
DriveMessageSeverity log_persistent_active(DriveMessageId id, uint32_t payload = 0);
DriveMessageSeverity log_persistent_inactive(DriveMessageId id);

// Clearing  (no automatic severity recalc)
void clear_time(DriveMessageId id);
void clear_payload(DriveMessageId id);
void clear_hit_count(DriveMessageId id);
void clear(DriveMessageId id);
void clear_all_times();
void clear_all_payloads();
void clear_all_hit_counts();
void clear_all();

// Severity
void recalc_severity();  // explicit; never called automatically

// Queries
DriveMessageSeverity get_active_severity() const;
bool is_active(DriveMessageId id) const;   // true if active_time > ok_time
uint64_t get_last_active_time(DriveMessageId id) const;
uint32_t get_last_payload(DriveMessageId id) const;
uint16_t get_hit_count(DriveMessageId id) const;

// Register service routine (no-op if set_register_interface not called)
void comm_update();
```

---

## Timestamp HAL macro

Define `MSG_GET_TIME_US()` before including the types header to provide a `uint64_t` microsecond timestamp. Falls back to `0` if not defined:

```c
#define MSG_GET_TIME_US() ((uint64_t)TIM2->CNT)  // example
```

---

## Host register interface (9 registers)

Call `set_register_interface()` to enable. `comm_update()` services this block each call:

| Register | Type | Dir | Description |
|----------|------|-----|-------------|
| `msg_count` | u16 | R | Total message count |
| `msg_active_severity` | u16 | R | Live max active severity |
| `msg_cmd` | u16 | R/W | Command (see `MsgCommand` enum) |
| `msg_control` | u16 | R/W | Select message by index |
| `msg_severity` | u16 | R | Static severity of selected message |
| `msg_time_lower` | u32 | R | Last active timestamp [31:0] |
| `msg_time_upper` | u32 | R | Last active timestamp [63:32] |
| `msg_payload` | u32 | R | Payload word at last trigger |
| `msg_hit_count` | u16 | R | Times selected message has fired |

---

## `MsgCommand` enum

| Value | Name | Effect |
|-------|------|--------|
| 0 | `NONE` | — |
| 1 | `RESET_SELECTED_TIME` | Clear timestamp for `msg_control` index |
| 2 | `RESET_SELECTED_PAYLOAD` | Clear payload for `msg_control` index |
| 3 | `RESET_SELECTED_HIT_COUNT` | Clear hit count for `msg_control` index |
| 4 | `RESET_SELECTED` | Clear all fields for `msg_control` index |
| 5 | `RESET_ALL_TIME` | Clear all timestamps |
| 6 | `RESET_ALL_PAYLOAD` | Clear all payloads |
| 7 | `RESET_ALL_HIT_COUNT` | Clear all hit counts |
| 8 | `RESET_ALL` | Clear all fields for all messages |
| 9 | `RECALC_SEVERITY` | Recompute `active_severity` from current state |

---

## Flash-resident string accessors

All string data lives in `.rodata` (zero RAM). Group paths are stored as a compressed node tree — one string per unique segment, no duplicates:

```cpp
const char* drive_msg_get_name(DriveMessageId id);
const char* drive_msg_get_desc(DriveMessageId id);
DriveMessageSeverity drive_msg_get_severity(DriveMessageId id);
const char* drive_severity_label(DriveMessageSeverity s);

// Group tree navigation — walk .parent to reconstruct full path
int8_t      drive_msg_get_group_idx(DriveMessageId id);  // -1 = no group
const char* drive_group_name(int8_t group_idx);
int8_t      drive_group_parent(int8_t group_idx);        // -1 = root level
```

---

## Per-message RAM cost

| Field | Size |
|-------|------|
| `_active_times` | 8 bytes |
| `_ok_times` | 8 bytes |
| `_payloads` | 4 bytes |
| `_hit_counts` | 2 bytes |
| **Total** | **22 bytes/message** |

---

## Internal pipeline (`MessagingGenerator`)

1. `_flatten()` — depth-first walk assigns sequential `MessageId` values; builds `_group_nodes` (compressed segment tree) and sets `_group_idx` on each `Message`.
2. `_ensure_group_path(path)` — lazily creates group nodes with parent linkage, reusing existing nodes to avoid duplicates.
3. `_emit_group_structs()` / `_emit_root_struct()` — post-order traversal emits C++17 constexpr accessor structs (children before parents, no forward declarations needed).
4. `generate(output_dir)` — calls all 4 emit methods.

---

## Test structure

| File | What it tests |
|------|--------------|
| `test_message.py` | Flatten pass, ID assignment, group path tracking, group node tree construction (parents, no duplicate segment strings), naming helpers |
| `test_emit.py` | String-presence checks across all 4 generated files; command enum values; group compression; `is_active` predicate; no-auto-recalc in clear body |
