# intro Messages

Total messages: 12

| ID | Path | Severity | Debounce | Description |
|----|------|----------|----------|-------------|
| 0 | `drive.fault` | ERROR | - | Drive fault — output disabled |
| 1 | `drive.overtemp` | WARNING | - | Motor temperature above safe operating limit |
| 2 | `comms.timeout` | ERROR | - | Host communication watchdog expired |
| 3 | `system.boot` | MESSAGE | - | Boot complete |
| 4 | `system.idle` | NONE | - | System idle marker |
| 5 | `system.power.low_voltage` | WARNING | 20000 us | DC bus low |
| 6 | `system.power.over_voltage` | ERROR | - | DC bus high |
| 7 | `motor.fault` | ERROR | - | Motor fault |
| 8 | `motor.overtemp` | WARNING | 50000 us | Motor temperature high |
| 9 | `motor.fault` | ERROR | - | Motor fault |
| 10 | `motor.overtemp` | WARNING | 50000 us | Motor temperature high |
| 11 | `safety.watchdog` | CRITICAL | - | Watchdog timeout |
