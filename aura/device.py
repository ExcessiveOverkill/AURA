import os
from dataclasses import dataclass, field
from pathlib import Path
from datetime import date

from register_mapper import RegisterMapGenerator, Register, Group
from device_firmware_gen import FirmwareGenerator
from device_messaging_gen import MessagingGenerator, Message, MessageGroup, MessageSeverity


@dataclass
class ProtocolConfig:
    """
    Top-level protocol and module configuration.
    Passed to RegisterMapGenerator and embedded in generated docs.
    """
    word_width: int = 32
    compatible_drivers: list = field(default_factory=list)
    desc: str = ""


class AURADevice:
    """
    Central integration class for AURA code generation.

    Usage::

        from aura import AURADevice, Register, Group, Message, MessageGroup, MessageSeverity

        device = AURADevice("my_module", word_width=32, desc="My embedded device")

        device.regmap.add(Register("status", rw="r", type="unsigned", width=8))
        device.regmap.add(Group("motor").add(Register("speed", rw="rw", type="float", width=32)))

        device.messages.append(MessageGroup("faults", [
            Message("overcurrent", MessageSeverity.ERROR, desc="Phase current exceeded limit"),
        ]))

        device.generate("generated/my_module")
    """

    def __init__(
        self,
        name: str,
        word_width: int = 32,
        compatible_drivers: list = [],
        desc: str = "",
    ):
        self.name = name
        self.protocol = ProtocolConfig(
            word_width=word_width,
            compatible_drivers=compatible_drivers,
            desc=desc,
        )
        self.regmap: RegisterMapGenerator = RegisterMapGenerator(
            name,
            compatible_drivers,
            desc=desc,
            word_width=word_width,
        )
        self.messages: list = []

    def generate(self, output_dir: str) -> None:
        """
        Generate all C++ files and docs into output_dir.

        Creates:
            <output_dir>/registers/     — register .hpp/.cpp files
            <output_dir>/messaging/     — messaging .hpp/.cpp files (if messages defined)
            <output_dir>/<name>_aura.hpp — master include
            <output_dir>/docs/          — markdown register map and message tables
        """
        from aura._docs import generate_register_docs, generate_message_docs

        out = Path(output_dir)
        reg_dir = out / "registers"
        msg_dir = out / "messaging"
        doc_dir = out / "docs"

        reg_dir.mkdir(parents=True, exist_ok=True)
        doc_dir.mkdir(parents=True, exist_ok=True)

        # Registers
        self.regmap.generate()
        self.regmap.exportJSON(str(reg_dir / f"{self.name}_regmap.json"))
        FirmwareGenerator(self.regmap).generate(str(reg_dir))

        # Messaging (optional)
        has_messages = bool(self.messages)
        if has_messages:
            msg_dir.mkdir(parents=True, exist_ok=True)
            MessagingGenerator(self.name, self.messages).generate(str(msg_dir))

        # Master include
        _write_master_include(out, self.name, has_messages)

        # Docs
        generate_register_docs(self.regmap, doc_dir)
        if has_messages:
            generate_message_docs(self.name, self.messages, doc_dir)

        print(f"\nAURA: generated '{self.name}' -> {out.resolve()}")
        print(f"  registers/ : {len(list(reg_dir.iterdir()))} files")
        if has_messages:
            print(f"  messaging/ : {len(list(msg_dir.iterdir()))} files")
        print(f"  {self.name}_aura.hpp")
        print(f"  docs/")


def _write_master_include(out: Path, name: str, has_messages: bool) -> None:
    lines = [
        f"// {name}_aura.hpp -- AURA generated master include -- do not edit",
        f"// Re-run config.py to regenerate.  Generated: {date.today()}",
        "#pragma once",
        "",
        "// Registers",
        f'#include "registers/{name}_reg_types.hpp"',
        f'#include "registers/{name}_reg_storage.hpp"',
        f'#include "registers/{name}_reg_device.hpp"',
        f'#include "registers/{name}_reg_comm.hpp"',
        f'#include "registers/{name}_reg_doc.hpp"',
        f'#include "registers/{name}_reg_meta.hpp"',
    ]
    if has_messages:
        lines += [
            "",
            "// Messaging",
            f'#include "messaging/{name}_msg_types.hpp"',
            f'#include "messaging/{name}_msg.hpp"',
        ]
    lines.append("")

    (out / f"{name}_aura.hpp").write_text("\n".join(lines), encoding="utf-8")
