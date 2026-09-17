# bench — bare Verilator harness and audio renderer

The cocotb bench in `tb/` is the correctness gate. This directory is the
*volume* gate: a C++ Verilator harness with no cocotb, no VPI and no Python
in the loop, fast enough to push ten seconds of real audio through the RTL
and compare all 480,000 samples against the reference model.

| File | What |
|---|---|
| `harness.cpp` | `./synth_bare <frames> <script.bin> <out.bin>`. Feeds a byte script through the direct byte port (one byte per clock from cycle 10 of frame *f−1*, matching how `SynthRef.render_script()` defines "immediately before frame *f*"), dumps samples as little-endian int16, prints a JSON stats line. |
| `render.py` | Builds the harness, generates a demo song, runs it, compares sample-for-sample against `synth_ref.render_script()`, writes a WAV. Any mismatch is a non-zero exit with the first differing frame named. |
| `demo/synth_demo.wav` | 10 s, one square voice, a melody with ADSR. |
| `demo/synth_demo_2voice.wav` | 10 s, square + sine. Peaks at 32768, i.e. it deliberately saturates the mixer. |

## Running it

```bash
python3 bench/render.py --build --voices 2 --out bench/demo/synth_demo_2voice.wav
```

Needs `verilator` and `numpy`. No PDK, no klayout-tools. `--build` forces a
rebuild; without it an existing `bench/build/synth_bare` is reused.

## Measured, in this repository

Apple M5 / macOS 26.5.1, Verilator 5.053 (devel), machine otherwise busy:

| Run | Result |
|---|---|
| 2-voice, 480,000 frames | **480,000/480,000 samples bit-exact**, 122.9 M cycles in 5.35 s = **23.0 M cycles/s**, 89.7 k samples/s, 0 FIFO overflows |
| 1-voice, 480,000 frames | **480,000/480,000 bit-exact**, 14.9 M cycles/s (concurrent load) |
| Verilator build from clean | 1.6 s |
| Reference model render of the same 10 s | 0.63 s |

Throughput numbers are lower bounds — the host was carrying other work. The
bit-exactness is not a bound; it is exact or it fails.

Both committed WAVs were regenerated from this repository's own sources, not
copied from the prototype.

## Why this exists alongside the cocotb bench

They fail differently. The cocotb bench is a small number of long, carefully
constructed scripts that pin specific contract clauses, including timing
corners a renderer would never hit. The renderer is one enormous, boring,
musically-shaped script — hundreds of overlapping note-ons, note-offs and
parameter changes at arbitrary frame offsets — run at a volume the cocotb
bench cannot reach in reasonable time. A defect that needs half a million
frames of mixed traffic to show up lands here; a defect that needs a command
byte in cycle 255 lands there.
