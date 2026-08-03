/*
 * firmware_main.cpp — Intro example: AURA register shell over UART
 *
 * Demonstrates wiring the generated register shell to a UART peripheral.
 * The HAL stubs below simulate a blocking single-byte UART; replace them
 * with your platform's actual driver (e.g. STM32 HAL, NRF UART, etc.).
 *
 * Build from examples/intro/:
 *   g++ -std=c++17 -I. firmware_main.cpp \
 *       generated/registers/reg_storage.cpp \
 *       generated/registers/reg_comm.cpp \
 *       generated/registers/reg_doc.cpp  \
 *       generated/registers/reg_shell.cpp      \
 *       generated/messaging/msg.cpp      \
 *       generated/messaging/msg_strings.cpp \
 *       -o firmware_main
 */

#include "generated/aura.hpp"
#include "generated/registers/reg_shell.hpp"

#include <cstdio>   // printf (stand-in for UART TX in this desktop build)
#include <cstring>

// ---------------------------------------------------------------------------
// Dummy HAL UART — replace with your platform SDK
// ---------------------------------------------------------------------------

// Small ring-buffer that stands in for the hardware RX FIFO.
static char    s_rx_buf[128];
static uint8_t s_rx_head = 0;
static uint8_t s_rx_tail = 0;

static void HAL_UART_PutChar(char c) {
    // On real hardware: spin until TXE, then write to the data register.
    putchar(c);
    fflush(stdout);
}

static bool HAL_UART_RxAvailable() {
    return s_rx_head != s_rx_tail;
}

static char HAL_UART_GetChar() {
    char c = s_rx_buf[s_rx_tail];
    s_rx_tail = (s_rx_tail + 1u) % (uint8_t)sizeof(s_rx_buf);
    return c;
}

// Helper: push a string into the fake RX buffer (simulates user typing).
static void uart_inject(const char* str) {
    for (; *str; ++str) {
        s_rx_buf[s_rx_head] = *str;
        s_rx_head = (s_rx_head + 1u) % (uint8_t)sizeof(s_rx_buf);
    }
}

// ---------------------------------------------------------------------------
// Shell
// ---------------------------------------------------------------------------

static RegShell g_shell;

static void shell_init() {
    RegShellConfig cfg = make_shell_config(HAL_UART_PutChar, "intro> ");
    g_shell.init(cfg);
}

static void shell_poll() {
    while (HAL_UART_RxAvailable())
        g_shell.feed(HAL_UART_GetChar());
}

// ---------------------------------------------------------------------------
// Messaging
// ---------------------------------------------------------------------------

static Messaging g_msgs;

// ---------------------------------------------------------------------------
// Simulated application loop
// ---------------------------------------------------------------------------

static uint32_t s_tick = 0;

static void app_update() {
    using namespace regs;

    // Drive basic_u32_r as a simulated read-only sensor value (firmware writes it).
    set_basic_u32_r(20u + (s_tick % 80u));

    // Example: instanced-group inline methods on the raw storage struct.
    // These methods are generated on MultipleGroupsInstance_t and are fully inline.
    const uint8_t group_idx = static_cast<uint8_t>((s_tick / 25u) & 0x03u);
    ::regs::regs.multiple_groups[group_idx].set_reg4(static_cast<uint8_t>(s_tick & 0xFFu));
    const uint8_t reg4_shadow = ::regs::regs.multiple_groups[group_idx].get_reg4();

    // Feed the value through a regular typed accessor to show both styles coexist.
    set_array_of_4_u8(group_idx, reg4_shadow);

    // Simulate a drive fault at tick 50.
    if (s_tick == 50u) {
        set_bool_rw(true);
        // Example: runtime-indexed messaging accessor (computed MessageId view).
        g_msgs.add(msgs.drive[0].fault(), /*payload=*/0xA1);
    }

    // Simulate the fault clearing at tick 100.
    if (s_tick == 100u) {
        set_bool_rw(false);
        g_msgs.clear(msgs.drive[0].fault());
    }

    ++s_tick;
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

int main() {
    g_msgs.init();
    shell_init();

    // Inject a demo command sequence (simulates the user typing over UART).
    uart_inject("help\r");
    uart_inject("ls\r");
    uart_inject("w basic_u32_rw 99\r");
    uart_inject("r basic_u32_rw\r");
    uart_inject("w enum_rw GREEN\r");
    uart_inject("r enum_rw\r");
    uart_inject("dump\r");

    // Main loop: update device state then service the shell.
    for (uint32_t i = 0; i < 200u; ++i) {
        app_update();
        shell_poll();
    }

    return 0;
}
