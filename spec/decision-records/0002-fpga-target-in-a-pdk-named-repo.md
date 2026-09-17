# 0002: An `fpga/` target inside a `<pdk>-<block>` repository

- **Status**: ratified
- **Date**: 2026-09-17
- **Decided by**: block agent, at repository creation

## Context

Every canary repository so far is named `<pdk>-<block>` — `gf180-bandgap`,
`sky130-modexp`, `gf180-pll` — and the convention carries a promise: the
prefix names the process the block is built on, and everything in the
repository is work toward that process. This repository breaks the promise in
a visible way. It is named `gf180-polysynth`, and it contains `fpga/`: a
complete ECP5 (Lattice LFE5U-25F) target with a PLL, an I2S transmitter, a
pin constraint file and a Makefile that produces a bitstream. ECP5 is not a
PDK. A reader scanning the repository list has no way to tell from the name
that a second, non-PDK target lives inside, and a reader inside the
repository has no way to tell which target a given claim is about unless
every claim says so.

The alternative shapes were available and were not obviously worse — a
separate `ecp5-polysynth` repository, or dropping the FPGA leg entirely — so
the departure needs a recorded reason rather than an accident of how the
prototype was laid out.

## Decision

The `fpga/` target stays in this repository, under an explicit asymmetry that
every document here must preserve:

1. **The ASIC leg is the graded artifact.** `asic/` on gf180mcu is what the
   repository name refers to, what the T1 evidence ladder grades, and what
   "this block is at tier N" will mean. The FPGA leg is graded by nothing.
2. **The FPGA leg is a demonstration and a verification target**, not a
   deliverable. It exists because a synthesizer whose output can be *heard*
   on real hardware is a different kind of evidence from a passing testbench,
   and because a second, independent synthesis path over the same RTL
   (`synth_ecp5` + `nextpnr-ecp5`) is a cheap, fast, structurally different
   check that the sources are portable and flow-clean — it catches a class of
   RTL defect in seconds that an ASIC P&R surfaces in a quarter of an hour.
3. **One RTL source, no forks.** `rtl/` is the single source for both legs.
   `fpga/` may add wrappers around it (clocking, IO, serialization) but may
   not contain a modified copy of any file in `rtl/`, and neither leg may
   carry a `\`ifdef` that changes what the block computes. If the two targets
   ever need different *behaviour*, that is a spec question and goes through a
   decision record, not a build flag.
4. **Every claim names its target.** No sentence in this repository says "the
   design closes timing" or "the design was verified" without naming ECP5 or
   gf180mcu. An ECP5 bitstream is never cited as ASIC evidence, and no `sim/`
   evidence record may cite an FPGA artifact for an item the ASIC leg owns.

## Alternatives considered

- **A separate `ecp5-polysynth` repository.** Keeps the naming convention
  exactly, and keeps the two evidence trails from ever being confused.
  Rejected: it would have to duplicate `rtl/`, `tb/`, `spec/` and the
  reference model, or depend on this repository as a submodule. Both are
  worse than an asymmetry stated once — a duplicated RTL tree is a fork
  waiting to happen, and the fork would be discovered by someone hearing two
  different synthesizers. The thing worth protecting is the single source,
  not the repository name.
- **Drop the FPGA leg.** Cleanest possible conformance. Rejected on what is
  lost: the fastest available demonstration that the block does what it says
  (an ASIC leg cannot be listened to for months, if ever), and a second
  synthesis engine over the same sources for the price of a three-second
  build. The prototype's own record is that the ECP5 build was the cheapest
  useful artifact it produced.
- **Rename the repository to something PDK-neutral (`polysynth`).** Removes
  the mismatch by removing the claim. Rejected: the prefix is load-bearing
  for the *other* thing it signals — tiers are granted per block per PDK
  (`klayout-tools/docs/design-evidence-tiers.md`), so a PDK-neutral name
  makes it harder, not easier, to tell what a tier claim on this block would
  mean. Decision record 0001 is the reason the prefix is `gf180`; that
  reasoning survives having an extra target in the tree.

## Consequences

- **The repository list is now slightly misleading**, and no README can fix
  that for someone who never opens the repository. Accepted cost. The
  top-level README's second paragraph names both targets before it names
  anything else.
- **Two build flows to keep working.** The ECP5 leg needs
  yosys/nextpnr-ecp5/prjtrellis on `$PATH`; the ASIC leg needs a gf180mcu
  PDK and OpenROAD. Neither is in CI (CI is PDK-free and toolchain-light by
  `.github/workflows/ci.yml`'s own scope statement), so an RTL change can
  break either leg without CI noticing. The mitigation is that both legs
  build from `rtl/` in seconds-to-minutes locally, not that anything
  automated catches it.
- **A tempting shortcut is now explicitly closed.** With an FPGA target in
  the tree, the cheapest way to make a stalled ASIC claim look satisfied is
  to cite an FPGA artifact for it. Rule 4 exists to close that, and it is the
  rule most likely to be violated by accident — a reviewer should read every
  evidence record's cited artifact against the target it claims.
- **`fpga/top.v` builds all four voices (`NV=4`).** It instantiated one when
  this record was first written, which made the ECP5 leg not even a
  full-scale demonstration of the ASIC target; at `NV = 4` the two legs now
  elaborate the same amount of logic, so their utilisation figures are
  comparable in kind (not in units — LUT4s are not standard cells). The
  voice count remains a module parameter the contract itself parameterizes,
  so rule 3 is intact either way.
