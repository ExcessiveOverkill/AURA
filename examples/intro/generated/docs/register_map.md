# intro Register Map

## Global Settings

| Setting | Value |
|---------|-------|
| Word Width | 8 bit |
| Min Access Words | 1 |
| Compatible Drivers | aura-intro |

---

## Registers

| Address | Name | Type | R/W | Bits | Default | Min | Max | Unit | Description |
|---------|------|------|-----|------|---------|-----|-----|------|-------------|
| 0x0000 | `basic_u32_rw` | unsigned | rw | [31:0] | - | - | - | - | basic read/write uint32 register |
| 0x0004 | `basic_u32_r` | unsigned | r | [31:0] | - | - | - | - | basic read-only uint32 register |
| 0x0008 | `u32_with_limits` | unsigned | rw | [31:0] | 50 | 0 | 100 | - | uint32 register with min/max/default values |
| 0x000C | `uint12_rw` | unsigned | rw | [3:0] | - | - | - | - | 4-bit unsigned integer |
| 0x000D | `bool_rw` | bool | rw | [0:0] | - | - | - | - | boolean value |
| 0x000E | `enum_rw` | unsigned | rw | [7:0] | - | - | - | - | enumerated type with values RED=0, GREEN=1, BLUE=2 |
| 0x0010 | `uint64_rw` | unsigned | rw | [63:0] | - | - | - | - | 64-bit unsigned integer |
| 0x0018 | `uint48_rw` | unsigned | rw | [47:0] | - | - | - | - | 48-bit unsigned integer |
| 0x0020 | `uint32_rw` | unsigned | rw | [31:0] | - | - | - | - | 32-bit unsigned integer |
| 0x0024 | `int32_rw` | signed | rw | [31:0] | - | - | - | - | 32-bit signed integer |
| 0x0028 | `float_rw` | float | rw | [31:0] | - | - | - | - | 32-bit floating point value |
| 0x002C | `array_of_4_u8[0]` | unsigned | rw | [7:0] | - | - | - | - | array of 4 uint8 registers |
| 0x002D | `array_of_4_u8[1]` | unsigned | rw | [7:0] | - | - | - | - | array of 4 uint8 registers |
| 0x002E | `array_of_4_u8[2]` | unsigned | rw | [7:0] | - | - | - | - | array of 4 uint8 registers |
| 0x002F | `array_of_4_u8[3]` | unsigned | rw | [7:0] | - | - | - | - | array of 4 uint8 registers |
| 0x0030 | `double_rw` | double | rw | [63:0] | - | - | - | - | 64-bit floating point value |
| 0x0038 | `array_of_4_u32[0]` | unsigned | rw | [31:0] | - | - | - | - | array of 4 uint32 registers |
| 0x003C | `array_of_4_u32[1]` | unsigned | rw | [31:0] | - | - | - | - | array of 4 uint32 registers |
| 0x0040 | `array_of_4_u32[2]` | unsigned | rw | [31:0] | - | - | - | - | array of 4 uint32 registers |
| 0x0044 | `array_of_4_u32[3]` | unsigned | rw | [31:0] | - | - | - | - | array of 4 uint32 registers |
| 0x0048 | `register_with_bitfields` | unsigned | rw | [15:0] | - | - | - | - | Register with multiple bit fields |
|  | `↳ field1` | unsigned | rw | [3:0] | - | - | - | - | 4-bit unsigned field starting at bit 0 |
|  | `↳ field2` | bool | rw | [4:4] | - | - | - | - | 1-bit boolean field at bit 4 |
|  | `↳ field3` | unsigned | rw | [7:5] | - | - | - | - | 3-bit unsigned field starting at bit 5 |
| 0x0080 | `command_u16_w` | unsigned | w | [15:0] | - | - | - | raw_cmd | write-only command register with fixed address and unit metadata |

**Enum `enum_rw`:**

| Name | Value |
|------|-------|
| `RED` | 0 |
| `GREEN` | 1 |
| `BLUE` | 2 |

#### `group1` — 0x0050–0x0057

> Example group containing two registers

**Alignment:** 8

| Address | Name | Type | R/W | Bits | Default | Min | Max | Unit | Description |
|---------|------|------|-----|------|---------|-----|-----|------|-------------|
| 0x0050 | `reg1` | unsigned | rw | [15:0] | - | - | - | - | 16-bit unsigned integer register in group1 |
| 0x0054 | `reg2` | float | rw | [31:0] | - | - | - | - | 32-bit float register in group1 |

#### `group2` — 0x000F

> Example group containing a nested group

**Alignment:** 1

##### `nested_group` — 0x000F

> Nested group inside group2

**Alignment:** 1

| Address | Name | Type | R/W | Bits | Default | Min | Max | Unit | Description |
|---------|------|------|-----|------|---------|-----|-----|------|-------------|
| 0x000F | `reg3` | bool | rw | [0:0] | - | - | - | - | boolean register in nested_group inside group2 |

#### `multiple_groups` — 0x004A–0x004D

> Example group with multiple instances

**Count:** 4  **Alignment:** 1

| Address | Name | Type | R/W | Bits | Default | Min | Max | Unit | Description |
|---------|------|------|-----|------|---------|-----|-----|------|-------------|
| 0x004A | `reg4` | unsigned | rw | [7:0] | - | - | - | - | 8-bit unsigned integer register in multiple_groups |

#### `aligned_group` — 0x0060–0x007F

> Group with explicit alignment and unit-bearing registers

**Alignment:** 32

| Address | Name | Type | R/W | Bits | Default | Min | Max | Unit | Description |
|---------|------|------|-----|------|---------|-----|-----|------|-------------|
| 0x0060 | `current_limit` | unsigned | rw | [15:0] | 2500 | 0 | 5000 | mA | Current limit with units and explicit group alignment |
| 0x0068 | `energy_wh` | unsigned | rw | [63:0] | 0 | 0 | 1000000 | Wh | Multi-word register with range/default and units |

