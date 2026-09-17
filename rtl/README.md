# rtl — Verilog sources

One source tree, two targets (`asic/` on gf180mcu, `fpga/` on ECP5) — see
`spec/decision-records/0002-fpga-target-in-a-pdk-named-repo.md`. Neither
target may fork these files.

| File | What |
|---|---|
| `synth_core.v` | Top. Cycle counter (256 cycles/frame, contract §2), UART/direct-byte-port merge, byte parser (contract §10.2–10.4), 8-deep command FIFO, `NV` voice instances, fixed 4-input mixer with saturation (contract §8). |
| `synth_voice.v` | One voice: 24-bit phase accumulator, all four waveforms (contract §5.4; sine via the 257-entry quarter table with mirror/sign logic), linear ADSR (§6.3) widened to 21 bits, the 3-stage scaler `env → g → (osc*g)>>>16`, command semantics (§10.5) and reset values (§9). |
| `uart_rx.v` | 8N1 receiver. Falling-edge start detect, mid-bit sampling, 107 clocks/bit by default; framing-error bytes are dropped. |
| `gen_tables.py` | Generates the two ROM includes below from the frozen tables in `spec/reference/synth_ref.py`. |
| `note_inc_rom.vh` | **Generated.** 128 MIDI-note phase increments as an `always @*` case block. Header carries `sha256(NOTE_INc)` — must match contract Appendix A. |
| `sine_q_rom.vh` | **Generated.** 257-entry quarter sine as an `always @*` case block. Header carries the hash from contract Appendix B. |

Regenerating must be a no-op:

```bash
python3 rtl/gen_tables.py && git diff --exit-code rtl/*.vh
```

## Parameters

| Parameter | Default | Notes |
|---|---|---|
| `NV` | `2` | Voices instantiated. The contract specifies **4**; the default is 2 for build speed, and the mixer is a fixed 4-input sum so `NV` ≤ 4. `NV = 1, 2, 4` are each verified 12/12 on both engines — see `tb/README.md`. |
| `UART_CLKS_PER_BIT` | `107` | 12.288 MHz core clock / 115200 baud. |

`fpga/top.v` instantiates `NV = 4`, the contract's voice count.

## Flow hygiene — why this RTL looks the way it does

These are not style preferences. Each one cost the prototype a failed
place-and-route attempt, and the rules are load-bearing for any edit:

- **No `signed` in any port or wire declaration.** Yosys preserves the
  keyword into the gate-level netlist and OpenROAD's Verilog reader rejects
  it (`[ERROR STA-0171] ... syntax error`). Signedness is applied with
  `$signed()` at the two operations that need it.
- **No Verilog functions.** Yosys leaves a function's argument as a dangling
  wire assigned `x`; OpenSTA reads that `x` as a constant and synthesizes an
  empty `GROUND` net, which TritonRoute then refuses to route
  (`[ERROR DRT-0305] Net zero_ ... is not routable`). Both ROMs and the
  opcode-length table are `always @*` case blocks instead.
- **No `integer` loop variables in synthesized always blocks.** One survived
  as a 32-bit wire fed by tie cells — pure wasted area.
- **No unpacked-array accumulator chains.** A generate-chain mixer tripped
  Verilator's `UNOPTFLAT` (fatal inside `klt`, invisible to `--lint-only`);
  it is a fixed 4-input sum with zero-padded unused voices instead.

The net result at the prototype stage was a Yosys netlist with zero `signed`
declarations and zero `x` constants, needing no post-edit before P&R. Keep it
that way.
