# AURA - Automatic Universal Register Addressing

AURA generates C++ firmware register and messaging code from Python definitions.

## Install

```bash
pip install git+https://github.com/ExcessiveOverkill/AURA.git
```

Upgrade:

```bash
pip install --upgrade --force-reinstall --no-cache-dir git+https://github.com/ExcessiveOverkill/AURA.git
```

## What AURA Generates

From one Python config, AURA emits:

- registers/: register storage, typed accessor functions, comm API, metadata/docs hooks
- messaging/: message IDs, string tables, group views, Messaging runtime class
- aura.hpp: single include for generated modules
- docs/: markdown register and message documentation

## Quick Start (Integrated API)

```python
from aura import (
	AURADevice,
	ProtocolInterface,
	Register,
	Group,
	Message,
	MessageGroup,
	MessageSeverity,
)

device = AURADevice(
	name="drive",
	word_width=32,
	compatible_drivers=["aura-drive"],
	desc="Servo drive controller",
	interfaces=[ProtocolInterface.SHELL],
)

# Top-level registers
device.regmap.add(Register("status", rw="r", type="unsigned", width=16, desc="Status bits"))
device.regmap.add(Register("command", rw="w", type="unsigned", width=16, desc="Command input"))
device.regmap.add(Register("setpoint", rw="rw", type="float", desc="Velocity setpoint"))

# Grouped registers
motor = Group("motor", count=2, desc="Per-motor control")
motor.add(Register("enable", rw="rw", type="bool", desc="Enable output"))
motor.add(Register("current_limit", rw="rw", type="unsigned", width=12, min_val=0, max_val=3000, default_val=1500, unit="mA"))
device.regmap.add(motor)

# Messaging groups
drive_msgs = MessageGroup("drive", count=2)
drive_msgs.add(Message("fault", MessageSeverity.ERROR, desc="Drive fault active"))
drive_msgs.add(Message("overtemp", MessageSeverity.WARNING, desc="Thermal warning", delay_us=50_000))

comms_msgs = MessageGroup("comms")
comms_msgs.add(Message("timeout", MessageSeverity.ERROR, desc="Host comm timeout"))

device.messages.extend([drive_msgs, comms_msgs])

device.generate("generated")
```

Run:

```bash
python config.py
```

## Register Definition Options

Register supports:

- rw: r, w, rw
- type: unsigned, signed, bool, float, double
- width: arbitrary integer/bit width where valid for the type
- bank_size: arrays of registers
- bit_field: sub-register fields packed in a parent register
- enum: named integer values for unsigned types
- min_val, max_val, default_val
- unit
- start_address (optional fixed placement)

Group supports:

- nested groups
- count for instanced groups
- alignment
- start_address

Comprehensive register example:

```python
from aura import Register, Group

# Scalar
r_status = Register("status", rw="r", type="unsigned", width=8)

# Enum register
r_mode = Register(
	"mode",
	rw="rw",
	type="unsigned",
	width=8,
	enum={"IDLE": 0, "RUN": 1, "FAULT": 2},
	default_val="IDLE",
)

# Bit-field register
r_ctrl = Register(
	"control",
	rw="rw",
	type="unsigned",
	width=16,
	bit_field=[
		Register("enable", type="bool"),
		Register("gain", type="unsigned", width=6, start_address=1),
		Register("profile", type="unsigned", width=3, start_address=8),
	],
)

# Banked register
r_samples = Register("samples", rw="rw", type="unsigned", width=16, bank_size=8)

# Multi-word + ranges/defaults
r_energy = Register(
	"energy_wh",
	rw="rw",
	type="unsigned",
	width=64,
	min_val=0,
	max_val=10_000_000,
	default_val=0,
)

# Nested/instanced groups
outer = Group("axis", count=3)
inner = Group("state")
inner.add(Register("position", rw="rw", type="signed", width=32, unit="counts"))
inner.add(Register("velocity", rw="rw", type="signed", width=32, unit="counts_per_s"))
outer.add(inner)
```

## Message Definition Options

Message supports:

- name
- severity: NONE, MESSAGE, WARNING, ERROR, CRITICAL
- desc
- delay_us

MessageGroup supports:

- nesting
- count for instanced message groups

Comprehensive messaging example:

```python
from aura import Message, MessageGroup, MessageSeverity

system = MessageGroup("system")
system.add(Message("boot", MessageSeverity.MESSAGE, desc="Boot complete"))

power = MessageGroup("power")
power.add(Message("low_voltage", MessageSeverity.WARNING, delay_us=20_000, desc="DC bus low"))
power.add(Message("over_voltage", MessageSeverity.ERROR, desc="DC bus high"))
system.add(power)

motor = MessageGroup("motor", count=4)
motor.add(Message("fault", MessageSeverity.ERROR, desc="Motor fault"))
motor.add(Message("overtemp", MessageSeverity.WARNING, desc="Motor temperature high"))
```

## Generation Modes

### 1) Integrated AURADevice (recommended)

Use AURADevice when you want registers + messages + docs + master include in one call.

```python
from aura import AURADevice

device = AURADevice("my_module", word_width=16)
# ... populate device.regmap and device.messages ...
device.generate("generated")
```

### 2) Registers only (standalone pipeline)

```python
from register_mapper import RegisterMapGenerator, Register, Group
from device_firmware_gen import FirmwareGenerator

rm = RegisterMapGenerator("my_module", compatible_drivers=["drv-a"], word_width=32)
rm.add(Register("status", rw="r", type="unsigned", width=8))

g = Group("periph", count=2)
g.add(Register("value", rw="rw", type="unsigned", width=16))
rm.add(g)

rm.generate()
rm.exportJSON("generated/registers/regmap.json")
FirmwareGenerator(rm).generate("generated/registers")
```

### 3) Registers from JSON

```python
from register_mapper import RegisterMapGenerator
from device_firmware_gen import FirmwareGenerator

rm = RegisterMapGenerator.fromJSON("generated/registers/regmap.json")
FirmwareGenerator(rm).generate("generated/registers")
```

### 4) Messages only

```python
from device_messaging_gen import MessagingGenerator, Message, MessageGroup, MessageSeverity

msgs = MessageGroup("comms")
msgs.add(Message("timeout", MessageSeverity.ERROR))

MessagingGenerator("my_module", [msgs]).generate("generated/messaging")
```

## Using Generated C++ Registers

```cpp
#include "generated/aura.hpp"

void app_tick() {
	using namespace Regs;

	// Scalar typed accessor
	set_setpoint(12.5f);
	float sp = get_setpoint();

	// Banked register
	set_samples(3, 1024u);
	uint16_t s3 = get_samples(3);

	// Bit-field accessor
	set_control_enable(true);
	set_control_gain(12u);
	bool en = get_control_enable();

	// Nested group register
	set_axis_state_position(0, 1234);

	// Counted-group direct storage access (instance methods)
	regs.axis[1].state.set_position(5678);

	(void)sp;
	(void)s3;
	(void)en;
}
```

Notes:

- Function names are path-based: group_subgroup_register
- Counted ancestor groups add index parameters in order
- Multi-word registers are exposed as typed get/set where possible

### Object-Oriented Access via Main regs Struct

When you want direct struct traversal instead of generated free-function wrappers, access the storage root at `::Regs::regs`.

```cpp
#include "generated/aura.hpp"

void demo_direct_storage_access() {
	auto& regmap = ::Regs::regs;

	// Scalar field
	regmap.uint12_rw.set(9u);
	uint8_t u12 = regmap.uint12_rw.get();

	// Nested group field
	regmap.group2.nested_group.reg3.set(true);

	// Group register leaf methods
	regmap.group1.reg1.set(static_cast<uint16_t>(777));
	uint16_t reg1_v = regmap.group1.reg1.get();

	// Optional generic helper templates
	set(regmap.group1.reg1, static_cast<uint16_t>(778));
	uint16_t reg1_v2 = get(regmap.group1.reg1);

	// Register bank indexing
	regmap.array_of_4_u32.set(3, 0xA5A5A5A5u);
	uint32_t bank_v = regmap.array_of_4_u32.get(3);

	// Counted-group indexing
	regmap.multiple_groups[1].reg4.set(static_cast<uint8_t>(reg1_v & 0xFFu));
	uint8_t reg4_v = regmap.multiple_groups[1].reg4.get();

	// Nested counted-group style: regs.outer[0].inner[1].leaf.get()

	(void)u12;
	(void)reg1_v2;
	(void)bank_v;
	(void)reg4_v;
}
```

This matches the intro firmware example and shows the current mixed API shape:

- register leaf structs expose `.get()` / `.set(...)`
- banked leaf structs expose `.get(idx)` / `.set(idx, ...)`
- counted groups use `operator[]` for instance selection
- optional generic helpers: `get(node)` and `set(node, value)`

## Using Generated C++ Messaging

```cpp
#include "generated/aura.hpp"

static Messaging g_msgs;

void init_messages() {
	g_msgs.init();
}

void check_faults(bool fault_active) {
	if (fault_active) {
		g_msgs.add(msgs.motor[2].fault(), 0x1234u);
	} else {
		g_msgs.clear(msgs.motor[2].fault());
	}

	g_msgs.recalc_severity();
	MessageSeverity sev = g_msgs.get_active_severity();
	(void)sev;
}
```

ID access styles:

- Compile-time member ID: msgs.comms.timeout
- Runtime indexed view ID: msgs.motor[2].fault()

## Intro Firmware Example

See the complete shell + register + messaging loop in:

- examples/intro/firmware_main.cpp

Build from that directory:

```bash
g++ -std=c++17 -I. firmware_main.cpp \
	generated/registers/reg_storage.cpp \
	generated/registers/reg_comm.cpp \
	generated/registers/reg_doc.cpp \
	generated/registers/reg_shell.cpp \
	generated/messaging/msg.cpp \
	generated/messaging/msg_strings.cpp \
	-o firmware_main
```

## Running Tests (repo)

```bash
.venv/Scripts/pytest.exe register_mapper/tests/ device_firmware_gen/tests/ device_messaging_gen/tests/ -v
```
