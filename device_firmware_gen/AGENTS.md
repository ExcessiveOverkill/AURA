# device_firmware_gen

Generates 8 C++ files from a `RegisterMapGenerator` instance. Depends on `register_mapper`.

---

## Usage

```python
from register_mapper import RegisterMapGenerator, Register
from device_firmware_gen import FirmwareGenerator

rm = RegisterMapGenerator("mymod", [], word_width=32)
rm.add(Register("status", rw="r", type="unsigned", width=8))
rm.generate()
gen = FirmwareGenerator(rm)   # raises ValueError if rm.generate() not called
gen.generate("output/")       # writes 8 files
```

---

## Generated files

| File | Contents |
|------|---------|
| `<mod>_reg_types.hpp` | `word_t` typedef, `RegStatus`/`RegAccess` enums, per-register enum classes, critical-section macros |
| `<mod>_reg_storage.hpp` | `RegMap_t` struct definition, `extern RegMap_t regs` |
| `<mod>_reg_storage.cpp` | `RegMap_t regs = {}` (owns all register memory) |
| `<mod>_reg_device.hpp` | Inline `get_*` / `set_*` accessors for every register, bitfield, and bank entry |
| `<mod>_reg_comm.hpp` | `RegInfo`, `RegAddrSlot` structs; `reg_read`/`reg_write`/`reg_reset` declarations |
| `<mod>_reg_comm.cpp` | Flat O(1) address table, multi-word R/W buffers, `reg_read`/`reg_write`/`reg_reset` implementation |
| `<mod>_reg_verify.cpp` | Device-compatible accessor self-test (uses `REG_VERIFY_ASSERT` macro) |
| `<mod>_reg_host.cpp` | Host-only binary protocol shim (stdin/stdout, compile with `-DAURA_HOST_TEST`) |

---

## Binary comm protocol

```
Request:  [CMD:1] [ADDR:2LE] [COUNT:2LE] [DATA: COUNT×word_bytes]
Response: [STATUS:1] [DATA: COUNT×word_bytes]   (data only on reads)
```

Commands: `READ=0x01`, `WRITE=0x02`, `RESET=0x03`, `VERIFY=0x04`

---

## Critical-section macros

The types header emits no-op defaults — override in your platform BSP:

```c
#ifndef MYMOD_REG_ENTER_CRITICAL
#  define MYMOD_REG_ENTER_CRITICAL()
#endif
#ifndef MYMOD_REG_EXIT_CRITICAL
#  define MYMOD_REG_EXIT_CRITICAL()
#endif
```

Example: `#define MYMOD_REG_ENTER_CRITICAL() __disable_irq()`

---

## Multi-word register paths

`reg_read`/`reg_write` have three paths:
1. **Single word** — direct storage access, no buffer.
2. **Full register** (`word_idx == 0 && count == valid_words`) — `memcpy` under critical section, no staging buffer.
3. **Partial** — snapshot/stage into `read_buf`/`write_buf`, commit on final word.

---

## `reg_probe.py` — Python host client

```python
from device_firmware_gen.reg_probe import RegProbe, RegStatus

with RegProbe("/path/to/mymod_reg_host", word_bytes=4) as probe:
    probe.reset()
    status, words = probe.read(0x0000)
    status = probe.write(0x0001, [0xAB])
    ok = probe.verify()
```

`word_bytes` must match `word_width / 8` (1, 2, or 4).

---

## Internal pipeline (`FirmwareGenerator`)

1. `_flatten()` — walks the register map, expands groups/banks, assigns addresses, builds `_elements: List[RegElement]` and `_slots: List[AddrSlot]`.
2. `_build_device_tree()` — reconstructs a hierarchical tree (`DeviceRegNode`, `DeviceGroupNode`) used for device-header generation.
3. `_emit_*()` — one method per output file; all call `CppWriter`.
4. `generate(output_dir)` — calls all 8 emit methods, creates `output_dir` if absent.

### Key internal types

| Type | Description |
|------|-------------|
| `RegElement` | One addressable element (one bank slot × one group instance). Has `.reg`, `.addr`, `.wpr`, `.ancestor_instances` |
| `AddrSlot` | One word-address slot. Has `.elem`, `.word_idx` |
| `DeviceRegNode` | Leaf in device tree. Has `.elem`, `.is_bank`, `.bank_size` |
| `DeviceGroupNode` | Interior node. Has `.name`, `.count`, `.children` |

---

## Test structure

| File | What it tests |
|------|--------------|
| `test_cpp_writer.py` | Every `CppWriter` method in isolation |
| `test_helpers.py` | `FirmwareGenerator` string/naming helpers |
| `test_data_classes.py` | `RegElement`, `AddrSlot`, `DeviceRegNode` properties |
| `test_flatten.py` | Flatten pipeline: element count, slot count, address assignment |
| `test_device_tree.py` | Device tree construction: `DeviceRegNode`, `DeviceGroupNode` |
| `test_emit.py` | String-presence checks across all 8 generated files |
| `test_integration.py` | End-to-end: file creation, correctness, compilation, exhaustive parametrize |
| `test_probe.py` | Behavioral via compiled host binary + `RegProbe`: permissions, round-trip, reset, bank/group isolation, multi-word coherence, accessor verify |

Compilation tests (`TestCompilation`, `test_parametrized_compiles`) and probe tests auto-skip if no `g++`/`clang++` is on PATH.

---

## Adding a new register type

1. Add parsing/validation in `register_mapper/register_mapper.py` (`Register.__init__`, `Register.from_map`).
2. Add C++ type mapping in `device_firmware_gen/firmware_gen.py` (`_cpp_type`, `_word_encode`, `_test_val`).
3. Add a parametrized case to `_cases()` in `test_integration.py`.
4. Add a fixture and emit check in `test_emit.py` if it needs a new output pattern.

---

## Extending the comm protocol

The binary protocol is defined in `_emit_host_shim` (host side) and `_emit_comm_source` (device side). Both use the same `RegStatus` enum values. To add a new command:

1. Add the status/command constant in `_emit_types_header`.
2. Handle it in `_emit_host_shim` (Python dispatch in `_reg_host.cpp`).
3. Add a corresponding method in `reg_probe.py` (`RegProbe` class).
4. Add tests in `test_probe.py`.
