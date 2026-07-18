"""
AURA example: Intro

Run to generate all C++ headers and sources:

    python examples/intro/config.py

Output: examples/intro/generated/
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from aura import (
    AURADevice,
    Register,
    Group,
    Message,
    MessageGroup,
    MessageSeverity,
)

device = AURADevice(
    name="intro",   # Device name, used in generated code and to identify the device on the host.
    word_width=8,  # The device's minimum addressable width (bits). Usually 8.
    compatible_drivers=["aura-intro"],  # Used by the host to identify which driver to load for this device, multiple may be specified.
    desc="Introductory example for AURA",   # Description of the device, used in generated code and documentation.
    interfaces="shell",   # Optional list of interfaces to generate code for, currently supports "shell" for generating a device shell and host shim. Multiple may be specified.
)

rm = device.regmap


# see Register docs for more details on the available options for each field.


# ---------------------------------------------------------------------------
# Top-level registers (not in any group)
# ---------------------------------------------------------------------------

# read/write permissions
# basic read/write uint32 register
rm.add(Register(
    "basic_u32_rw",
    rw="rw",
    type="unsigned",
    width=32,
    desc="basic read/write uint32 register"
))

# read only uint32 register, the device can still read/write, but the host can only read
rm.add(Register(
    "basic_u32_r",
    rw="r",
    type="unsigned",
    width=32,
    desc="basic read-only uint32 register"
))


# min/max/default values can be specified for all variable types, and will be enforced in generated code on the host side only
# each param is independently optional, but if specified together they must be consistent (e.g. default must be between min and max, min must be less than max).
rm.add(Register(
    "u32_with_limits",
    rw="rw",
    type="unsigned",
    width=32,
    desc="uint32 register with min/max/default values",
    min_val=0,
    max_val=100,
    default_val=50,
))


# configurable widths
# for integer types, width can be set to any value above 1, register will take up the minimum aligned number of words required to hold the specified width
# (e.g. a 12-bit register will take up 16 bits, so 2 bytes in an 8-bit word device, and 1 word in a 32-bit word device).
# small uint
rm.add(Register(
    "uint12_rw",
    rw="rw",
    type="unsigned",
    width=4,
    desc="4-bit unsigned integer"
))

# large uint
rm.add(Register(
    "uint64_rw",
    rw="rw",
    type="unsigned",
    width=64,
    desc="64-bit unsigned integer"
))

# custom sized uint
rm.add(Register(
    "uint48_rw",
    rw="rw",
    type="unsigned",
    width=48,
    desc="48-bit unsigned integer"
))


# different variable types
# unsigned
rm.add(Register(
    "uint32_rw",
    rw="rw",
    type="unsigned",
    width=32,
    desc="32-bit unsigned integer"
))

# signed
rm.add(Register(
    "int32_rw",
    rw="rw",
    type="signed",
    width=32,
    desc="32-bit signed integer"
))

# boolean
rm.add(Register(
    "bool_rw",
    rw="rw",
    type="bool",
    width=1,    # bool types must be 1 bit wide, or left at default which will auto-assign to the correct width
    desc="boolean value"
))

# float
rm.add(Register(
    "float_rw",
    rw="rw",
    type="float",
    width=32,   # float types must be 32 bits wide, or left at default which will auto-assign to the correct width
    desc="32-bit floating point value"
))

# double
rm.add(Register(
    "double_rw",
    rw="rw",
    type="double",
    width=64,   # double types must be 64 bits wide, or left at default which will auto-assign to the correct width
    desc="64-bit floating point value"
))

# enums
# if min/max/default is specified for an enum, it applies to the underlying value, but may be specified as the enum string OR value
rm.add(Register(
    "enum_rw",
    rw="rw",
    type="unsigned",    # enums must be unsigned, or left at default which will auto-assign to unsigned
    width=8,    # width must be wide enough to hold all enum values, or left at default which will auto-assign to the correct width
    desc="enumerated type with values RED=0, GREEN=1, BLUE=2",
    enum={"RED": 0, "GREEN": 1, "BLUE": 2},
))

# register banks
# a register with the bank size set above 1 (default) will create an indexable array of that register
# banks are organized as contiguous blocks of registers, each with their own address, registers larger than the word width will be spaced accordingly
# 4x 32-bit, will take 4x 32 bit words on a 32bit word device, will take 16 words on an 8-bit word device since each register takes up 4 words
rm.add(Register(
    "array_of_4_u32",
    rw="rw",
    type="unsigned",
    width=32,
    bank_size=4,
    desc="array of 4 uint32 registers"
))

# 4x 8-bit, will still take 4x 32 bit words on a 32bit word device since each register takes up a full word at minimum, will be packed more efficiently on an 8-bit word device with only 4 bytes total
rm.add(Register(
    "array_of_4_u8",
    rw="rw",
    type="unsigned",
    width=8,
    bank_size=4,
    desc="array of 4 uint8 registers"
))


# register bit fields (sub-registers)
# registers can be broken down into bit fields, which are sub-registers that occupy a portion of the parent register's width, and share the same address as the parent register (for single word registers, multi-word will have more complex addressing but the same concept applies)
# bit fields must be contained within the parent register's width, and cannot overlap with each other, but otherwise can be configured with the same options as a normal register (except bank size and rw permissions, which are not allowed since they share the same address)
# rw permissions will automatically inherit from the parent register, can be left unspecified

# multiple bit fields within a register
rm.add(Register(
    "register_with_bitfields",
    rw="rw",
    type="unsigned",
    width=16,
    desc="Register with multiple bit fields",
    bit_field=[
        Register("field1", type="unsigned", width=4, start_address=0,   # start_address will set the starting bit of the field. if not specified, fields will be packed sequentially
                 desc="4-bit unsigned field starting at bit 0"),
        Register("field2", type="bool", width=1,
                 desc="1-bit boolean field at bit 4"),
        Register("field3", type="unsigned", width=3,
                 desc="3-bit unsigned field starting at bit 5"),
    ],
))


# groups
# groups contain registers or other groups, and are used to organize the registers and allow object-oriented layout
# groups are sized and aligned to the smallest(unless configured otherwise) power-of-2 based on their contents, and can be nested to any depth

# adding a register to a group
group1 = Group("group1", desc="Example group containing two registers")
group1.add(Register(
    "reg1",
    rw="rw",
    type="unsigned",
    width=16,
    desc="16-bit unsigned integer register in group1"
))
group1.add(Register(
    "reg2",
    rw="rw",
    type="float",
    width=32,
    desc="32-bit float register in group1"
))
rm.add(group1)  # dont forget to add the group to the regmap after configuring it

# nested groups
group2 = Group("group2", desc="Example group containing a nested group")
nested_group = Group("nested_group", desc="Nested group inside group2")
nested_group.add(Register(
    "reg3",
    rw="rw",
    type="bool",
    width=1,
    desc="boolean register in nested_group inside group2"
))
group2.add(nested_group)    # add the nested group to the parent group
rm.add(group2)  # then add the parent group to the regmap after

# multiple group instances
# groups can be instantiated multiple times to create multiple instances of the same layout and internal objects, accessed with an index
# group alignment will be a power of 2 large enough to contain the group, so multiple instances will be spaced accordingly to maintain alignment (may result in large gaps between instances)
multiple_groups = Group("multiple_groups", desc="Example group with multiple instances", count=4)   # count specifies how many instances of the group, defaults to 1 if not specified
multiple_groups.add(Register(
    "reg4",
    rw="rw",
    type="unsigned",
    width=8,
    desc="8-bit unsigned integer register in multiple_groups"
))
rm.add(multiple_groups)


# 
# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

drive_msgs = MessageGroup("drive")
drive_msgs.add(Message(
    "fault",
    MessageSeverity.ERROR,
    desc="Drive fault — output disabled",
)).add(Message(
    "overtemp",
    MessageSeverity.WARNING,
    desc="Motor temperature above safe operating limit",
))

comms_msgs = MessageGroup("comms")
comms_msgs.add(Message(
    "timeout",
    MessageSeverity.ERROR,
    desc="Host communication watchdog expired",
))

device.messages.extend([drive_msgs, comms_msgs])

# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "generated")
    device.generate(out)
