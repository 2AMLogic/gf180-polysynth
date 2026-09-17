# layout

Where the routed DEF, the merged GDS, and the DRC / LVS / ERC reports on the
gf180mcu implementation of `synth_core` will live once `asic/` has actually
executed. **Nothing has been run on gf180mcu yet** — see the README's status
section — so this directory holds only its toolchain pin today.

The flow request documents are in `asic/` (`synthesize-polysynth.json` →
`par-polysynth.json` → `lvs-polysynth.json` / `sta-polysynth.json`, driven by
`asic/run-signoff.sh`). `asic/par-polysynth.json` carries a `power` block
(Metal1 followpins, Metal4/Metal5 straps, via-stack tuning), so the first
routed artifact committed here is expected to arrive with a real power
delivery network — `response.power.pdn: true`, a tapcell master named — rather
than the row-rail fallback. That is the structural power-delivery requirement
(T1 item 11) a claim on this block will be graded against, alongside item 4's
`power_connectivity.status: "match"` and a `klt erc` supply-connectivity read
(one island per supply, zero `erc.missing_tie`).

## Contents (once populated)

- `synth_core.def` / `synth_core.gds` — the `route`-stage outputs of
  `klt place-and-route`, with the resolved standard-cell GDS merged in.
- `drc/`, `lvs/`, `erc/` — the JSON reports, each citing the GDS sha256 it
  was run on; the evidence records that *cite* these reports are append-only
  under `sim/`, per `sim/README.md`.
- `toolchain.json` — the `klt` capability pin every runner in this directory
  checks before doing anything (see the file's own comment; append-only).

This directory exists from admission so the repo has the same shape as its
sibling canaries; it is not evidence of any result.
