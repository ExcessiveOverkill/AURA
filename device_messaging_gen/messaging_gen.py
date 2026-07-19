"""
messaging_gen.py — C++ messaging/logging code generator.

Takes a list of Message and MessageGroup definitions and emits four C++ files:

    <module>_msg_types.hpp    MessageId/MessageSeverity/MsgCommand enums, message
                              value/delay arrays, register interface struct,
                              string function declarations, compile-time ID
                              accessor structs (C++17).

    <module>_msg_strings.cpp  Flash-resident name/desc/group string arrays and
                              accessor function implementations (.rodata, zero RAM).

    <module>_msg.hpp          Messaging class declaration.

    <module>_msg.cpp          Messaging class implementation.

Usage:
    from device_messaging_gen import Message, MessageGroup, MessageSeverity, MessagingGenerator

    system = MessageGroup("system")
    system.add(Message("clock_fault", MessageSeverity.ERROR, desc="Clock failure"))

    power = MessageGroup("power")
    power.add(Message("low_voltage", MessageSeverity.WARNING, delay_us=5000))
    system.add(power)

    gen = MessagingGenerator(
        module_name="drive",
        messages=[
            system,
            Message("watchdog", MessageSeverity.CRITICAL, desc="Watchdog timeout"),
        ]
    )
    gen.generate("output/")

    Instanced groups (count > 1) generate per-instance enum members and a
    constexpr array accessor.  String tables (names/descs) are deduplicated so
    each unique message type is stored only once regardless of instance count.

    Example:
        MessageGroup("motor", [
            Message("fault", MessageSeverity.ERROR),
        ], count=3)

    Generates MOTOR_0__FAULT, MOTOR_1__FAULT, MOTOR_2__FAULT in the enum and
    a static constexpr _Msg_Motor motor[3] = {...} accessor in the root
    struct, accessible as msgs.motor[i].fault.
"""

import copy
import enum
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

from cpp_writer import CppWriter


# ---------------------------------------------------------------------------
# Python data model
# ---------------------------------------------------------------------------

class MessageSeverity(enum.IntEnum):
    NONE     = 0
    MESSAGE  = 1
    WARNING  = 2
    ERROR    = 3
    CRITICAL = 4


@dataclass
class Message:
    name: str
    severity: MessageSeverity
    desc: str = ""
    delay_us: int = 0

    # Assigned during flatten pass
    _id: int = field(default=-1, init=False, repr=False)
    _string_id: int = field(default=-1, init=False, repr=False)  # canonical instance-0 ID
    _group_path: list = field(default_factory=list, init=False, repr=False)
    _group_idx: int = field(default=-1, init=False, repr=False)  # index into group node table


@dataclass
class MessageGroup:
    name: str
    children: list[Union["MessageGroup", Message]] = field(default_factory=list)
    count: int = 1  # > 1 creates an instanced group

    def add(self, item: Union["MessageGroup", Message]) -> "MessageGroup":
        """Add a Message or nested MessageGroup and return self for chaining."""
        if not isinstance(item, (MessageGroup, Message)):
            raise ValueError("Invalid item. Expected Message or MessageGroup")
        if any(child.name == item.name for child in self.children):
            raise ValueError(
                f"Item name '{item.name}' already exists in group '{self.name}'"
            )
        self.children.append(item)
        return self


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class MessagingGenerator:
    def __init__(self, module_name: str, messages: list):
        self.module_name = module_name
        self.messages = messages  # top-level list of Message | MessageGroup
        self._flat: list = []
        self._group_nodes: list = []        # list of (name: str, parent_idx: int)
        self._group_path_to_idx: dict = {}  # tuple(path) -> int
        self._unique_count: int = 0
        self._has_instanced_groups: bool = False
        self._instanced_groups: list = []   # metadata for instanced groups
        self._group_metadata: dict = {}     # tuple(path) -> {base_id, child_count, stride}

    # ------------------------------------------------------------------
    # Naming helpers
    # ------------------------------------------------------------------

    def _pascal(self, name: str) -> str:
        """Convert snake_case or single word to PascalCase."""
        return "".join(w.capitalize() for w in name.split("_"))

    def _enum_member(self, msg: Message) -> str:
        """SYSTEM__POWER__LOW_VOLTAGE style enum member name."""
        parts = [p.upper() for p in msg._group_path] + [msg.name.upper()]
        return "__".join(parts)

    def _struct_type(self, path: list) -> str:
        """Generate C++ struct type name for a group at the given path.

        path=[]              -> _Msg
        path=["system"]      -> _Msg_System
        path=["system","power"] -> _Msg_System_Power
        """
        if not path:
            return "_Msg"
        suffix = "".join(f"_{self._pascal(p)}" for p in path)
        return f"_Msg{suffix}"

    def _id_type(self) -> str:
        return "MessageId"

    def _sev_type(self) -> str:
        return "MessageSeverity"

    def _cmd_type(self) -> str:
        return "MsgCommand"

    def _class_name(self) -> str:
        return "Messaging"

    def _iface_type(self) -> str:
        return "MsgRegIface"

    def _count_macro(self) -> str:
        return "MESSAGE_COUNT"

    def _unique_count_macro(self) -> str:
        return "UNIQUE_MSG_COUNT"

    def _values_name(self) -> str:
        return "message_values"

    def _delays_name(self) -> str:
        return "message_delays"

    def _accessor_name(self) -> str:
        return "msgs"

    def _group_node_type(self) -> str:
        return "GroupNode"

    def _group_count_macro(self) -> str:
        return "GROUP_COUNT"

    def _group_nodes_name(self) -> str:
        return "msg_group_nodes"

    def _group_idx_name(self) -> str:
        return "msg_group_idx"

    # ------------------------------------------------------------------
    # Flatten pass
    # ------------------------------------------------------------------

    def _ensure_group_path(self, path: list) -> int:
        """Return group node index for path, creating nodes as needed. -1 if empty."""
        if not path:
            return -1
        key = tuple(path)
        if key in self._group_path_to_idx:
            return self._group_path_to_idx[key]
        parent_idx = self._ensure_group_path(path[:-1])
        idx = len(self._group_nodes)
        self._group_nodes.append((path[-1], parent_idx))
        self._group_path_to_idx[key] = idx
        return idx

    def _flatten(self):
        self._flat = []
        self._group_nodes = []
        self._group_path_to_idx = {}
        self._has_instanced_groups = False
        self._instanced_groups = []
        self._group_metadata = {}
        self._flatten_items(self.messages, [])
        self._unique_count = sum(1 for m in self._flat if m._string_id == m._id)

    def _flatten_items(self, items: list, path: list, canonical_path: list = None):
        """Flatten items into self._flat.

        path:           enum-naming path (includes instance suffixes like motor_0)
        canonical_path: group-node path (base names only, e.g. motor); defaults to path
        """
        if canonical_path is None:
            canonical_path = path

        for item in items:
            if isinstance(item, MessageGroup):
                if item.count > 1:
                    # Flatten instance 0 using original message objects
                    base = len(self._flat)
                    self._flatten_items(
                        item.children,
                        path + [f"{item.name}_0"],
                        path + [item.name],
                    )
                    stride = len(self._flat) - base
                    canonical_ids = [m._id for m in self._flat[base:base + stride]]

                    # Track group metadata for operator[]
                    child_count = sum(1 for child in item.children if isinstance(child, Message))
                    self._group_metadata[tuple(path + [item.name])] = {
                        "base_id": canonical_ids[0] if canonical_ids else 0,
                        "child_count": child_count,
                        "stride": stride,
                        "count": item.count,
                    }

                    self._instanced_groups.append({
                        "name":          item.name,
                        "count":         item.count,
                        "stride":        stride,
                        "canonical_ids": canonical_ids,
                        "children":      item.children,
                    })
                    self._has_instanced_groups = True

                    # Instances 1..count-1: add copies with offset IDs
                    for inst in range(1, item.count):
                        self._flatten_instanced_walk(
                            item.children,
                            path + [f"{item.name}_{inst}"],
                            path + [item.name],
                            inst, stride, canonical_ids,
                            [0],
                        )
                else:
                    # Non-instanced group: track metadata before recursing
                    base_before = len(self._flat)
                    self._flatten_items(
                        item.children,
                        path + [item.name],
                        canonical_path + [item.name],
                    )
                    base_after = len(self._flat)
                    child_count = sum(1 for child in item.children if isinstance(child, Message))
                    self._group_metadata[tuple(canonical_path + [item.name])] = {
                        "base_id": base_before if base_after > base_before else 0,
                        "child_count": child_count,
                        "stride": base_after - base_before,
                        "count": 1,
                    }
            else:
                item._id = len(self._flat)
                item._string_id = item._id
                item._group_path = path[:]
                item._group_idx = self._ensure_group_path(canonical_path)
                self._flat.append(item)

    def _flatten_instanced_walk(
        self, items, path, canonical_path, inst, stride, canonical_ids, pos
    ):
        """Recursively add message copies for instance `inst` to self._flat.

        pos is a single-element list used as a mutable counter shared across
        the recursive traversal.
        """
        for item in items:
            if isinstance(item, MessageGroup):
                self._flatten_instanced_walk(
                    item.children,
                    path + [item.name],
                    canonical_path + [item.name],
                    inst, stride, canonical_ids,
                    pos,
                )
            else:
                msg = copy.copy(item)
                msg._id = canonical_ids[pos[0]] + inst * stride
                msg._string_id = canonical_ids[pos[0]]
                msg._group_path = path[:]
                msg._group_idx = self._ensure_group_path(canonical_path)
                self._flat.append(msg)
                pos[0] += 1

    # ------------------------------------------------------------------
    # Constexpr struct emission helpers
    # ------------------------------------------------------------------

    def _instanced_row(self, children, canonical_ids, inst, stride, pos):
        """Return (aggregate_init_string, updated_pos) for one instance row."""
        parts = []
        for child in children:
            if isinstance(child, MessageGroup):
                inner, pos = self._instanced_row(
                    child.children, canonical_ids, inst, stride, pos
                )
                parts.append(inner)
            else:
                parts.append(f"{self._id_type()}({canonical_ids[pos] + inst * stride})")
                pos += 1
        return "{ " + ", ".join(parts) + " }", pos

    def _emit_group_structs(
        self, w: CppWriter, items: list, path: list, instanced: bool = False
    ):
        """Post-order traversal: emit child group structs before their parent.

        instanced=True means we are inside an instanced group subtree — members
        are non-static aggregates rather than static constexpr values.
        """
        for item in items:
            if isinstance(item, MessageGroup):
                child_path = path + [item.name]
                is_inst = item.count > 1
                # Children of an instanced group also use non-static members
                self._emit_group_structs(
                    w, item.children, child_path, instanced or is_inst
                )
                type_name = self._struct_type(child_path)
                w.open_struct(type_name)
                for child in item.children:
                    if isinstance(child, MessageGroup):
                        child_type = self._struct_type(child_path + [child.name])
                        if instanced or is_inst:
                            w.line(f"{child_type} {child.name};")
                        else:
                            w.line(f"static constexpr {child_type} {child.name}{{}};")
                    else:
                        if instanced or is_inst:
                            # Value baked into the array initializer — just declare the member
                            w.line(f"{self._id_type()} {child.name};")
                        else:
                            w.line(
                                f"static constexpr {self._id_type()} "
                                f"{child.name} = {self._id_type()}({child._id});"
                            )
                
                # Emit operator[] for runtime indexing (all groups, uniform interface)
                if not (instanced or is_inst):
                    w.blank()
                    view_type = self._struct_type(child_path) + "_View"
                    metadata = self._group_metadata.get(tuple(child_path), {})
                    base_id = metadata.get("base_id", 0)
                    stride = metadata.get("stride", 0)
                    
                    w.line(f"{view_type} operator[](uint8_t idx) const {{")
                    w.indent()
                    w.line(
                        f"return {view_type}{{.base_msg_id = "
                        f"{self._id_type()}(static_cast<uint16_t>({base_id}) + "
                        f"static_cast<uint16_t>(idx) * {stride})}};"
                    )
                    w.dedent()
                    w.line("}")

                
                w.close_struct()
                w.blank()

    def _emit_group_view_structs(self, w: CppWriter, items: list, path: list):
        """Emit view structs for runtime group indexing (pre-order traversal)."""
        for item in items:
            if isinstance(item, MessageGroup):
                child_path = path + [item.name]
                view_type = self._struct_type(child_path) + "_View"
                
                # Emit view struct
                w.open_struct(view_type)
                w.line(f"{self._id_type()} base_msg_id;")
                
                # Emit accessor methods for each direct Message child
                for child in item.children:
                    if isinstance(child, Message):
                        # Find child index in flattened list
                        child_idx = 0
                        for idx, c in enumerate(item.children):
                            if isinstance(c, Message) and c is child:
                                break
                            if isinstance(c, Message):
                                child_idx += 1
                        w.line(
                            f"{self._id_type()} {child.name}() const {{ "
                            f"return {self._id_type()}(static_cast<uint16_t>(base_msg_id) + {child_idx}); }}"
                        )
                
                w.close_struct()
                w.blank()
                
                # Recurse into nested groups
                self._emit_group_view_structs(w, item.children, child_path)

    def _emit_root_struct(self, w: CppWriter):
        root_type = self._struct_type([])
        w.open_struct(root_type)
        for item in self.messages:
            if isinstance(item, MessageGroup):
                child_type = self._struct_type([item.name])
                if item.count > 1:
                    ig = next(
                        ig for ig in self._instanced_groups
                        if ig["name"] == item.name
                    )
                    w.line(
                        f"static constexpr {child_type} "
                        f"{item.name}[{item.count}] = {{"
                    )
                    w.indent()
                    for inst in range(item.count):
                        row, _ = self._instanced_row(
                            ig["children"], ig["canonical_ids"],
                            inst, ig["stride"], 0
                        )
                        w.line(f"{row},")
                    w.dedent()
                    w.line("};")
                else:
                    w.line(f"static constexpr {child_type} {item.name}{{}};")
            else:
                w.line(
                    f"static constexpr {self._id_type()} "
                    f"{item.name} = {self._id_type()}({item._id});"
                )
        w.close_struct()
        w.blank()
        w.line(f"inline constexpr {root_type} {self._accessor_name()}{{}};")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, output_dir: str):
        self._flatten()
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        self._emit_types(out)
        self._emit_strings(out)
        self._emit_header(out)
        self._emit_impl(out)

    # ------------------------------------------------------------------
    # Emit: <mod>_msg_types.hpp
    # ------------------------------------------------------------------

    def _emit_types(self, out: Path):
        fname = out / "msg_types.hpp"
        n = len(self._flat)

        with CppWriter(str(fname), is_header=True) as w:
            w.generated_header("Message types, enums, compile-time ID accessors, register interface.")
            w.pragma_once()
            w.include("cstdint", system=True)
            w.blank()

            # Timestamp HAL macro
            w.separator("Timestamp HAL macro")
            w.comment("Define MSG_GET_TIME_US() before including this file to return a uint64_t")
            w.comment("microsecond timestamp. Falls back to 0 if not defined.")
            w.open_ifndef("MSG_GET_TIME_US")
            w.define("MSG_GET_TIME_US()", "((uint64_t)0)")
            w.close_ifdef("MSG_GET_TIME_US")
            w.blank()

            # Message count constants
            w.separator("Constants")
            w.line(f"constexpr uint16_t {self._count_macro()} = {n};")
            if self._has_instanced_groups:
                w.line(
                    f"constexpr uint16_t {self._unique_count_macro()} = {self._unique_count};"
                )
            w.blank()

            # MessageId enum (flattened, sequential)
            w.separator("MessageId enum")
            w.open_enum_class(self._id_type(), "uint16_t")
            for i, msg in enumerate(self._flat):
                w.enum_value(self._enum_member(msg), msg._id, last=(i == n - 1))
            w.close_enum_class()
            w.blank()

            # MessageSeverity enum
            w.separator("MessageSeverity enum")
            w.open_enum_class(self._sev_type(), "uint8_t")
            levels = [("NONE", 0), ("MESSAGE", 1), ("WARNING", 2), ("ERROR", 3), ("CRITICAL", 4)]
            for i, (name, val) in enumerate(levels):
                w.enum_value(name, val, last=(i == len(levels) - 1))
            w.close_enum_class()
            w.blank()

            # MsgCommand enum
            w.separator("MsgCommand enum")
            w.open_enum_class(self._cmd_type(), "uint16_t")
            commands = [
                ("NONE",                    0),
                ("RESET_SELECTED_TIME",      1),
                ("RESET_SELECTED_PAYLOAD",   2),
                ("RESET_SELECTED_HIT_COUNT", 3),
                ("RESET_SELECTED",           4),
                ("RESET_ALL_TIME",           5),
                ("RESET_ALL_PAYLOAD",        6),
                ("RESET_ALL_HIT_COUNT",      7),
                ("RESET_ALL",                8),
                ("RECALC_SEVERITY",          9),
            ]
            for i, (name, val) in enumerate(commands):
                w.enum_value(name, val, last=(i == len(commands) - 1))
            w.close_enum_class()
            w.blank()

            # Extern declarations
            w.separator("Message value/delay tables (defined in _msg_strings.cpp)")
            w.line(f"extern const uint32_t {self._values_name()}[{self._count_macro()}];")
            w.line(f"extern const uint32_t {self._delays_name()}[{self._count_macro()}];")
            w.blank()

            # Register interface struct
            w.separator("Optional register interface struct")
            w.comment("Pass to set_register_interface() to enable host-accessible messaging.")
            w.open_struct(self._iface_type())
            w.line("uint16_t* count;")
            w.line("uint16_t* active_severity;")
            w.line("uint16_t* cmd;")
            w.line("uint16_t* control;")
            w.line("uint16_t* severity;")
            w.line("uint32_t* time_lower;")
            w.line("uint32_t* time_upper;")
            w.line("uint32_t* payload;")
            w.line("uint16_t* hit_count;")
            w.close_struct()
            w.blank()

            # String function declarations
            w.separator("Flash-resident string accessors (defined in msg_strings.cpp)")
            id_t = self._id_type()
            sev_t = self._sev_type()
            pf = "msg"
            w.line(f"const char* {pf}_get_name({id_t} id);")
            w.line(f"const char* {pf}_get_desc({id_t} id);")
            w.line(f"{sev_t} {pf}_get_severity({id_t} id);")
            w.line(f"const char* severity_label({sev_t} s);")
            w.blank()

            # Group node tree
            w.separator("Group node tree  (compressed hierarchy — one string per segment)")
            w.comment("Each node stores its segment name and parent index (-1 = root level).")
            w.comment("Reconstruct full paths by walking parent links up to -1.")
            w.line(f"constexpr int8_t {self._group_count_macro()} = {len(self._group_nodes)};")
            w.blank()
            w.open_struct(self._group_node_type())
            w.line("const char* name;")
            w.line("int8_t      parent;")
            w.close_struct()
            w.blank()
            if self._group_nodes:
                w.line(
                    f"extern const {self._group_node_type()} "
                    f"{self._group_nodes_name()}[{self._group_count_macro()}];"
                )
            w.line(f"extern const int8_t {self._group_idx_name()}[{self._count_macro()}];")
            w.blank()
            if self._group_nodes:
                w.line(f"int8_t      {pf}_get_group_idx({id_t} id);")
                w.line(f"const char* group_name(int8_t group_idx);")
                w.line(f"int8_t      group_parent(int8_t group_idx);")
                w.blank()

            # Compile-time ID accessor structs
            w.separator("Compile-time ID accessors — C++17 required")
            w.comment("Access message IDs via dot notation at zero runtime cost.")
            if self._has_instanced_groups:
                w.comment(
                    f"Instanced groups: {self._accessor_name()}.motor[i].fault"
                )
            else:
                w.comment(f"Example: {self._accessor_name()}.system.power.low_voltage")
            w.blank()
            
            # Emit view structs for runtime indexing
            self._emit_group_view_structs(w, self.messages, [])
            
            self._emit_group_structs(w, self.messages, [])
            self._emit_root_struct(w)

    # ------------------------------------------------------------------
    # Emit: <mod>_msg_strings.cpp
    # ------------------------------------------------------------------

    def _emit_strings(self, out: Path):
        fname = out / "msg_strings.cpp"

        # Build unique-message list and string-id lookup table (instanced case only)
        unique_msgs = [m for m in self._flat if m._string_id == m._id]
        canon_to_idx = {m._id: i for i, m in enumerate(unique_msgs)}

        with CppWriter(str(fname)) as w:
            w.generated_header("Flash-resident message string tables and accessor functions.")
            w.include("msg_types.hpp")
            w.blank()

            # message_values[] — full size, severity packed in bits 28-31
            w.separator("Message value table  (severity packed in bits 28-31, id in lower bits)")
            w.line(f"const uint32_t {self._values_name()}[{self._count_macro()}] = {{")
            w.indent()
            for msg in self._flat:
                packed = (int(msg.severity) << 28) | msg._id
                w.line(
                    f"0x{packed:08X}u,  "
                    f"// [{msg._id:3}] {self._enum_member(msg)}"
                    f"  severity={msg.severity.name}"
                )
            w.dedent()
            w.line("};")
            w.blank()

            # message_delays[] — full size (not deduplicated; used as direct array by impl)
            w.separator("Persistent-mode debounce delay table (microseconds)")
            w.line(f"const uint32_t {self._delays_name()}[{self._count_macro()}] = {{")
            w.indent()
            for msg in self._flat:
                w.line(f"{msg.delay_us}u,")
            w.dedent()
            w.line("};")
            w.blank()

            # String tables — .rodata, zero RAM
            # When instanced groups exist, deduplicate: only emit one entry per unique type.
            w.separator("String tables (.rodata — zero RAM)")

            if self._has_instanced_groups:
                sz = self._unique_count_macro()
                name_arr = "_msg_names"
                desc_arr = "_msg_descs"

                # String-id indirection array (maps full id -> unique table index)
                w.line(
                    f"static const uint8_t _msg_string_id[{self._count_macro()}] = {{"
                )
                w.indent()
                for msg in self._flat:
                    w.line(
                        f"{canon_to_idx[msg._string_id]},  "
                        f"// {self._enum_member(msg)}"
                    )
                w.dedent()
                w.line("};")
                w.blank()

                w.line(f"static const char* const {name_arr}[{sz}] = {{")
                w.indent()
                for msg in unique_msgs:
                    w.line(f'"{msg.name}",')
                w.dedent()
                w.line("};")
                w.blank()

                w.line(f"static const char* const {desc_arr}[{sz}] = {{")
                w.indent()
                for msg in unique_msgs:
                    w.line(f'"{msg.desc}",')
                w.dedent()
                w.line("};")
                w.blank()
            else:
                name_arr = "_msg_names"
                desc_arr = "_msg_descs"

                w.line(f"static const char* const {name_arr}[{self._count_macro()}] = {{")
                w.indent()
                for msg in self._flat:
                    w.line(f'"{msg.name}",')
                w.dedent()
                w.line("};")
                w.blank()

                w.line(f"static const char* const {desc_arr}[{self._count_macro()}] = {{")
                w.indent()
                for msg in self._flat:
                    w.line(f'"{msg.desc}",')
                w.dedent()
                w.line("};")
                w.blank()

            w.line(f"static const char* const _severity_labels[] = {{")
            w.indent()
            for label in ["none", "message", "warning", "error", "critical"]:
                w.line(f'"{label}",')
            w.dedent()
            w.line("};")
            w.blank()

            # Group node table — one entry per unique segment, no duplicate strings
            w.separator("Group node table  (reverse linked list — walk .parent to reconstruct path)")
            if self._group_nodes:
                gnt = self._group_node_type()
                w.line(f"const {gnt} {self._group_nodes_name()}[{self._group_count_macro()}] = {{")
                w.indent()
                for i, (name, parent) in enumerate(self._group_nodes):
                    w.line(f'{{ "{name}", {parent} }},  // [{i}]')
                w.dedent()
                w.line("};")
                w.blank()

            # Per-message group index
            w.line(f"const int8_t {self._group_idx_name()}[{self._count_macro()}] = {{")
            w.indent()
            for msg in self._flat:
                w.line(f"{msg._group_idx},  // {self._enum_member(msg)}")
            w.dedent()
            w.line("};")
            w.blank()

            # Accessor implementations
            w.separator("Accessor function implementations")
            id_t = self._id_type()
            sev_t = self._sev_type()
            pf = "msg"

            if self._has_instanced_groups:
                sid = "_msg_string_id"
                for fn_name, array in [
                    (f"{pf}_get_name", name_arr),
                    (f"{pf}_get_desc", desc_arr),
                ]:
                    w.open_function(f"const char* {fn_name}({id_t} id)")
                    w.line(f"return {array}[{sid}[uint16_t(id)]];")
                    w.close_function()
                    w.blank()
            else:
                for fn_name, array in [
                    (f"{pf}_get_name", name_arr),
                    (f"{pf}_get_desc", desc_arr),
                ]:
                    w.open_function(f"const char* {fn_name}({id_t} id)")
                    w.line(f"return {array}[uint16_t(id)];")
                    w.close_function()
                    w.blank()

            w.open_function(f"{sev_t} {pf}_get_severity({id_t} id)")
            w.line(f"return {sev_t}({self._values_name()}[uint16_t(id)] >> 28);")
            w.close_function()
            w.blank()

            w.open_function(f"const char* severity_label({sev_t} s)")
            w.line(f"return _severity_labels[uint8_t(s)];")
            w.close_function()
            w.blank()

            if self._group_nodes:
                w.open_function(f"int8_t {pf}_get_group_idx({id_t} id)")
                w.line(f"return {self._group_idx_name()}[uint16_t(id)];")
                w.close_function()
                w.blank()

                w.open_function(f"const char* group_name(int8_t group_idx)")
                w.line(f"return {self._group_nodes_name()}[group_idx].name;")
                w.close_function()
                w.blank()

                w.open_function(f"int8_t group_parent(int8_t group_idx)")
                w.line(f"return {self._group_nodes_name()}[group_idx].parent;")
                w.close_function()


    # ------------------------------------------------------------------
    # Emit: <mod>_msg.hpp
    # ------------------------------------------------------------------

    def _emit_header(self, out: Path):
        fname = out / "msg.hpp"
        cls = self._class_name()
        id_t = self._id_type()
        sev_t = self._sev_type()
        cnt = self._count_macro()

        with CppWriter(str(fname), is_header=True) as w:
            w.generated_header("Messaging class declaration.")
            w.pragma_once()
            w.include("msg_types.hpp")
            w.include("cstdint", system=True)
            w.blank()

            w.open_struct(cls)
            w.blank()

            w.separator("Lifecycle")
            w.line("void init();")
            w.line(f"void set_register_interface(const {self._iface_type()}& iface);")
            w.blank()

            w.separator("Logging")
            w.line(f"{sev_t} add({id_t} id, uint32_t payload = 0);")
            w.line(f"{sev_t} log_persistent_active({id_t} id, uint32_t payload = 0);")
            w.line(f"{sev_t} log_persistent_inactive({id_t} id);")
            w.blank()

            w.separator("Clearing  (no automatic severity recalc — call recalc_severity() explicitly)")
            w.line(f"void clear_time({id_t} id);")
            w.line(f"void clear_payload({id_t} id);")
            w.line(f"void clear_hit_count({id_t} id);")
            w.line(f"void clear({id_t} id);")
            w.line("void clear_all_times();")
            w.line("void clear_all_payloads();")
            w.line("void clear_all_hit_counts();")
            w.line("void clear_all();")
            w.blank()

            w.separator("Severity")
            w.line("void recalc_severity();")
            w.blank()

            w.separator("Queries")
            w.line(f"{sev_t} get_active_severity() const;")
            w.line(f"bool is_active({id_t} id) const;")
            w.line(f"uint64_t get_last_active_time({id_t} id) const;")
            w.line(f"uint32_t get_last_payload({id_t} id) const;")
            w.line(f"uint16_t get_hit_count({id_t} id) const;")
            w.blank()

            w.separator("Register service routine")
            w.line("void comm_update();")
            w.blank()

            w.dedent()
            w.line("private:")
            w.indent()
            w.blank()

            w.line("void _recalc_severity();")
            w.line("void _clear_time(uint16_t idx);")
            w.line("void _clear_payload(uint16_t idx);")
            w.line("void _clear_hit_count(uint16_t idx);")
            w.line("void _clear_one(uint16_t idx);")
            w.blank()

            w.line(f"uint64_t _active_times[{cnt}] = {{}};")
            w.line(f"uint64_t _ok_times[{cnt}] = {{}};")
            w.line(f"uint32_t _payloads[{cnt}] = {{}};")
            w.line(f"uint16_t _hit_counts[{cnt}] = {{}};")
            w.line(f"{sev_t} _active_severity = {sev_t}::NONE;")
            w.blank()
            w.line(f"{self._iface_type()} _regs = {{}};")
            w.line("bool _has_regs = false;")
            w.blank()
            w.close_struct()

    # ------------------------------------------------------------------
    # Emit: <mod>_msg.cpp
    # ------------------------------------------------------------------

    def _emit_impl(self, out: Path):
        fname = out / "msg.cpp"
        cls = self._class_name()
        id_t = self._id_type()
        sev_t = self._sev_type()
        cmd_t = self._cmd_type()
        cnt = self._count_macro()
        vals = self._values_name()
        delays = self._delays_name()

        with CppWriter(str(fname)) as w:
            w.generated_header("Messaging class implementation.")
            w.include("msg.hpp")
            w.include("cstring", system=True)
            w.blank()

            # init
            w.open_function(f"void {cls}::init()")
            w.line("memset(_active_times, 0, sizeof(_active_times));")
            w.line("memset(_ok_times,     0, sizeof(_ok_times));")
            w.line("memset(_payloads,     0, sizeof(_payloads));")
            w.line("memset(_hit_counts,   0, sizeof(_hit_counts));")
            w.line(f"_active_severity = {sev_t}::NONE;")
            w.open_brace("if (_has_regs)")
            w.line(f"*_regs.count           = {cnt};")
            w.line("*_regs.active_severity = 0;")
            w.line("*_regs.cmd             = 0;")
            w.close_brace()
            w.close_function()
            w.blank()

            # set_register_interface
            w.open_function(
                f"void {cls}::set_register_interface(const {self._iface_type()}& iface)"
            )
            w.line("_regs     = iface;")
            w.line("_has_regs = true;")
            w.line(f"*_regs.count           = {cnt};")
            w.line("*_regs.active_severity = uint16_t(_active_severity);")
            w.line("*_regs.cmd             = 0;")
            w.line("*_regs.control         = 0;")
            w.line("*_regs.severity        = 0;")
            w.line("*_regs.time_lower      = 0;")
            w.line("*_regs.time_upper      = 0;")
            w.line("*_regs.payload         = 0;")
            w.line("*_regs.hit_count       = 0;")
            w.close_function()
            w.blank()

            # add
            w.open_function(f"{sev_t} {cls}::add({id_t} id, uint32_t payload)")
            w.line("uint16_t idx        = uint16_t(id);")
            w.line("_active_times[idx]  = MSG_GET_TIME_US();")
            w.line("_payloads[idx]      = payload;")
            w.line("if (_hit_counts[idx] < 0xFFFFu) _hit_counts[idx]++;")
            w.line(f"{sev_t} sev = {sev_t}({vals}[idx] >> 28);")
            w.open_brace("if (sev > _active_severity)")
            w.line("_active_severity = sev;")
            w.line("if (_has_regs) *_regs.active_severity = uint16_t(sev);")
            w.close_brace()
            w.line("return _active_severity;")
            w.close_function()
            w.blank()

            # log_persistent_active
            w.open_function(
                f"{sev_t} {cls}::log_persistent_active({id_t} id, uint32_t payload)"
            )
            w.line("uint16_t idx = uint16_t(id);")
            w.open_brace(f"if (_ok_times[idx] + {delays}[idx] <= MSG_GET_TIME_US())")
            w.line("return add(id, payload);")
            w.close_brace()
            w.line("return _active_severity;")
            w.close_function()
            w.blank()

            # log_persistent_inactive
            w.open_function(f"{sev_t} {cls}::log_persistent_inactive({id_t} id)")
            w.line("_ok_times[uint16_t(id)] = MSG_GET_TIME_US();")
            w.line("return _active_severity;")
            w.close_function()
            w.blank()

            # Private field helpers
            w.open_function(f"void {cls}::_clear_time(uint16_t idx)")
            w.line("_active_times[idx] = 0;")
            w.line("_ok_times[idx]     = MSG_GET_TIME_US();")
            w.close_function()
            w.blank()

            w.open_function(f"void {cls}::_clear_payload(uint16_t idx)")
            w.line("_payloads[idx] = 0;")
            w.close_function()
            w.blank()

            w.open_function(f"void {cls}::_clear_hit_count(uint16_t idx)")
            w.line("_hit_counts[idx] = 0;")
            w.close_function()
            w.blank()

            w.open_function(f"void {cls}::_clear_one(uint16_t idx)")
            w.line("_clear_time(idx);")
            w.line("_clear_payload(idx);")
            w.line("_clear_hit_count(idx);")
            w.close_function()
            w.blank()

            # Public field clears (no auto severity recalc)
            for fn, helper in [
                (f"clear_time",      "_clear_time"),
                (f"clear_payload",   "_clear_payload"),
                (f"clear_hit_count", "_clear_hit_count"),
            ]:
                w.open_function(f"void {cls}::{fn}({id_t} id)")
                w.line(f"{helper}(uint16_t(id));")
                w.close_function()
                w.blank()

            w.open_function(f"void {cls}::clear({id_t} id)")
            w.line("_clear_one(uint16_t(id));")
            w.close_function()
            w.blank()

            # Mass clears
            for fn, helper in [
                ("clear_all_times",      "_clear_time"),
                ("clear_all_payloads",   "_clear_payload"),
                ("clear_all_hit_counts", "_clear_hit_count"),
            ]:
                w.open_function(f"void {cls}::{fn}()")
                w.open_brace(f"for (uint16_t i = 0; i < {cnt}; i++)")
                w.line(f"{helper}(i);")
                w.close_brace()
                w.close_function()
                w.blank()

            w.open_function(f"void {cls}::clear_all()")
            w.open_brace(f"for (uint16_t i = 0; i < {cnt}; i++)")
            w.line("_clear_one(i);")
            w.close_brace()
            w.close_function()
            w.blank()

            # _recalc_severity (private impl)
            w.open_function(f"void {cls}::_recalc_severity()")
            w.line(f"{sev_t} worst = {sev_t}::NONE;")
            w.open_brace(f"for (uint16_t i = 0; i < {cnt}; i++)")
            w.open_brace("if (_active_times[i] > _ok_times[i])")
            w.line(f"{sev_t} s = {sev_t}({vals}[i] >> 28);")
            w.line("if (s > worst) worst = s;")
            w.close_brace()
            w.close_brace()
            w.line("_active_severity = worst;")
            w.line("if (_has_regs) *_regs.active_severity = uint16_t(worst);")
            w.close_function()
            w.blank()

            # recalc_severity (public)
            w.open_function(f"void {cls}::recalc_severity()")
            w.line("_recalc_severity();")
            w.close_function()
            w.blank()

            # Getters
            w.open_function(f"{sev_t} {cls}::get_active_severity() const")
            w.line("return _active_severity;")
            w.close_function()
            w.blank()

            w.open_function(f"bool {cls}::is_active({id_t} id) const")
            w.line("uint16_t idx = uint16_t(id);")
            w.line("return _active_times[idx] > _ok_times[idx];")
            w.close_function()
            w.blank()

            w.open_function(f"uint64_t {cls}::get_last_active_time({id_t} id) const")
            w.line("return _active_times[uint16_t(id)];")
            w.close_function()
            w.blank()

            w.open_function(f"uint32_t {cls}::get_last_payload({id_t} id) const")
            w.line("return _payloads[uint16_t(id)];")
            w.close_function()
            w.blank()

            w.open_function(f"uint16_t {cls}::get_hit_count({id_t} id) const")
            w.line("return _hit_counts[uint16_t(id)];")
            w.close_function()
            w.blank()

            # comm_update — switch over all granular commands
            w.open_function(f"void {cls}::comm_update()")
            w.line("if (!_has_regs) return;")
            w.blank()
            w.line(f"{cmd_t} cmd = {cmd_t}(*_regs.cmd);")
            w.line("uint16_t idx = *_regs.control;")
            w.blank()
            w.open_brace("switch (cmd)")
            w.line(f"case {cmd_t}::NONE: break;")
            w.blank()
            for case, body in [
                (f"RESET_SELECTED_TIME",
                 f"if (idx < {cnt}) _clear_time(idx);"),
                (f"RESET_SELECTED_PAYLOAD",
                 f"if (idx < {cnt}) _clear_payload(idx);"),
                (f"RESET_SELECTED_HIT_COUNT",
                 f"if (idx < {cnt}) _clear_hit_count(idx);"),
                (f"RESET_SELECTED",
                 f"if (idx < {cnt}) _clear_one(idx);"),
            ]:
                w.line(f"case {cmd_t}::{case}:")
                w.indent()
                w.line(body)
                w.line("break;")
                w.dedent()
            w.blank()
            for case, body in [
                ("RESET_ALL_TIME",      "clear_all_times();"),
                ("RESET_ALL_PAYLOAD",   "clear_all_payloads();"),
                ("RESET_ALL_HIT_COUNT", "clear_all_hit_counts();"),
                ("RESET_ALL",           "clear_all();"),
                ("RECALC_SEVERITY",     "_recalc_severity();"),
            ]:
                w.line(f"case {cmd_t}::{case}: {body} break;")
            w.close_brace()
            w.blank()
            w.line(f"if (cmd != {cmd_t}::NONE) *_regs.cmd = 0;")
            w.blank()
            w.open_brace(f"if (idx < {cnt})")
            w.line(f"*_regs.severity   = uint16_t({sev_t}({vals}[idx] >> 28));")
            w.line("*_regs.time_lower = uint32_t(_active_times[idx] & 0xFFFFFFFFu);")
            w.line("*_regs.time_upper = uint32_t(_active_times[idx] >> 32);")
            w.line("*_regs.payload    = _payloads[idx];")
            w.line("*_regs.hit_count  = _hit_counts[idx];")
            w.close_brace()
            w.close_function()


# ---------------------------------------------------------------------------
# Example — regenerates output/ when run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    gen = MessagingGenerator("drive", [
        MessageGroup("system", [
            Message("clock_fault",  MessageSeverity.ERROR,    desc="System clock failure"),
            Message("init_failed",  MessageSeverity.CRITICAL, desc="Initialization sequence failed"),
            MessageGroup("power", [
                Message("low_voltage",  MessageSeverity.WARNING, desc="Supply below threshold", delay_us=5000),
                Message("overvoltage",  MessageSeverity.ERROR,   desc="Supply exceeded limit"),
                Message("overcurrent",  MessageSeverity.ERROR,   desc="Phase current limit exceeded"),
            ]),
        ]),
        MessageGroup("communication", [
            Message("timeout",        MessageSeverity.ERROR,   desc="Host communication timeout"),
            Message("checksum_error", MessageSeverity.WARNING, desc="Packet checksum mismatch"),
        ]),
        Message("watchdog", MessageSeverity.CRITICAL, desc="Watchdog timer expired"),
        Message("hw_fault",  MessageSeverity.CRITICAL, desc="Hardware fault detected"),
    ])

    out = os.path.join(os.path.dirname(__file__), "output")
    gen.generate(out)
    print(f"Generated {len(gen._flat)} messages -> {out}/")
