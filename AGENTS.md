# AGENTS.md — AURA Project Guide

**AURA** (Automatic Universal Register Addressing) generates C++ firmware code from Python definitions — both register maps and structured message/logging systems.

---

## Repository Layout

```
AURA/
├── aura/                             # Central integration package
│   ├── __init__.py                   # AURADevice, ProtocolConfig + re-exports
│   ├── device.py                     # AURADevice, ProtocolConfig
│   └── _docs.py                      # Markdown doc generators
│
├── register_mapper/                  # Register map definition library
│   ├── register_mapper.py            # RegisterMapGenerator, Register, Group
│   ├── test.json                     # Real JSON fixture used by integration tests
│   ├── test_enum.json                # JSON fixture with enum registers
│   └── tests/
│
├── device_firmware_gen/              # Register-access C++ code generator
│   ├── firmware_gen.py               # FirmwareGenerator (imports register_mapper)
│   ├── reg_map_decoder.py            # Register map decoder
│   ├── reg_probe.py                  # Python client for the host binary protocol
│   └── tests/
│
├── device_messaging_gen/             # Messaging/logging C++ code generator
│   ├── messaging_gen.py              # MessagingGenerator, Message, MessageGroup, MessageSeverity
│   └── tests/
│
├── cpp_writer.py                     # Shared CppWriter utility (used by both generators)
└── examples/
    └── servo_drive/
        └── config.py                 # Example: AURADevice usage, run to generate output
```

---

## Module docs

- [`register_mapper/AGENTS.md`](register_mapper/AGENTS.md) — data model classes, behaviors, test structure
- [`device_firmware_gen/AGENTS.md`](device_firmware_gen/AGENTS.md) — generated files, binary protocol, internal pipeline, how-to guides
- [`device_messaging_gen/AGENTS.md`](device_messaging_gen/AGENTS.md) — Python API, generated files, Messaging class, register interface, string accessors

---

## Running Tests

Always use the venv:

```bash
# Individual modules
.venv/Scripts/pytest.exe register_mapper/tests/ -v
.venv/Scripts/pytest.exe device_firmware_gen/tests/ -v
.venv/Scripts/pytest.exe device_messaging_gen/tests/ -v

# All at once
.venv/Scripts/pytest.exe register_mapper/tests/ device_firmware_gen/tests/ device_messaging_gen/tests/ -v

# Skip compilation tests (no C++ compiler needed)
.venv/Scripts/pytest.exe device_firmware_gen/tests/ -v -k "not compil"

# Only behavioral probe tests
.venv/Scripts/pytest.exe device_firmware_gen/tests/test_probe.py -v
```

Compilation and probe tests auto-skip if no `g++`/`clang++` is found on PATH.
