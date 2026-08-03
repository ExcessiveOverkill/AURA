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

static void app_demo_accessors_once() {
    using namespace regs;

    // Scalar registers (typed get/set wrappers).
    set_basic_u32_rw(123u);
    const uint32_t basic_val = get_basic_u32_rw();
    set_u32_with_limits((basic_val % 100u));

    // Type coverage examples.
    set_uint12_rw(7u);
    set_uint64_rw(0x1122334455667788ULL);
    set_uint48_rw(0x00ABCDEF1234ULL);
    set_int32_rw(-42);
    set_float_rw(3.25f);
    set_double_rw(6.5);

    // Enum + bit-fields.
    set_enum_rw(enum_rw_e::GREEN);
    set_register_with_bitfields_field1(0xAu);
    set_register_with_bitfields_field2(true);
    set_register_with_bitfields_field3(0x3u);

    // Banked registers.
    set_array_of_4_u32(0, 100u);
    set_array_of_4_u8(1, static_cast<uint8_t>(get_array_of_4_u32(0) & 0xFFu));

    // Fixed-address and explicitly aligned-group examples.
    set_command_u16_w(0x1234u);
    set_aligned_group_current_limit(3200u);
    set_aligned_group_energy_wh(424242ULL);
    const uint64_t energy_wh = get_aligned_group_energy_wh();
    (void)energy_wh;

    // Nested single-instance groups.
    set_group1_reg1(55u);
    set_group1_reg2(12.5f);
    set_group2_nested_group_reg3(true);

    // Counted group access through storage instance methods.
    ::regs::regs.multiple_groups[2].set_reg4(0x5Au);
    const uint8_t reg4_v = ::regs::regs.multiple_groups[2].get_reg4();
    set_array_of_4_u8(2, reg4_v);

    // Messaging API and both ID styles (compile-time + runtime-indexed views).
    g_msgs.add(msgs.drive.fault, /*payload=*/0xDEADu);
    g_msgs.add(msgs.drive[0].overtemp(), /*payload=*/0xBEEFu);

    // Nested and instanced message groups.
    g_msgs.add(msgs.system.power.low_voltage, /*payload=*/0x1111u);
    g_msgs.add(msgs.motor[1].fault, /*payload=*/0x2222u);

    // Persistent state style helpers.
    g_msgs.log_persistent_active(msgs.safety.watchdog, /*payload=*/0x9999u);
    g_msgs.log_persistent_inactive(msgs.safety.watchdog);

    g_msgs.recalc_severity();

    // String/group helpers for host UI or diagnostics.
    const MessageId id = msgs.system.power.over_voltage;
    const char* name = msg_get_name(id);
    const char* desc = msg_get_desc(id);
    const char* sev = severity_label(msg_get_severity(id));
    const int8_t grp_idx = msg_get_group_idx(id);
    const char* grp_name = group_name(grp_idx);

    printf("msg: %s | sev=%s | group=%s | desc=%s\n", name, sev, grp_name, desc);

    if (g_msgs.is_active(msgs.drive.fault)) {
        const uint16_t hits = g_msgs.get_hit_count(msgs.drive.fault);
        if (hits > 0u) {
            g_msgs.clear_payload(msgs.drive.fault);
        }
    }

    // Demonstrate the rest of the clear/query helpers.
    (void)g_msgs.get_last_active_time(msgs.drive.fault);
    (void)g_msgs.get_last_payload(msgs.drive.fault);
    g_msgs.clear_time(msgs.drive.fault);
    g_msgs.clear_hit_count(msgs.drive.fault);
    g_msgs.clear(msgs.drive.fault);
    g_msgs.clear(msgs.drive[0].overtemp());
    g_msgs.clear(msgs.system.power.low_voltage);
    g_msgs.clear(msgs.motor[1].fault);
}

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

    // Optional register-interface wiring for host-visible messaging state.
    uint16_t msg_count = 0;
    uint16_t msg_active_severity = 0;
    uint16_t msg_cmd = 0;
    uint16_t msg_control = 0;
    uint16_t msg_sel_severity = 0;
    uint32_t msg_time_lo = 0;
    uint32_t msg_time_hi = 0;
    uint32_t msg_payload = 0;
    uint16_t msg_hit_count = 0;
    MsgRegIface iface = {
        .count = &msg_count,
        .active_severity = &msg_active_severity,
        .cmd = &msg_cmd,
        .control = &msg_control,
        .severity = &msg_sel_severity,
        .time_lower = &msg_time_lo,
        .time_upper = &msg_time_hi,
        .payload = &msg_payload,
        .hit_count = &msg_hit_count,
    };
    g_msgs.set_register_interface(iface);

    shell_init();
    app_demo_accessors_once();

    // Inject a demo command sequence (simulates the user typing over UART).
    uart_inject("help\r");
    uart_inject("ls\r");
    uart_inject("w basic_u32_rw 99\r");
    uart_inject("r basic_u32_rw\r");
    uart_inject("w enum_rw GREEN\r");
    uart_inject("r enum_rw\r");
    uart_inject("w command_u16_w 4660\r");
    uart_inject("w aligned_group_current_limit 2800\r");
    uart_inject("r aligned_group_current_limit\r");
    uart_inject("dump\r");

    // Main loop: update device state then service the shell.
    for (uint32_t i = 0; i < 200u; ++i) {
        app_update();
        shell_poll();
    }

    return 0;
}
