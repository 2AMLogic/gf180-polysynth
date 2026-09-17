# 0001: PDK selection — gf180mcu over sky130

- **Status**: ratified
- **Date**: 2026-09-17
- **Decided by**: block agent, at repository creation

## Context

The block's functional specification (`spec/NUMERIC-CONTRACT.md`, revision 1,
frozen) is deliberately PDK-neutral: it fixes widths, arithmetic and a byte
protocol, and names no process. The prototype that produced this repo's RTL
and testbench (a 53-minute timed rehearsal) ran its ASIC leg on **sky130**,
because that was the PDK already installed on the rehearsal host — a
convenience choice, not a design one. Standing this up as a canary block
forces the question to be answered on its merits, and the answer has to be
made before any flow artifact is produced, because a routed layout is not
portable between PDKs and every evidence record is stamped with the PDK it
was measured on.

Two facts constrain the choice. First, a T1 claim is graded **per block per
PDK** (`klayout-tools/docs/design-evidence-tiers.md`) — picking a PDK is
picking which flow runs count. Second, the sibling canaries are on gf180mcu
(`gf180-bandgap`, `gf180-pll`) and their fab route — Chipalooza / Wafer.Space
on GF180MCU — has no sky130 equivalent that is currently open to this
program.

## Decision

This block targets **gf180mcu**, as the repository name says.

Concretely: `gf180mcu_fd_sc_mcu9t5v0` (9-track, 5 V) standard cells, on a
**5LM** PDK variant (`gf180mcuC` or `gf180mcuD`), with `klt drc --deck
gf180mcu` as the physical-verification deck. The 3LM `gf180mcuA` variant is
explicitly excluded: it ships a complete `gf180mcu_fd_sc_mcu9t5v0` liberty
and LEF set but only `Metal1`–`Metal3`, and this flow's signal routing range
is `Metal2`–`Metal5`, so a 3LM install dies in the `place` stage with
`[ERROR PPL-0051] Layer Metal4 not found.` The variant must be pinned rather
than discovered.

The sky130 prototype results are kept as prototype results — they are cited
in this repo's README as evidence that *the flow shape works*, and nowhere as
evidence about this block on gf180mcu.

## Alternatives considered

- **sky130, i.e. keep what the prototype ran.** The cheapest option by a
  wide margin: the whole signoff chain (synthesize → P&R → DRC → extract →
  LVS → STA → ERC) is already demonstrated end to end on this design at
  sky130, and re-running it would produce a T1-shaped evidence trail in
  roughly the time a single P&R takes. Rejected on two grounds. **Fab
  route**: the program's open shuttle access is a GF180MCU one, and a block
  that cannot reach the same shuttle as its siblings cannot progress past T1
  however good its simulation evidence is — T3 is defined by measured
  silicon, and silicon needs a seat. **Physical verification**: the one
  physical-verification defect the prototype did surface was a gf180-flavoured
  one in disguise — a layout produced without a power grid. gf180mcu is the
  node where klayout-tools' own record shows omitting `request.power` is not
  merely incomplete but *DRC-failing* (19 identical `nwell.space.1`
  violations from unfilled standard-cell row gaps, `klt place-and-route`'s
  own gf180mcu run notes), whereas the prototype's sky130 run reported DRC
  clean with no power grid at all and no complaint. Choosing the PDK whose
  deck actually catches that class of omission is the point of a canary.
- **Both PDKs from one RTL source, as a portability demonstration.** The
  RTL is already flow-clean enough that this is plausible, and it would
  double the deck coverage. Rejected as scope, not as a bad idea: two PDKs
  means two evidence trails, two corner sets, two DRC decks and two sets of
  staleness to keep fresh, and this block has *zero* complete trails today.
  One PDK taken to a real T1 claim is worth more than two taken halfway. If
  it is revisited, it needs its own record and its own repository naming
  decision — `gf180-polysynth` is a per-PDK name by construction.
- **IHP sg13g2.** A genuinely open PDK with a working `klt` path and, at
  130 nm, more headroom than either 180 nm option. Rejected: no fab route
  available to this program, no sibling canary on it, and — unlike gf180mcu
  and sky130 — the one thing the toolkit's own notes flag is that it has no
  CI equivalent and thinner in-repo verification of its platform tables. A
  canary should be on a node the program can actually ship to.

## Consequences

- **Every sky130 number this design has is now a prototype number.** The
  routed layout, the 4009/9240-cell synthesis figures, the +73 ns worst
  slack, the clean DRC and matching LVS: none of it is evidence about this
  repo's target. The README must say so, and does. The gf180mcu flow starts
  from zero.
- **The flow config in `asic/` is untested by construction.** It is written
  against gf180mcu's own platform data (cell library, site
  `GF018hv5v_green_sc9`, IO layers `Metal3`/`Metal4`, the ORFS
  `pdn_grid_strategy_9t_6M.cfg` strap geometry) rather than adapted by
  search-and-replace from the sky130 request, but nothing has run it. Its
  first run is the block's first work item.
- **Area and timing will both move, and not in the same direction.**
  gf180mcu 9-track 5 V cells are substantially larger than sky130's
  9-track 1.8 V ones, so the area figure will grow; the 12.288 MHz core
  clock (81.38 ns period) has so much slack in the prototype that the node
  change is very unlikely to threaten closure. Neither statement is a
  measurement — both are predictions to be checked against the first real
  run and recorded under `sim/`.
- **A 5 V library has consequences the contract does not cover.** IO levels,
  the UART's electrical interface and any analog neighbour's supply are all
  outside `NUMERIC-CONTRACT.md`'s scope, which stops at the digital boundary.
  A physical spec table (see `spec/README.md`, "What is not ratified yet")
  has to close those.
- **`gf180mcuA` installs are a live failure mode.** Variant discovery picks
  the alphabetically-first install, which is exactly the one that cannot
  route this design. `asic/README.md` records the pin; a run that forgets it
  fails late, in `place`, after a full synthesis.
