# 0000: <short title>

<!--
Copy this file to spec/decision-records/NNNN-<slug>.md and fill it in.
Use the next unused NNNN (zero-padded 4 digits). One decision per record;
keep it to one page. A decision record is required for every change that
extends `spec/NUMERIC-CONTRACT.md`, and for every repo-level convention
choice that a reader would otherwise have to reverse-engineer. Never edit
the frozen text of `spec/NUMERIC-CONTRACT.md` itself — a decision record
extends and cites it, it does not rewrite it.

Numbering rule: before picking NNNN, check every filename already in this
directory on `main` (including superseded records) and use one greater than
the highest number found — never guess or reuse a number, and re-check if
another record may have landed concurrently, to avoid a collision.
-->

- **Status**: proposed | ratified | superseded by NNNN
- **Date**: YYYY-MM-DD
- **Decided by**: <name / role>

## Context

What forced this decision? One short paragraph: the constraint, the
measurement, or the conflict that made the current spec inadequate. Link to
the issue, the reproducible measurement in `sim/`, or the prior record it
extends.

## Decision

The decision, stated as an addition to the spec — the parameter and its new
value, or the contract now ratified. Be specific enough that design work can
lock to it without further interpretation.

## Alternatives considered

- **<alternative>** — why it was not chosen.
- **<alternative>** — why it was not chosen.

## Consequences

What follows from this: what becomes possible, what becomes harder, which
testbenches or corner sets change, what work is invalidated or must be
re-run. Include the bad consequences, not just the good ones.
