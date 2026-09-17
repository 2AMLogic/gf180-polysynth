# sim/ — evidence record format

This directory holds the results of runs. Results are **append-only
evidence**: once a record is written, it is never edited or deleted. A re-run
— even one that corrects a mistake — mints a new record with a new ID; a
correction references the record it supersedes rather than overwriting it in
place.

This convention exists because CLAUDE.md commits this repo to two rules that
need a concrete schema to be enforceable:

- **Verification is the product.** No claim without a testbench. For this
  block the testbench comparison is bit-exact against
  `spec/reference/synth_ref.py` with no tolerance, and every recorded
  functional result names the engine it ran on.
- **`sim/` is append-only evidence.** Re-runs get new records; records are
  never edited or deleted.

**This file is the authoritative convention.** It is the same convention
`gf180-bandgap`'s `sim/README.md` ratified, adapted from an analog block's
PVT-swept SPICE runs to a digital block's simulator/corner runs. Where a tool
or a script disagrees with this document, this document wins and the tool is
the thing that gets fixed.

> **Empty today, and that is the honest state.** No record has been minted.
> The results quoted in this repository's READMEs were produced by running
> the committed sources and are reproducible from them, but they are *README
> numbers*, not evidence records — they carry no record ID, no provenance
> block and no append-only guarantee. Minting the first records is part of
> the same work item as the first gf180mcu flow run.

## Directory / naming convention

Each distinct claim gets its own experiment directory:

```
sim/
  <experiment-slug>/                 # e.g. functional-bitexact, synthesis,
                                     #      place-and-route, drc-lvs, sta-corners
    request/                         # the klt request document(s) used
    artifacts/
      <record-id>/
        <report>.json                # the klt JSON report(s), verbatim
        <report>.stderr              # kept when a stage failed
    records/
      <record-id>.md                 # append-only summary record
```

- **`<experiment-slug>`** — short, kebab-case, one directory per distinct
  claim being tested, not per run.
- **`<record-id>`** — `<YYYYMMDD>-<HHMMSS>-<short-git-sha>`, e.g.
  `20260917-140355-a1283c3`. The sha is the commit the *sources* were at, so
  a record is checkable against the tree that produced it. The same
  `<record-id>` ties together the request, the raw reports and the summary.
- **`<run-id>`** — where one record covers several runs that differ in one
  axis (simulator engine, `NV`, liberty corner), each run's artifacts get a
  subdirectory named for that axis value: `icarus/`, `verilator/`,
  `tt_025C_5v00/`, `nv4/`. The record's **Matrix run** field lists them.

## Summary record format

Each run produces one `records/<record-id>.md` with these fields. The first
nine are required; a record missing one is not a record.

- **Record ID** — matches the filename and the `artifacts/` subdirectory.
- **Claim** — which specific thing this substantiates: a clause of
  `spec/NUMERIC-CONTRACT.md`, a row of the physical spec table once one is
  ratified, or a named T1 checklist item.
- **Target** — **`gf180mcu`**, `sky130`, `ecp5`, or `simulation-only`. This
  field exists because this repository has two build targets and a prototype
  history on a third PDK, and because tiers are graded per block per PDK. A
  record whose Target is not `gf180mcu` can never satisfy a gf180mcu tier
  item, whatever it says. There is no default; omitting it invalidates the
  record.
- **Source provenance** — `rtl` (pre-synthesis), `gate-level` (synthesized
  netlist), or `post-route` (as-built netlist / routed DEF / routed GDS).
  Required so a post-route re-run is never mistaken for the pre-layout one.
- **Matrix run** — the explicit list of points actually executed: simulator
  engines, `NV` values, liberty corners, PVT points. Naming a subset is
  allowed; the record must say why.
- **Tool versions** — every engine with its version string (`klt`, Yosys,
  OpenROAD, KLayout, Icarus, Verilator, cocotb), plus the PDK variant and its
  open_pdks hash where one was used. A number without the tool that produced
  it is not reproducible.
- **Result** — per-point pass/fail, plus one overall verdict. For a
  functional run: tests passed / total, and the count of samples compared.
  For a flow run: the report's own top-level status field, quoted.
- **Coverage gaps** — what the tools did *not* check. For a DRC record this
  means quoting the report's own `coverage.layers_in_stream_without_rules`,
  `coverage.rules_skipped` and `coverage.deck_scope`; for an LVS record,
  `power_connectivity.status` (and saying so plainly when it is
  `"unchecked"`, which means the question was never asked, not that the
  answer was yes). A clean verdict from a deck with undisclosed holes is a
  false claim.
- **Links** — paths to the request document, the raw reports, and the
  testbench or flow script.
- **Timestamp / author** — when, and who (human or agent).
- **Supersedes** (optional) — the prior `<record-id>` this replaces, for a
  correction or for a post-route re-run reporting a delta against the
  pre-layout record.
- **Notes** (optional, `## Notes`) — free-form detail that does not fit
  above. Not part of the verdict.

## Append-only rule

`records/*.md` are never edited or deleted after creation. A re-run or a
correction always creates a new record with a new `<record-id>` and
references the old one via **Supersedes**. This applies even to typo fixes —
the append-only guarantee is what makes `sim/` usable as an evidence trail,
and "fixing" a record in place defeats it.

The same rule governs `spec/decision-records/`: a ratified record is
superseded, never rewritten.

## What CI does and does not do

CI mints **no records**, ever. `.github/workflows/ci.yml` runs the
PDK-free legs (the cocotb suite on both engines, the reference model's own
suite, lint) so a pull request never waits on a PDK download; records are
minted deliberately, locally, against a pinned environment, by someone who
then commits the raw reports alongside the summary.

A green CI run is therefore not evidence of anything in this directory. It is
evidence that the sources still build and the bit-exact comparison still
passes on two simulators, which is a different and smaller claim.
