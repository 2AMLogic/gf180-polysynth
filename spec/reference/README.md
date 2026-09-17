# spec/reference — the executable half of the contract

`NUMERIC-CONTRACT.md` is prose; this directory is the same specification as
runnable Python. Where the two could be read differently, the model is what
the testbench actually compares against, so the model is what "bit-exact"
means in this repository.

| File | What |
|---|---|
| `synth_ref.py` | The reference model. Integer-only, no floating point in any path that produces a sample. Public API: `feed(bytes)`, `step()`, `render(n)`, `render_script(events, n)`, plus `cmd_*` helpers that build protocol bytes. Carries `CONTRACT_REV`, which moves with the contract's revision number. |
| `test_synth_ref.py` | The model's own suite — **102 tests**, contract clause by contract clause. Every test that renders samples goes through the public API and asserts exact integers, which is what lets the cocotb bench replay the same byte scripts into the RTL. |
| `render_wav.py` | Renders "Ode to Joy" through the model (sawtooth melody, square bass, two pad voices) and writes a mono 16-bit 48 kHz WAV, so the specification can be *heard* before any hardware exists. |
| `ode_to_joy.wav` | That render, committed. 28.3 s, produced by the model alone — no RTL involved. |
| `tables/` | The frozen lookup tables as hex: `note_inc.hex` (128 MIDI note phase increments), `sine_q.hex` (257-entry quarter sine), `sine_full.hex` (the 1024-point expansion the quarter table reconstructs). |

## Running it

```bash
cd spec/reference
python3 -m pytest -q test_synth_ref.py     # 102 tests, ~0.3 s
python3 render_wav.py ode_to_joy.wav       # regenerate the audible spec
```

Needs `numpy` and `pytest`; nothing else, no PDK, no simulator.

## The tables are the contract's, not the RTL's

`rtl/note_inc_rom.vh` and `rtl/sine_q_rom.vh` are **generated** from
`synth_ref.NOTE_INC` and `synth_ref.SINE_Q` by `rtl/gen_tables.py`, and each
generated file carries the SHA-256 of the table it was built from. Those two
hashes are printed in the contract's own Appendix A and B:

```
NOTE_INC  e771e6b7b39d3941c471b772bfb5cdca398b78ee7fa964c3c90388d2cc888ba4
SINE_Q    72e3ab187d9c5e27be2a1dfbf209610aca3bf553eea8d15b0db53e05b240ef4f
```

So the RTL's tables and the model's tables cannot silently diverge: re-running
`python3 rtl/gen_tables.py` must leave both `.vh` files byte-identical, and the
hash in each header must still match the contract. That check is one `diff`,
and it is worth running after any touch to this directory.

## Provenance

Authored during the specification phase that preceded the RTL, and carried in
here unmodified apart from this README. The contract it implements is frozen
at revision 1.
