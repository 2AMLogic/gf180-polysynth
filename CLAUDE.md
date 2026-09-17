# gf180-polysynth — agent instructions

Open-source canary block: a 4-voice polyphonic digital synthesizer on the
gf180mcu PDK, designed and verified by AI agents. The program's second
**digital** block after `sky130-modexp` — the flow here is RTL→GDS, not
schematic→layout.

- **PDK**: gf180mcu (open PDK), `gf180mcu_fd_sc_mcu9t5v0` 9-track 5 V
  standard cells, 5LM variant (`gf180mcuC`/`gf180mcuD`). Open-source flow:
  cocotb + Icarus/Verilator for functional verification, Yosys for synthesis,
  OpenROAD for place-and-route, klayout-tools (`klt`) for DRC/LVS/STA/ERC on
  the produced GDS. `klt synthesize`, `klt place-and-route`,
  `klt functional-verification`, `klt drc`, `klt lvs`, `klt sta` are the entry
  points — drive the engines through `klt` rather than around it, since
  dogfooding that surface is half the point of this repo. The one deliberate
  exception is `tb/run_tb.py`, a klt-free cocotb runner that exists so CI and
  a cold-start contributor need no klt install; it runs the *same* testbench
  and produces no evidence record.
- **Friction protocol (the canary's job)**: every time klayout-tools is
  awkward, missing a capability, or wrong for what you need, file an issue at
  `2AMLogic/klayout-tools` describing the tool gap generically — that tracker
  is scoped to the tool, so keep design-specific detail (spec values, this
  repo's content) out of it and describe the gap, not the design.
- **Verification is the product**: no claim without a testbench. The
  testbench compares the DUT against the frozen reference model
  (`spec/reference/synth_ref.py`) **sample for sample with no tolerance** — a
  claim that the RTL is correct means exactly that comparison passed, on a
  named engine, at a named commit. Recorded results in `sim/` are append-only
  evidence.
- Spec changes go through `spec/` with a decision record; agents do not relax
  the ratified spec to make results pass. `spec/NUMERIC-CONTRACT.md` is frozen
  — it is not edited to match what the RTL does. If the RTL and the contract
  disagree, the RTL is wrong until a decision record says otherwise.

## The honesty rule — read before writing any status line

This block arrived here from a 53-minute timed rehearsal (`trial1`) that
targeted **sky130**, not gf180mcu. The RTL, the testbench, the Verilator
harness and the ECP5 target carry over verified; **the ASIC flow does not**.
Nothing in `asic/` has been run against gf180mcu, so nothing in this repo may
state or imply a gf180mcu synthesis, P&R, DRC, LVS, STA or ERC result until
one has actually been produced and recorded under `sim/`. T1 is graded per
block **per PDK** (`klayout-tools/docs/design-evidence-tiers.md`): a sky130
result is not a gf180mcu result, and neither is an ECP5 bitstream. The
README's status section is the load-bearing one — keep it conspicuously
honest, including about what the prototype did on the *other* PDK.

<!-- BEGIN LOOM ORCHESTRATION -->
This repository uses [Loom](https://github.com/rjwalters/loom) for AI-powered development orchestration — see the Loom repository for the full guide (roles, labels, worktrees, configuration). When installed, Loom also writes a locally-substituted copy of that guide to `.loom/CLAUDE.md`.
<!-- END LOOM ORCHESTRATION -->
