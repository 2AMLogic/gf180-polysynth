# spec — the frozen numeric contract + decision records

- [`NUMERIC-CONTRACT.md`](NUMERIC-CONTRACT.md) — **revision 1, frozen.** The
  complete bit-exact specification of the block: fixed widths, the phase
  accumulator, the four waveform derivations, the linear ADSR state machine,
  the saturating mixer, the UART byte protocol, the frame/command timing
  rules, and reset values. Its own words: *"If two readers could interpret a
  sentence differently, that is a defect in this document. File it; do not
  resolve it by picking one reading."* Any change to a normative statement
  bumps the revision and moves `synth_ref.CONTRACT_REV` with it.
- [`reference/`](reference/) — the executable half of the contract: the
  reference model that *is* the specification's meaning wherever prose and
  code could diverge, its own 102-test suite, and a renderer that makes the
  spec audible before any hardware exists. See
  [`reference/README.md`](reference/README.md).
- [`decision-records/`](decision-records/) — decisions that extend the
  contract without editing its frozen text. Each record cites what it
  extends.
  - [`TEMPLATE.md`](decision-records/TEMPLATE.md) — copy this to start a new
    record; it also carries the numbering rule.

## Decision records

One page per decision: the context that forced it, the decision itself
(stated as a concrete spec change), alternatives considered, and
consequences — including the bad ones.

| Record | Title | Status |
|---|---|---|
| [0001](decision-records/0001-pdk-selection-gf180mcu.md) | PDK selection — gf180mcu over sky130 | Ratified |
| [0002](decision-records/0002-fpga-target-in-a-pdk-named-repo.md) | An `fpga/` target inside a `<pdk>-<block>` repository | Ratified |

A record is never deleted or rewritten once ratified — a later change
supersedes it with a new record rather than editing history in place (the
same append-only convention as `sim/`, see [`sim/README.md`](../sim/README.md)).

## What is *not* ratified yet

The numeric contract is frozen, but it is a **functional** contract only: it
fixes what the block computes, not what silicon it must close in. There is no
ratified **physical** spec table — target clock, area budget, corner set,
power, IO timing — and therefore no ratified row for a T1 item 5 verdict to
be measured against. Writing that table for gf180mcu, and getting it through
the two-key ratification the other canaries use, is open work. Until it
exists, every physical number in this repo is a measurement, never a verdict.
