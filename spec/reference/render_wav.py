"""render_wav.py -- render a short recognisable phrase through the reference
model so the specification can be heard before any hardware exists.

Plays the first two lines of "Ode to Joy" (melody on a sawtooth voice, bass on
a square voice, two triangle/sine pad voices holding the chord) at 144 BPM and
writes a mono 16-bit 48 kHz WAV.  Everything goes through the same byte
protocol the hardware will receive; this script only builds the byte script.

    python3 render_wav.py [output.wav]
"""
import os
import sys
import time
import wave

import numpy as np

import synth_ref as S

QUARTER = 20000                     # frames per quarter note (144 BPM at 48 kHz)
GATE = 0.85                         # fraction of a note's duration before note-off

# --- score ---------------------------------------------------------------
# (MIDI note, duration in quarter notes)
LINE = [(64, 1), (64, 1), (65, 1), (67, 1), (67, 1), (65, 1), (64, 1), (62, 1),
        (60, 1), (60, 1), (62, 1), (64, 1)]
MELODY = (LINE + [(64, 1.5), (62, 0.5), (62, 2)]
          + LINE + [(62, 1.5), (60, 0.5), (60, 2)])
# one chord per bar (4 quarters): bass root, pad note A, pad note B
CHORDS = [(48, 52, 55), (43, 50, 55), (48, 52, 55), (43, 50, 55),
          (48, 52, 55), (43, 50, 55), (43, 50, 55), (48, 52, 55)]

V_MEL, V_BASS, V_PAD1, V_PAD2 = 0, 1, 2, 3


def build_events():
    ev = []
    setup = (S.cmd_set_wave(V_MEL, S.WAVE_SAW) + S.cmd_set_adsr(V_MEL, 4096, 300, 0x7000, 200)
             + S.cmd_set_wave(V_BASS, S.WAVE_SQUARE) + S.cmd_set_adsr(V_BASS, 8192, 64, 0x5000, 100)
             + S.cmd_set_wave(V_PAD1, S.WAVE_TRI) + S.cmd_set_adsr(V_PAD1, 48, 32, 0xB000, 40)
             + S.cmd_set_wave(V_PAD2, S.WAVE_SINE) + S.cmd_set_adsr(V_PAD2, 48, 32, 0xB000, 40))
    ev.append((0, setup))
    t = 0.0
    for note, beats in MELODY:
        on = int(t * QUARTER)
        off = int((t + beats * GATE) * QUARTER)
        ev.append((on, S.cmd_note_on(V_MEL, note, 80)))
        ev.append((off, S.cmd_note_off(V_MEL)))
        t += beats
    for bar, (root, a, b) in enumerate(CHORDS):
        on = bar * 4 * QUARTER
        off = int((bar * 4 + 4 * 0.9) * QUARTER)
        ev.append((on, S.cmd_note_on(V_BASS, root, 50) + S.cmd_note_on(V_PAD1, a, 24)
                   + S.cmd_note_on(V_PAD2, b, 24)))
        ev.append((off, S.cmd_note_off(V_BASS) + S.cmd_note_off(V_PAD1) + S.cmd_note_off(V_PAD2)))
    total = int(t * QUARTER) + QUARTER * 2          # two beats of tail for the releases
    ev.sort(key=lambda e: e[0])
    return ev, total


def main(path):
    events, total = build_events()
    m = S.SynthRef()
    t0 = time.time()
    samples = m.render_script(events, total)
    dt = time.time() - t0
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(S.SAMPLE_RATE)
        w.writeframes(samples.astype("<i2").tobytes())
    clipped = int(np.sum((samples == S.SAMPLE_MAX) | (samples == S.SAMPLE_MIN)))
    print(f"wrote {path}: {total} frames = {total / S.SAMPLE_RATE:.2f} s, mono s16 @ {S.SAMPLE_RATE} Hz")
    print(f"  {len(events)} command events, {sum(len(b) for _, b in events)} bytes")
    print(f"  peak +{int(samples.max())} / {int(samples.min())}, saturated samples: {clipped}")
    print(f"  render time {dt:.1f} s ({total / dt / 1000:.0f} kframes/s)")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "ode_to_joy.wav")
    main(out)
