/*
 * reg_shell.cpp — Generic UART register shell implementation.
 *
 * Include <mod>_reg_doc.hpp and reg_shell.hpp before this translation unit.
 * Compile alongside <mod>_reg_doc.cpp and <mod>_reg_comm.cpp.
 */

#include "reg_shell.hpp"

// Pull in doc struct definitions
#include <cstdint>
#include <cstring>
#include <cstdio>   // snprintf
#include <cstdlib>  // strtoul, strtod

// We need the RegDocEntry/GroupNode/BitField/Enum types at definition time.
// They are declared in the generated <mod>_reg_doc.hpp.  To keep this file
// generic we forward-declare the common field layout here; it must match.

// RegDocType codes (must match generated header)
static constexpr uint8_t _DOC_TYPE_UNSIGNED = 0;
static constexpr uint8_t _DOC_TYPE_SIGNED   = 1;
static constexpr uint8_t _DOC_TYPE_BOOL     = 2;
static constexpr uint8_t _DOC_TYPE_FLOAT    = 3;
static constexpr uint8_t _DOC_TYPE_DOUBLE   = 4;

// We rely on the generated header having been included before this TU.
// Confirm the structs are complete by accessing their fields directly.

// ---------------------------------------------------------------------------
// init
// ---------------------------------------------------------------------------

void RegShell::init(const RegShellConfig& cfg) {
    _cfg = cfg;
    _len = 0; _cur = 0;
    _hist_head = 0; _hist_count = 0; _hist_pos = -1;
    _esc = Esc::NONE;
    _show_prompt();
}

// ---------------------------------------------------------------------------
// Output helpers
// ---------------------------------------------------------------------------

void RegShell::_puts(const char* s) {
    while (*s) _putc(*s++);
}

void RegShell::_putu32(uint32_t v) {
    char buf[12];
    snprintf(buf, sizeof(buf), "%lu", (unsigned long)v);
    _puts(buf);
}

void RegShell::_puti32(int32_t v) {
    char buf[13];
    snprintf(buf, sizeof(buf), "%ld", (long)v);
    _puts(buf);
}

void RegShell::_putf(float v) {
    char buf[20];
    snprintf(buf, sizeof(buf), "%f", (double)v);
    _puts(buf);
}

void RegShell::_putx32(uint32_t v) {
    char buf[11];
    snprintf(buf, sizeof(buf), "0x%08lX", (unsigned long)v);
    _puts(buf);
}

// ---------------------------------------------------------------------------
// Line editing
// ---------------------------------------------------------------------------

void RegShell::_show_prompt() {
    _puts(_cfg.prompt ? _cfg.prompt : "> ");
}

void RegShell::_erase_line() {
    // Move cursor to start, overwrite with spaces, return
    for (uint8_t i = 0; i < _len + (uint8_t)(_cfg.prompt ? strlen(_cfg.prompt) : 2); ++i)
        _putc('\b');
    const char* p = _cfg.prompt ? _cfg.prompt : "> ";
    uint8_t plen = (uint8_t)strlen(p);
    for (uint8_t i = 0; i < _len + plen; ++i)
        _putc(' ');
    for (uint8_t i = 0; i < _len + plen; ++i)
        _putc('\b');
    _show_prompt();
    _len = 0; _cur = 0;
    _line[0] = '\0';
}

void RegShell::_history_push(const char* line) {
    if (!line[0]) return;
    // Don't push duplicate of most recent
    if (_hist_count > 0 && strcmp(_hist[_hist_head], line) == 0) return;
    _hist_head = (_hist_head + 1) % SHELL_HISTORY_DEPTH;
    strncpy(_hist[_hist_head], line, SHELL_LINE_LEN);
    _hist[_hist_head][SHELL_LINE_LEN] = '\0';
    if (_hist_count < SHELL_HISTORY_DEPTH) ++_hist_count;
}

void RegShell::_history_navigate(int delta) {
    if (_hist_count == 0) return;
    int new_pos = _hist_pos + delta;
    if (new_pos < 0) {
        // Newer than oldest entry — return to empty line
        _hist_pos = -1;
        _erase_line();
        return;
    }
    if (new_pos >= _hist_count) return;  // nothing older
    _hist_pos = new_pos;

    // Find the history entry (hist_head - hist_pos wraps around)
    int idx = (_hist_head - _hist_pos + SHELL_HISTORY_DEPTH) % SHELL_HISTORY_DEPTH;
    const char* entry = _hist[idx];

    // Erase current line and redraw with history entry
    _erase_line();
    _puts(entry);
    uint8_t n = (uint8_t)strlen(entry);
    if (n > SHELL_LINE_LEN) n = SHELL_LINE_LEN;
    memcpy(_line, entry, n);
    _line[n] = '\0';
    _len = n; _cur = n;
}

// ---------------------------------------------------------------------------
// TAB completion
// ---------------------------------------------------------------------------

void RegShell::_handle_tab() {
    // Complete the last path segment in the line buffer.
    // We look for the longest prefix of a path segment that matches one or
    // more known names (registers or group names at the appropriate level).
    // If exactly one match: complete it.  If multiple: print all and redisplay.

    // Find the last '.' separator (or start of line)
    int sep = -1;
    for (int i = _len - 1; i >= 0; --i) {
        if (_line[i] == '.') { sep = i; break; }
        if (_line[i] == ' ') { sep = i; break; }
    }
    const char* prefix = _line + sep + 1;
    uint8_t prefix_len = (uint8_t)(_len - (sep + 1));

    // Collect matches: register names and group names
    static const char* matches[32];
    uint8_t match_count = 0;

    // Check register names
    for (uint16_t i = 0; i < _cfg.entry_count && match_count < 32; ++i) {
        const char* n = _cfg.entries[i].name;
        if (strncmp(n, prefix, prefix_len) == 0)
            matches[match_count++] = n;
    }
    // Check group names
    for (uint8_t i = 0; i < _cfg.group_count && match_count < 32; ++i) {
        const char* n = _cfg.groups[i].name;
        // Deduplicate
        bool dup = false;
        for (uint8_t j = 0; j < match_count; ++j)
            if (strcmp(matches[j], n) == 0) { dup = true; break; }
        if (!dup && strncmp(n, prefix, prefix_len) == 0)
            matches[match_count++] = n;
    }

    if (match_count == 0) {
        // No match — bell
        _putc('\a');
        return;
    }
    if (match_count == 1) {
        // Complete the segment
        const char* full = matches[0];
        uint8_t add_len = (uint8_t)(strlen(full) - prefix_len);
        if (_len + add_len > SHELL_LINE_LEN) return;
        for (uint8_t i = 0; i < add_len; ++i) {
            char c = full[prefix_len + i];
            _line[_len++] = c;
            _putc(c);
        }
        _line[_len] = '\0';
        _cur = _len;
    } else {
        // Print all matches below the current line
        _puts("\r\n");
        for (uint8_t i = 0; i < match_count; ++i) {
            _puts(matches[i]);
            _putc(' ');
        }
        _puts("\r\n");
        _show_prompt();
        _puts(_line);
    }
}

// ---------------------------------------------------------------------------
// feed — main byte handler
// ---------------------------------------------------------------------------

void RegShell::feed(char c) {
    // VT100 escape sequence state machine
    if (_esc == Esc::ESC) {
        if (c == '[') { _esc = Esc::BRACKET; return; }
        _esc = Esc::NONE;
        return;
    }
    if (_esc == Esc::BRACKET) {
        _esc = Esc::NONE;
        if (c == 'A') { _history_navigate(+1); return; }  // up
        if (c == 'B') { _history_navigate(-1); return; }  // down
        return;
    }

    if (c == '\x1B') { _esc = Esc::ESC; return; }

    // Ctrl+C — cancel line
    if (c == '\x03') {
        _puts("^C\r\n");
        _len = 0; _cur = 0; _line[0] = '\0';
        _hist_pos = -1;
        _show_prompt();
        return;
    }

    // TAB
    if (c == '\t') { _handle_tab(); return; }

    // Backspace / DEL
    if (c == '\b' || c == '\x7F') {
        if (_len > 0) {
            --_len; _cur = _len;
            _line[_len] = '\0';
            _putc('\b'); _putc(' '); _putc('\b');
        }
        return;
    }

    // Line end: \r, \n, or \r\n
    if (c == '\r' || c == '\n') {
        _puts("\r\n");
        _line[_len] = '\0';
        _history_push(_line);
        _hist_pos = -1;
        _accept_line();
        _len = 0; _cur = 0; _line[0] = '\0';
        _show_prompt();
        return;
    }

    // Printable
    if (c >= 0x20 && c < 0x7F) {
        if (_len < SHELL_LINE_LEN) {
            _line[_len++] = c;
            _cur = _len;
            _line[_len] = '\0';
            _putc(c);   // local echo
        }
    }
}

// ---------------------------------------------------------------------------
// accept_line — tokenise and dispatch
// ---------------------------------------------------------------------------

void RegShell::_accept_line() {
    // Trim leading whitespace
    const char* p = _line;
    while (*p == ' ') ++p;
    if (!*p) return;

    // Split into command and arguments (max 3 tokens)
    static char tokens[3][SHELL_LINE_LEN + 1];
    uint8_t tc = 0;
    const char* src = p;
    while (*src && tc < 3) {
        while (*src == ' ') ++src;
        if (!*src) break;
        uint8_t i = 0;
        while (*src && *src != ' ' && i < SHELL_LINE_LEN)
            tokens[tc][i++] = *src++;
        tokens[tc][i] = '\0';
        ++tc;
    }
    if (tc == 0) return;

    const char* cmd = tokens[0];
    const char* arg1 = tc > 1 ? tokens[1] : "";
    const char* arg2 = tc > 2 ? tokens[2] : "";

    _dispatch(cmd);
    (void)arg1; (void)arg2;  // suppress unused — dispatch uses tokens[] directly

    // Re-dispatch with args for commands that need them
    if (strcmp(cmd, "r") == 0 || strcmp(cmd, "read") == 0)
        { _cmd_read(arg1); return; }
    if (strcmp(cmd, "w") == 0 || strcmp(cmd, "write") == 0)
        { _cmd_write(arg1, arg2); return; }
    if (strcmp(cmd, "d") == 0 || strcmp(cmd, "describe") == 0)
        { _cmd_describe(arg1); return; }
    if (strcmp(cmd, "ls") == 0 || strcmp(cmd, "list") == 0)
        { _cmd_ls(arg1); return; }
}

void RegShell::_dispatch(const char* cmd) {
    if (strcmp(cmd, "help") == 0 || strcmp(cmd, "?") == 0)
        { _cmd_help(); return; }
    if (strcmp(cmd, "dump") == 0)
        { _cmd_dump(); return; }
    if (strcmp(cmd, "reset") == 0)
        { _cmd_reset(); return; }
    // ls/r/w/d are handled after _dispatch returns — nothing more to do here
    if (strcmp(cmd, "ls") == 0 || strcmp(cmd, "list") == 0)   return;
    if (strcmp(cmd, "r")  == 0 || strcmp(cmd, "read") == 0)   return;
    if (strcmp(cmd, "w")  == 0 || strcmp(cmd, "write") == 0)  return;
    if (strcmp(cmd, "d")  == 0 || strcmp(cmd, "describe") == 0) return;

    _puts("error: unknown command '"); _puts(cmd);
    _puts("' — type 'help' for usage\r\n");
}

// ---------------------------------------------------------------------------
// Path resolution
// ---------------------------------------------------------------------------

// Parse an integer index from "[N]" inside a path segment.
// Returns -1 if no brackets present, otherwise the integer value.
static int _parse_bracket_index(const char* seg, char* base_out, uint8_t base_max) {
    const char* lb = strchr(seg, '[');
    if (!lb) {
        strncpy(base_out, seg, base_max);
        base_out[base_max] = '\0';
        return -1;
    }
    uint8_t n = (uint8_t)(lb - seg);
    if (n >= base_max) n = base_max - 1;
    memcpy(base_out, seg, n);
    base_out[n] = '\0';
    return (int)strtoul(lb + 1, nullptr, 10);
}

RegShell::PathResult RegShell::_resolve(const char* path) {
    PathResult r;
    if (!path || !path[0]) {
        _puts("error: empty path\r\n");
        return r;
    }

    // Split path on '.' into at most 4 segments
    static char segs[4][SHELL_LINE_LEN + 1];
    uint8_t n_segs = 0;
    const char* p = path;
    while (*p && n_segs < 4) {
        uint8_t i = 0;
        while (*p && *p != '.' && i < SHELL_LINE_LEN)
            segs[n_segs][i++] = *p++;
        segs[n_segs][i] = '\0';
        ++n_segs;
        if (*p == '.') ++p;
    }

    // Determine if path has a bit-field segment at the end
    // (a segment that is NOT a group name)
    // Strategy: walk segments left-to-right resolving groups, then a register,
    // then optionally a bit-field.

    // Identify group path prefix and instance indices
    int group_idx     = -1;   // final resolved group (-1 = root)
    int group_inst    = 0;    // instance index within that group
    int bank_idx      = 0;    // register bank index (from last segment [N])
    int reg_seg       = -1;   // which segs[] index is the register
    int bf_seg        = -1;   // which segs[] index is the bit-field

    uint8_t seg_i = 0;

    // Consume group segments
    while (seg_i < n_segs) {
        char base[SHELL_LINE_LEN + 1];
        int inst_idx = _parse_bracket_index(segs[seg_i], base, SHELL_LINE_LEN);

        // Check if this segment matches a group name
        bool found_group = false;
        for (uint8_t gi = 0; gi < _cfg.group_count; ++gi) {
            if (strcmp(_cfg.groups[gi].name, base) == 0 &&
                _cfg.groups[gi].parent == group_idx) {
                group_idx  = gi;
                group_inst = (inst_idx >= 0) ? inst_idx : 0;
                found_group = true;
                break;
            }
        }
        if (found_group) { ++seg_i; continue; }

        // Not a group — this is the register segment
        reg_seg = seg_i;
        ++seg_i;
        // Optionally one more segment = bit-field
        if (seg_i < n_segs) bf_seg = seg_i;
        break;
    }

    if (reg_seg < 0) {
        _puts("error: path '"); _puts(path); _puts("' does not end with a register name\r\n");
        return r;
    }

    // Parse register segment (may contain [N] for bank index)
    char reg_base[SHELL_LINE_LEN + 1];
    int raw_bank = _parse_bracket_index(segs[reg_seg], reg_base, SHELL_LINE_LEN);
    if (raw_bank >= 0) bank_idx = raw_bank;

    // Find the register entry
    const RegDocEntry* entry = nullptr;
    for (uint16_t ei = 0; ei < _cfg.entry_count; ++ei) {
        const RegDocEntry& e = _cfg.entries[ei];
        if (strcmp(e.name, reg_base) != 0) continue;
        if (e.group_node != group_idx) continue;
        entry = &e;
        break;
    }
    if (!entry) {
        _puts("error: no register at path '"); _puts(path); _puts("'\r\n");
        return r;
    }

    // Validate bank index
    if (bank_idx < 0 || (uint16_t)bank_idx >= entry->bank_size) {
        _puts("error: bank index "); _putu32(bank_idx);
        _puts(" out of range for '"); _puts(entry->name);
        _puts("' (bank_size="); _putu32(entry->bank_size);
        _puts(", valid 0–"); _putu32(entry->bank_size - 1); _puts(")\r\n");
        return r;
    }

    // Validate group instance
    if (group_idx >= 0) {
        uint8_t gcount = _cfg.groups[group_idx].count;
        if ((uint8_t)group_inst >= gcount) {
            _puts("error: group instance "); _putu32(group_inst);
            _puts(" out of range (count="); _putu32(gcount); _puts(")\r\n");
            return r;
        }
    }

    // Compute absolute word address
    uint32_t base_addr = entry->offset_in_group;
    if (group_idx >= 0) {
        base_addr += _cfg.groups[group_idx].base_address
                   + (uint32_t)group_inst * _cfg.groups[group_idx].alignment;
    }
    base_addr += (uint32_t)bank_idx * entry->words_per_reg;

    // Resolve bit-field segment
    int bf_global_idx = -1;
    if (bf_seg >= 0) {
        const char* bf_name = segs[bf_seg];
        for (uint8_t bi = 0; bi < entry->bf_count; ++bi) {
            uint8_t gi = entry->bf_start + bi;
            if (strcmp(_cfg.bitfields[gi].name, bf_name) == 0) {
                bf_global_idx = gi;
                break;
            }
        }
        if (bf_global_idx < 0) {
            _puts("error: no bit-field '"); _puts(bf_name);
            _puts("' in register '"); _puts(entry->name); _puts("'\r\n");
            return r;
        }
    }

    r.entry  = entry;
    r.bf_idx = bf_global_idx;
    r.addr   = (uint16_t)base_addr;
    r.valid  = true;
    return r;
}

// ---------------------------------------------------------------------------
// Value formatting
// ---------------------------------------------------------------------------

uint32_t RegShell::_mask_for_bits(uint8_t width) {
    if (width >= 32) return 0xFFFFFFFFu;
    return (1u << width) - 1u;
}

const char* RegShell::_rw_label(uint8_t rw) {
    if (rw == 0) return "r";
    if (rw == 1) return "w";
    return "rw";
}

const char* RegShell::_type_label(uint8_t t) {
    if (t == _DOC_TYPE_UNSIGNED) return "unsigned";
    if (t == _DOC_TYPE_SIGNED)   return "signed";
    if (t == _DOC_TYPE_BOOL)     return "bool";
    if (t == _DOC_TYPE_FLOAT)    return "float";
    if (t == _DOC_TYPE_DOUBLE)   return "double";
    return "?";
}

void RegShell::_print_value(const RegDocEntry* e, int bf_idx, uint32_t word) {
    // If a bit-field: mask/shift first
    uint32_t val = word;
    uint8_t  width   = (uint8_t)(e->width_bits < 255 ? e->width_bits : 32);
    uint8_t  type_c  = (uint8_t)e->type;
    uint8_t  enum_s  = e->enum_start;
    uint8_t  enum_n  = e->enum_count;

    if (bf_idx >= 0) {
        const RegDocBitField& bf = _cfg.bitfields[bf_idx];
        val    = (word >> bf.starting_bit) & _mask_for_bits(bf.width);
        width  = bf.width;
        type_c = (uint8_t)bf.type;
        enum_s = bf.enum_start;
        enum_n = bf.enum_count;
    }

    // Check enum
    for (uint8_t i = 0; i < enum_n; ++i) {
        if (_cfg.enums[enum_s + i].value == val) {
            _puts(_cfg.enums[enum_s + i].name);
            _putc(' '); _putc('('); _putu32(val); _putc(')');
            return;
        }
    }

    // Bool
    if (type_c == _DOC_TYPE_BOOL) {
        _puts(val ? "true" : "false");
        return;
    }
    // Float
    if (type_c == _DOC_TYPE_FLOAT) {
        float f;
        memcpy(&f, &val, 4);
        _putf(f);
        return;
    }
    // Signed
    if (type_c == _DOC_TYPE_SIGNED) {
        int32_t sv = (width < 32)
            ? (int32_t)(val << (32 - width)) >> (32 - width)
            : (int32_t)val;
        _puti32(sv);
        return;
    }
    // Default: unsigned decimal
    _putu32(val);
    if (e->unit && e->unit[0]) { _putc(' '); _puts(e->unit); }
}

void RegShell::_print_entry_meta(const RegDocEntry* e) {
    _puts("  name:   "); _puts(e->name);        _puts("\r\n");
    _puts("  type:   "); _puts(_type_label((uint8_t)e->type)); _puts("\r\n");
    _puts("  width:  "); _putu32(e->width_bits); _puts(" bits\r\n");
    _puts("  access: "); _puts(_rw_label(e->access)); _puts("\r\n");
    _puts("  bank:   "); _putu32(e->bank_size);  _puts("\r\n");
    if (e->desc && e->desc[0]) { _puts("  desc:   "); _puts(e->desc); _puts("\r\n"); }
    if (e->unit && e->unit[0]) { _puts("  unit:   "); _puts(e->unit); _puts("\r\n"); }
    if (e->has_range) {
        _puts("  range:  ["); _putu32(e->min_val);
        _puts(", "); _putu32(e->max_val); _puts("]\r\n");
    }
    if (e->enum_count) {
        _puts("  enums:\r\n");
        for (uint8_t i = 0; i < e->enum_count; ++i) {
            _puts("    "); _puts(_cfg.enums[e->enum_start + i].name);
            _puts(" = "); _putu32(_cfg.enums[e->enum_start + i].value); _puts("\r\n");
        }
    }
    if (e->bf_count) {
        _puts("  bit-fields:\r\n");
        for (uint8_t i = 0; i < e->bf_count; ++i) {
            const RegDocBitField& bf = _cfg.bitfields[e->bf_start + i];
            _puts("    ["); _putu32(bf.starting_bit);
            _puts("+"); _putu32(bf.width); _puts("] ");
            _puts(bf.name);
            if (bf.desc && bf.desc[0]) { _puts(" — "); _puts(bf.desc); }
            _puts("\r\n");
        }
    }
}

// ---------------------------------------------------------------------------
// Value parsing
// ---------------------------------------------------------------------------

bool RegShell::_parse_value(const RegDocEntry* e, const char* s, uint32_t* out) {
    if (!s || !s[0]) {
        _puts("error: missing value\r\n");
        return false;
    }

    // Bool
    if ((uint8_t)e->type == _DOC_TYPE_BOOL) {
        if (strcmp(s, "true") == 0 || strcmp(s, "1") == 0) { *out = 1u; return true; }
        if (strcmp(s, "false") == 0 || strcmp(s, "0") == 0) { *out = 0u; return true; }
        _puts("error: bool value must be true/false/1/0\r\n");
        return false;
    }

    // Float
    if ((uint8_t)e->type == _DOC_TYPE_FLOAT) {
        char* ep;
        float fv = (float)strtod(s, &ep);
        if (*ep) { _puts("error: invalid float '"); _puts(s); _puts("'\r\n"); return false; }
        memcpy(out, &fv, 4);
        return true;
    }

    // Enum name lookup
    for (uint8_t i = 0; i < e->enum_count; ++i) {
        if (strcmp(_cfg.enums[e->enum_start + i].name, s) == 0) {
            *out = _cfg.enums[e->enum_start + i].value;
            return true;
        }
    }

    // Hex / binary / decimal
    char* ep;
    uint32_t v;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X'))
        v = (uint32_t)strtoul(s + 2, &ep, 16);
    else if (s[0] == '0' && (s[1] == 'b' || s[1] == 'B'))
        v = (uint32_t)strtoul(s + 2, &ep, 2);
    else
        v = (uint32_t)strtoul(s, &ep, 10);

    if (*ep) {
        _puts("error: invalid value '"); _puts(s); _puts("'\r\n");
        return false;
    }

    // Width check
    uint8_t w = (uint8_t)(e->width_bits < 32 ? e->width_bits : 32);
    if (w < 32 && v > _mask_for_bits(w)) {
        _puts("error: value "); _putx32(v);
        _puts(" exceeds "); _putu32(w); _puts("-bit width of '");
        _puts(e->name); _puts("'\r\n");
        return false;
    }

    // Range check
    if (e->has_range && (v < e->min_val || v > e->max_val)) {
        _puts("error: value "); _putu32(v);
        _puts(" out of range ["); _putu32(e->min_val);
        _puts(", "); _putu32(e->max_val);
        _puts("] for '"); _puts(e->name); _puts("'\r\n");
        return false;
    }

    *out = v;
    return true;
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

void RegShell::_cmd_help() {
    _puts("Commands:\r\n");
    _puts("  help / ?           — this message\r\n");
    _puts("  ls [path]          — list registers or group contents\r\n");
    _puts("  r  <path>          — read register or bit-field\r\n");
    _puts("  w  <path> <value>  — write register (full value; bit-field writes rejected)\r\n");
    _puts("  d  <path>          — describe register metadata\r\n");
    _puts("  dump               — read and print all readable registers\r\n");
    _puts("  reset              — reset all registers to defaults\r\n");
    _puts("\r\n");
    _puts("Path syntax:\r\n");
    _puts("  reg                — top-level register\r\n");
    _puts("  group.reg          — register in group\r\n");
    _puts("  group[2].reg       — group instance 2\r\n");
    _puts("  group.reg[3]       — bank element 3\r\n");
    _puts("  group.reg.field    — bit-field (read + describe only)\r\n");
    _puts("\r\n");
    _puts("Value formats:  decimal  0xHEX  0bBINARY  ENUM_NAME  true/false  3.14\r\n");
}

void RegShell::_cmd_ls(const char* arg) {
    // If arg is a group name, list only that group's registers
    int8_t filter_group = -2;   // -2 = no filter, -1 = root, >=0 = group index
    if (arg && arg[0]) {
        bool found = false;
        for (uint8_t gi = 0; gi < _cfg.group_count; ++gi) {
            if (strcmp(_cfg.groups[gi].name, arg) == 0) {
                filter_group = (int8_t)gi;
                found = true;
                break;
            }
        }
        if (!found) {
            _puts("error: no group '"); _puts(arg); _puts("'\r\n");
            return;
        }
    }

    if (filter_group == -2) {
        // Print group names first
        for (uint8_t gi = 0; gi < _cfg.group_count; ++gi) {
            _puts("[grp] ");
            _puts(_cfg.groups[gi].name);
            if (_cfg.groups[gi].count > 1) {
                _puts("[0.."); _putu32(_cfg.groups[gi].count - 1); _puts("]");
            }
            _puts("\r\n");
        }
    }

    // Print registers
    for (uint16_t i = 0; i < _cfg.entry_count; ++i) {
        const RegDocEntry& e = _cfg.entries[i];
        int8_t gn = e.group_node;
        if (filter_group == -2) {
            // Show all, but prefix group name if not root
        } else if (gn != filter_group) {
            continue;
        }
        _puts("  ");
        if (filter_group == -2 && gn >= 0) {
            _puts(_cfg.groups[gn].name); _putc('.');
        }
        _puts(e.name);
        if (e.bank_size > 1) {
            _puts("["); _putu32(e.bank_size); _puts("]");
        }
        _puts("  ("); _puts(_rw_label(e.access));
        _puts(", "); _puts(_type_label((uint8_t)e.type));
        _puts(", "); _putu32(e.width_bits); _puts("-bit");
        if (e.desc && e.desc[0]) { _puts(", "); _puts(e.desc); }
        _puts(")\r\n");
    }
}

void RegShell::_cmd_read(const char* path) {
    if (!path || !path[0]) {
        _puts("error: usage: r <path>\r\n");
        return;
    }
    PathResult pr = _resolve(path);
    if (!pr.valid) return;

    const RegDocEntry* e = pr.entry;
    if (e->access == 1) {   // write-only
        _puts("error: '"); _puts(e->name); _puts("' is write-only\r\n");
        return;
    }

    uint32_t word = 0;
    uint8_t s = _cfg.reg_read(pr.addr, &word, 1);
    if (s > 2) {
        _puts("error: reg_read failed (status="); _putu32(s); _puts(")\r\n");
        return;
    }
    _print_value(e, pr.bf_idx, word);
    _puts("\r\n");
}

void RegShell::_cmd_write(const char* path, const char* val_str) {
    if (!path || !path[0]) {
        _puts("error: usage: w <path> <value>\r\n");
        return;
    }
    PathResult pr = _resolve(path);
    if (!pr.valid) return;

    const RegDocEntry* e = pr.entry;

    // Bit-field write: rejected
    if (pr.bf_idx >= 0) {
        _puts("error: '"); _puts(path);
        _puts("' is read-only via bit field — write '");
        // Print the register path (without the bit-field segment)
        if (e->group_node >= 0) {
            _puts(_cfg.groups[e->group_node].name); _putc('.');
        }
        _puts(e->name);
        _puts("' to set the full register\r\n");
        return;
    }

    if (e->access == 0) {   // read-only
        _puts("error: '"); _puts(e->name); _puts("' is read-only\r\n");
        return;
    }

    uint32_t val;
    if (!_parse_value(e, val_str, &val)) return;

    uint8_t s = _cfg.reg_write(pr.addr, &val, 1);
    if (s > 2) {
        _puts("error: reg_write failed (status="); _putu32(s); _puts(")\r\n");
        return;
    }
    // Echo written value
    _puts("ok: "); _puts(e->name); _puts(" = ");
    _print_value(e, -1, val);
    _puts("\r\n");
}

void RegShell::_cmd_describe(const char* path) {
    if (!path || !path[0]) {
        _puts("error: usage: d <path>\r\n");
        return;
    }
    PathResult pr = _resolve(path);
    if (!pr.valid) return;

    const RegDocEntry* e = pr.entry;
    if (pr.bf_idx >= 0) {
        const RegDocBitField& bf = _cfg.bitfields[pr.bf_idx];
        _puts("bit-field: "); _puts(bf.name); _puts("\r\n");
        _puts("  parent:  "); _puts(e->name);   _puts("\r\n");
        _puts("  bits:    ["); _putu32(bf.starting_bit);
        _puts("+"); _putu32(bf.width); _puts("]\r\n");
        _puts("  type:    "); _puts(_type_label((uint8_t)bf.type)); _puts("\r\n");
        _puts("  access:  "); _puts(_rw_label(bf.rw)); _puts("\r\n");
        if (bf.desc && bf.desc[0]) { _puts("  desc:    "); _puts(bf.desc); _puts("\r\n"); }
        if (bf.enum_count) {
            _puts("  enums:\r\n");
            for (uint8_t i = 0; i < bf.enum_count; ++i) {
                _puts("    "); _puts(_cfg.enums[bf.enum_start + i].name);
                _puts(" = "); _putu32(_cfg.enums[bf.enum_start + i].value); _puts("\r\n");
            }
        }
    } else {
        _print_entry_meta(e);
    }
}

void RegShell::_cmd_dump() {
    for (uint16_t i = 0; i < _cfg.entry_count; ++i) {
        const RegDocEntry& e = _cfg.entries[i];
        if (e.access == 1) continue;   // skip write-only

        // Compute base address for instance[0]
        uint32_t base = e.offset_in_group;
        if (e.group_node >= 0)
            base += _cfg.groups[e.group_node].base_address;

        for (uint16_t b = 0; b < e.bank_size; ++b) {
            uint32_t addr = base + (uint32_t)b * e.words_per_reg;
            uint32_t word = 0;
            uint8_t s = _cfg.reg_read((uint16_t)addr, &word, 1);
            if (s > 2) continue;

            if (e.group_node >= 0) {
                _puts(_cfg.groups[e.group_node].name); _putc('.');
            }
            _puts(e.name);
            if (e.bank_size > 1) {
                _putc('['); _putu32(b); _putc(']');
            }
            _puts(" = ");
            _print_value(&e, -1, word);
            _puts("\r\n");
        }
    }
}

void RegShell::_cmd_reset() {
    _cfg.reg_reset();
    _puts("ok: registers reset\r\n");
}
