# fpga — ECP5 demonstration target

**This is not the graded artifact.** `asic/` on gf180mcu is. This leg exists
because a synthesizer you can hear is a different kind of evidence from a
passing testbench, and because a second, structurally different synthesis path
over the same `rtl/` is a fast check that the sources are portable and
flow-clean. See
[`spec/decision-records/0002-fpga-target-in-a-pdk-named-repo.md`](../spec/decision-records/0002-fpga-target-in-a-pdk-named-repo.md)
for why it lives in a `gf180-`prefixed repository at all, and for the rule
that no FPGA artifact may ever be cited as ASIC evidence.

Target: **Icepi Zero**, Lattice ECP5 `LFE5U-25F`, CABGA256.

| File | What |
|---|---|
| `top.v` | Wrapper: 50 MHz board clock → PLL → 12.288 MHz core clock, UART in from the FTDI (`usb_rx`), I2S out on `gpio[0..2]`, five status LEDs (heartbeat, UART activity, non-silent output, FIFO overflow, PLL lock). The direct byte port is tied off — it is a simulation-only interface. Instantiates `synth_core` with `NV = 1`. |
| `pll.v` | `ecppll`-generated `EHXPLLL` instance: CLKI_DIV 2, CLKOP_DIV 29, CLKOS_DIV 59 → 12.2881 MHz, matching the contract's informative clocking note. |
| `i2s_tx.v` | I2S transmitter, one 16-bit mono sample per frame. |
| `icepi-zero.lpf` | Board pin constraints. |
| `Makefile` | yosys (`synth_ecp5`) → nextpnr-ecp5 → ecppack. Stops at a bitstream file; it never programs a board. |

## Building

```bash
cd fpga && make build                                  # tools on $PATH
cd fpga && make build TOOLS=/path/to/oss-cad-suite/bin  # or point at an install
```

Needs `yosys`, `nextpnr-ecp5` and `ecppack` — an OSS CAD Suite install is the
easy way. Note that a `yosys` which is actually a container wrapper (for
example the one a `klt` ASIC virtualenv puts on `$PATH`) will fail here with
`File '../rtl/uart_rx.v' not found`, because the sources are outside the
container's bind mounts. Use `TOOLS=` to point at a native install.

Build products (`bitstream.bit`, `bitstream.json`, `bitstream.config`, the
two logs) are gitignored — they regenerate in seconds from the committed
sources.

## Measured, in this repository

yosys + nextpnr-ecp5 + ecppack from the OSS CAD Suite (2026-09-16), Apple M5:

| Metric | Value |
|---|---|
| LUT4 (TRELLIS_COMB) | 1294 / 24288 (5 %) |
| FF (TRELLIS_FF) | 433 / 24288 (1 %) |
| MULT18X18D | 2 / 28 |
| EHXPLLL | 1 / 2 |
| Max frequency, `clk12` | **82.01 MHz** — PASS at the required 12.29 MHz |
| `bitstream.bit` | 117,970 bytes |
| Wall clock, clean build | 3.4 s |

## What has *not* happened

**The bitstream has never been loaded onto hardware.** No board was attached.
Everything above is a toolchain result: the design elaborates, maps, places,
routes and packs, with timing met by a factor of 6.7 in the static analysis
nextpnr does. Whether it makes a sound through a real I2S DAC is untested,
and so is the I2S transmitter's electrical behaviour, the FTDI UART path, and
the LPF's pin assignment against a physical board.

`i2s_tx.v` in particular has **no testbench at all** — it is outside the
cocotb bench's boundary (which stops at `synth_core`'s sample port) and
outside the contract's scope. It is the least-verified file in this
repository. Treat it accordingly.
