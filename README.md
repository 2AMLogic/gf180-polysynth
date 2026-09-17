# gf180-polysynth

A 4-voice polyphonic digital synthesizer on the
[gf180mcu](https://github.com/google/gf180mcu-pdk) open PDK, taken from a
frozen numeric contract to verified RTL by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the
open-source digital flow — cocotb + Icarus/Verilator for verification, Yosys
for synthesis, OpenROAD for place-and-route.

One RTL source, two targets: **`asic/`** on gf180mcu, which is the graded
artifact, and **`fpga/`** on a Lattice ECP5, which is a demonstration and a
second synthesis path. The asymmetry between them is recorded in
[`spec/decision-records/0002`](spec/decision-records/0002-fpga-target-in-a-pdk-named-repo.md),
and it is strict: no FPGA artifact may ever be cited as evidence for the ASIC
leg.

## Status — read this before believing any number

**Verified, in this repository, from these sources:**

| Claim | Evidence |
|---|---|
| The RTL matches the frozen contract **sample for sample, with no tolerance** | `tb/test_synth_core.py`, 12 tests, **12/12 on Icarus 14.0 and Verilator 5.053**, at `NV` = 1, 2 and 4 — all six combinations |
| The contract's own reference model is self-consistent | `spec/reference/test_synth_ref.py`, **102/102** |
| The comparison holds at volume, not just on crafted vectors | `bench/render.py`: **480,000/480,000 samples bit-exact** over 10 s of audio, 122.9 M cycles |
| The testbench can actually fail | four `INJECT_BUG_*` defines, **all four caught**, each with its intended failure signature |
| The RTL's lookup tables are the contract's | regenerating `rtl/*.vh` is a byte-identical no-op and both SHA-256s match contract Appendix A/B |
| The design maps to an FPGA | ECP5 `LFE5U-25F` at `NV = 4`: 3468 LUT4, 1145 FF, 8/28 MULT18X18D, post-route Fmax **78.24 MHz** against a required 12.29 MHz, 150,361-byte bitstream |
| The I2S output is decoded the way a DAC decodes it | `fpga/tb_i2s.v`: bit order, polarity, sign, slot padding, BCLK/LRCLK ratio — and `INJECT_BUG_I2S` is caught |

**Not verified. Not claimed. Not true yet:**

- **Nothing has been run on gf180mcu.** No synthesis, no floorplan, no
  route, no GDS, no DRC, no LVS, no STA, no ERC. `asic/` contains a
  configuration that has never executed; the single thing checked about it is
  that `klt synthesize` accepts the request document and then fails at
  liberty resolution because this host has no gf180mcu install. Running that
  flow is [the first work item](#gap-to-t1-on-gf180mcu).
- **Nothing has been fabricated**, and no shuttle seat is held.
- **The ECP5 bitstream has never been loaded onto hardware.** No board was
  attached. It is a toolchain result, not a sound anyone has heard.
- **There is no ratified physical spec table** — no target clock, area,
  power, corner set or IO timing has been through ratification, so there is
  nothing for a per-row pass/fail verdict to be measured *against*. See
  [`spec/README.md`](spec/README.md#what-is-not-ratified-yet).
- **`sim/` is empty.** Every number on this page is reproducible from the
  committed sources, but none of it carries a record ID, a provenance block
  or an append-only guarantee. They are README numbers, not evidence records.
- **The I2S transmitter is verified only in simulation, and only for
  waveform shape.** `fpga/tb_i2s.v` decodes SDATA as a DAC would and checks
  bit order, polarity, sign, slot padding and clock ratios — it found two
  real defects in the prototype's transmitter — but it sits outside the
  contract's scope, and nothing electrical about the I2S link has been
  tested. Earlier revisions of this repository carried the prototype's
  transmitter with those two defects and said so; that file is now fixed and
  covered.
- **The T1 (sim-validated) checklist is not met on gf180mcu**, and not on
  anything else either. See the gap list below.

### What a prototype did on a *different* PDK

This block's RTL and testbench came out of a 53-minute timed rehearsal that
targeted **sky130**. That rehearsal took the design through a complete flow —
`klt synthesize` → `klt place-and-route` → `klt drc` (clean, 0 violations) →
`klt extract` → `klt lvs` (match, 0 errors) → `klt sta` (0 setup / 0 hold
violations, +73.1 ns worst slack) → `klt erc`. It is honest evidence that the
*flow shape* works on this design, and it is why the RTL is written the way
it is. It is **not** evidence about this repository's target, for four
separate reasons, each of which matters on its own:

1. **Different PDK.** Tiers are graded per block per PDK
   ([`design-evidence-tiers.md`](https://github.com/2AMLogic/klayout-tools/blob/main/docs/design-evidence-tiers.md)).
   A sky130 result says nothing about gf180mcu.
2. **Different design.** The routed layout was the *base-scope* netlist —
   one voice, square wave only — not the RTL in `rtl/` today, which has four
   waveforms and four available voices, and which `fpga/top.v` now builds at
   `NV = 4`.
3. **No power grid.** That place-and-route request carried no `power` block,
   so the layout had no PDN, no tapcells and no filler cells. sky130's deck
   called it clean anyway. gf180mcu's deck does not: the same omission there
   produces 19 `nwell.space.1` violations. That contrast is one of the two
   reasons the PDK choice went the way it did
   ([`spec/decision-records/0001`](spec/decision-records/0001-pdk-selection-gf180mcu.md)),
   and it is why `asic/par-polysynth.json` carries a mandatory `power` block.
4. **Hand-edited netlist.** That run needed two manual edits to the Yosys
   output before OpenROAD would read it. The RTL was subsequently rewritten
   to be flow-clean so no post-edit is needed — but that rewritten RTL is the
   one that has *never* been placed and routed, on any PDK.

The prototype's ERC run also found **6 of 9434 gates violating the antenna
ratio** on the tie-high net. That defect was reported, not fixed. Nothing
about changing PDK is expected to make it disappear.

## What this block is

Four independent voices. Each is a 24-bit phase-accumulator oscillator
(square, sawtooth, triangle, or sine from a 257-entry quarter table with
mirror/sign reconstruction), scaled by a linear ADSR envelope and a 7-bit
velocity through a three-stage integer scaler. The four voice outputs sum
into one saturating 16-bit sample per frame at 48 000 frames/s. A host drives
it over an 8N1 UART with a small byte protocol — note on, note off, per-voice
parameters, reset — parsed into an 8-deep command FIFO and applied at frame
boundaries under cycle-exact rules.

```
UART RX ──► byte parser ──► command FIFO ──► (applied at frame boundaries)
                                               │
            ┌──────────────────────────────────┴───────────┐
            │ voice 0: phase acc ─► waveform ─► × gain ─┐  │
            │ voice 1:      "          "          "     ├─► Σ ─► saturate ─► s16
            │ voice 2:      "          "          "     │  │
            │ voice 3:      "          "          "     ┘  │
            └──────────────────────────────────────────────┘
```

Everything in that picture is integer arithmetic with no tolerance anywhere.
There is no floating point in any path that produces a sample, in the RTL or
in the reference model, which is what makes "bit-exact" a check rather than
a figure of speech.

### Why this block

The sibling canaries are analog (`gf180-bandgap`, `gf180-pll`) and the one
prior digital canary (`sky130-modexp`) is a datapath with a single scalar
answer per run. A synthesizer is a different and useful shape for a canary:

- **Its correctness is a 480,000-sample stream, not a return value.** A
  defect that only shows up on the 12,000th frame of overlapping note events
  is a realistic defect, and it is one that a testbench built around
  single-transaction vectors structurally cannot find.
- **Its spec is timing, not just arithmetic.** The hard part of the contract
  is not the oscillator — it is which frame a command byte lands in when it
  arrives in cycle 255. That is a cycle-exact property, and it is where the
  prototype's one injected bug that *survived* the first bench was hiding.
- **It is demonstrable.** Correctness you can listen to is a different kind
  of argument from a green test run. `bench/demo/` holds two 10-second WAVs
  rendered *through the RTL* and checked sample-for-sample against the
  reference; `spec/reference/ode_to_joy.wav` is the specification itself,
  rendered before any hardware existed.

## The contract is frozen

[`spec/NUMERIC-CONTRACT.md`](spec/NUMERIC-CONTRACT.md) revision 1 fixes every
width, every arithmetic step, the ADSR state machine, the byte protocol and
the frame/command timing rules. Its own words: *"If two readers could
interpret a sentence differently, that is a defect in this document. File it;
do not resolve it by picking one reading."*

It is not edited to match what the RTL does. If the RTL and the contract
disagree, the RTL is wrong until a decision record says otherwise. The
contract's executable half is [`spec/reference/`](spec/reference/) — the
reference model *is* what "bit-exact" means here.

## Repo layout

```
spec/          the frozen numeric contract, its reference model, decision records
rtl/           Verilog sources -- one tree, both targets
tb/            cocotb testbench (bit-exact) + klt request documents + a klt-free runner
bench/         bare Verilator C++ harness, audio renderer, demo WAVs
asic/          the gf180mcu flow -- UNTESTED, and the first work item
fpga/          ECP5 demonstration target
sim/           append-only evidence records (empty; the convention is ratified)
```

## Reproducing everything on this page

No PDK, no klayout-tools, no Docker. `python3`, `iverilog`, `verilator`,
`pip install cocotb numpy pytest`.

```bash
# the contract's executable half                            (~0.3 s, 102 tests)
(cd spec/reference && python3 -m pytest -q test_synth_ref.py)

# the bit-exact bench, both engines, the contract's voice count  (~10 s each)
python3 tb/run_tb.py --sim icarus    --nv 4
python3 tb/run_tb.py --sim verilator --nv 4

# the negative controls -- each of these MUST fail
for b in GAIN TICK UART ENV; do
  python3 tb/run_tb.py --sim icarus --define INJECT_BUG_$b=1 && echo "SURVIVED: $b"
done

# 10 s of audio through the RTL, every sample checked           (~8 s)
python3 bench/render.py --build --voices 2 --out bench/demo/synth_demo_2voice.wav

# lint, exactly as CI runs it
bash .github/scripts/lint.sh

# the ECP5 bitstream (needs yosys + nextpnr-ecp5 + ecppack)     (~3.4 s)
(cd fpga && make build)
```

The gf180mcu flow needs a PDK and is documented separately in
[`asic/README.md`](asic/README.md) — including the fact that it has never
been run.

## Gap to T1 on gf180mcu

T1 ("sim-validated") is the tier this toolchain can close, and it is graded
**per block per PDK**. This block is at **none of it** on gf180mcu. Against
the ten-item checklist, in the order the work has to happen:

| # | T1 item | State | What must happen |
|---|---|---|---|
| — | *precondition* | missing | **Ratify a physical spec table** — target clock, area budget, power, corner set, IO timing. Item 5 is defined as per-row pass/fail against a *ratified* table; without one there is nothing to grade. Needs a decision record and the two-key ratification the sibling canaries use. |
| — | *precondition* | missing | **Install and pin a 5LM gf180mcu PDK** (`gf180mcuC`/`gf180mcuD`, with its open_pdks hash recorded). `gf180mcuA` is 3LM, ships a complete cell library, and still cannot route this design. |
| 1 | Design sources + synthesized netlist | **half** | RTL is committed and verified. No gf180mcu gate-level netlist exists — `klt synthesize` has never resolved a gf180mcu liberty. |
| 2 | Routed GDS, reproducibly generated | **not started** | Run `klt place-and-route` with the committed `power` block. Expect the first attempt to fail on something; the prototype needed four attempts on sky130, all for netlist-hygiene reasons this RTL was rewritten to avoid. |
| 3 | DRC clean, deck identified, **coverage gaps disclosed** | **not started** | `klt drc --deck gf180mcu`, `status: clean`. The claim must quote the report's own `coverage.layers_in_stream_without_rules`, `coverage.rules_skipped` and `coverage.deck_scope` — a clean verdict from a deck with undisclosed holes is a false claim, and `klt signoff` does not check this for you. |
| 4 | LVS `status: match` **and** `power_connectivity` not mismatched | **not started** | `klt extract --abstract-cells` then `klt lvs` against the as-built gate-level netlist. Both verdicts must be stated; an `unchecked` power-connectivity result means the question was never asked and must be reported as such. |
| 5 | Multi-corner STA + bit-exact functional suite, per-corner pass/fail | **half** | The functional half is done and re-runnable. The STA half needs `klt sta` across a declared gf180mcu corner set — at minimum `tt_025C_5v00`, `ss_125C_4v50`, `ss_n40C_4v50`, `ff_125C_5v50`, `ff_n40C_5v50` — every corner `timing_status: constrained` with non-negative setup **and** hold slack. `asic/sta-polysynth.json` is single-corner today. |
| 6 | Statistical rows carry Monte Carlo evidence | **not started** | This block's spec rows are expected to be non-statistical (functional correctness, Fmax, area, power). The item is satisfied by *saying so explicitly* in the claim, not by omitting it — and that statement can only be made once the spec table of item 5's precondition exists. |
| 7 | Post-layout functional re-run with back-annotated SDF | **not started** | Re-run the same cocotb suite against the post-route gate-level netlist with `options.sdf`, so `environment.sdf.annotated` is `true`. An unannotated gate-level regression renders `not_post_layout`, and an STA run — even a SPEF-annotated one — does not satisfy this item. |
| 8 | Aggregated characterization report | **not started** | Fmax, area and power across the gf180mcu corner set, each verdict citing the record it rests on. |
| 9 | Testbenches shipped, cold-start documented, PDK pinned | **half** | Testbenches, runner and cold-start commands are committed and work. The PDK revision is not pinned anywhere, because none is installed. |
| 10 | README + spec table + reproduction + licence + CI | **half** | README, licence and CI are here and CI is green on the PDK-free legs. The spec table is the functional contract only; a physical one does not exist. |

Two further things that are not T1 items but should not be lost:

- The prototype's **6 antenna-ratio violations** on the tie-high net are a
  live, demonstrated defect class for this design. `klt erc` cannot even be
  run here yet, because the gf180mcu stackup spec document it needs has two
  entries that must be read off an installed PDK rather than invented — see
  [`asic/README.md`](asic/README.md#antennaerc-the-missing-spec-document).
- **Metal4/Metal5 strap pitch is 44.8 / 89.6 µm.** If the first real
  floorplan comes out small, the committed PDN geometry needs revisiting.
  That is a measurement, so it waits for the first run.

## Continuous integration

Every PR and push to `main` runs
[`.github/workflows/ci.yml`](.github/workflows/ci.yml): lint (python, JSON,
shell, `verilator --lint-only -Wall`, and a check that the generated ROMs
still regenerate byte-identically with the contract's own hashes), the
reference model's 102-test suite, the bit-exact cocotb suite over
{Icarus, Verilator} × {`NV`=2, `NV`=4}, and the four injected-bug negative
controls, each of which must fail.

All of it is PDK-free and runs on hosted runners in single-digit minutes.
Nothing is routed to `[self-hosted, heavy]`. CI mints no evidence records —
see [`sim/README.md`](sim/README.md).

## Provenance

The RTL, the cocotb testbench, the Verilator harness and the ECP5 target were
produced in a timed rehearsal before this repository existed, and are carried
in here rather than rewritten. What is new here: the gf180mcu flow
configuration, the two decision records, the evidence-record convention, the
klt-free test runner, CI, and the `NV = 4` verification runs. What was
dropped: the rehearsal's sky130 flow artifacts, its host-bound scripts and
its run logs, none of which describe this repository's target.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).
