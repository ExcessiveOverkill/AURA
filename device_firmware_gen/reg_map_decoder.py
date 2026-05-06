"""
reg_map_decoder.py — Reconstruct a RegisterMapGenerator from a firmware meta blob.

The meta blob is produced by FirmwareGenerator._build_meta_blob() and served
over the binary protocol via CMD_META_READ (0x05).  Call RegMapDecoder.from_bytes()
to parse it back into a RegisterMapGenerator that is identical to the one that
generated the firmware.
"""

import struct

from register_mapper import Group, Register, RegisterMapGenerator


_MAGIC   = 0x41555241   # 'AURA'
_VERSION = 1

_TYPE_NAMES = {0: "unsigned", 1: "signed", 2: "bool", 3: "float", 4: "double"}
_RW_NAMES   = {0: "r", 1: "w", 2: "rw"}

# Record sizes matching _build_meta_blob()
_HDR = 38
_GRP = 14
_REG = 36
_BF  = 10
_EN  =  6
_DRV =  2
_DS  =  4


class RegMapDecoder:
    """Reconstructs a RegisterMapGenerator from a firmware meta blob."""

    @staticmethod
    def from_bytes(data: bytes) -> RegisterMapGenerator:
        if len(data) < _HDR:
            raise ValueError("Meta blob too short for header")

        (magic, version, word_width, total_size, str_table_off,
         group_count, reg_count, bf_count, enum_count,
         driver_count, ds_count,
         mod_name_off, mod_desc_off, base_group_alignment, bg_desc_off
         ) = struct.unpack_from("<IHHIHHHHHHHHHiH", data, 0)

        if magic != _MAGIC:
            raise ValueError(f"Bad magic: 0x{magic:08X} (expected 0x{_MAGIC:08X})")
        if version != _VERSION:
            raise ValueError(f"Unsupported version: {version}")
        if total_size != len(data):
            raise ValueError(f"total_size {total_size} != actual {len(data)}")

        # --- String table helper -----------------------------------------
        def read_str(off: int) -> str:
            if off == 0:
                return ""
            start = str_table_off + off
            end   = data.index(b"\x00", start)
            return data[start:end].decode("utf-8")

        # --- Section offsets ---------------------------------------------
        off_grp = _HDR
        off_reg = off_grp + _GRP * group_count
        off_bf  = off_reg + _REG * reg_count
        off_en  = off_bf  + _BF  * bf_count
        off_drv = off_en  + _EN  * enum_count
        off_ds  = off_drv + _DRV * driver_count

        # --- Compatible drivers ------------------------------------------
        compatible_drivers = []
        for i in range(driver_count):
            (name_off,) = struct.unpack_from("<H", data, off_drv + i * _DRV)
            compatible_drivers.append(read_str(name_off))

        # --- Driver settings ---------------------------------------------
        driver_settings = {}
        for i in range(ds_count):
            key_off, val_off = struct.unpack_from("<HH", data, off_ds + i * _DS)
            driver_settings[read_str(key_off)] = read_str(val_off)

        # --- Enum records (global flat list) -----------------------------
        enum_records = []
        for i in range(enum_count):
            en_name_off, en_value = struct.unpack_from("<HI", data, off_en + i * _EN)
            enum_records.append((read_str(en_name_off), en_value))

        # --- Bit-field records (global flat list) ------------------------
        bf_records = []
        for i in range(bf_count):
            (bf_no, bf_do, starting_bit, width,
             type_code, rw_code,
             bf_enum_start, bf_enum_count
             ) = struct.unpack_from("<HHBBBBBB", data, off_bf + i * _BF)
            bf_records.append({
                "name":         read_str(bf_no),
                "desc":         read_str(bf_do),
                "starting_bit": starting_bit,
                "width":        width,
                "type":         _TYPE_NAMES[type_code],
                "rw":           _RW_NAMES[rw_code],
                "enum_start":   bf_enum_start,
                "enum_count":   bf_enum_count,
            })

        # --- Group records -----------------------------------------------
        group_records = []
        for i in range(group_count):
            (parent, count, g_name_off, g_desc_off,
             address_offset, alignment
             ) = struct.unpack_from("<bBHHII", data, off_grp + i * _GRP)
            group_records.append({
                "name":           read_str(g_name_off),
                "desc":           read_str(g_desc_off),
                "parent":         parent,
                "count":          count,
                "address_offset": address_offset,
                "alignment":      alignment,
            })

        # --- Register records --------------------------------------------
        reg_records = []
        for i in range(reg_count):
            (group_node, type_code, rw_code, flags,
             r_name_off, r_desc_off, r_unit_off,
             width_bits, bank_size,
             address_offset,
             min_val, max_val, default_val,
             bf_start, bf_count_r, enum_start, enum_count_r,
             _padding
             ) = struct.unpack_from("<bBBBHHHHHIIIIBBBBH", data, off_reg + i * _REG)

            has_range   = bool(flags & 1)
            has_default = bool(flags & 2)
            reg_records.append({
                "name":           read_str(r_name_off),
                "desc":           read_str(r_desc_off),
                "unit":           read_str(r_unit_off),
                "type":           _TYPE_NAMES[type_code],
                "rw":             _RW_NAMES[rw_code],
                "width":          width_bits,
                "bank_size":      bank_size,
                "address_offset": address_offset,
                "group_node":     group_node,
                "min_val":        min_val if has_range   else None,
                "max_val":        max_val if has_range   else None,
                "default_val":    default_val if has_default else None,
                "bf_start":       bf_start,
                "bf_count":       bf_count_r,
                "enum_start":     enum_start,
                "enum_count":     enum_count_r,
            })

        # --- Build RegisterMapGenerator ----------------------------------
        mod_name = read_str(mod_name_off)
        mod_desc = read_str(mod_desc_off)

        rm = RegisterMapGenerator(
            name=mod_name,
            compatible_drivers=compatible_drivers,
            driver_settings=driver_settings,
            desc=mod_desc,
            word_width=word_width,
        )
        rm.base_group.desc = read_str(bg_desc_off)

        # Build group objects indexed by position in group_records
        group_objs = []
        for gr in group_records:
            g = Group(
                name=gr["name"],
                address_offset=gr["address_offset"],
                description=gr["desc"],
                alignment=gr["alignment"],
                count=gr["count"],
            )
            group_objs.append(g)

        # Establish parent→children nesting (parent=-1 → add directly to base_group)
        # We need to add children after parent Group objects are fully built.
        # Collect children lists keyed by parent index (-1 = base_group).
        from collections import defaultdict
        children_by_parent: dict = defaultdict(list)
        for i, gr in enumerate(group_records):
            children_by_parent[gr["parent"]].append(i)

        # Recursively attach groups to their parents
        def attach_groups(parent_group, parent_idx: int):
            for child_idx in children_by_parent[parent_idx]:
                child_obj = group_objs[child_idx]
                parent_group.add(child_obj)
                attach_groups(child_obj, child_idx)

        attach_groups(rm.base_group, -1)

        # --- Attach registers to their groups ----------------------------
        for rr in reg_records:
            # Build enum dict
            enum_dict = {}
            for j in range(rr["enum_start"], rr["enum_start"] + rr["enum_count"]):
                en_name, en_val = enum_records[j]
                enum_dict[en_name] = en_val

            # Build bit_field dict (sub-Register objects)
            bit_field = {}
            for j in range(rr["bf_start"], rr["bf_start"] + rr["bf_count"]):
                bf = bf_records[j]
                bf_enum = {}
                for k in range(bf["enum_start"], bf["enum_start"] + bf["enum_count"]):
                    be_name, be_val = enum_records[k]
                    bf_enum[be_name] = be_val
                sub_reg = Register(
                    name=bf["name"],
                    address_offset=rr["address_offset"],
                    type=bf["type"],
                    bank_size=1,
                    description=bf["desc"],
                    width=bf["width"],
                    word_width=word_width,
                    starting_bit=bf["starting_bit"],
                    bit_field={},
                    enum=bf_enum,
                    min=None,
                    max=None,
                    default_val=None,
                    unit="",
                    rw=bf["rw"],
                )
                bit_field[bf["name"]] = sub_reg

            reg_obj = Register(
                name=rr["name"],
                address_offset=rr["address_offset"],
                type=rr["type"],
                bank_size=rr["bank_size"],
                description=rr["desc"],
                width=rr["width"],
                word_width=word_width,
                starting_bit=0,
                bit_field=bit_field,
                enum=enum_dict,
                min=rr["min_val"],
                max=rr["max_val"],
                default_val=rr["default_val"],
                unit=rr["unit"],
                rw=rr["rw"],
            )

            # Add to the correct group (or base_group if group_node == -1)
            gn = rr["group_node"]
            if gn == -1:
                rm.base_group.add(reg_obj)
            else:
                group_objs[gn].add(reg_obj)

        return rm

    @staticmethod
    def from_device(probe) -> RegisterMapGenerator:
        """Read the meta blob from a connected RegProbe and reconstruct the map."""
        return RegMapDecoder.from_bytes(probe.read_full_meta())
