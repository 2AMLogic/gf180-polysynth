# gf180-polysynth — agent instructions

Runtime-neutral copy of [`CLAUDE.md`](CLAUDE.md), for OpenAI Codex CLI and
other AGENTS.md-aware runtimes. The two files are kept in substance
identical: change one, change the other in the same commit.

Open-source canary block: a 4-voice polyphonic digital synthesizer on the
gf180mcu PDK, designed and verified by AI agents.

- **PDK**: gf180mcu (open PDK), `gf180mcu_fd_sc_mcu9t5v0` 9-track 5 V
  standard cells, 5LM variant (`gf180mcuC`/`gf180mcuD`). Open-source flow:
  cocotb + Icarus/Verilator, Yosys, OpenROAD, klayout-tools (`klt`). Drive the
  engines through `klt` rather than around it; `tb/run_tb.py` is the one
  deliberate klt-free path (same testbench, no evidence record).
- **Friction protocol (the canary's job)**: every time klayout-tools is
  awkward, missing a capability, or wrong for what you need, file an issue at
  `2AMLogic/klayout-tools` describing the tool gap generically — keep
  design-specific detail out of it and describe the gap, not the design.
- **Verification is the product**: no claim without a testbench. The
  testbench compares the DUT against `spec/reference/synth_ref.py` sample for
  sample with no tolerance. Recorded results in `sim/` are append-only
  evidence.
- Spec changes go through `spec/` with a decision record; agents do not relax
  the ratified spec to make results pass. `spec/NUMERIC-CONTRACT.md` is
  frozen: if the RTL and the contract disagree, the RTL is wrong until a
  decision record says otherwise.

## The honesty rule

Nothing in `asic/` has been run against gf180mcu. No file in this repo may
state or imply a gf180mcu synthesis, P&R, DRC, LVS, STA or ERC result until
one has been produced and recorded under `sim/`. T1 is graded per block **per
PDK**: a sky130 result is not a gf180mcu result, and an ECP5 bitstream is not
an ASIC result.
