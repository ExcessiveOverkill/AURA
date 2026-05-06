"""
Markdown documentation generators for AURA register maps and message tables.
"""
from pathlib import Path


def generate_register_docs(regmap, output_dir: Path) -> None:
    """Write register_map.md from a generated RegisterMapGenerator."""
    map_data = regmap.map
    lines: list[str] = []

    lines += [f"# {regmap.name} Register Map", ""]

    # --- Global settings ---
    drivers = ", ".join(map_data.get("compatible_drivers") or []) or "-"
    lines += [
        "## Global Settings",
        "",
        "| Setting | Value |",
        "|---------|-------|",
        f"| Word Width | {map_data['word_width']} bit |",
        f"| Min Access Words | {map_data.get('min_access_words', 1)} |",
        f"| Compatible Drivers | {drivers} |",
        "",
    ]

    driver_settings = map_data.get("driver_settings") or {}
    if driver_settings:
        lines += [
            "### Driver Settings",
            "",
            "| Key | Value |",
            "|-----|-------|",
        ]
        for k, v in driver_settings.items():
            lines.append(f"| `{k}` | `{v}` |")
        lines.append("")

    lines += ["---", "", "## Registers", ""]

    _render_group(
        map_data["base_group"],
        base_addr=0,
        lines=lines,
        word_width=map_data["word_width"],
        level=3,
        is_root=True,
    )

    (output_dir / "register_map.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _render_group(
    group_map: dict,
    base_addr: int,
    lines: list,
    word_width: int,
    level: int,
    is_root: bool = False,
) -> None:
    abs_addr = base_addr + (group_map.get("address_offset") or 0)
    count = group_map.get("count", 1)
    alignment = group_map.get("alignment") or 0
    desc = group_map.get("description", "") or ""

    if not is_root:
        heading = "#" * min(level, 6)
        if alignment and (count > 1 or alignment > 1):
            end_addr = abs_addr + alignment * count - 1
            addr_range = f"0x{abs_addr:04X}–0x{end_addr:04X}"
        else:
            addr_range = f"0x{abs_addr:04X}"

        lines += [f"{heading} `{group_map['name']}` — {addr_range}", ""]

        if desc:
            lines += [f"> {desc}", ""]

        meta: list[str] = []
        if count > 1:
            meta.append(f"**Count:** {count}")
        if alignment:
            meta.append(f"**Alignment:** {alignment}")
        if meta:
            lines += ["  ".join(meta), ""]

    registers = group_map.get("registers") or {}
    if registers:
        lines += [
            "| Address | Name | Type | R/W | Bits | Default | Min | Max | Unit | Description |",
            "|---------|------|------|-----|------|---------|-----|-----|------|-------------|",
        ]

        enums_to_show: list[tuple[str, dict]] = []
        sorted_regs = sorted(registers.values(), key=lambda r: r.get("address_offset") or 0)

        for reg_map in sorted_regs:
            bank_size = reg_map.get("bank_size", 1)
            words_per = reg_map.get("words_per_register", 1)
            reg_base = abs_addr + (reg_map.get("address_offset") or 0)

            for i in range(bank_size):
                reg_addr = reg_base + i * words_per
                reg_name = f"{reg_map['name']}[{i}]" if bank_size > 1 else reg_map["name"]
                width = reg_map["width"]

                lines.append(_reg_row(
                    addr=f"0x{reg_addr:04X}",
                    name=reg_name,
                    reg=reg_map,
                    bits=f"[{width - 1}:0]",
                ))

                enum = reg_map.get("enum") or {}
                if enum:
                    enums_to_show.append((reg_name, enum))

                bit_fields = reg_map.get("bit_field") or {}
                if bit_fields:
                    sorted_bfs = sorted(
                        bit_fields.values(), key=lambda b: b.get("starting_bit") or 0
                    )
                    for bf in sorted_bfs:
                        bf_start = bf.get("starting_bit") or 0
                        bf_width = bf["width"]
                        lines.append(_reg_row(
                            addr="",
                            name=f"↳ {bf['name']}",
                            reg=bf,
                            bits=f"[{bf_start + bf_width - 1}:{bf_start}]",
                        ))
                        bf_enum = bf.get("enum") or {}
                        if bf_enum:
                            enums_to_show.append((f"{reg_name}.{bf['name']}", bf_enum))

        lines.append("")

        for reg_name, enum in enums_to_show:
            lines += [
                f"**Enum `{reg_name}`:**",
                "",
                "| Name | Value |",
                "|------|-------|",
            ]
            for k, v in sorted(enum.items(), key=lambda x: x[1]):
                lines.append(f"| `{k}` | {v} |")
            lines.append("")

    for sub_map in (group_map.get("groups") or {}).values():
        _render_group(
            sub_map,
            base_addr=abs_addr,
            lines=lines,
            word_width=word_width,
            level=level + 1,
            is_root=False,
        )


def _reg_row(addr: str, name: str, reg: dict, bits: str) -> str:
    default = reg.get("default")
    min_v = reg.get("min")
    max_v = reg.get("max")
    return (
        f"| {addr} | `{name}` | {reg['type']} | {reg['rw']} | {bits}"
        f" | {default if default is not None else '-'}"
        f" | {min_v if min_v is not None else '-'}"
        f" | {max_v if max_v is not None else '-'}"
        f" | {reg.get('unit') or '-'}"
        f" | {reg.get('description') or '-'} |"
    )


def generate_message_docs(module_name: str, messages: list, output_dir: Path) -> None:
    """Write messages.md from a list of Message / MessageGroup objects."""
    rows: list = []
    _walk_messages(messages, path="", id_counter=[0], rows=rows)

    lines = [
        f"# {module_name} Messages",
        "",
        f"Total messages: {len(rows)}",
        "",
        "| ID | Path | Severity | Debounce | Description |",
        "|----|------|----------|----------|-------------|",
    ]
    for r in rows:
        debounce = f"{r['delay_us']} us" if r["delay_us"] else "-"
        lines.append(
            f"| {r['id']} | `{r['path']}` | {r['severity']} "
            f"| {debounce} | {r['desc']} |"
        )

    (output_dir / "messages.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _walk_messages(items: list, path: str, id_counter: list, rows: list) -> None:
    from aura.device import Message, MessageGroup

    for item in items:
        if isinstance(item, Message):
            full_path = f"{path}.{item.name}" if path else item.name
            rows.append({
                "id":       id_counter[0],
                "path":     full_path,
                "severity": item.severity.name,
                "delay_us": item.delay_us,
                "desc":     item.desc,
            })
            id_counter[0] += 1
        elif isinstance(item, MessageGroup):
            group_path = f"{path}.{item.name}" if path else item.name
            for _ in range(item.count):
                _walk_messages(item.children, group_path, id_counter, rows)
