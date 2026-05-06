"""
Type stubs for the aura package.
Provides full IntelliSense for AURADevice, Register, Group, Message, MessageGroup,
MessageSeverity, and ProtocolConfig when writing device configuration files.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Union
import enum as _enum


# ---------------------------------------------------------------------------
# Register map types
# ---------------------------------------------------------------------------

class Register:
    """
    A single addressable register in the device register map.

    Supported types: ``"unsigned"``, ``"signed"``, ``"bool"``, ``"float"``, ``"double"``

    Examples::

        Register("status", rw="r", type="unsigned", width=8, desc="Drive status flags")

        Register("speed", rw="rw", type="float", width=32,
                 unit="RPM", min_val=-6000.0, max_val=6000.0, default=0.0)

        Register("flags", rw="r", type="unsigned", width=8, bit_field=[
            Register("fault", rw="r", type="bool", width=1, start_address=0),
            Register("ready", rw="r", type="bool", width=1, start_address=1),
        ])
    """

    def __init__(
        self,
        name: str,
        rw: str = "",
        type: str = "unsigned",
        width: Optional[int] = None,
        start_address: Optional[int] = None,
        desc: str = "",
        bank_size: int = 1,
        bit_field: list[Register] = ...,
        enum: dict[str, int] = ...,
        min_val: Optional[float] = None,
        max_val: Optional[float] = None,
        default: Optional[float] = None,
        unit: str = "",
    ) -> None:
        """
        Args:
            name: Register name (used in generated C++ identifiers).
            rw: Access mode — ``"r"`` read-only, ``"w"`` write-only, ``"rw"`` read-write.
            type: Data type — ``"unsigned"``, ``"signed"``, ``"bool"``, ``"float"``, ``"double"``.
            width: Bit width (1–64+). Defaults: bool=1, float=32, double=64, others=32.
            start_address: Fixed address offset. Auto-assigned if ``None``.
            desc: Human-readable description (appears in docs and shell).
            bank_size: Array length. ``1`` = scalar register, ``>1`` = indexed bank.
            bit_field: Sub-registers packed into this register's bits.
                Each sub-register's ``start_address`` is a bit offset within the parent.
            enum: Named values for ``type="unsigned"`` registers, e.g. ``{"OFF": 0, "ON": 1}``.
            min_val: Minimum allowed value (enforced by comm layer on single-word registers).
            max_val: Maximum allowed value.
            default: Reset/default value written by ``reg_reset()``.
            unit: Physical unit string (e.g. ``"RPM"``, ``"degC"``). Shown in docs and shell.
        """
        ...


class Group:
    """
    A named container of ``Register`` and nested ``Group`` objects.

    Groups are allocated as a contiguous aligned block in the address space.
    Set ``count > 1`` to create an array of identical group instances.

    Example::

        motor = Group("motor", desc="Motor setpoints")
        motor.add(Register("speed_cmd", rw="rw", type="float", width=32, unit="RPM"))
        motor.add(Register("torque_cmd", rw="rw", type="float", width=32, unit="Nm"))
    """

    def __init__(
        self,
        name: str,
        count: int = 1,
        start_address: Optional[int] = None,
        desc: str = "",
        alignment: Optional[int] = None,
    ) -> None:
        """
        Args:
            name: Group name (used in generated C++ struct and accessor names).
            count: Number of identical instances. ``>1`` generates an array of structs.
            start_address: Fixed base address offset. Auto-assigned if ``None``.
            desc: Human-readable description.
            alignment: Force alignment to a power-of-2 boundary (in word units).
                Auto-computed from group size if ``None``.
        """
        ...

    def add(self, item: Union[Register, Group]) -> None:
        """
        Add a ``Register`` or nested ``Group`` to this group.

        Args:
            item: A ``Register`` or ``Group`` to add. Names must be unique within the group.
        """
        ...


# ---------------------------------------------------------------------------
# Messaging types
# ---------------------------------------------------------------------------

class MessageSeverity(_enum.IntEnum):
    """Severity level assigned to a ``Message``.

    Used to prioritise fault handling and drive status LED / stop behaviour.
    """
    NONE     = 0
    """No severity — informational only."""
    MESSAGE  = 1
    """Low-priority status message."""
    WARNING  = 2
    """Non-critical warning — system can continue operating."""
    ERROR    = 3
    """Recoverable error — output may be inhibited."""
    CRITICAL = 4
    """Non-recoverable fault — immediate shutdown required."""


class Message:
    """
    A single loggable event in the messaging system.

    Messages are identified at compile time by their position in the definition
    tree, generating a zero-overhead ``MessageId`` enum and dot-notation accessor::

        messaging.add(servo_drive_msgs.thermal.motor_overtemp, payload)

    Example::

        Message("overcurrent", MessageSeverity.ERROR,
                desc="Phase current exceeded hardware limit", delay_us=100)
    """

    def __init__(
        self,
        name: str,
        severity: MessageSeverity,
        desc: str = "",
        delay_us: int = 0,
    ) -> None:
        """
        Args:
            name: Message name (used in generated C++ enum members and docs).
            severity: Fault severity level (``MessageSeverity.WARNING/ERROR/CRITICAL/...``).
            desc: Human-readable description (appears in docs and shell).
            delay_us: Debounce delay in microseconds. The message is only logged after the
                condition has been active for this long. ``0`` = no debounce.
        """
        ...


class MessageGroup:
    """
    A named group of ``Message`` and nested ``MessageGroup`` objects.

    Groups create dot-notation path hierarchy in the generated C++ accessors::

        servo_drive_msgs.thermal.motor_overtemp   # thermal is a MessageGroup

    Set ``count > 1`` for instanced groups (e.g. per-axis faults on multi-axis drives).

    Example::

        MessageGroup("thermal", [
            Message("motor_overtemp",  MessageSeverity.WARNING, desc="..."),
            Message("drive_overtemp",  MessageSeverity.WARNING, desc="..."),
        ])
    """

    def __init__(
        self,
        name: str,
        children: list[Union[Message, MessageGroup]],
        count: int = 1,
    ) -> None:
        """
        Args:
            name: Group name (used in generated C++ accessor struct names).
            children: List of ``Message`` and/or nested ``MessageGroup`` objects.
            count: Number of identical instances. ``>1`` creates an indexed group
                   (e.g. ``servo_drive_msgs.motor[0].fault``).
        """
        ...


# ---------------------------------------------------------------------------
# Register map generator
# ---------------------------------------------------------------------------

class RegisterMapGenerator:
    """Manages the device register map. Use ``.add()`` to populate it."""

    def add(self, item: Union[Register, Group]) -> None:
        """Add a ``Register`` or ``Group`` to the register map."""
        ...


# ---------------------------------------------------------------------------
# Device configuration
# ---------------------------------------------------------------------------

@dataclass
class ProtocolConfig:
    """Top-level protocol and module metadata, set automatically by ``AURADevice``."""
    word_width: int = 32
    """Bus word width in bits (8, 16, or 32). All register addresses are in word units."""
    compatible_drivers: list[str] = field(default_factory=list)
    """Driver compatibility tags embedded in the generated register map."""
    desc: str = ""
    """Module description embedded in the generated register map."""


class AURADevice:
    """
    Central integration class — configure your device here, then call ``.generate()``.

    ``regmap`` is a ``RegisterMapGenerator``; add registers and groups to it.
    ``messages`` is a plain list; append ``Message`` and ``MessageGroup`` objects.
    ``protocol`` holds module-level metadata (word width, driver tags, description).

    Example::

        from aura import AURADevice, Register, Group, Message, MessageGroup, MessageSeverity

        device = AURADevice("servo_drive", word_width=32, desc="3-phase servo controller")

        device.regmap.add(Register("status", rw="r", type="unsigned", width=8))

        motor = Group("motor")
        motor.add(Register("speed_cmd", rw="rw", type="float", width=32, unit="RPM"))
        device.regmap.add(motor)

        device.messages.append(MessageGroup("faults", [
            Message("overcurrent", MessageSeverity.ERROR, delay_us=100),
        ]))

        device.generate("generated/servo_drive")
    """

    name: str
    protocol: ProtocolConfig
    regmap: RegisterMapGenerator
    messages: list[Union[Message, MessageGroup]]

    def __init__(
        self,
        name: str,
        word_width: int = 32,
        compatible_drivers: Optional[list[str]] = None,
        desc: str = "",
    ) -> None:
        """
        Args:
            name: Module name — used as prefix for all generated C++ symbols and filenames.
            word_width: Bus word width in bits. All register addresses are counted in words.
                Must be 8, 16, or 32. Defaults to 32.
            compatible_drivers: Driver compatibility tags embedded in the register map JSON.
            desc: Human-readable module description.
        """
        ...

    def generate(self, output_dir: str) -> None:
        """
        Generate all C++ source files and markdown docs into ``output_dir``.

        Creates the following layout::

            <output_dir>/
              registers/          12 .hpp/.cpp files (types, storage, device, comm, doc, meta)
              messaging/           4 .hpp/.cpp files (only if messages are defined)
              <name>_aura.hpp     master include — add this one include to your firmware
              docs/
                register_map.md   address table for all registers
                messages.md       severity/debounce table for all messages

        Args:
            output_dir: Destination directory. Created if it does not exist.
        """
        ...
