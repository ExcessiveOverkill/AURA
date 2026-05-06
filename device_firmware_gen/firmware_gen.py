"""
firmware_gen.py — C++ firmware register-access code generator.

Takes a RegisterMapGenerator (which can be loaded from a JSON map file) and
emits six C++ files that together provide:
  - Device-side struct layout and typed inline accessors (zero overhead).
  - A binary comm interface with an O(1) flat address table for reading and
    writing registers word-by-word or in bulk from a host over any protocol.

Generated files:
    <module>_reg_types.hpp    word_t typedef, RegStatus/RegAccess enums,
                              per-register enum classes.
    <module>_reg_storage.hpp  Device-side C++ struct definitions and
                              'extern RegMap_t regs' declaration.
    <module>_reg_storage.cpp  Single translation unit that owns all register
                              memory — 'RegMap_t regs = {}' (zero-init).
    <module>_reg_device.hpp   Inline getters/setters for every register,
                              bit-field, and bank element.
    <module>_reg_comm.hpp     RegInfo / RegAddrSlot structs and comm function
                              declarations.
    <module>_reg_comm.cpp     Flat address table, read/write buffers for
                              multi-word registers, reg_read/write/reset impl.

Usage:
    from device_firmware_gen import FirmwareGenerator
    from register_mapper import RegisterMapGenerator

    rm = RegisterMapGenerator.fromJSON("module.json")
    gen = FirmwareGenerator(rm)
    gen.generate("output/")
"""

import math
import os
from dataclasses import dataclass
from typing import Any, List, Tuple

from register_mapper import Group, Register, RegisterMapGenerator
from cpp_writer import CppWriter


# ---------------------------------------------------------------------------
# Internal data model — built during the flattening pass
# ---------------------------------------------------------------------------


@dataclass
class RegElement:
    """
    One unique addressable register element: a specific bank entry within a
    specific combination of enclosing group instances.

    Every element maps to one RegInfo entry in the generated comm table.
    Multi-word elements additionally get read/write buffer arrays.
    """

    reg: Any                            # Register object from register-mapper
    bank_idx: int                       # index into the bank; 0 when bank_size == 1
    ancestor_instances: List[Tuple]     # [(group_name, group_count, inst_idx), ...]
    base_address: int                   # absolute word address of this element's word[0]
    words_per_reg: int                  # total words allocated (power-of-2 padded)
    valid_words: int                    # ceil(width / word_width) — words that carry data
    last_word_used_bits: int            # width % word_width; 0 = last word is fully used
    min_access_words: int = 1           # from map settings; hardware can atomically access this many words

    @property
    def is_multi_word(self) -> bool:
        return self.words_per_reg > 1

    @property
    def needs_buffers(self) -> bool:
        """Registers larger than the hardware's minimum atomic access width need buffers."""
        return self.words_per_reg > self.min_access_words

    @property
    def qualified_name(self) -> str:
        """Underscore-joined path from the outermost group down to the register name."""
        parts = [name for name, *_ in self.ancestor_instances]
        parts.append(self.reg.name)
        return "_".join(parts)


@dataclass
class AddrSlot:
    """
    One entry in the flat word-addressed comm table.

    Every word of every register element gets its own slot.  Unoccupied
    addresses (alignment gaps between registers) are represented by a null
    slot (element = None) in the generated C++ table.
    """

    element: RegElement
    word_idx: int       # 0 = base word of the element; >0 = subsequent word


# ---------------------------------------------------------------------------
# Device-side struct tree — mirrors the C++ struct hierarchy (not expanded)
# ---------------------------------------------------------------------------


@dataclass
class DeviceRegNode:
    """A register or bank leaf in the device struct tree."""

    name: str
    reg: Any        # Register object
    is_bank: bool
    bank_size: int


@dataclass
class DeviceGroupNode:
    """A group node, with optional count > 1, containing registers and sub-groups."""

    name: str
    count: int
    alignment: int
    children: List[Any]     # DeviceRegNode | DeviceGroupNode


# ---------------------------------------------------------------------------
# Doc / meta data model — built during _build_doc_data()
# ---------------------------------------------------------------------------


@dataclass
class DocGroupNode:
    """One group in the logical hierarchy (not expanded by instance)."""
    name: str
    desc: str
    parent: int          # -1 = direct child of base_group
    count: int           # instance count
    base_address: int    # absolute word address of instance[0]
    alignment: int       # word stride per instance
    address_offset: int  # word offset from parent group base (= start_address for reconstruction)


@dataclass
class DocEntry:
    """One logical register (not expanded by group instance or bank)."""
    name: str
    desc: str
    unit: str
    type: str            # "unsigned", "signed", "bool", "float", "double"
    rw: str              # "r", "w", "rw"
    width: int           # bit width
    words_per_reg: int   # padded word count
    bank_size: int
    has_range: bool
    min_val: int         # word_t bit-pattern (0 if not applicable)
    max_val: int
    has_default: bool
    default_val: int     # word_t bit-pattern (0 if not applicable)
    group_node: int      # index into DocGroupNode list; -1 = root
    offset_in_group: int # word offset from immediate parent group base_address[instance=0]
    enum_start: int      # index into flat enum list
    enum_count: int
    bf_start: int        # index into flat bit-field list
    bf_count: int


@dataclass
class DocBitField:
    """One bit-field sub-register."""
    name: str
    desc: str
    starting_bit: int
    width: int
    type: str
    rw: str
    enum_start: int
    enum_count: int


@dataclass
class DocEnum:
    """One enum value entry."""
    name: str
    value: int


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class FirmwareGenerator:
    """
    Drives the full code-generation pipeline from a RegisterMapGenerator to
    six C++ output files.  Instantiate once per register map and call generate().
    """

    # Supported word widths → C++ stdint type
    _WORD_TYPES = {8: "uint8_t", 16: "uint16_t", 32: "uint32_t", 64: "uint64_t"}

    def __init__(self, reg_map: RegisterMapGenerator, interfaces=frozenset()):
        if not reg_map.generated:
            raise ValueError("RegisterMapGenerator.generate() must be called before use.")

        self._reg_map = reg_map
        # Accept a single string/enum value or any iterable; normalise to frozenset of strings.
        if isinstance(interfaces, str):
            interfaces = frozenset({interfaces})
        else:
            try:
                interfaces = frozenset(
                    i.value if hasattr(i, "value") else i for i in interfaces
                )
            except TypeError:
                interfaces = frozenset({interfaces.value if hasattr(interfaces, "value") else interfaces})
        self._interfaces: frozenset = interfaces
        self._module_name = (
            reg_map.name.lower().replace(" ", "_").replace("-", "_")
        )
        self._word_width: int = reg_map.word_width
        self._word_type: str = self._WORD_TYPES.get(reg_map.word_width, "uint32_t")
        self._min_access_words: int = reg_map.map.get("min_access_words", 1)

        # Populated by _flatten()
        self._elements: List[RegElement] = []
        self._slots: dict = {}          # int(address) → AddrSlot
        self._max_address: int = 0
        self._max_words_per_reg: int = 1

        # Populated by _build_device_tree()
        self._device_tree: List = []    # top-level DeviceRegNode / DeviceGroupNode

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, output_dir: str):
        """Write core register files to output_dir.

        Always emits 6 core files: reg_types.hpp, reg_storage.hpp/.cpp,
        reg_device.hpp, reg_comm.hpp/.cpp.

        With "shell" in interfaces, additionally emits 6 shell files
        (reg_verify.cpp, reg_host.cpp, reg_doc.hpp/.cpp, reg_meta.hpp/.cpp)
        and copies the 3 static device-shell support files into output_dir.
        """
        os.makedirs(output_dir, exist_ok=True)

        self._flatten()
        self._build_device_tree()

        self._emit_types_header(output_dir)
        self._emit_storage_header(output_dir)
        self._emit_storage_source(output_dir)
        self._emit_device_header(output_dir)
        self._emit_comm_header(output_dir)
        self._emit_comm_source(output_dir)

        if "shell" in self._interfaces:
            self._emit_accessor_verify(output_dir)
            self._emit_host_shim(output_dir)
            self._emit_reg_doc_header(output_dir)
            self._emit_reg_doc_source(output_dir)
            self._emit_reg_meta_header(output_dir)
            self._emit_reg_meta_source(output_dir)
            self._copy_shell_static_files(output_dir)

    # ------------------------------------------------------------------
    # Flattening — walk the group tree, build elements + address slots
    # ------------------------------------------------------------------

    def _copy_shell_static_files(self, output_dir: str):
        import shutil
        shell_src = os.path.join(os.path.dirname(__file__), "..", "device-shell")
        for fname in ("reg_shell.hpp", "reg_shell.cpp", "reg_doc_types.hpp"):
            shutil.copy2(os.path.join(shell_src, fname), os.path.join(output_dir, fname))

    def _flatten(self):
        """
        Walk the full register map tree and produce:
          self._elements  — list of RegElement, sorted by base_address
          self._slots     — dict mapping every occupied word address to its AddrSlot
          self._max_address, self._max_words_per_reg
        """
        # base_group is always count=1 starting at address 0
        self._walk_group(
            group=self._reg_map.base_group,
            inst_base=0,
            ancestor_instances=[],
        )
        self._elements.sort(key=lambda e: e.base_address)
        if self._slots:
            self._max_address = max(self._slots)

    def _walk_group(
        self,
        group: Group,
        inst_base: int,
        ancestor_instances: List[Tuple],
    ):
        """
        Recursively walk one group instance, expanding all contained items.

        inst_base             — absolute word address of this instance's start
        ancestor_instances    — [(group_name, group_count, instance_idx), ...]
                                accumulated from the outermost group inward
        """
        for item in group.contents.values():
            if isinstance(item, Register):
                self._process_register(item, inst_base, ancestor_instances)

            elif isinstance(item, Group):
                # Offset of this sub-group within its parent group
                sub_rel = item.map["address_offset"]
                # Absolute base address of sub-group instance 0
                sub_base = inst_base + sub_rel

                for inst_idx in range(item.count):
                    sub_inst_base = sub_base + inst_idx * item.alignment
                    self._walk_group(
                        group=item,
                        inst_base=sub_inst_base,
                        ancestor_instances=ancestor_instances
                        + [(item.name, item.count, inst_idx)],
                    )

    def _process_register(
        self,
        reg: Register,
        group_inst_base: int,
        ancestor_instances: List[Tuple],
    ):
        """
        Create a RegElement and one AddrSlot per word for each bank entry of
        a register.  Raises on address collisions (overlapping registers).
        """
        reg_abs_base = group_inst_base + reg.map["address_offset"]
        valid_words = math.ceil(reg.width / self._word_width)

        for bank_idx in range(reg.bank_size):
            bank_abs_base = reg_abs_base + bank_idx * reg.words_per_register

            elem = RegElement(
                reg=reg,
                bank_idx=bank_idx,
                ancestor_instances=ancestor_instances,
                base_address=bank_abs_base,
                words_per_reg=reg.words_per_register,
                valid_words=valid_words,
                last_word_used_bits=reg.width % self._word_width,
                min_access_words=self._min_access_words,
            )
            self._elements.append(elem)
            self._max_words_per_reg = max(
                self._max_words_per_reg, reg.words_per_register
            )

            # One slot per valid data word; padding beyond valid_words is a gap (nullptr).
            for word_idx in range(valid_words):
                abs_addr = bank_abs_base + word_idx
                if abs_addr in self._slots:
                    existing = self._slots[abs_addr].element.qualified_name
                    raise ValueError(
                        f"Address collision at 0x{abs_addr:X}: "
                        f"'{elem.qualified_name}' overlaps '{existing}'"
                    )
                self._slots[abs_addr] = AddrSlot(element=elem, word_idx=word_idx)

    # ------------------------------------------------------------------
    # Device tree — mirrors the C++ struct hierarchy (groups not expanded)
    # ------------------------------------------------------------------

    def _build_device_tree(self):
        """Build the DeviceNode tree from base_group, used for struct generation."""
        self._device_tree = self._group_children(self._reg_map.base_group)

    def _group_children(self, group: Group) -> List:
        """Return a list of DeviceRegNode / DeviceGroupNode for a group's contents."""
        nodes = []
        for item in group.contents.values():
            if isinstance(item, Register):
                nodes.append(
                    DeviceRegNode(
                        name=item.name,
                        reg=item,
                        is_bank=(item.bank_size > 1),
                        bank_size=item.bank_size,
                    )
                )
            elif isinstance(item, Group):
                nodes.append(
                    DeviceGroupNode(
                        name=item.name,
                        count=item.count,
                        alignment=item.alignment,
                        children=self._group_children(item),
                    )
                )
        return nodes

    # ------------------------------------------------------------------
    # File emission — basic file structure (content is TODO)
    # ------------------------------------------------------------------

    def _emit_types_header(self, output_dir: str):
        """
        <module>_reg_types.hpp

        word_t typedef, RegStatus / RegAccess enums, per-register enum classes.
        No other headers depend on this file, so it can be included anywhere
        without pulling in the full register layout.
        """
        big_endian_macro = f"{self._prefix().upper()}_REG_BIG_ENDIAN"

        with CppWriter(self._filepath(output_dir, "reg_types.hpp"), is_header=True) as w:
            w.generated_header("word_t typedef, RegStatus/RegAccess enums, per-register enum classes")
            w.pragma_once()
            w.include("cstdint", system=True)
            w.blank()

            # Endianness detection — preprocessor macro, intentionally outside the
            # namespace so it is usable in non-namespaced contexts (e.g. ISRs, C files).
            # Falls back to little-endian if the toolchain doesn't expose __BYTE_ORDER__.
            # Critical-section hooks — user overrides these for their platform
            # (e.g. __disable_irq()/__enable_irq() on bare-metal ARM, or
            # taskENTER_CRITICAL()/taskEXIT_CRITICAL() on FreeRTOS).
            # They wrap only the snapshot/commit copies in reg_read/reg_write.
            critical_enter = f"{self._prefix().upper()}_REG_ENTER_CRITICAL"
            critical_exit  = f"{self._prefix().upper()}_REG_EXIT_CRITICAL"
            w.separator("Critical-section hooks (user-overridable)")
            w.line(f"#ifndef {critical_enter}")
            w.line(f"#  define {critical_enter}()")
            w.line(f"#endif")
            w.line(f"#ifndef {critical_exit}")
            w.line(f"#  define {critical_exit}()")
            w.line(f"#endif")
            w.blank()

            w.separator("Endianness")
            w.line(f"#if defined(__BYTE_ORDER__) && (__BYTE_ORDER__ == __ORDER_BIG_ENDIAN__)")
            w.line(f"#  define {big_endian_macro} 1")
            w.line(f"#elif defined(__BIG_ENDIAN__) || defined(__ARMEB__) || defined(__MIPSEB__)")
            w.line(f"#  define {big_endian_macro} 1")
            w.line(f"#else")
            w.line(f"#  define {big_endian_macro} 0")
            w.line(f"#endif")
            w.blank()

            w.open_namespace(self._ns())
            w.blank()

            # word_t — smallest addressable unit; all register addresses are in
            # units of this type.
            w.separator("Word type")
            w.line(f"// Smallest addressable unit: {self._word_width} bits.")
            w.line(f"using word_t = {self._word_type};")
            w.blank()

            # RegStatus — returned by every comm function.
            # RegAccess — stored in the address table to enforce r/w permissions.
            w.separator("Comm status and access codes")
            w.open_enum_class("RegStatus", "uint8_t")
            w.enum_value("OK",                          0,                    comment="operation succeeded")
            w.enum_value("OK_ATOMIC_BUFFERED",          1,                    comment="operation succeeded, but is using buffered data")
            w.enum_value("OK_ATOMIC_UPDATED",           2,                    comment="operation succeeded, buffer synced with true register value")
            w.enum_value("BAD_ADDRESS_OUT_OF_RANGE",    3,                    comment="address is outside the range of defined registers")
            w.enum_value("BAD_ADDRESS",                 4,                    comment="no register at this word address")
            w.enum_value("BAD_ACCESS_READ_ONLY",        5,                    comment="write to read only register")
            w.enum_value("BAD_ACCESS_WRITE_ONLY",       6,                    comment="read from write only register")
            w.enum_value("BITS_ABOVE_WIDTH",            7,                    comment="write value has bits set above valid register width")
            w.enum_value("REGISTER_OVERFLOW",           8,                    comment="count extends past end of this register")
            w.enum_value("OUT_OF_RANGE",                9,                    comment="write value outside declared [min, max] range")
            w.enum_value("BAD_RETURN",                 10, last=True,         comment="should never be returned unless the code is broken")
            w.close_enum_class()
            w.blank()

            w.open_enum_class("RegAccess", "uint8_t")
            w.enum_value("READ",       0)
            w.enum_value("WRITE",      1)
            w.enum_value("READ_WRITE", 2, last=True)
            w.close_enum_class()
            w.blank()

            # One enum class per register that has named enum values.
            # Underlying type is word_t so casts to/from register storage are lossless.
            w.separator("Per-register enums")
            seen_reg_ids: set = set()
            has_any = False

            for elem in self._elements:
                reg = elem.reg
                if id(reg) in seen_reg_ids:
                    continue
                seen_reg_ids.add(id(reg))
                if not reg.enum:
                    continue

                has_any = True

                # Name: group path without instance indices + register name + _e.
                # Instance indices are omitted because all instances share the same
                # register definition and therefore the same enum values.
                path_parts = [name for name, *_ in elem.ancestor_instances]
                path_parts.append(reg.name)
                enum_name = "_".join(path_parts) + "_e"

                w.comment(f"'{'/'.join(path_parts)}' — {reg.width}-bit unsigned")
                w.open_enum_class(enum_name, "word_t")
                items = list(reg.enum.items())
                for i, (val_name, val) in enumerate(items):
                    w.enum_value(val_name.upper(), val, last=(i == len(items) - 1))
                w.close_enum_class()
                w.blank()

            if not has_any:
                w.comment("No registers with enum entries in this map.")
                w.blank()

            w.close_namespace(self._ns())

    def _emit_storage_header(self, output_dir: str):
        """
        <module>_reg_storage.hpp

        C++ struct definitions for every register, bank, and group, composed
        into a top-level RegMap_t.  The single extern 'regs' variable is
        declared here and defined in _reg_storage.cpp.
        """
        with CppWriter(self._filepath(output_dir, "reg_storage.hpp"), is_header=True) as w:
            w.generated_header("device-side register storage — struct layout and extern regs declaration")
            w.pragma_once()
            w.include(f"{self._prefix()}_reg_types.hpp")
            w.blank()

            w.open_namespace(self._ns())
            w.blank()

            # Struct types — depth-first so inner types are always declared
            # before the outer structs that reference them.
            w.separator("Register and group struct types")
            self._emit_struct_types(w, self._device_tree, [])

            # All top-level members collected into one map struct.
            w.separator("Top-level register map")
            w.open_struct("RegMap_t")
            # Pre-compute column widths for aligned member declarations.
            decl_width = max(
                len(f"{self._struct_type(n.name)} {n.name};")
                for n in self._device_tree
            )
            for node in self._device_tree:
                type_name = self._struct_type(node.name)
                addr = self._reg_map.base_group.contents[node.name].map["address_offset"]
                decl = f"{type_name} {node.name};"
                w.line(f"{decl:<{decl_width}}  // 0x{addr:04X}")
            w.close_struct()
            w.blank()

            w.comment("Single static instance — all register memory lives here.")
            w.comment("Defined in _reg_storage.cpp, zero-initialised at startup.")
            w.line("extern RegMap_t regs;")
            w.blank()

            w.close_namespace(self._ns())

    def _emit_storage_source(self, output_dir: str):
        """
        <module>_reg_storage.cpp

        Defines 'regs', zero-initialised at startup (BSS).  This is the only
        translation unit that owns register memory — everything else takes a
        reference or pointer into it.
        """
        with CppWriter(self._filepath(output_dir, "reg_storage.cpp"), is_header=False) as w:
            w.generated_header("register storage definitions — single owner of all register memory")
            w.include(f"{self._prefix()}_reg_storage.hpp")
            w.blank()

            w.open_namespace(self._ns())
            w.blank()

            w.comment("Zero-initialised: all registers start at 0 until reg_reset() or explicit writes.")
            w.line("RegMap_t regs = {};")
            w.blank()

            w.close_namespace(self._ns())

    def _emit_device_header(self, output_dir: str):
        """
        <module>_reg_device.hpp

        Inline getters and setters for every register, bit-field, and bank
        element.  All functions are header-only so the compiler can always
        inline them — there is zero call overhead in optimised builds.
        """
        with CppWriter(self._filepath(output_dir, "reg_device.hpp"), is_header=True) as w:
            w.generated_header("inline device-side accessors — zero call overhead after optimisation")
            w.pragma_once()
            w.include(f"{self._prefix()}_reg_storage.hpp")
            w.include("cstring", system=True)
            w.blank()

            w.open_namespace(self._ns())
            w.blank()

            w.separator("Register accessors")
            self._emit_accessor_nodes(w, self._device_tree, [], [])

            w.close_namespace(self._ns())

    def _cpp_reg_type(self, reg, fn_parts: list, node_name: str) -> str:
        """C++ value type for this register's accessor functions.

        Enums take precedence; otherwise maps reg.type + reg.width to the
        smallest standard C++ integer/float/bool type.  Falls back to word_t
        with a printed warning for unsupported combinations.
        """
        if reg.enum:
            return "_".join(fn_parts + [node_name]) + "_e"

        t = reg.type
        w = reg.width

        if t == "bool":
            return "bool"
        if t == "unsigned":
            if w <= 8:  return "uint8_t"
            if w <= 16: return "uint16_t"
            if w <= 32: return "uint32_t"
            if w <= 64: return "uint64_t"
            print(f"WARNING: '{reg.name}': unsigned width {w} > 64 — using word_t")
            return "word_t"
        if t == "signed":
            if w <= 8:  return "int8_t"
            if w <= 16: return "int16_t"
            if w <= 32: return "int32_t"
            if w <= 64: return "int64_t"
            print(f"WARNING: '{reg.name}': signed width {w} > 64 — using word_t")
            return "word_t"
        if t == "float":  return "float"
        if t == "double": return "double"

        print(f"WARNING: '{reg.name}': unsupported type '{t}' — using word_t")
        return "word_t"

    def _sw_get(self, reg, val_type: str, storage: str) -> str:
        """Getter body for a single-word storage expression (the part inside { })."""
        t = reg.type
        if t == "bool":
            return f"return {storage} != 0u;"
        if t in ("float", "double"):
            return f"{t} _v; memcpy(&_v, &{storage}, sizeof({t})); return _v;"
        if val_type in ("word_t", self._word_type):
            return f"return {storage};"
        return f"return static_cast<{val_type}>({storage});"

    def _sw_set(self, reg, val_type: str, storage: str) -> str:
        """Setter body for a single-word storage expression (the part inside { })."""
        t = reg.type
        wt = self._word_type
        if t == "bool":
            return f"{storage} = v ? 1u : 0u;"
        if t in ("float", "double"):
            return f"memcpy(&{storage}, &v, sizeof({t}));"
        if val_type in ("word_t", self._word_type):
            return f"{storage} = v;"
        if t == "signed" and reg.width < self._word_width:
            mask = (1 << reg.width) - 1
            return f"{storage} = static_cast<{wt}>(v) & 0x{mask:X}u;"
        return f"{storage} = static_cast<{wt}>(v);"

    def _emit_accessor_nodes(self, w: CppWriter, nodes: list, struct_path: list, fn_parts: list):
        for node in nodes:
            if isinstance(node, DeviceGroupNode):
                if node.count > 1:
                    w.comment(f"{node.name}: count={node.count} — access via regs.{node.name}[i]...")
                    w.blank()
                else:
                    self._emit_accessor_nodes(
                        w, node.children, struct_path + [node.name], fn_parts + [node.name]
                    )
            elif isinstance(node, DeviceRegNode):
                self._emit_reg_accessors(w, node, struct_path, fn_parts)

    def _emit_reg_accessors(self, w: CppWriter, node: DeviceRegNode, struct_path: list, fn_parts: list):
        reg = node.reg
        bs = node.bank_size
        wpr = reg.words_per_register
        rw = reg.rw

        fn_base = "_".join(fn_parts + [node.name])
        mem_base = "regs." + ".".join(struct_path + [node.name])

        rw_label = {"r": "read-only", "w": "write-only", "rw": "read-write"}.get(rw, rw)
        can_read = True
        can_write = True

        val_type = self._cpp_reg_type(reg, fn_parts, node.name)
        path_str = "/".join(fn_parts + [node.name])
        bank_note = f" (bank_size={bs})" if bs > 1 else ""
        self._emit_reg_doc(w, reg, f"{path_str} — {reg.type} {reg.width}-bit{bank_note} | {rw_label}")

        if bs == 1 and wpr == 1:
            if can_read:
                w.inline_function(
                    f"{val_type} get_{fn_base}()",
                    self._sw_get(reg, val_type, f"{mem_base}.value"),
                )
            if can_write:
                w.inline_function(
                    f"void set_{fn_base}({val_type} v)",
                    self._sw_set(reg, val_type, f"{mem_base}.value"),
                )

        elif bs == 1:
            # Multi-word, no bank.
            if val_type not in ("word_t", self._word_type) or reg.type in ("float", "double"):
                # Typed return-by-value via memcpy.
                sz = f"sizeof({val_type})"
                if can_read:
                    w.open_function(f"inline {val_type} get_{fn_base}()")
                    w.line(f"{val_type} v;")
                    w.line(f"memcpy(&v, {mem_base}.words, {sz});")
                    w.line("return v;")
                    w.close_function()
                if can_write:
                    w.open_function(f"inline void set_{fn_base}({val_type} v)")
                    w.line(f"memcpy({mem_base}.words, &v, {sz});")
                    w.close_function()
            else:
                # Fallback bulk copy with word_t* buffer.
                if can_read:
                    w.open_function(f"inline void get_{fn_base}(word_t* out)")
                    w.line(f"for (uint8_t i = 0; i < {wpr}; ++i) out[i] = {mem_base}.words[i];")
                    w.close_function()
                if can_write:
                    w.open_function(f"inline void set_{fn_base}(const word_t* data)")
                    w.line(f"for (uint8_t i = 0; i < {wpr}; ++i) {mem_base}.words[i] = data[i];")
                    w.close_function()

        elif wpr == 1:
            # Bank, single-word.
            if can_read:
                w.inline_function(
                    f"{val_type} get_{fn_base}(uint8_t idx)",
                    self._sw_get(reg, val_type, f"{mem_base}.entries[idx]"),
                )
            if can_write:
                w.inline_function(
                    f"void set_{fn_base}(uint8_t idx, {val_type} v)",
                    self._sw_set(reg, val_type, f"{mem_base}.entries[idx]"),
                )

        else:
            # Bank + multi-word.
            if val_type not in ("word_t", self._word_type) or reg.type in ("float", "double"):
                sz = f"sizeof({val_type})"
                if can_read:
                    w.open_function(f"inline {val_type} get_{fn_base}(uint8_t idx)")
                    w.line(f"{val_type} v;")
                    w.line(f"memcpy(&v, {mem_base}.entries[idx], {sz});")
                    w.line("return v;")
                    w.close_function()
                if can_write:
                    w.open_function(f"inline void set_{fn_base}(uint8_t idx, {val_type} v)")
                    w.line(f"memcpy({mem_base}.entries[idx], &v, {sz});")
                    w.close_function()
            else:
                if can_read:
                    w.open_function(f"inline void get_{fn_base}(uint8_t idx, word_t* out)")
                    w.line(f"for (uint8_t i = 0; i < {wpr}; ++i) out[i] = {mem_base}.entries[idx][i];")
                    w.close_function()
                if can_write:
                    w.open_function(f"inline void set_{fn_base}(uint8_t idx, const word_t* data)")
                    w.line(f"for (uint8_t i = 0; i < {wpr}; ++i) {mem_base}.entries[idx][i] = data[i];")
                    w.close_function()

        if reg.bit_field and bs == 1:
            for field_name, field in reg.bit_field.items():
                self._emit_bitfield_accessor(w, field_name, field, fn_base, mem_base, wpr, reg.width)

        w.blank()

    def _emit_bitfield_accessor(
        self,
        w: CppWriter,
        field_name: str,
        field: Any,
        reg_fn_base: str,
        mem_base: str,
        reg_wpr: int,
        reg_width: int,
    ):
        start_bit = field.starting_bit
        width = field.width
        word_idx = start_bit // self._word_width
        bit_in_word = start_bit % self._word_width
        end_bit_in_word = bit_in_word + width - 1

        if start_bit + width > reg_width:
            print(
                f"WARNING: '{field_name}' in '{reg_fn_base}': bit-field "
                f"[{start_bit + width - 1}:{start_bit}] exceeds register width {reg_width}"
            )

        fn_name = f"{reg_fn_base}_{field_name}"
        fvt = self._cpp_reg_type(field, [], "")   # field's C++ value type
        do_read = True
        do_write = True

        bit_hi = start_bit + width - 1
        field_rw_label = {"r": "read-only", "w": "write-only", "rw": "read-write"}.get(field.rw, field.rw)

        if end_bit_in_word >= self._word_width:
            self._emit_reg_doc(w, field, f"{fn_name} — {field.type} {width}-bit | bits [{bit_hi}:{start_bit}] | {field_rw_label} | cross-word: not yet implemented")
            w.comment(
                f"TODO: get/set_{fn_name} — cross-word field"
                f" bits [{start_bit + width - 1}:{start_bit}]"
            )
            return

        self._emit_reg_doc(w, field, f"{fn_name} — {field.type} {width}-bit | bits [{bit_hi}:{start_bit}] | {field_rw_label}")

        mask = (1 << width) - 1
        mask_hex = f"0x{mask:X}u"
        storage = f"{mem_base}.value" if reg_wpr == 1 else f"{mem_base}.words[{word_idx}]"

        if field.type == "bool":
            bit_mask = f"({mask_hex} << {bit_in_word})" if bit_in_word else mask_hex
            raw = f"{storage} & {bit_mask}" if bit_in_word == 0 else f"({storage} >> {bit_in_word}) & {mask_hex}"
            if do_read:
                w.inline_function(f"bool get_{fn_name}()", f"return ({raw}) != 0u;")
            if do_write:
                w.inline_function(
                    f"void set_{fn_name}(bool v)",
                    f"{storage} = ({storage} & ~{bit_mask}) | (v ? {bit_mask} : 0u);",
                )
            return

        # Non-bool: extract bits, cast to typed return.
        if bit_in_word == 0:
            raw_extract = f"{storage} & {mask_hex}"
        else:
            raw_extract = f"({storage} >> {bit_in_word}) & {mask_hex}"

        if fvt in ("word_t", self._word_type):
            get_expr = f"return {raw_extract};"
        else:
            get_expr = f"return static_cast<{fvt}>({raw_extract});"

        wt = self._word_type
        if bit_in_word == 0:
            set_expr = (
                f"{storage} = ({storage} & ~{mask_hex})"
                f" | (static_cast<{wt}>(v) & {mask_hex});"
            )
        else:
            set_expr = (
                f"{storage} = ({storage} & ~({mask_hex} << {bit_in_word}))"
                f" | ((static_cast<{wt}>(v) & {mask_hex}) << {bit_in_word});"
            )

        if do_read:
            w.inline_function(f"{fvt} get_{fn_name}()", get_expr)
        if do_write:
            w.inline_function(f"void set_{fn_name}({fvt} v)", set_expr)

    def _emit_comm_header(self, output_dir: str):
        """
        <module>_reg_comm.hpp

        Declares the binary comm interface used by protocol handlers (UART,
        SPI, I2C, etc.).  The interface is intentionally narrow: only an
        address, a word buffer, and a count are needed — the firmware handles
        all packing, permission checks, and multi-word buffering internally.
        """
        with CppWriter(self._filepath(output_dir, "reg_comm.hpp"), is_header=True) as w:
            w.generated_header("binary comm interface — address-based register read/write for protocol handlers")
            w.pragma_once()
            w.include(f"{self._prefix()}_reg_types.hpp")
            w.include("cstdint", system=True)
            w.blank()

            w.open_namespace(self._ns())
            w.blank()

            w.separator("Register type tag")
            w.open_enum_class("RegType")
            w.enum_value("UNSIGNED", 0)
            w.enum_value("SIGNED",   1)
            w.enum_value("FLOAT",    2)
            w.enum_value("DOUBLE",   3, last=True)
            w.close_enum_class()
            w.blank()

            w.separator("Register metadata")
            w.comment("Shared by all word-slots of one register element.  Lives in ROM.")
            w.comment("Pointer members (storage, read_buf, write_buf) point into RAM.")
            w.open_struct("RegInfo")
            w.line("word_t*        storage;     // first word of this element in the regs struct")
            w.line("word_t*        read_buf;    // null for single-word; coherent snapshot buffer")
            w.line("word_t*        write_buf;   // null for single-word; staged write buffer")
            w.line("const word_t*  default_val; // null = no default; length = valid_words word(s), little-endian")
            w.line("const word_t*  min_val;     // null = no lower bound; length = valid_words word(s)")
            w.line("const word_t*  max_val;     // null = no upper bound; length = valid_words word(s)")
            w.line("uint8_t        words_per_reg;  // total allocated words (may include padding)")
            w.line("uint8_t        valid_words;    // ceil(width / word_width) — words carrying data")
            w.line("uint8_t        last_word_bits; // effective bits in last word; 0 = fully used")
            w.line("RegAccess      access;")
            w.line("RegType        type;")
            w.close_struct()
            w.blank()

            w.separator("Address table slot")
            w.comment("One slot per word address.  reg == nullptr means the address is unoccupied.")
            w.open_struct("RegAddrSlot")
            w.line("const RegInfo* reg;      // nullptr = gap / alignment padding")
            w.line("uint8_t        word_idx; // 0 = base word of this element")
            w.close_struct()
            w.blank()

            w.separator("Comm API")
            w.comment("Read 'count' words starting at 'address' into 'out'.")
            w.comment("Snapshots the full register when word_idx 0 is included, for coherent reads.")
            w.line("RegStatus reg_read(uint16_t address, word_t* out, uint16_t count = 1);")
            w.blank()
            w.comment("Write 'count' words starting at 'address' from 'data'.")
            w.comment("Commits staged write to storage when the last valid word is included.")
            w.line("RegStatus reg_write(uint16_t address, const word_t* data, uint16_t count = 1);")
            w.blank()
            w.comment("Zero all register storage and clear all pending write buffers.")
            w.line("void reg_reset();")
            w.blank()

            w.close_namespace(self._ns())

    def _emit_comm_source(self, output_dir: str):
        """
        <module>_reg_comm.cpp

        Contains the flat address table (direct-indexed for O(1) lookup), the
        per-element read/write buffers for multi-word registers, and the
        reg_read / reg_write / reg_reset implementations.
        """
        with CppWriter(self._filepath(output_dir, "reg_comm.cpp"), is_header=False) as w:
            w.generated_header(
                "comm interface implementation: address table, multi-word buffers, "
                "reg_read / reg_write / reg_reset"
            )
            w.include(f"{self._prefix()}_reg_comm.hpp")
            w.include(f"{self._prefix()}_reg_storage.hpp")
            w.include("cstring", system=True)
            w.blank()

            w.open_namespace(self._ns())
            w.blank()

            # ----------------------------------------------------------
            # Per-element read/write buffers (multi-word elements only)
            # ----------------------------------------------------------
            w.separator("Multi-word register buffers")
            multi_word_elems = [e for e in self._elements if e.needs_buffers]
            if multi_word_elems:
                for elem in multi_word_elems:
                    sym = self._elem_sym(elem)
                    wpr = elem.words_per_reg
                    w.line(f"static word_t {sym}_rbuf[{wpr}];")
                    w.line(f"static word_t {sym}_wbuf[{wpr}];")
            else:
                w.comment("No multi-word registers in this map.")
            w.blank()

            # ----------------------------------------------------------
            # Static const arrays for default / min / max values
            # ----------------------------------------------------------
            w.separator("Default and range value arrays")
            any_val_arrays = False
            for elem in self._elements:
                reg = elem.reg
                sym = self._elem_sym(elem)
                vw = elem.valid_words
                default_words = self._words_encode(reg, reg.default, vw)
                if default_words is not None:
                    any_val_arrays = True
                    vals = ", ".join(f"0x{v:X}u" for v in default_words)
                    w.line(f"static const word_t {sym}_default[{vw}] = {{ {vals} }};")
                if reg.min_val is not None and reg.max_val is not None:
                    min_words = self._words_encode(reg, reg.min_val, vw)
                    max_words = self._words_encode(reg, reg.max_val, vw)
                    if min_words is not None and max_words is not None:
                        any_val_arrays = True
                        min_vals = ", ".join(f"0x{v:X}u" for v in min_words)
                        max_vals = ", ".join(f"0x{v:X}u" for v in max_words)
                        w.line(f"static const word_t {sym}_min[{vw}] = {{ {min_vals} }};")
                        w.line(f"static const word_t {sym}_max[{vw}] = {{ {max_vals} }};")
            if not any_val_arrays:
                w.comment("No defaults or ranges declared in this map.")
            w.blank()

            # ----------------------------------------------------------
            # RegInfo table — one entry per element
            # ----------------------------------------------------------
            w.separator("Register info table")
            w.line("static const RegInfo reg_info[] = {")
            with w.indented():
                for i, elem in enumerate(self._elements):
                    reg = elem.reg
                    sym = self._elem_sym(elem)
                    vw = elem.valid_words
                    default_words = self._words_encode(reg, reg.default, vw)
                    min_words = self._words_encode(reg, reg.min_val, vw)
                    max_words = self._words_encode(reg, reg.max_val, vw)
                    has_range = min_words is not None and max_words is not None
                    default_ptr = f"{sym}_default" if default_words is not None else "nullptr"
                    min_ptr = f"{sym}_min" if has_range else "nullptr"
                    max_ptr = f"{sym}_max" if has_range else "nullptr"
                    storage = self._storage_expr(elem)
                    rbuf = f"{sym}_rbuf" if elem.needs_buffers else "nullptr"
                    wbuf = f"{sym}_wbuf" if elem.needs_buffers else "nullptr"
                    access = self._rw_to_access(elem.reg.rw)
                    w.comment(f"[{i}] {elem.qualified_name} (bank {elem.bank_idx})"
                              f"  @ 0x{elem.base_address:04X}")
                    reg_type = self._reg_type_cpp(elem.reg)
                    w.line(
                        f"{{ {storage}, {rbuf}, {wbuf},"
                        f" {default_ptr}, {min_ptr}, {max_ptr},"
                        f" {elem.words_per_reg}, {elem.valid_words},"
                        f" {elem.last_word_used_bits}, {access}, {reg_type} }},"
                    )
            w.line("};")
            w.line(f"static constexpr uint16_t REG_INFO_COUNT ="
                   f" {len(self._elements)};")
            w.blank()

            # ----------------------------------------------------------
            # Flat address table
            # ----------------------------------------------------------
            w.separator("Flat address table")
            table_size = self._max_address + 1
            w.comment(f"Direct-indexed by word address [0x0000 .. 0x{self._max_address:04X}].")
            w.line(f"static constexpr uint16_t REG_TABLE_SIZE = {table_size};")
            w.line("static const RegAddrSlot reg_table[REG_TABLE_SIZE] = {")
            elem_to_idx = {id(e): i for i, e in enumerate(self._elements)}
            with w.indented():
                for addr in range(table_size):
                    if addr in self._slots:
                        slot = self._slots[addr]
                        idx = elem_to_idx[id(slot.element)]
                        w.line(
                            f"/* 0x{addr:04X} */ {{ &reg_info[{idx}],"
                            f" {slot.word_idx} }},"
                        )
                    else:
                        w.line(f"/* 0x{addr:04X} */ {{ nullptr, 0 }},")
            w.line("};")
            w.blank()

            # ----------------------------------------------------------
            # Range comparison helpers
            # ----------------------------------------------------------
            w.separator("Range comparison helpers")
            w.comment("All helpers return true if a <= b.")
            w.blank()

            w.comment("Unsigned / bool: little-endian word comparison from MSB to LSB.")
            w.open_function("static bool reg_cmp_le(const word_t* a, const word_t* b, uint8_t n)")
            w.open_brace("for (int8_t _i = (int8_t)(n - 1u); _i >= 0; --_i)")
            w.open_brace("if (a[_i] < b[_i])")
            w.line("return true;")
            w.close_brace()
            w.open_brace("if (a[_i] > b[_i])")
            w.line("return false;")
            w.close_brace()
            w.close_brace()
            w.line("return true;")
            w.close_function()
            w.blank()

            w.comment("Signed: locate the actual sign bit (last_word_bits gives MSB position),")
            w.comment("then compare as positive/negative before falling back to unsigned word order.")
            w.open_function(
                "static bool reg_cmp_le_signed"
                "(const word_t* a, const word_t* b, uint8_t n, uint8_t last_word_bits)"
            )
            w.comment("last_word_bits==0 → last word fully used; sign bit is the MSB of word_t.")
            w.line("const uint8_t sign_shift = (last_word_bits == 0u)")
            w.line("    ? (uint8_t)(sizeof(word_t) * 8u - 1u)")
            w.line("    : (uint8_t)(last_word_bits - 1u);")
            w.line("const word_t sign_bit = word_t(1u) << sign_shift;")
            w.line("const bool a_neg = (a[n - 1u] & sign_bit) != 0u;")
            w.line("const bool b_neg = (b[n - 1u] & sign_bit) != 0u;")
            w.open_brace("if (a_neg != b_neg)")
            w.line("return a_neg;")
            w.close_brace()
            w.line("return reg_cmp_le(a, b, n);")
            w.close_function()
            w.blank()

            w.comment("Float: reconstruct and compare as IEEE 754 single.")
            w.open_function("static bool reg_cmp_le_float(const word_t* a, const word_t* b)")
            w.line("float fa, fb;")
            w.line("memcpy(&fa, a, sizeof(float));")
            w.line("memcpy(&fb, b, sizeof(float));")
            w.line("return fa <= fb;")
            w.close_function()
            w.blank()

            w.comment("Double: reconstruct and compare as IEEE 754 double.")
            w.open_function("static bool reg_cmp_le_double(const word_t* a, const word_t* b)")
            w.line("double da, db;")
            w.line("memcpy(&da, a, sizeof(double));")
            w.line("memcpy(&db, b, sizeof(double));")
            w.line("return da <= db;")
            w.close_function()
            w.blank()

            # ----------------------------------------------------------
            # reg_read
            # ----------------------------------------------------------
            w.separator("reg_read")
            ce = f"{self._prefix().upper()}_REG_ENTER_CRITICAL"
            cx = f"{self._prefix().upper()}_REG_EXIT_CRITICAL"
            w.open_function("RegStatus reg_read(uint16_t address, word_t* out, uint16_t count)")
            w.line("if (address >= REG_TABLE_SIZE)")
            with w.indented():
                w.line("return RegStatus::BAD_ADDRESS_OUT_OF_RANGE;")
            w.blank()
            w.line("const RegAddrSlot& slot = reg_table[address];")
            w.blank()
            w.line("if (!slot.reg)")
            with w.indented():
                w.line("return RegStatus::BAD_ADDRESS;")
            w.blank()
            w.line("const RegInfo&     info = *slot.reg;")
            w.blank()
            w.line("if (info.access == RegAccess::WRITE)")
            with w.indented():
                w.line("return RegStatus::BAD_ACCESS_WRITE_ONLY;")
            w.line("if (slot.word_idx + count > info.valid_words)")
            with w.indented():
                w.line("return RegStatus::REGISTER_OVERFLOW;")
            w.blank()
            w.open_brace("if (info.words_per_reg == 1)")
            w.line("out[0] = info.storage[0];")
            w.line("return RegStatus::OK;")
            w.close_brace()
            w.open_brace("else if (slot.word_idx == 0 && count == info.valid_words)")
            w.comment("Full register read — copy directly from storage under critical section.")
            w.line(f"{ce}();")
            w.line("memcpy(out, info.storage, info.valid_words * sizeof(word_t));")
            w.line(f"{cx}();")
            w.line("return RegStatus::OK;")
            w.close_brace()
            w.open_brace("else")
            w.comment("Partial read — hardware atomic (no buffer) or snapshot path.")
            w.open_brace("if (info.read_buf == nullptr)")
            w.comment("No software buffer: hardware atomicity covers this register width.")
            w.line(f"{ce}();")
            w.line("memcpy(out, &info.storage[slot.word_idx], count * sizeof(word_t));")
            w.line(f"{cx}();")
            w.line("return RegStatus::OK;")
            w.close_brace()
            w.open_brace("if (slot.word_idx == 0)")
            w.line(f"{ce}();")
            w.line("memcpy(info.read_buf, info.storage, info.valid_words * sizeof(word_t));")
            w.line(f"{cx}();")
            w.close_brace()
            w.line("memcpy(out, &info.read_buf[slot.word_idx], count * sizeof(word_t));")
            w.open_brace("if (slot.word_idx == 0)")
            w.line("return RegStatus::OK_ATOMIC_UPDATED;")
            w.close_brace()
            w.line("return RegStatus::OK_ATOMIC_BUFFERED;")
            w.dedent()
            w.line("}")
            w.blank()
            w.line("return RegStatus::BAD_RETURN;")
            w.close_function()
            w.blank()

            # ----------------------------------------------------------
            # reg_write
            # ----------------------------------------------------------
            w.separator("reg_write")
            w.open_function("RegStatus reg_write(uint16_t address, const word_t* data, uint16_t count)")
            w.line("if (address >= REG_TABLE_SIZE)")
            with w.indented():
                w.line("return RegStatus::BAD_ADDRESS_OUT_OF_RANGE;")
            w.blank()
            w.line("const RegAddrSlot& slot = reg_table[address];")
            w.blank()
            w.line("if (!slot.reg)")
            with w.indented():
                w.line("return RegStatus::BAD_ADDRESS;")
            w.blank()
            w.line("const RegInfo&     info = *slot.reg;")
            w.blank()
            w.line("if (info.access == RegAccess::READ)")
            with w.indented():
                w.line("return RegStatus::BAD_ACCESS_READ_ONLY;")
            w.line("if (slot.word_idx + count > info.valid_words)")
            with w.indented():
                w.line("return RegStatus::REGISTER_OVERFLOW;")
            w.blank()
            w.comment("Check that the last valid word has no bits set above the register width.")
            w.open_brace("if (info.last_word_bits != 0)")
            w.line("uint8_t last_idx = info.valid_words - 1u;")
            w.open_brace("if (slot.word_idx + count > last_idx)")
            w.open_brace("if (data[last_idx - slot.word_idx] >> info.last_word_bits)")
            w.line("return RegStatus::BITS_ABOVE_WIDTH;")
            w.close_brace()
            w.close_brace()
            w.close_brace()
            w.blank()
            w.comment("Range check: dispatch to the correct comparator for the register's type.")
            w.open_brace("if (info.min_val)")
            w.line("bool _in_range;")
            w.open_brace("switch (info.type)")
            w.line("case RegType::SIGNED:")
            with w.indented():
                w.line("_in_range = reg_cmp_le_signed(info.min_val, data, info.valid_words, info.last_word_bits)")
                w.line("         && reg_cmp_le_signed(data, info.max_val, info.valid_words, info.last_word_bits);")
                w.line("break;")
            w.line("case RegType::FLOAT:")
            with w.indented():
                w.line("_in_range = reg_cmp_le_float(info.min_val, data)")
                w.line("         && reg_cmp_le_float(data, info.max_val);")
                w.line("break;")
            w.line("case RegType::DOUBLE:")
            with w.indented():
                w.line("_in_range = reg_cmp_le_double(info.min_val, data)")
                w.line("         && reg_cmp_le_double(data, info.max_val);")
                w.line("break;")
            w.line("default:")
            with w.indented():
                w.line("_in_range = reg_cmp_le(info.min_val, data, info.valid_words)")
                w.line("         && reg_cmp_le(data, info.max_val, info.valid_words);")
                w.line("break;")
            w.close_brace()
            w.open_brace("if (!_in_range)")
            w.line("return RegStatus::OUT_OF_RANGE;")
            w.close_brace()
            w.close_brace()
            w.blank()
            w.open_brace("if (info.words_per_reg == 1)")
            w.line("info.storage[0] = data[0];")
            w.line("return RegStatus::OK;")
            w.close_brace()
            w.open_brace("else if (slot.word_idx == 0 && count == info.valid_words)")
            w.comment("Full register write — commit directly to storage under critical section.")
            w.line(f"{ce}();")
            w.line("memcpy(info.storage, data, info.valid_words * sizeof(word_t));")
            w.line(f"{cx}();")
            w.line("return RegStatus::OK;")
            w.close_brace()
            w.open_brace("else")
            w.comment("Partial write — hardware atomic (no buffer) or staged path.")
            w.open_brace("if (info.write_buf == nullptr)")
            w.comment("No software buffer: write directly; hardware atomicity covers this register width.")
            w.line(f"{ce}();")
            w.line("memcpy(&info.storage[slot.word_idx], data, count * sizeof(word_t));")
            w.line(f"{cx}();")
            w.line("return RegStatus::OK;")
            w.close_brace()
            w.line("memcpy(&info.write_buf[slot.word_idx], data, count * sizeof(word_t));")
            w.open_brace("if (slot.word_idx + count == info.valid_words)")
            w.line(f"{ce}();")
            w.line("memcpy(info.storage, info.write_buf, info.valid_words * sizeof(word_t));")
            w.line(f"{cx}();")
            w.close_brace()
            w.dedent()
            w.line("}")
            w.blank()
            w.line("return RegStatus::BAD_RETURN;")
            w.close_function()
            w.blank()

            # ----------------------------------------------------------
            # reg_reset
            # ----------------------------------------------------------
            w.separator("reg_reset")
            w.open_function("void reg_reset()")
            w.line("memset(&regs, 0, sizeof(regs));")
            w.open_brace("for (uint16_t i = 0; i < REG_INFO_COUNT; ++i)")
            w.line("const RegInfo& info = reg_info[i];")
            w.comment("Restore declared defaults after zeroing.")
            w.open_brace("if (info.default_val)")
            w.line("memcpy(info.storage, info.default_val, info.valid_words * sizeof(word_t));")
            w.close_brace()
            w.open_brace("if (info.read_buf)")
            w.line("memset(info.read_buf,  0, info.words_per_reg * sizeof(word_t));")
            w.close_brace()
            w.open_brace("if (info.write_buf)")
            w.line("memset(info.write_buf, 0, info.words_per_reg * sizeof(word_t));")
            w.close_brace()
            w.close_brace()
            w.close_function()
            w.blank()

            w.close_namespace(self._ns())

    # ------------------------------------------------------------------
    # Accessor-verify helpers
    # ------------------------------------------------------------------

    def _test_val(self, reg, val_type: str) -> str:
        """Return a C++ literal that is safe to write to this register via its accessor."""
        t = reg.type
        if t == "bool":   return "true"
        if t == "float":  return "1.5f"
        if t == "double": return "1.5"
        if reg.enum:
            first = next(iter(reg.enum.keys()))
            return f"{val_type}::{first.upper()}"
        if t == "unsigned":
            mask = (1 << reg.width) - 1
            return f"static_cast<{val_type}>({0xAB & mask}u)"
        if t == "signed":
            max_pos = (1 << (reg.width - 1)) - 1
            return f"static_cast<{val_type}>({min(0x42, max_pos)})"
        return f"static_cast<{val_type}>(1u)"

    def _verify_single_sw(self, w: "CppWriter", fn_base: str, val_type: str, reg, can_read: bool, can_write: bool):
        tv = self._test_val(reg, val_type)
        ns = self._ns()
        if can_write and can_read:
            w.line(f"{ns}::set_{fn_base}({tv});")
            w.line(f"REG_VERIFY_ASSERT({ns}::get_{fn_base}() == {tv});")
        elif can_write:
            w.line(f"{ns}::set_{fn_base}({tv});")
        elif can_read:
            w.line(f"(void){ns}::get_{fn_base}();")

    def _verify_bulk_mw(self, w: "CppWriter", fn_base: str, wpr: int, can_read: bool, can_write: bool):
        ns = self._ns()
        if can_write:
            vals = ", ".join(f"static_cast<{ns}::word_t>(0x{(i + 1) * 0x11:02X}u)" for i in range(wpr))
            w.line(f"const {ns}::word_t _tw[{wpr}] = {{{vals}}};")
            w.line(f"{ns}::set_{fn_base}(_tw);")
        if can_read and can_write:
            w.line(f"{ns}::word_t _rb[{wpr}];")
            w.line(f"{ns}::get_{fn_base}(_rb);")
            for i in range(wpr):
                w.line(f"REG_VERIFY_ASSERT(_rb[{i}] == _tw[{i}]);")
        elif can_read:
            w.line(f"{ns}::word_t _rb[{wpr}];")
            w.line(f"{ns}::get_{fn_base}(_rb);")

    def _verify_bank_sw(self, w: "CppWriter", fn_base: str, val_type: str, reg, bs: int, can_read: bool, can_write: bool):
        ns = self._ns()
        mask = (1 << reg.width) - 1
        if can_write:
            for i in range(bs):
                if reg.type == "bool":
                    v = "true" if i % 2 == 0 else "false"
                else:
                    v = f"static_cast<{val_type}>({(i + 1) & mask}u)"
                w.line(f"{ns}::set_{fn_base}({i}u, {v});")
        if can_read and can_write:
            for i in range(bs):
                if reg.type == "bool":
                    v = "true" if i % 2 == 0 else "false"
                else:
                    v = f"static_cast<{val_type}>({(i + 1) & mask}u)"
                w.line(f"REG_VERIFY_ASSERT({ns}::get_{fn_base}({i}u) == {v});")
        elif can_read:
            for i in range(bs):
                w.line(f"(void){ns}::get_{fn_base}({i}u);")

    def _verify_bank_typed_mw(self, w: "CppWriter", fn_base: str, val_type: str, reg, bs: int, can_read: bool, can_write: bool):
        ns = self._ns()
        if can_write:
            for i in range(bs):
                w.line(f"{ns}::set_{fn_base}({i}u, static_cast<{val_type}>({i + 1}u));")
        if can_read and can_write:
            for i in range(bs):
                w.line(f"REG_VERIFY_ASSERT({ns}::get_{fn_base}({i}u) == static_cast<{val_type}>({i + 1}u));")
        elif can_read:
            for i in range(bs):
                w.line(f"(void){ns}::get_{fn_base}({i}u);")

    def _verify_bank_bulk_mw(self, w: "CppWriter", fn_base: str, wpr: int, bs: int, can_read: bool, can_write: bool):
        ns = self._ns()
        if can_write:
            for i in range(bs):
                vals = ", ".join(f"static_cast<{ns}::word_t>({(i + 1) * 0x10 + j}u)" for j in range(wpr))
                w.line(f"{{ const {ns}::word_t _tw{i}[{wpr}] = {{{vals}}}; {ns}::set_{fn_base}({i}u, _tw{i}); }}")
        if can_read and can_write:
            for i in range(bs):
                vals = ", ".join(f"static_cast<{ns}::word_t>({(i + 1) * 0x10 + j}u)" for j in range(wpr))
                w.line(f"{{ {ns}::word_t _rb{i}[{wpr}]; {ns}::get_{fn_base}({i}u, _rb{i});")
                for j in range(wpr):
                    w.line(f"  REG_VERIFY_ASSERT(_rb{i}[{j}] == static_cast<{ns}::word_t>({(i + 1) * 0x10 + j}u));")
                w.line("}")
        elif can_read:
            for i in range(bs):
                w.line(f"{{ {ns}::word_t _rb{i}[{wpr}]; {ns}::get_{fn_base}({i}u, _rb{i}); }}")

    def _verify_bitfields(self, w: "CppWriter", fn_base: str, reg, can_read: bool, can_write: bool):
        if not reg.bit_field:
            return
        ns = self._ns()
        fields = []
        for field_name, field in reg.bit_field.items():
            fvt = self._cpp_reg_type(field, [], "")
            f_can_read  = True
            f_can_write = True
            w_bits = field.width
            mask = (1 << w_bits) - 1
            if field.type == "bool":
                tv, zv = "true",  "false"
            elif field.type == "unsigned":
                tv = f"static_cast<{fvt}>({min(0xA, mask)}u)"
                zv = f"static_cast<{fvt}>(0u)"
            elif field.type == "signed":
                tv = f"static_cast<{fvt}>({min(5, (1 << (w_bits - 1)) - 1)})"
                zv = f"static_cast<{fvt}>(0)"
            else:
                tv, zv = f"static_cast<{fvt}>(1u)", f"static_cast<{fvt}>(0u)"
            fields.append((field_name, fvt, f_can_read, f_can_write, tv, zv))

        for fn, fvt, cr, cw, tv, zv in fields:
            if cr and not cw: w.line(f"(void){ns}::get_{fn_base}_{fn}();")
            elif cw and not cr: w.line(f"{ns}::set_{fn_base}_{fn}({tv});")

        rw_fields = [(fn, fvt, cr, cw, tv, zv) for fn, fvt, cr, cw, tv, zv in fields if cr and cw]
        if not rw_fields:
            return

        for fn, fvt, cr, cw, tv, zv in rw_fields:
            w.line(f"{ns}::set_{fn_base}_{fn}({tv});")
        for fn, fvt, cr, cw, tv, zv in rw_fields:
            w.line(f"REG_VERIFY_ASSERT({ns}::get_{fn_base}_{fn}() == {tv});")

        if len(rw_fields) > 1:
            for i, (fn, fvt, cr, cw, tv, zv) in enumerate(rw_fields):
                w.line(f"{ns}::set_{fn_base}_{fn}({zv});")
                w.line(f"REG_VERIFY_ASSERT({ns}::get_{fn_base}_{fn}() == {zv});")
                for j, (ofn, *_, otv, _) in enumerate(rw_fields):
                    if i != j:
                        w.line(f"REG_VERIFY_ASSERT({ns}::get_{fn_base}_{ofn}() == {otv});")
                w.line(f"{ns}::set_{fn_base}_{fn}({tv});")

    def _verify_reg_node(self, w: "CppWriter", node: "DeviceRegNode", fn_parts: list):
        reg = node.reg
        bs  = node.bank_size
        wpr = reg.words_per_register
        rw  = reg.rw
        fn_base  = "_".join(fn_parts + [node.name])
        val_type = self._cpp_reg_type(reg, fn_parts, node.name)
        if reg.enum:
            val_type = f"{self._ns()}::{val_type}"
        can_read  = True
        can_write = True
        is_typed  = val_type not in ("word_t", self._word_type) or reg.type in ("float", "double")

        w.comment(f"{fn_base}: {reg.type} {reg.width}-bit | {rw} | bank={bs} | wpr={wpr}")
        w.open_brace()
        w.line(f"{self._ns()}::reg_reset();")

        if bs > 1 and wpr > 1:
            if is_typed:
                self._verify_bank_typed_mw(w, fn_base, val_type, reg, bs, can_read, can_write)
            else:
                self._verify_bank_bulk_mw(w, fn_base, wpr, bs, can_read, can_write)
        elif bs > 1:
            self._verify_bank_sw(w, fn_base, val_type, reg, bs, can_read, can_write)
        elif wpr > 1:
            if is_typed:
                ns = self._ns()
                tv = self._test_val(reg, val_type)
                if can_write and can_read:
                    w.line(f"{val_type} _tv = {tv};")
                    w.line(f"{ns}::set_{fn_base}(_tv);")
                    w.line(f"REG_VERIFY_ASSERT({ns}::get_{fn_base}() == _tv);")
                elif can_write:
                    w.line(f"{ns}::set_{fn_base}({tv});")
                elif can_read:
                    w.line(f"(void){ns}::get_{fn_base}();")
            else:
                self._verify_bulk_mw(w, fn_base, wpr, can_read, can_write)
        elif reg.bit_field:
            self._verify_bitfields(w, fn_base, reg, can_read, can_write)
        else:
            self._verify_single_sw(w, fn_base, val_type, reg, can_read, can_write)

        w.close_brace()
        w.blank()

    def _verify_accessor_nodes(self, w: "CppWriter", nodes: list, fn_parts: list):
        for node in nodes:
            if isinstance(node, DeviceGroupNode):
                if node.count > 1:
                    w.comment(f"{node.name}: count={node.count} — no per-instance accessors; tested via comm protocol")
                    w.blank()
                else:
                    self._verify_accessor_nodes(w, node.children, fn_parts + [node.name])
            elif isinstance(node, DeviceRegNode):
                self._verify_reg_node(w, node, fn_parts)

    def _emit_accessor_verify(self, output_dir: str):
        """
        <module>_reg_verify.cpp

        Accessor functional verification.  Callable from host (via reg_host.cpp)
        and from device startup/POST.  Uses REG_VERIFY_ASSERT which defaults to
        <cassert> but can be overridden per-platform.
        """
        prefix = self._prefix()
        with CppWriter(self._filepath(output_dir, "reg_verify.cpp"), is_header=False) as w:
            w.generated_header("accessor functional verification — callable on host and device")
            w.separator("Assert hook — override for your platform before including this TU")
            w.line("#ifndef REG_VERIFY_ASSERT")
            w.line("#  include <cassert>")
            w.line("#  define REG_VERIFY_ASSERT(x) assert(x)")
            w.line("#endif")
            w.blank()
            w.include(f"{prefix}_reg_device.hpp")
            w.include(f"{prefix}_reg_comm.hpp")
            w.blank()
            w.separator(f"{prefix}_reg_verify")
            w.comment("Returns 0 on success.  On host, REG_VERIFY_ASSERT aborts on first failure.")
            w.open_function(f"int {prefix}_reg_verify()")
            self._verify_accessor_nodes(w, self._device_tree, [])
            w.line("return 0;")
            w.close_function()

    def _emit_host_shim(self, output_dir: str):
        """
        <module>_reg_host.cpp

        Host-only binary protocol shim over stdin/stdout.  Compile with
        -DAURA_HOST_TEST alongside the generated storage and comm TUs.

        Protocol (little-endian):
          Request:  [CMD:1] [ADDR:2LE] [COUNT:2LE] [DATA: COUNT * sizeof(word_t)]
          Response: [STATUS:1] [DATA: COUNT * sizeof(word_t)]   (data only on reads)

          CMD 0x01 = reg_read   CMD 0x02 = reg_write
          CMD 0x03 = reg_reset  CMD 0x04 = run accessor verify
        """
        prefix    = self._prefix()
        word_bytes = self._word_width // 8

        with CppWriter(self._filepath(output_dir, "reg_host.cpp"), is_header=False) as w:
            w.generated_header(
                "host-only test shim — binary protocol over stdin/stdout; "
                "compile with -DAURA_HOST_TEST"
            )
            w.line("#ifndef AURA_HOST_TEST")
            w.line('#  error "reg_host.cpp is for host testing only — do not flash to device."')
            w.line("#endif")
            w.blank()
            w.include(f"{prefix}_reg_comm.hpp")
            w.include(f"{prefix}_reg_storage.hpp")
            w.include(f"{prefix}_reg_meta.hpp")
            w.include("cstdio",   system=True)
            w.include("cstdint",  system=True)
            w.include("cstdlib",  system=True)
            w.include("vector",   system=True)
            w.blank()
            w.separator("Windows: force binary mode on stdin/stdout")
            w.line("#ifdef _WIN32")
            w.line("#  include <fcntl.h>")
            w.line("#  include <io.h>")
            w.line("#endif")
            w.blank()
            w.separator("Protocol constants")
            w.line("static constexpr uint8_t CMD_READ      = 0x01;")
            w.line("static constexpr uint8_t CMD_WRITE     = 0x02;")
            w.line("static constexpr uint8_t CMD_RESET     = 0x03;")
            w.line("static constexpr uint8_t CMD_VERIFY    = 0x04;")
            w.line("static constexpr uint8_t CMD_META_READ = 0x05;")
            w.blank()
            w.separator("Forward declaration — defined in reg_verify.cpp")
            w.line(f"int {prefix}_reg_verify();")
            w.blank()
            w.separator("I/O helpers")
            w.open_function("static bool rd(void* buf, size_t n)")
            w.line("return fread(buf, 1, n, stdin) == n;")
            w.close_function()
            w.blank()
            w.open_function("static void wr(const void* buf, size_t n)")
            w.line("fwrite(buf, 1, n, stdout);")
            w.close_function()
            w.blank()
            w.separator("main")
            w.open_function("int main()")
            w.line("#ifdef _WIN32")
            w.line("    _setmode(_fileno(stdin),  _O_BINARY);")
            w.line("    _setmode(_fileno(stdout), _O_BINARY);")
            w.line("#endif")
            w.line(f"{self._ns()}::reg_reset();")
            w.blank()
            w.line("uint8_t  cmd;")
            w.line("uint16_t addr, count;")
            w.open_brace("while (rd(&cmd, 1))")
            w.line("if (!rd(&addr, 2) || !rd(&count, 2)) break;")
            w.blank()
            w.open_brace("if (cmd == CMD_READ)")
            w.line(f"std::vector<{self._ns()}::word_t> out(count);")
            w.line(f"uint8_t s = static_cast<uint8_t>({self._ns()}::reg_read(addr, out.data(), count));")
            w.line("wr(&s, 1);")
            w.open_brace("if (s <= 2)")
            w.line(f"wr(out.data(), count * {word_bytes}u);")
            w.close_brace()
            w.close_brace(" else if (cmd == CMD_WRITE) {")
            w.indent()
            w.line(f"std::vector<{self._ns()}::word_t> data(count);")
            w.line(f"if (!rd(data.data(), count * {word_bytes}u)) break;")
            w.line(f"uint8_t s = static_cast<uint8_t>({self._ns()}::reg_write(addr, data.data(), count));")
            w.line("wr(&s, 1);")
            w.dedent()
            w.close_brace(" else if (cmd == CMD_RESET) {")
            w.indent()
            w.line(f"{self._ns()}::reg_reset();")
            w.line("uint8_t s = 0; wr(&s, 1);")
            w.dedent()
            w.close_brace(" else if (cmd == CMD_VERIFY) {")
            w.indent()
            w.line(f"int r = {prefix}_reg_verify();")
            w.line("uint8_t s = (r == 0) ? 0u : 0xFFu; wr(&s, 1);")
            w.dedent()
            w.close_brace(" else if (cmd == CMD_META_READ) {")
            w.indent()
            w.line("// addr field reused as byte offset; count field = byte count")
            w.line("std::vector<uint8_t> meta_out(count);")
            w.line(f"uint8_t s = {self._ns()}::meta_read(addr, meta_out.data(), count);")
            w.line("wr(&s, 1);")
            w.open_brace("if (s == 0)")
            w.line("wr(meta_out.data(), count);")
            w.close_brace()
            w.dedent()
            w.line("}")
            w.blank()
            w.line("fflush(stdout);")
            w.close_brace()
            w.line("return 0;")
            w.close_function()

    # ------------------------------------------------------------------
    # Struct-type helpers
    # ------------------------------------------------------------------

    def _to_pascal(self, name: str) -> str:
        return "".join(part.capitalize() for part in name.split("_"))

    def _struct_type(self, *parts: str) -> str:
        return "".join(self._to_pascal(p) for p in parts) + "_t"

    def _emit_reg_struct(self, w: CppWriter, node: DeviceRegNode, name_path: list):
        type_name = self._struct_type(*name_path, node.name)
        reg = node.reg
        bs = node.bank_size
        wpr = reg.words_per_register
        rw_label = {"r": "read-only", "w": "write-only", "rw": "read-write"}.get(
            reg.rw, reg.rw
        )
        path_str = "/".join(name_path + [node.name])
        bank_note = f" (bank_size={bs})" if bs > 1 else ""
        self._emit_reg_doc(w, reg, f"{path_str} — {reg.type} {reg.width}-bit{bank_note} | {rw_label}")
        w.open_struct(type_name)
        if bs == 1 and wpr == 1:
            w.line("word_t value = 0;")
        elif bs == 1:
            w.line(f"word_t words[{wpr}] = {{}};")
        elif wpr == 1:
            w.line(f"word_t entries[{bs}] = {{}};")
        else:
            w.line(f"word_t entries[{bs}][{wpr}] = {{}};")
        w.close_struct()
        w.blank()

    def _emit_struct_types(self, w: CppWriter, nodes: list, name_path: list):
        """Depth-first: emit inner types before outer structs that reference them."""
        for node in nodes:
            if isinstance(node, DeviceRegNode):
                self._emit_reg_struct(w, node, name_path)
            elif isinstance(node, DeviceGroupNode):
                child_path = name_path + [node.name]
                self._emit_struct_types(w, node.children, child_path)

                group_type = self._struct_type(*child_path)

                if node.count > 1:
                    inst_type = self._struct_type(*child_path, "instance")
                    w.comment(f"{'/' .join(child_path)} — instance fields")
                    w.open_struct(inst_type)
                    for child in node.children:
                        w.line(f"{self._struct_type(*child_path, child.name)} {child.name};")
                    w.close_struct()
                    w.blank()

                    w.comment(f"{'/' .join(child_path)} — {node.count} instances")
                    w.open_struct(group_type)
                    w.line(f"{inst_type} instances[{node.count}];")
                    w.inline_function(
                        f"{inst_type}& operator[](uint8_t i)",
                        "return instances[i];"
                    )
                    w.close_struct()
                    w.blank()
                else:
                    w.comment(f"{'/' .join(child_path)}")
                    w.open_struct(group_type)
                    for child in node.children:
                        w.line(f"{self._struct_type(*child_path, child.name)} {child.name};")
                    w.close_struct()
                    w.blank()

    def _storage_expr(self, elem: RegElement) -> str:
        """C++ expression for the first word of this element's storage in the regs struct."""
        parts = ["regs"]
        for grp_name, grp_count, inst_idx in elem.ancestor_instances:
            if grp_count > 1:
                parts.append(f"{grp_name}.instances[{inst_idx}]")
            else:
                parts.append(grp_name)
        parts.append(elem.reg.name)
        base = ".".join(parts)
        bs, wpr, bank = elem.reg.bank_size, elem.words_per_reg, elem.bank_idx
        if bs == 1 and wpr == 1:
            return f"&{base}.value"
        elif bs == 1:
            return f"{base}.words"         # array decays to word_t*
        elif wpr == 1:
            return f"&{base}.entries[{bank}]"
        else:
            return f"{base}.entries[{bank}]"  # array decays to word_t*

    def _elem_sym(self, elem: RegElement) -> str:
        """Unique C identifier for this element, used to name buffer variables."""
        parts = []
        for grp_name, grp_count, inst_idx in elem.ancestor_instances:
            parts.append(f"{grp_name}{inst_idx}" if grp_count > 1 else grp_name)
        parts.append(elem.reg.name)
        if elem.reg.bank_size > 1:
            parts.append(f"b{elem.bank_idx}")
        return "_".join(parts)

    # ------------------------------------------------------------------
    # Doc / meta helpers
    # ------------------------------------------------------------------

    _TYPE_CODES = {"unsigned": 0, "signed": 1, "bool": 2, "float": 3, "double": 4}
    _RW_CODES   = {"r": 0, "w": 1, "rw": 2}

    def _build_doc_data(self):
        """
        Build and cache the four doc/meta tables from the flattened register map.

        Returns (group_nodes, doc_entries, bf_entries, enum_entries).
        Must be called after _flatten().
        """
        if hasattr(self, "_doc_cache"):
            return self._doc_cache

        group_nodes: List[DocGroupNode] = []
        doc_entries: List[DocEntry]     = []
        bf_entries:  List[DocBitField]  = []
        enum_entries: List[DocEnum]     = []

        # Map (tuple-of-group-names) → index in group_nodes
        group_path_to_idx: dict = {}

        def walk_groups(group, parent_idx: int, inst_base: int, parent_path: tuple):
            for item in group.contents.values():
                if isinstance(item, Group):
                    sub_rel  = item.map["address_offset"]
                    sub_base = inst_base + sub_rel
                    g_idx    = len(group_nodes)
                    full_path = parent_path + (item.name,)
                    group_path_to_idx[full_path] = g_idx
                    group_nodes.append(DocGroupNode(
                        name=item.name,
                        desc=item.desc,
                        parent=parent_idx,
                        count=item.count,
                        base_address=sub_base,
                        alignment=item.alignment,
                        address_offset=sub_rel,
                    ))
                    walk_groups(item, g_idx, sub_base, full_path)

        walk_groups(self._reg_map.base_group, -1, 0, ())

        # Build doc entries — one per logical register (deduplicated by id(reg)).
        # Use only bank_idx==0 elements; bank_size is already on the Register object.
        seen_reg_ids: set = set()
        for elem in self._elements:
            if elem.bank_idx != 0:
                continue
            if id(elem.reg) in seen_reg_ids:
                continue
            seen_reg_ids.add(id(elem.reg))

            reg = elem.reg

            # Immediate parent group from ancestor_instances
            if not elem.ancestor_instances:
                group_node_idx = -1
            else:
                anc_path = tuple(name for name, *_ in elem.ancestor_instances)
                group_node_idx = group_path_to_idx.get(anc_path, -1)

            # Enum entries for this register
            enum_start = len(enum_entries)
            for en_name, en_val in reg.enum.items():
                enum_entries.append(DocEnum(name=en_name, value=int(en_val)))
            enum_count = len(enum_entries) - enum_start

            # Bit-field entries for this register
            bf_start = len(bf_entries)
            for _bf_name, bf_reg in reg.bit_field.items():
                bf_enum_start = len(enum_entries)
                for en_name, en_val in bf_reg.enum.items():
                    enum_entries.append(DocEnum(name=en_name, value=int(en_val)))
                bf_enum_count = len(enum_entries) - bf_enum_start
                bf_entries.append(DocBitField(
                    name=_bf_name,
                    desc=bf_reg.desc,
                    starting_bit=bf_reg.map["starting_bit"],
                    width=bf_reg.width,
                    type=bf_reg.type,
                    rw=bf_reg.rw,
                    enum_start=bf_enum_start,
                    enum_count=bf_enum_count,
                ))
            bf_count = len(bf_entries) - bf_start

            has_range   = reg.min_val is not None and reg.max_val is not None
            has_default = reg.default is not None
            doc_entries.append(DocEntry(
                name=reg.name,
                desc=reg.desc,
                unit=reg.unit,
                type=reg.type,
                rw=reg.rw,
                width=reg.width,
                words_per_reg=elem.words_per_reg,
                bank_size=reg.bank_size,
                has_range=has_range,
                min_val=self._word_encode(reg, reg.min_val),
                max_val=self._word_encode(reg, reg.max_val),
                has_default=has_default,
                default_val=self._word_encode(reg, reg.default),
                group_node=group_node_idx,
                offset_in_group=reg.map["address_offset"],
                enum_start=enum_start,
                enum_count=enum_count,
                bf_start=bf_start,
                bf_count=bf_count,
            ))

        self._doc_cache = (group_nodes, doc_entries, bf_entries, enum_entries)
        return self._doc_cache

    def _build_meta_blob(self) -> bytes:
        """
        Build the compact binary metadata blob for host-side enumeration.

        Format (all little-endian):
          Header           38 bytes
          Group records    14 bytes × group_count
          Register records 36 bytes × reg_count
          Bit-field records 10 bytes × bf_count
          Enum records      6 bytes × enum_count
          Driver records    2 bytes × driver_count
          Drv-setting recs  4 bytes × ds_count
          String table      variable (null-terminated strings, deduped)
        """
        import struct as _struct

        group_nodes, doc_entries, bf_entries, enum_entries = self._build_doc_data()
        rm = self._reg_map

        # --- String table -----------------------------------------------
        str_table  = bytearray(b"\x00")   # offset 0 = empty string
        str_map: dict = {"": 0}

        def intern(s: str) -> int:
            s = s or ""
            if s not in str_map:
                str_map[s] = len(str_table)
                str_table.extend(s.encode("utf-8") + b"\x00")
            return str_map[s]

        mod_name_off = intern(rm.name)
        mod_desc_off = intern(getattr(rm, "desc", "") or "")
        bg_desc_off  = intern(rm.base_group.desc or "")

        grp_offs   = [(intern(g.name), intern(g.desc))              for g in group_nodes]
        ent_offs   = [(intern(e.name), intern(e.desc), intern(e.unit)) for e in doc_entries]
        bf_offs    = [(intern(b.name), intern(b.desc))              for b in bf_entries]
        en_offs    = [intern(e.name)                                 for e in enum_entries]
        drv_offs   = [intern(d) for d in rm.compatible_drivers]
        ds_offs    = [(intern(str(k)), intern(str(v))) for k, v in rm.driver_settings.items()]

        # --- Section sizes & offsets ------------------------------------
        HDR = 38; GRP = 14; REG = 36; BF = 10; EN = 6; DRV = 2; DS = 4

        off_grp  = HDR
        off_reg  = off_grp  + GRP * len(group_nodes)
        off_bf   = off_reg  + REG * len(doc_entries)
        off_en   = off_bf   + BF  * len(bf_entries)
        off_drv  = off_en   + EN  * len(enum_entries)
        off_ds   = off_drv  + DRV * len(rm.compatible_drivers)
        off_str  = off_ds   + DS  * len(rm.driver_settings)

        blob = bytearray()

        # Header: I H H I H H H H H H H H H I H
        blob += _struct.pack(
            "<IHHIHHHHHHHHHiH",
            0x41555241,                   # magic 'AURA'
            1,                            # version
            rm.word_width,
            0,                            # total_size (filled below)
            off_str,                      # str_table_off
            len(group_nodes),
            len(doc_entries),
            len(bf_entries),
            len(enum_entries),
            len(rm.compatible_drivers),
            len(rm.driver_settings),
            mod_name_off,
            mod_desc_off,
            rm.base_group.alignment,      # base_group_alignment (int32 → 4 bytes)
            bg_desc_off,
        )

        # Group records: b B H H I I
        for i, g in enumerate(group_nodes):
            no, do = grp_offs[i]
            blob += _struct.pack("<bBHHII",
                g.parent, g.count, no, do,
                g.address_offset, g.alignment)

        # Register records: b B B B H H H H H I I I I B B B B H
        for i, e in enumerate(doc_entries):
            no, do, uo = ent_offs[i]
            flags = (1 if e.has_range else 0) | (2 if e.has_default else 0)
            blob += _struct.pack(
                "<bBBBHHHHHIIIIBBBBH",
                e.group_node,
                self._TYPE_CODES[e.type],
                self._RW_CODES[e.rw],
                flags,
                no, do, uo,
                e.width, e.bank_size,
                e.offset_in_group,
                e.min_val, e.max_val, e.default_val,
                e.bf_start, e.bf_count,
                e.enum_start, e.enum_count,
                0,  # padding
            )

        # Bit-field records: H H B B B B B B
        for i, b in enumerate(bf_entries):
            no, do = bf_offs[i]
            blob += _struct.pack("<HHBBBBBB",
                no, do,
                b.starting_bit, b.width,
                self._TYPE_CODES[b.type],
                self._RW_CODES[b.rw],
                b.enum_start, b.enum_count)

        # Enum records: H I
        for i, e in enumerate(enum_entries):
            blob += _struct.pack("<HI", en_offs[i], e.value)

        # Driver records: H
        for no in drv_offs:
            blob += _struct.pack("<H", no)

        # Driver-settings records: H H
        for ko, vo in ds_offs:
            blob += _struct.pack("<HH", ko, vo)

        # String table
        blob += bytes(str_table)

        # Fix up total_size at offset 8
        _struct.pack_into("<I", blob, 8, len(blob))

        return bytes(blob)

    # ------------------------------------------------------------------
    # Doc header  — <module>_reg_doc.hpp
    # ------------------------------------------------------------------

    def _emit_reg_doc_header(self, output_dir: str):
        """
        <module>_reg_doc.hpp

        Declares the ROM metadata structs and accessor API used by the shell.
        Also declares make_shell_config() which wires up the module's comm
        functions and doc tables into a RegShellConfig.
        """
        p   = self._prefix()
        P   = p.upper()
        ns  = self._ns()
        group_nodes, doc_entries, bf_entries, enum_entries = self._build_doc_data()

        with CppWriter(self._filepath(output_dir, "reg_doc.hpp"), is_header=True) as w:
            w.generated_header("ROM register metadata — doc structs and accessor API for the shell")
            w.pragma_once()
            w.include(f"{p}_reg_comm.hpp")
            w.include("reg_doc_types.hpp")
            w.blank()

            w.separator("Table-size constants")
            w.line(f"constexpr uint16_t {P}_REG_DOC_COUNT       = {len(doc_entries)};")
            w.line(f"constexpr uint8_t  {P}_REG_DOC_GROUP_COUNT = {len(group_nodes)};")
            w.line(f"constexpr uint8_t  {P}_REG_DOC_BF_COUNT    = {len(bf_entries)};")
            w.line(f"constexpr uint16_t {P}_REG_DOC_ENUM_COUNT  = {len(enum_entries)};")
            w.blank()

            w.separator("ROM table declarations")
            w.line(f"extern const RegDocEntry     {p}_reg_doc_entries[{P}_REG_DOC_COUNT];")
            w.line(f"extern const RegDocGroupNode {p}_reg_doc_groups[{P}_REG_DOC_GROUP_COUNT];")
            w.line(f"extern const RegDocBitField  {p}_reg_doc_bitfields[{P}_REG_DOC_BF_COUNT];")
            w.line(f"extern const RegDocEnum      {p}_reg_doc_enums[{P}_REG_DOC_ENUM_COUNT];")
            w.blank()

            w.separator("Accessor functions")
            w.comment("O(n) linear scan — only called on debug/shell paths, not in hot loops.")
            w.line(f"const RegDocEntry* {p}_reg_doc_by_addr(uint16_t addr);")
            w.line(f"uint8_t            {p}_reg_doc_word_bytes();")
            w.blank()

            w.separator("Shell config factory")
            w.comment("Wires this module's comm functions and doc tables into a RegShellConfig.")
            w.comment("Include reg_shell.hpp before calling this.")
            w.line("struct RegShellConfig;")
            w.line(f"RegShellConfig {p}_make_shell_config(void (*putc_fn)(char c),")
            w.line(f"                                      const char* prompt = nullptr);")
            w.blank()

    # ------------------------------------------------------------------
    # Doc source — <module>_reg_doc.cpp
    # ------------------------------------------------------------------

    def _emit_reg_doc_source(self, output_dir: str):
        """
        <module>_reg_doc.cpp

        ROM string pointer arrays + struct tables + accessor implementations
        + make_shell_config() factory body.
        """
        p  = self._prefix()
        P  = p.upper()
        ns = self._ns()
        wt = self._word_type
        group_nodes, doc_entries, bf_entries, enum_entries = self._build_doc_data()

        def c_str(s: str) -> str:
            s = (s or "").replace("\\", "\\\\").replace('"', '\\"')
            return f'"{s}"'

        def type_code(t: str) -> str:
            return f"RegDocType::{t.upper()}"

        with CppWriter(self._filepath(output_dir, "reg_doc.cpp"), is_header=False) as w:
            w.generated_header("ROM register metadata — string tables, struct tables, and accessors")
            w.include(f"{p}_reg_doc.hpp")
            w.include(f"{p}_reg_comm.hpp")
            w.include("reg_shell.hpp")
            w.include("cstring", system=True)
            w.blank()

            # --- String pointer arrays -----------------------------------
            if doc_entries:
                w.separator("Register string tables (.rodata)")
                w.line(f"static const char* const _reg_names[{P}_REG_DOC_COUNT] = {{")
                with w.indented():
                    for e in doc_entries:
                        w.line(f"{c_str(e.name)},")
                w.line("};")
                w.blank()
                w.line(f"static const char* const _reg_descs[{P}_REG_DOC_COUNT] = {{")
                with w.indented():
                    for e in doc_entries:
                        w.line(f"{c_str(e.desc)},")
                w.line("};")
                w.blank()
                w.line(f"static const char* const _reg_units[{P}_REG_DOC_COUNT] = {{")
                with w.indented():
                    for e in doc_entries:
                        w.line(f"{c_str(e.unit)},")
                w.line("};")
                w.blank()

            if bf_entries:
                w.separator("Bit-field string tables (.rodata)")
                w.line(f"static const char* const _bf_names[{P}_REG_DOC_BF_COUNT] = {{")
                with w.indented():
                    for b in bf_entries:
                        w.line(f"{c_str(b.name)},")
                w.line("};")
                w.blank()
                w.line(f"static const char* const _bf_descs[{P}_REG_DOC_BF_COUNT] = {{")
                with w.indented():
                    for b in bf_entries:
                        w.line(f"{c_str(b.desc)},")
                w.line("};")
                w.blank()

            if enum_entries:
                w.separator("Enum name table (.rodata)")
                w.line(f"static const char* const _enum_names[{P}_REG_DOC_ENUM_COUNT] = {{")
                with w.indented():
                    for e in enum_entries:
                        w.line(f"{c_str(e.name)},")
                w.line("};")
                w.blank()

            if group_nodes:
                w.separator("Group name table (.rodata)")
                w.line(f"static const char* const _grp_names[{P}_REG_DOC_GROUP_COUNT] = {{")
                with w.indented():
                    for g in group_nodes:
                        w.line(f"{c_str(g.name)},")
                w.line("};")
                w.blank()

            # --- Enum table ----------------------------------------------
            if enum_entries:
                w.separator("Enum value table")
                w.line(f"const RegDocEnum {p}_reg_doc_enums[{P}_REG_DOC_ENUM_COUNT] = {{")
                with w.indented():
                    for i, e in enumerate(enum_entries):
                        w.line(f"{{ _enum_names[{i}], {e.value}u }},")
                w.line("};")
                w.blank()
            else:
                w.line(f"const RegDocEnum {p}_reg_doc_enums[1] = {{}};")
                w.blank()

            # --- Bit-field table -----------------------------------------
            if bf_entries:
                w.separator("Bit-field table")
                w.line(f"const RegDocBitField {p}_reg_doc_bitfields[{P}_REG_DOC_BF_COUNT] = {{")
                with w.indented():
                    for i, b in enumerate(bf_entries):
                        w.line(
                            f"{{ _bf_names[{i}], _bf_descs[{i}],"
                            f" {b.starting_bit}, {b.width},"
                            f" {type_code(b.type)}, {self._RW_CODES[b.rw]},"
                            f" {b.enum_start}, {b.enum_count} }},"
                        )
                w.line("};")
                w.blank()
            else:
                w.line(f"const RegDocBitField {p}_reg_doc_bitfields[1] = {{}};")
                w.blank()

            # --- Group node table ----------------------------------------
            if group_nodes:
                w.separator("Group node table")
                w.line(f"const RegDocGroupNode {p}_reg_doc_groups[{P}_REG_DOC_GROUP_COUNT] = {{")
                with w.indented():
                    for i, g in enumerate(group_nodes):
                        w.line(
                            f"{{ _grp_names[{i}], {g.parent}, {g.count},"
                            f" {g.base_address}u, {g.alignment}u }},"
                        )
                w.line("};")
                w.blank()
            else:
                w.line(f"const RegDocGroupNode {p}_reg_doc_groups[1] = {{}};")
                w.blank()

            # --- Entry table ---------------------------------------------
            w.separator("Register entry table")
            if doc_entries:
                w.line(f"const RegDocEntry {p}_reg_doc_entries[{P}_REG_DOC_COUNT] = {{")
                with w.indented():
                    for i, e in enumerate(doc_entries):
                        hr = "true" if e.has_range else "false"
                        w.line(
                            f"{{ _reg_names[{i}], _reg_descs[{i}], _reg_units[{i}],"
                            f" {type_code(e.type)}, {self._RW_CODES[e.rw]},"
                            f" {e.width}, {e.words_per_reg}, {e.bank_size},"
                            f" {hr}, {e.min_val}u, {e.max_val}u,"
                            f" {e.group_node}, {e.offset_in_group}u,"
                            f" {e.enum_start}, {e.enum_count},"
                            f" {e.bf_start}, {e.bf_count} }},"
                        )
                w.line("};")
            else:
                w.line(f"const RegDocEntry {p}_reg_doc_entries[1] = {{}};")
            w.blank()

            # --- Accessor functions --------------------------------------
            w.separator("Accessor functions")
            w.comment("Returns the first entry whose base address covers `addr`.")
            w.open_function(f"const RegDocEntry* {p}_reg_doc_by_addr(uint16_t addr)")
            if doc_entries:
                w.open_brace(f"for (uint16_t i = 0; i < {P}_REG_DOC_COUNT; ++i)")
                w.line(f"const RegDocEntry& e = {p}_reg_doc_entries[i];")
                w.line("uint16_t end = (uint16_t)(e.offset_in_group")
                w.line("    + (e.group_node >= 0 ?")
                w.line(f"       {p}_reg_doc_groups[e.group_node].base_address : 0u)")
                w.line("    + e.bank_size * e.words_per_reg);")
                w.line("uint16_t base = (uint16_t)(e.offset_in_group")
                w.line("    + (e.group_node >= 0 ?")
                w.line(f"       {p}_reg_doc_groups[e.group_node].base_address : 0u));")
                w.open_brace("if (addr >= base && addr < end)")
                w.line(f"return &{p}_reg_doc_entries[i];")
                w.close_brace()
                w.close_brace()
            w.line("return nullptr;")
            w.close_function()
            w.blank()

            w.open_function(f"uint8_t {p}_reg_doc_word_bytes()")
            w.line(f"return static_cast<uint8_t>(sizeof({ns}::word_t));")
            w.close_function()
            w.blank()

            # --- make_shell_config factory --------------------------------
            w.separator("Shell config factory")
            wb = self._word_width // 8  # word_bytes

            # Trampoline functions for comm callbacks (uint32_t* ↔ word_t*)
            if self._word_width == 32:
                w.line("static uint8_t _shell_read(uint16_t a, uint32_t* o, uint16_t c) {")
                w.line(f"    return static_cast<uint8_t>({ns}::reg_read(a, o, c));")
                w.line("}")
                w.line("static uint8_t _shell_write(uint16_t a, const uint32_t* d, uint16_t c) {")
                w.line(f"    return static_cast<uint8_t>({ns}::reg_write(a, d, c));")
                w.line("}")
            else:
                # For 8/16-bit word_t: copy through a small stack buffer
                w.line("static uint8_t _shell_read(uint16_t a, uint32_t* o, uint16_t c) {")
                w.line(f"    {wt} tmp[c];")
                w.line(f"    uint8_t s = static_cast<uint8_t>({ns}::reg_read(a, tmp, c));")
                w.line("    if (s <= 2u) for (uint16_t i = 0; i < c; ++i) o[i] = tmp[i];")
                w.line("    return s;")
                w.line("}")
                w.line("static uint8_t _shell_write(uint16_t a, const uint32_t* d, uint16_t c) {")
                w.line(f"    {wt} tmp[c];")
                w.line("    for (uint16_t i = 0; i < c; ++i)")
                w.line(f"        tmp[i] = static_cast<{wt}>(d[i]);")
                w.line(f"    return static_cast<uint8_t>({ns}::reg_write(a, tmp, c));")
                w.line("}")
            w.blank()

            w.open_function(
                f"RegShellConfig {p}_make_shell_config("
                "void (*putc_fn)(char c), const char* prompt)"
            )
            w.line("RegShellConfig cfg;")
            w.line("cfg.reg_read  = _shell_read;")
            w.line("cfg.reg_write = _shell_write;")
            w.line(f"cfg.reg_reset = {ns}::reg_reset;")
            w.line(f"cfg.entries     = {p}_reg_doc_entries;")
            w.line(f"cfg.entry_count = {P}_REG_DOC_COUNT;")
            w.line(f"cfg.groups      = {p}_reg_doc_groups;")
            w.line(f"cfg.group_count = {P}_REG_DOC_GROUP_COUNT;")
            w.line(f"cfg.bitfields   = {p}_reg_doc_bitfields;")
            w.line(f"cfg.enums       = {p}_reg_doc_enums;")
            w.line(f"cfg.word_bytes  = {wb};")
            w.line("cfg.putc_fn     = putc_fn;")
            w.line("cfg.prompt      = prompt;")
            w.line("return cfg;")
            w.close_function()

    # ------------------------------------------------------------------
    # Meta header — <module>_reg_meta.hpp
    # ------------------------------------------------------------------

    def _emit_reg_meta_header(self, output_dir: str):
        """
        <module>_reg_meta.hpp

        Declares the ROM metadata blob size and the meta_read() byte-stream
        accessor used by the binary protocol's CMD_META_READ command.
        """
        p  = self._prefix()
        P  = p.upper()
        ns = self._ns()
        blob = self._build_meta_blob()

        with CppWriter(self._filepath(output_dir, "reg_meta.hpp"), is_header=True) as w:
            w.generated_header(
                "ROM metadata blob — compact binary stream for host-side register enumeration"
            )
            w.pragma_once()
            w.include("cstdint", system=True)
            w.blank()

            w.open_namespace(ns)
            w.blank()

            w.line(f"constexpr uint16_t REG_META_SIZE = {len(blob)}u;")
            w.blank()

            w.comment("Read `count` raw bytes from the metadata blob starting at byte `offset`.")
            w.comment("Returns 0 on success, 1 if offset + count > REG_META_SIZE.")
            w.line("uint8_t meta_read(uint16_t offset, uint8_t* out, uint16_t count);")
            w.blank()

            w.close_namespace(ns)

    # ------------------------------------------------------------------
    # Meta source — <module>_reg_meta.cpp
    # ------------------------------------------------------------------

    def _emit_reg_meta_source(self, output_dir: str):
        """
        <module>_reg_meta.cpp

        The binary metadata blob as a ROM byte array, plus the meta_read()
        implementation (trivial memcpy with bounds check).
        """
        p   = self._prefix()
        ns  = self._ns()
        blob = self._build_meta_blob()

        with CppWriter(self._filepath(output_dir, "reg_meta.cpp"), is_header=False) as w:
            w.generated_header(
                "ROM metadata blob — serves host-side register enumeration via CMD_META_READ"
            )
            w.include(f"{p}_reg_meta.hpp")
            w.include("cstring", system=True)
            w.blank()

            w.open_namespace(ns)
            w.blank()

            # Emit blob as a hex byte array, 16 bytes per line
            w.separator("Metadata byte stream (ROM)")
            w.line(f"static const uint8_t _meta_blob[REG_META_SIZE] = {{")
            with w.indented():
                for i in range(0, len(blob), 16):
                    chunk = blob[i:i+16]
                    hex_str = ", ".join(f"0x{b:02X}" for b in chunk)
                    w.line(f"{hex_str},")
            w.line("};")
            w.blank()

            w.separator("meta_read")
            w.open_function("uint8_t meta_read(uint16_t offset, uint8_t* out, uint16_t count)")
            w.open_brace("if (static_cast<uint32_t>(offset) + count > REG_META_SIZE)")
            w.line("return 1u;")
            w.close_brace()
            w.line("memcpy(out, _meta_blob + offset, count);")
            w.line("return 0u;")
            w.close_function()
            w.blank()

            w.close_namespace(ns)

    def _rw_to_access(self, rw: str) -> str:
        return {
            "r":  "RegAccess::READ",
            "w":  "RegAccess::WRITE",
            "rw": "RegAccess::READ_WRITE",
        }[rw]

    def _emit_reg_doc(self, w: CppWriter, reg, headline: str):
        """Emit a documentation comment block for a register or bit-field."""
        w.comment(headline)
        if reg.desc:
            w.comment(f"  {reg.desc}")
        meta = []
        if reg.unit:
            meta.append(f"unit={reg.unit}")
        if reg.min_val is not None:
            meta.append(f"min={reg.min_val}")
        if reg.max_val is not None:
            meta.append(f"max={reg.max_val}")
        if reg.default is not None:
            meta.append(f"default={reg.default}")
        if meta:
            w.comment(f"  {', '.join(meta)}")
        if getattr(reg, "bit_field", None):
            fields_str = ", ".join(
                f"{fn}[{f.starting_bit + f.width - 1}:{f.starting_bit}]"
                for fn, f in reg.bit_field.items()
            )
            w.comment(f"  Fields: {fields_str}")

    def _word_encode(self, reg, value) -> int:
        """Encode a Python scalar as a word_t bit pattern for the given register type."""
        if value is None:
            return 0
        mask = (1 << self._word_width) - 1
        t = reg.type
        if t in ("bool", "unsigned", "signed"):
            return int(value) & mask
        if t == "float" and self._word_width == 32:
            import struct
            return struct.unpack("<I", struct.pack("<f", float(value)))[0]
        return 0

    def _words_encode(self, reg, value, valid_words: int):
        """Encode a Python scalar as a list of word_t bit patterns (little-endian, word[0] = LSB).

        Returns None if value is None or the type is unsupported.
        """
        if value is None:
            return None
        import struct
        mask = (1 << self._word_width) - 1
        t = reg.type
        if t in ("bool", "unsigned"):
            raw = int(value)
            return [(raw >> (i * self._word_width)) & mask for i in range(valid_words)]
        if t == "signed":
            raw = int(value)
            if raw < 0:
                raw += (1 << reg.width)  # two's complement in actual register width, not full word
            return [(raw >> (i * self._word_width)) & mask for i in range(valid_words)]
        if t == "float" and self._word_width == 32:
            bits = struct.unpack("<I", struct.pack("<f", float(value)))[0]
            return [bits]
        if t == "double":
            bits = struct.unpack("<Q", struct.pack("<d", float(value)))[0]
            return [(bits >> (i * self._word_width)) & mask for i in range(valid_words)]
        return None

    def _reg_type_cpp(self, reg) -> str:
        """Return the RegType enum value for a register's declared type."""
        return {
            "unsigned": "RegType::UNSIGNED",
            "bool":     "RegType::UNSIGNED",
            "signed":   "RegType::SIGNED",
            "float":    "RegType::FLOAT",
            "double":   "RegType::DOUBLE",
        }.get(reg.type, "RegType::UNSIGNED")

    def _ns(self) -> str:
        """C++ namespace that wraps all generated symbols."""
        return f"{self._module_name}_regs"

    def _prefix(self) -> str:
        """File name prefix and C symbol prefix."""
        return self._module_name

    def _filepath(self, output_dir: str, suffix: str) -> str:
        return os.path.join(output_dir, f"{self._prefix()}_{suffix}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    rm = RegisterMapGenerator.fromJSON(
        os.path.join(os.path.dirname(__file__), "..", "register-mapper", "test.json")
    )
    gen = FirmwareGenerator(rm)
    gen.generate(os.path.join(os.path.dirname(__file__), "output"))
    print("Generation complete.")
