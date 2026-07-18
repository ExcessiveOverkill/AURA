# AURA — Automatic Universal Register Addressing

Generate C++ firmware register maps and messaging systems from Python definitions.

## Installation

```bash
pip install git+https://github.com/ExcessiveOverkill/AURA.git
```

## Usage

Create a `config.py` in your project:

```python
from aura import AURADevice, Register, Group, Message, MessageGroup, MessageSeverity

device = AURADevice("my_device", word_width=32, desc="My embedded device")

# Registers
device.regmap.add(Register("status",  rw="r",  type="unsigned", width=8))
device.regmap.add(Register("control", rw="rw", type="unsigned", width=8))

# Optional: register groups
motor = Group("motor")
motor.add(Register("speed",   rw="rw", type="float"))
motor.add(Register("torque",  rw="rw", type="float"))
device.regmap.add(motor)

# Optional: messages/logging
faults = MessageGroup("faults")
faults.add(Message("overcurrent", MessageSeverity.ERROR, desc="Phase current exceeded limit"))
device.messages.append(faults)

device.generate("generated/my_device")
```

Run it:

```bash
python config.py
```

This produces `generated/my_device/` containing:
- `registers/` — C++ register structs, accessors, and binary comm interface
- `messaging/` — C++ message enums and logging class (if messages defined)
- `my_device_aura.hpp` — single master include
- `docs/` — markdown register map and message tables

See `examples/` for complete working examples.
