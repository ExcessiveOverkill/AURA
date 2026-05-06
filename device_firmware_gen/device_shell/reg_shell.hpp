/*
 * reg_shell.hpp — Generic UART register shell.
 *
 * Provides a human-friendly terminal interface for any AURA register module.
 * Wire it up using the generated <mod>_make_shell_config() factory, then feed
 * received bytes into RegShell::feed().  All output goes through putc_fn.
 *
 * Features:
 *   - Path navigation: reg, group.reg, group[2].reg, group.reg[3], group.reg.field
 *   - Commands: help/?, ls, r/read, w/write, d/describe, dump, reset
 *   - Value formats: decimal, 0x hex, 0b binary, enum names, true/false, float
 *   - VT100 arrow-key history (SHELL_HISTORY_DEPTH entries)
 *   - TAB completion on path segments
 *   - Bit-field reads: allowed.  Bit-field writes: rejected with a message.
 *
 * C++17 required (uses if-constexpr and structured bindings internally).
 */

#pragma once

#include "reg_doc_types.hpp"

// ---------------------------------------------------------------------------
// Configuration struct — filled by <mod>_make_shell_config()
// ---------------------------------------------------------------------------

struct RegShellConfig {
    // Comm callbacks (from the generated namespace)
    uint8_t (*reg_read) (uint16_t addr, uint32_t* out,        uint16_t count);
    uint8_t (*reg_write)(uint16_t addr, const uint32_t* data, uint16_t count);
    void    (*reg_reset)();

    // Doc tables (ROM — pointers remain valid forever)
    const RegDocEntry*     entries;
    uint16_t               entry_count;
    const RegDocGroupNode* groups;
    uint8_t                group_count;
    const RegDocBitField*  bitfields;
    const RegDocEnum*      enums;
    uint8_t                word_bytes;   // sizeof(word_t) for this module

    // I/O
    void (*putc_fn)(char c);
    const char* prompt;                  // displayed before each input line; nullptr → "> "
};

// ---------------------------------------------------------------------------
// RegShell — the terminal state machine
// ---------------------------------------------------------------------------

#ifndef SHELL_LINE_LEN
#define SHELL_LINE_LEN     80
#endif

#ifndef SHELL_HISTORY_DEPTH
#define SHELL_HISTORY_DEPTH 8
#endif

class RegShell {
public:
    void init(const RegShellConfig& cfg);

    // Feed one received byte.  May emit multiple output bytes via putc_fn.
    // Safe to call from an ISR; internal state is updated atomically per-byte.
    void feed(char c);

    // Convenience: feed a buffer.
    void feed(const char* s, uint16_t n) {
        for (uint16_t i = 0; i < n; ++i) feed(s[i]);
    }

private:
    // ----- configuration -------------------------------------------------
    RegShellConfig _cfg;

    // ----- line buffer ---------------------------------------------------
    char     _line[SHELL_LINE_LEN + 1];
    uint8_t  _len   = 0;
    uint8_t  _cur   = 0;   // cursor position (for future insert/delete)

    // ----- history -------------------------------------------------------
    char     _hist[SHELL_HISTORY_DEPTH][SHELL_LINE_LEN + 1];
    uint8_t  _hist_head  = 0;   // index of the most recent entry
    uint8_t  _hist_count = 0;
    int8_t   _hist_pos   = -1;  // -1 = not navigating

    // ----- VT100 escape state --------------------------------------------
    enum class Esc { NONE, ESC, BRACKET } _esc = Esc::NONE;

    // ----- output helpers ------------------------------------------------
    void _puts(const char* s);
    void _putc(char c) { _cfg.putc_fn(c); }
    void _putu32(uint32_t v);
    void _puti32(int32_t  v);
    void _putf  (float    v);
    void _putx32(uint32_t v);

    // ----- line editing --------------------------------------------------
    void _show_prompt();
    void _accept_line();
    void _history_push(const char* line);
    void _history_navigate(int delta);  // +1 = older, -1 = newer
    void _erase_line();
    void _handle_tab();

    // ----- command dispatch ----------------------------------------------
    void _dispatch(const char* line);

    // ----- path resolution -----------------------------------------------
    struct PathResult {
        const RegDocEntry* entry   = nullptr;
        int                bf_idx  = -1;    // index in global bitfields[], -1 = whole reg
        uint16_t           addr    = 0;     // resolved absolute word address
        bool               valid   = false;
    };
    PathResult _resolve(const char* path);

    // ----- commands ------------------------------------------------------
    void _cmd_help();
    void _cmd_ls(const char* arg);
    void _cmd_read(const char* path);
    void _cmd_write(const char* path, const char* val_str);
    void _cmd_describe(const char* path);
    void _cmd_dump();
    void _cmd_reset();

    // ----- value formatting ----------------------------------------------
    void _print_value(const RegDocEntry* e, int bf_idx, uint32_t word);
    void _print_entry_meta(const RegDocEntry* e);

    // ----- value parsing -------------------------------------------------
    bool _parse_value(const RegDocEntry* e, const char* s, uint32_t* out);

    // ----- helpers -------------------------------------------------------
    const char* _rw_label(uint8_t rw);
    const char* _type_label(uint8_t type_code);
    uint32_t    _mask_for_bits(uint8_t width);
};
