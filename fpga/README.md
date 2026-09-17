# fpga — ECP5 demonstration target

**This is not the graded artifact.** `asic/` on gf180mcu is. This leg exists
because a synthesizer you can hear is a different kind of evidence from a
passing testbench, and because a second, structurally different synthesis path
over the same `rtl/` is a fast check that the sources are portable and
flow-clean. See
[`spec/decision-records/0002-fpga-target-in-a-pdk-named-repo.md`](../spec/decision-records/0002-fpga-target-in-a-pdk-named-repo.md)
for why it lives in a `gf180-`prefixed repository at all, and for the rule
that no FPGA artifact may ever be cited as ASIC evidence.

Target: **Icepi Zero**, Lattice ECP5 `LFE5U-25F`, CABGA256, board revision 1.3.

| File | What |
|---|---|
| `top.v` | Wrapper: 50 MHz board clock → PLL → 12.288 MHz core clock, UART in from the FTDI (`usb_rx`), I2S out on the Pi header's PCM pins, five status LEDs (heartbeat, UART activity, non-silent output, FIFO overflow, PLL lock). The direct byte port is tied off — it is a simulation-only interface. Instantiates `synth_core` with `NV = 4`, the contract's voice count. |
| `pll.v` | `ecppll`-generated `EHXPLLL` instance: CLKI_DIV 2, CLKOP_DIV 29, CLKOS_DIV 59 → 12.2881 MHz, matching the contract's informative clocking note. |
| `i2s_tx.v` | I2S transmitter, one 16-bit mono sample per frame, same sample on both channels. |
| `tb_i2s.v` | Decodes SDATA the way a DAC does and checks it. See "The I2S output is tested" below. |
| `icepi-zero.lpf` | Board pin constraints (vendor file, verbatim). |
| `Makefile` | yosys (`synth_ecp5`) → nextpnr-ecp5 → ecppack, plus the `sim` targets. Stops at a bitstream file; it never programs a board. |

## Pinout: I2S is on the Raspberry Pi PCM pins

`top.v` drives I2S on the header pins a PCM5102A pHAT expects, so the board
plugs on with no jumpers:

| Signal | `gpio` bit | ECP5 site | Header pin | BCM | pHAT |
|---|---|---|---|---|---|
| BCLK | `gpio[18]` | N4 | 12 | BCM18 `PCM_CLK` | BCK |
| LRCLK | `gpio[19]` | E4 | 35 | BCM19 `PCM_FS` | LRCK |
| SDATA | `gpio[21]` | F2 | 40 | BCM21 `PCM_DOUT` | DIN |
| — (driven low) | `gpio[20]` | F1 | 38 | BCM20 `PCM_DIN` | — |

Power comes off the header: pins 2/4 = +5 V, 1/17 = +3V3, 6/9/14/20/25/30/34/39
= GND.

**Do not move I2S to `gpio[0..2]`.** That is header 27/28/3 — BCM0/BCM1 are
`ID_SD`/`ID_SC`, the HAT ID EEPROM lines, and BCM2 is I2C1 SDA. A pHAT that
carries an ID EEPROM has those two wired to it, so the clocks would be
contending with the EEPROM and no PCM pin would be driven at all. The
prototype this repository came from had exactly that wiring.

The PCM5102A needs no master clock (it recovers from BCLK with SCK tied low).
A Digilent Pmod I2S2 does, because its CS4344 requires MCLK; `make build
PMOD_MCLK=1` adds 12.288 MHz on `pi_sclk` (site G2 = header pin 23) for that
case. The pHAT build does not drive it.

## Building

```bash
cd fpga && make build                                   # tools on $PATH
cd fpga && make build TOOLS=/path/to/oss-cad-suite/bin   # or point at an install
cd fpga && make build PMOD_MCLK=1                        # Pmod I2S2 variant
```

Needs `yosys`, `nextpnr-ecp5` and `ecppack` — an OSS CAD Suite install is the
easy way. Note that a `yosys` which is actually a container wrapper (for
example the one a `klt` ASIC virtualenv puts on `$PATH`) will fail here with
`File '../rtl/uart_rx.v' not found`, because the sources are outside the
container's bind mounts. Use `TOOLS=` to point at a native install.

Build products (`bitstream.bit`, `bitstream.json`, `bitstream.config`, the
logs, the `.vvp` files) are gitignored — they regenerate in seconds from the
committed sources.

## The I2S output *is* tested

```bash
cd fpga && make sim-check TOOLS=/path/to/oss-cad-suite/bin
```

`tb_i2s.v` samples SDATA on the rising edge of BCLK exactly as an I2S receiver
does — one delay bit after the LRCLK edge, then 16 bits MSB first — and
asserts that each decoded word is a sample that was actually fed in (so bit
order, polarity and sign are all checked), that the low 16 bits of each 32-bit
slot are zero, that both channels carry the same sample, and that
BCLK = 64 × LRCLK with a 256-clock LRCLK period.

`make sim-check` also rebuilds `i2s_tx.v` with `-DINJECT_BUG_I2S` and requires
that build to **fail** the testbench, the same watch-it-fail discipline the
cocotb bench's `INJECT_BUG_*` controls use. Both directions run in CI.

This matters because the sample port of `synth_core` is where the cocotb
bench's boundary is: nothing downstream of it is covered by the bit-exact
suite, and the prototype's transmitter was wrong in a way that no amount of
green in that suite would have revealed (see the file header for both
defects).

## Measured, in this repository

yosys + nextpnr-ecp5 + ecppack from the OSS CAD Suite (2026-09-17), Apple M5,
default (pHAT) build at `NV = 4`:

| Metric | Value |
|---|---|
| LUT4 (TRELLIS_COMB) | 3468 / 24288 (14 %) |
| FF (TRELLIS_FF) | 1145 / 24288 (4 %) |
| MULT18X18D | 8 / 28 (28 %) |
| DP16KD (block RAM) | 0 / 56 |
| EHXPLLL | 1 / 2 |
| Max frequency, `clk12` | **78.24 MHz** post-route — PASS at the required 12.29 MHz by 6.4× (nextpnr's post-placement estimate, printed earlier in the same log, is 70.39 MHz; the post-route figure is the one that counts) |
| `bitstream.bit` | 150,361 bytes |
| Wall clock, clean build | 11 s |

The `PMOD_MCLK=1` variant builds to 149,760 bytes.

## What has *not* happened

**The bitstream has never been loaded onto hardware.** No board was attached.
Everything above is a toolchain result: the design elaborates, maps, places,
routes and packs, with timing met by a factor of 6.4 in the static analysis
nextpnr does, and the I2S waveform is correct in simulation. What remains
untested is everything electrical — real signal integrity on the header, the
DAC's response to these clocks, the FTDI UART path at speed, and whether the
LPF's sites match the board in hand. The pin assignments above were checked
against the v1.3 schematic and the Raspberry Pi header map, not against a
board.
