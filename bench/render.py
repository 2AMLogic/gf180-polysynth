#!/usr/bin/env python
"""Render the demo song through the bare Verilator harness, check it
bit-exactly against synth_ref.render_script, and write a WAV.
    python bench/render.py [--seconds 10] [--build]
"""
import argparse, json, os, struct, subprocess, sys, time, wave
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# the frozen reference model lives with the contract it implements
sys.path.insert(0, os.path.join(_ROOT, "spec", "reference"))
import numpy as np
import synth_ref as S

T1 = _ROOT
ap = argparse.ArgumentParser()
ap.add_argument("--seconds", type=float, default=10.0)
ap.add_argument("--build", action="store_true")
ap.add_argument("--out", default=os.path.join(T1, "bench", "demo", "synth_demo.wav"))
ap.add_argument("--voices", type=int, default=1)
a = ap.parse_args()
FS = S.SAMPLE_RATE
N = int(a.seconds * FS)
BUILD = os.path.join(T1, "bench", "build")
os.makedirs(BUILD, exist_ok=True)

# ---- the song: one square voice, a little melody with ADSR --------------------
def song(nvoices=1):
    ev = []
    A, D, SUS, R = 0x2000, 0x400, 0x8000, 0x200         # attack 128 fr, decay ~10 ms, release ~21 ms
    for v in range(nvoices):
        ev.append((1, S.cmd_set_adsr(v, A, D, SUS, R) + S.cmd_set_wave(v, S.WAVE_SINE if v == 1 else S.WAVE_SQUARE)))
    # melody in C major-ish (MIDI), 150 ms per step, note held 120 ms
    tune = [60, 64, 67, 72, 67, 64, 60, 62, 65, 69, 74, 69, 65, 62,
            64, 67, 71, 76, 71, 67, 64, 65, 69, 72, 77, 72, 69, 65,
            60, 64, 67, 72, 76, 79, 84, 79, 76, 72, 67, 64, 60, 55, 52, 48]
    step, hold = int(0.150 * FS), int(0.120 * FS)
    f = 2
    i = 0
    while f + step < N - 1:
        note = tune[i % len(tune)]
        vel = 100 + (i * 7) % 28
        ev.append((f, S.cmd_note_on(0, note, vel)))
        ev.append((f + hold, S.cmd_note_off(0)))
        if nvoices >= 2:                                   # second voice: a fifth below, offset
            ev.append((f + step // 2, S.cmd_note_on(1, note - 7, 80)))
            ev.append((f + step // 2 + hold, S.cmd_note_off(1)))
        f += step
        i += 1
    return ev

events = song(a.voices)
script = os.path.join(BUILD, "script.bin")
os.makedirs(BUILD, exist_ok=True)
with open(script, "wb") as f:
    for fr, data in sorted(events, key=lambda e: e[0]):
        f.write(struct.pack("<IB", fr, len(data)) + bytes(data))

exe = os.path.join(BUILD, "synth_bare")
if a.build or not os.path.exists(exe):
    t0 = time.perf_counter()
    cmd = ["verilator", "--cc", "--exe", "--build", "-j", "0", "-Mdir", BUILD, "-I" + os.path.join(T1, "rtl"),
           "--top-module", "synth_core", "-GNV=%d" % a.voices,
           os.path.join(T1, "rtl", "uart_rx.v"), os.path.join(T1, "rtl", "synth_voice.v"), os.path.join(T1, "rtl", "synth_core.v"),
           os.path.join(T1, "bench", "harness.cpp"), "-o", "synth_bare"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    open(os.path.join(BUILD, "harness-build.log"), "w").write(r.stdout + r.stderr)
    if r.returncode:
        print(r.stdout[-3000:], r.stderr[-3000:]); sys.exit("verilator build failed")
    print(f"verilator build: {time.perf_counter() - t0:.2f} s")

t0 = time.perf_counter()
r = subprocess.run([exe, str(N), script, os.path.join(BUILD, "samples.bin")], capture_output=True, text=True)
print(r.stdout.strip())
if r.returncode:
    print(r.stderr); sys.exit("harness failed")
stats = json.loads(r.stdout.strip().splitlines()[-1])
got = np.fromfile(os.path.join(BUILD, "samples.bin"), dtype="<i2")

t1 = time.perf_counter()
exp = S.SynthRef().render_script(events, N)
t_ref = time.perf_counter() - t1
bad = np.nonzero(got != exp)[0]
print(f"reference render: {t_ref:.2f} s; DUT samples {len(got)}, reference {len(exp)}")
if len(got) != len(exp) or len(bad):
    i = int(bad[0]) if len(bad) else -1
    sys.exit(f"MISMATCH: {len(bad)} samples differ; first at frame {i}: DUT {got[i]} ref {exp[i]}")
with wave.open(a.out, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS)
    w.writeframes(got.astype("<i2").tobytes())
print(f"OK: {len(exp)} samples bit-exact against synth_ref; wrote {a.out} ({a.seconds} s, peak {int(np.abs(got.astype(int)).max())})")
