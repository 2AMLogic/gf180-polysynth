# 0003: Sibling instrument repositories, and where the shared digital substrate lives

- **Status**: proposed — part 3 and the cross-repo half of part 1 need operator
  ratification; see "Ratification" below
- **Date**: 2026-09-17
- **Decided by**: block agent — proposed, not ratified

## Context

The hardware memo (v0.3) names several instruments beyond this one: a
Minimoog-inspired monosynth, a drum machine with FM percussion, a two- or
four-operator FM voice, a wavetable/wavefolding voice. These are not variants
of this block. Each would have its own numeric contract, its own area budget
and its own fabrication decision. Two questions follow: does each get a
repository, and what happens to the substrate they all share?

The naming convention is measured, not assumed. The organisation has 38 block
repositories named `<pdk>-<block>`, and the unit is **(block × PDK)**, not
(product): nine block names already exist on more than one PDK as separate
repositories — `bandgap`, `comparator`, `ldo`, `opamp` and `pll` on three PDKs
each, `sar-adc`, `temp-por`, `trng` and `usb2-phy` on two. No repository in
the organisation uses a git submodule; the count is zero across all 50.

Two pieces of evidence bear on the shared-substrate half, and they agree.

**The same block on two PDKs has already diverged completely.**
`sky130-usb2-phy` and `gf180-usb2-phy` implement the same USB 2.0 protocol
logic. They share not one git blob. Module names differ
(`usb_linestate.v` against `usb_line_state_decode.v`; `usb_bit_sync.v` against
`usb_sync_detector.v`), the file counts differ (13 against 9), and
`usb_nrzi_encoder.v` — NRZI line coding, defined by the USB specification,
containing nothing PDK-dependent whatsoever — exists twice with incompatible
interfaces: `bit_stb`/`bypass`/`sof`/`level_out` in one, and
`data_valid`/`init`/`line_valid`/`line_bit` in the other. Neither is wrong.
They simply cannot be checked against each other, and a defect fixed in one
never reaches the other.

**This repository has already been bitten by the copy.** `fpga/i2s_tx.v` and
`fpga/top.v` arrived here as a copy of the sky130 prototype's files. Both were
defective, and PR #4 fixed them: the I2S MSB was one BCLK late, so a receiver
reads every word shifted right by one with bit 15 clear — `0x8000` decodes as
`0x4000`, every negative sample plays positive, a square wave becomes near-DC;
and I2S was assigned to the Raspberry Pi header's ID-EEPROM pins, where no DAC
would have heard any of it. The copy carried both defects silently. Nothing in
either repository recorded that they held the same file, so nothing could
notice that they held the same broken one.

The organisation has already solved this problem once, for prose.
`2am/ratification/canary-variant.md` rejects a hand-maintained second copy of
the EE-key skill in terms that transfer without modification: *"A
hand-maintained second copy would drift from the master the first time either
one is edited without the other — exactly the failure mode a mechanism whose
entire job is disclosure discipline cannot afford."* Masters live in one place
and installed copies are generated mechanically. RTL has a sharper version of
the same argument: a drifted paragraph is a documentation bug; a drifted
transmitter is silence on a board.

## Decision

**1. One repository per instrument, on the existing name shape.**
`<pdk>-<instrument>` — `gf180-monosynth`, `gf180-drumsynth`, and so on. Not
directories inside this repository, and not branches. Each instrument carries
its own numeric contract, climbs its own evidence tier and holds its own
fabrication decision. A port to a second PDK is a further repository
(`sky130-monosynth`), exactly as `bandgap`, `comparator`, `ldo`, `opamp` and
`pll` already are.

**2. A repository is created when its contract is worth freezing, and it is
never admitted to the fleet by an agent.** `2am/CLAUDE.md` cross-cutting rule 8
is explicit: *"Adding a repo to the fleet is never an agent decision."* This
repository is the template for the shape; the next instrument begins when its
numeric contract exists, not when its name is chosen. Creating repositories for
the memo's full ladder now would produce empty shells that claim nothing.

**3. Shared RTL is generated from a single master with recorded provenance,
never copied — and the trigger is the second instrument, not this one.**

At the moment a second instrument repository is created:

- The shared substrate is named explicitly. On today's tree that is
  `rtl/uart_rx.v`, the note→increment ROM and `rtl/gen_tables.py` that emits
  it, the envelope generator, `fpga/i2s_tx.v` with `fpga/tb_i2s.v`,
  `tb/run_tb.py` with its three-way exit contract, the `INJECT_BUG_*`
  negative-control discipline, and `spec/decision-records/TEMPLATE.md`.
- Those files have exactly one master. Until a dedicated repository is
  justified, the master is this repository.
- Each sibling carries them under `rtl/common/` and `tb/common/` beside a
  manifest recording the upstream repository, the upstream commit SHA, and a
  per-file SHA-256.
- Each sibling runs a CI job that recomputes those hashes against the recorded
  upstream and fails on any mismatch.
- A sibling **may** diverge from the master, but the divergence must be
  recorded as a decision record in the diverging repository. That is the whole
  point: divergence stops being an accident and becomes a decision someone
  made on purpose and wrote down.

Deliberately **not** done now: nothing is extracted while there is one
instrument. Extraction at the second instrument costs an afternoon. Not having
decided costs what `usb2-phy` cost.

## Ratification

Parts 1 and 2 are within this repository's authority for its own conventions
and are proposed as ratified-on-merge here. Part 3, and the half of part 1 that
binds repositories this one does not own, are **not this repository's to
ratify** — they are a cross-cutting convention, and cross-cutting rules live in
`2am/CLAUDE.md` under operator governance. This record is the proposal; the
operator ratifies it there, or rejects it, and this file's status is updated to
match. Per `gf180-drone-fc`'s DR-0005 precedent, the status field must not
claim ratification before that act has actually happened.

## Alternatives considered

- **A shared `audio-core` repository consumed as a git submodule** — zero
  precedent: no repository in the organisation uses a submodule. It also breaks
  the property every canary depends on, that a fresh clone builds and runs its
  own evidence with no second checkout, and it makes each sibling's evidence
  depend on a moving external reference, which the evidence tiers treat as a
  provenance problem rather than a convenience.
- **A monorepo holding every instrument** — breaks per-block, per-PDK grading,
  which is the entire point of the canary programme. Fleet admission, evidence
  tiers and `klt signoff` all key on the repository.
- **Copy and accept divergence — the status quo** — honest for analog, where an
  opamp on two PDKs really is two designs with two device-level answers. Not
  honest for a PDK-independent state machine that has one correct behaviour,
  which is how the organisation ended up with two incompatible NRZI encoders.
- **Extract the shared core now, before a second instrument exists** — an
  interface designed against exactly one consumer is an interface that fits
  exactly one consumer. The second instrument is what reveals which boundaries
  are real.

## Consequences

- The second instrument costs more up front: a manifest and a hash job, perhaps
  an afternoon. That cost is paid once and is the point of the record.
- This repository becomes a de-facto master the moment a second instrument
  exists. Its `rtl/` changes then acquire a downstream audience, and
  `rtl/README.md` must say so when that happens.
- The hash job is a new source of red CI, by design. A sibling that edits a
  shared file in place gets a failure rather than a silent fork.
- This does **not** retroactively fix `sky130-usb2-phy` and `gf180-usb2-phy`.
  Their divergence is already real and reconciling it is out of scope here; it
  is worth an issue in those repositories, not a clause in this one.
- If the operator rejects part 3, the fallback is copying with a mandatory
  provenance header naming the source repository, file and commit. Strictly
  weaker — a header does not fail CI when it goes stale — but better than the
  unmarked copy that produced the `i2s_tx.v` defect.
- Nothing here licenses creating repositories. Part 2 withholds that
  deliberately, and rule 8 withholds fleet admission regardless.
