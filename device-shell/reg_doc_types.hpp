/*
 * reg_doc_types.hpp — Shared ROM metadata struct definitions.
 *
 * Included by reg_shell.hpp (so the shell can use complete types) and by
 * generated <mod>_reg_doc.hpp (so the ROM tables use the same layout).
 * Never include the generated header before this one.
 */

#pragma once

#include <cstdint>

enum class RegDocType : uint8_t {
    UNSIGNED = 0,
    SIGNED   = 1,
    BOOL     = 2,
    FLOAT    = 3,
    DOUBLE   = 4,
};

struct RegDocEnum {
    const char* name;
    uint32_t    value;
};

struct RegDocBitField {
    const char* name;
    const char* desc;
    uint8_t     starting_bit;
    uint8_t     width;
    RegDocType  type;
    uint8_t     rw;
    uint8_t     enum_start;
    uint8_t     enum_count;
};

struct RegDocEntry {
    const char* name;
    const char* desc;
    const char* unit;
    RegDocType  type;
    uint8_t     access;           // 0=r  1=w  2=rw
    uint16_t    width_bits;
    uint8_t     words_per_reg;
    uint16_t    bank_size;
    bool        has_range;
    uint32_t    min_val;
    uint32_t    max_val;
    int8_t      group_node;       // index in group table; -1 = root
    uint16_t    offset_in_group;  // word offset from group base_address[inst=0]
    uint8_t     enum_start;
    uint8_t     enum_count;
    uint8_t     bf_start;
    uint8_t     bf_count;
};

struct RegDocGroupNode {
    const char* name;
    int8_t      parent;       // -1 = direct child of base_group
    uint8_t     count;        // instance count
    uint32_t    base_address; // absolute word address of instance[0]
    uint32_t    alignment;    // word stride per instance
};
