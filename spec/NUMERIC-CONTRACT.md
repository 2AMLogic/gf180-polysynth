# Synth Core — Numeric Contract

**Revision 1 — 2026-09-16 — status: FROZEN pending operator ratification (see NOTES.md)**

This document is the complete, bit-exact specification of the hackathon synth
core. The reference model `reference/synth_ref.py` implements it; the Verilog
written during the event is checked against that model, sample for sample.

If two readers could interpret a sentence differently, that is a defect in this
document. File it; do not resolve it by picking one reading. Any change to a
normative statement bumps the revision number, and the reference model's
`CONTRACT_REV` moves with it.

Words: **MUST** is normative. *Informative* paragraphs explain or motivate and
carry no obligation. Numbers written `0x..` are hexadecimal.

---

## 1. What the core is

A 4-voice monophonic-output digital synthesizer. Each voice is a phase-accumulator
oscillator (square, sawtooth, triangle, sine) scaled by a linear ADSR envelope
and a note velocity. The four voice outputs are summed with saturation into one
signed 16-bit sample per frame at a nominal 48 000 frames per second. A host
controls it over a UART with a small byte protocol (note on, note off, per-voice
parameters, reset).

```
UART RX ──► byte parser ──► command queue ──► (applied at frame boundaries)
                                                │
             ┌──────────────────────────────────┴───────────┐
             │ voice 0: phase acc ─► waveform ─► × gain ─┐  │
             │ voice 1:      "          "          "     ├─► Σ ─► saturate ─► s16 sample
             │ voice 2:      "          "          "     │  │
             │ voice 3:      "          "          "     ┘  │
             └──────────────────────────────────────────────┘
```

The core's observable behaviour is exactly two things: the sequence of output
samples, and how that sequence depends on the sequence of bytes received and the
frames in which they were received. Everything below defines those two things.

---

## 2. Fixed numbers

| Quantity | Value |
|---|---|
| Voices | 4 (numbered 0..3) |
| Nominal frame rate | 48 000 frames/s |
| Output sample | signed 16-bit two's complement, range −32768..+32767 inclusive, **mono** (one sample per frame) |
| Phase accumulator | 24-bit unsigned per voice |
| Phase increment | 24-bit unsigned per voice |
| Envelope level | 20-bit unsigned per voice |
| Envelope rates (A, D, R) | 16-bit unsigned per voice |
| Sustain level | 16-bit unsigned per voice |
| Velocity | 7-bit unsigned per voice |
| Waveform select | 2-bit per voice |
| Tuning | A4 (MIDI note 69) = 440 Hz |
| Worst-case cycles-per-frame budget | 256 core clock cycles |
| Assumed core clock | 12.288 MHz (= 256 × 48 000) |
| UART | 115 200 baud, 8 data bits, no parity, 1 stop bit, no flow control, receive only |

---

## 3. Arithmetic conventions

1. All signed quantities are two's complement.
2. `x >> k` on a signed value is an **arithmetic** shift: the result is
   `floor(x / 2^k)`. For negative `x` this rounds toward −∞, e.g. `−1 >> 16 = −1`,
   `−32768·65535 >> 16 = −32768` (since `−32767.5` floors to `−32768`).
3. `x >> k` on an unsigned value is a logical shift; identical result.
4. Bit numbering is LSB = bit 0. `x[a:b]` means bits `a` down to `b` inclusive.
5. Intermediate products MUST be computed exactly (no intermediate truncation)
   and then shifted as stated. Every product in this document fits in 32 signed bits.
6. Addition of the phase accumulator is modulo 2^24. No other addition wraps;
   every other addition is either provably in range or explicitly saturated.
7. "round half up" means `floor(x + 0.5)`. It is used only in the derivation of
   the two frozen tables; no rounding other than the floors above occurs at run time.

---

## 4. Frames

### 4.1 Definition

A **frame** is the production of one output sample. Frames are numbered from 0,
where frame 0 is the first frame after reset is released. Frame n produces
sample n. Nominally a frame lasts 1/48 000 s.

The core clock is divided so that a **frame tick** occurs exactly once every
`CYCLES_PER_FRAME = 256` clock cycles. The clock cycle in which the n-th tick is
asserted is **cycle 0 of frame n**; cycle 255 of frame n is the cycle before the
(n+1)-th tick.

### 4.2 What happens in a frame

The output sample of frame n is a **pure function of the register state at the
start of frame n**. Conceptually, in this order:

1. **Apply commands.** Every command that became complete during frame n−1
   (section 10.4) is applied to the registers, in order of completion.
2. **Compute.** For each voice, the oscillator sample, envelope gain, effective
   gain and voice output are computed from the *current* register values
   (sections 5–7). The four voice outputs are summed and saturated (section 8).
   The result is sample n.
3. **Advance.** For each voice: the phase accumulator is advanced (5.2), then the
   envelope is updated (6.3). Advancing happens in every frame for every voice
   regardless of envelope state.

An implementation may schedule this work across the 256 cycles however it likes,
provided the resulting sample sequence is identical. In particular an
implementation MUST NOT let a command received during frame n affect sample n.

### 4.3 Cycle budget and clock

The **worst-case cycles per frame** of an implementation is the largest number
of clock cycles it can take, from the frame tick, to finish steps 1–3 for all
four voices. The relation between that number and the clock is

```
minimum core clock = (worst-case cycles per frame) × 48 000
```

| Worst-case cycles/frame | Minimum core clock | Note |
|---:|---:|---|
| 32 | 1.536 MHz | roughly a fully parallel design |
| 64 | 3.072 MHz | one shared multiplier, ~8 cycles per voice |
| 128 | 6.144 MHz | |
| 192 | 9.216 MHz | |
| **256** | **12.288 MHz** | **the budget and the assumed clock** |
| 512 | 24.576 MHz | |
| 1041 | 49.968 MHz | the 50 MHz oscillator used directly; 50 000 000/48 000 is not an integer, so 48 000 Hz is not exactly reachable this way |

The board's oscillator is 50 MHz. The assumed core clock is 12.288 MHz obtained
from it with the FPGA's PLL. *Informative:* on the ECP5 the ratio
CLKI_DIV = 2, CLKFB_DIV = 29, CLKOP_DIV = 59 gives a 725 MHz VCO and
12.288136 MHz (+11 ppm), which is tighter than the crystal's own tolerance; this
was computed by hand and should be confirmed with `ecppll` (NOTES.md). 12.288 MHz
is also 256 × fs, the conventional audio master clock, so the I2S bit clock
(64 × fs) and word clock are integer divisions of it.

An implementation MUST complete a frame within 256 cycles. An implementation
that needs fewer MAY be clocked slower per the table; the sample sequence does
not change because nothing in the core depends on the clock frequency.

---

## 5. Oscillator

### 5.1 Registers

Per voice: `phase` (24-bit unsigned), `inc` (24-bit unsigned), `wave` (2-bit).

### 5.2 Phase advance

Once per frame, in step 3 of 4.2:

```
phase ← (phase + inc) mod 2^24
```

The oscillator sample of a frame is computed from `phase` **before** this
advance. The first sample after a NOTE_ON therefore uses `phase = 0`.

### 5.3 Frequency to increment; MIDI note to increment

A phase increment `inc` produces a nominal frequency `f = inc × 48 000 / 2^24` Hz
(resolution 0.00286 Hz).

The frequency of MIDI note number n (0..127) is

```
f(n) = 440 × 2^((n − 69) / 12)   Hz
```

and its increment is

```
NOTE_INC[n] = floor( f(n) × 2^24 / 48 000 + 0.5 )        (round half up)
```

**The 128-entry table in Appendix A is normative.** It was generated by this
formula; the formula is stated so that the table can be re-derived and checked,
but an implementation is checked against the table, not the formula. (It has
been verified that no entry's exact value lies within 2.7 × 10⁻³ of a rounding
boundary, so any reasonable evaluation of the formula reproduces the table.)
Examples: `NOTE_INC[69] = 153791`, `NOTE_INC[0] = 2858`, `NOTE_INC[127] = 4384395`.
Every entry is below 2^23, i.e. below Nyquist.

The mapping MUST behave as a lookup table: NOTE_ON with note n sets
`inc ← NOTE_INC[n]`. Whether the implementation stores the table in ROM or
computes it is its own business as long as every one of the 128 values is
reproduced exactly.

`inc` can also be written directly with SET_PHASE_INC (section 10). Any 24-bit
value is legal, including 0 (a stalled oscillator) and values ≥ 2^23 (above
Nyquist; the output is whatever the formulas below produce).

### 5.4 Waveforms

Let `p` be the 24-bit phase before advance. `osc` is a signed 16-bit value.

| `wave` | Name | Formula |
|---:|---|---|
| 0 | square | `osc = +32767` if `p < 0x800000`, else `osc = −32768` |
| 1 | sawtooth | `osc = (p >> 8) − 32768` (rising ramp: −32768 at p = 0, +32767 at p ≥ 0xFFFF00) |
| 2 | triangle | let `q = p >> 7` (0..131071). `osc = q − 32768` if `q < 65536`, else `osc = 98303 − q` |
| 3 | sine | `osc = SINE_TABLE[p >> 14]` (top 10 bits of the phase index the 1024-entry table) |

*Informative, equivalent bit-level forms:* square is `p[23] ? 0x8000 : 0x7FFF`;
saw is `p[23:8] XOR 0x8000` read as signed; triangle is
`(p[23] ? ~p[22:7] : p[22:7]) XOR 0x8000` read as signed. The square wave's
+32767/−32768 asymmetry (a −0.5 LSB DC offset) is intentional: both values are
the exact positive and negative limits of the sample format.

**SINE_TABLE** (1024 entries, signed 16-bit) is derived from the 257-entry
quarter-wave table **SINE_Q** in Appendix B, which is normative, by these exact
rules, applied in this order:

```
SINE_Q[i]            = floor(32767 × sin(2π·i / 1024) + 0.5)     for i = 0..256   (Appendix B)
SINE_TABLE[i]        = SINE_Q[i]                                 for i = 0..256
SINE_TABLE[512 − i]  = SINE_Q[i]                                 for i = 0..255   (fills 257..512)
SINE_TABLE[512 + i]  = −SINE_TABLE[i]                            for i = 0..511   (fills 512..1023)
```

Consequences an implementation may rely on: `SINE_TABLE[0] = SINE_TABLE[512] = 0`,
`SINE_TABLE[256] = 32767`, `SINE_TABLE[768] = −32767`; the table is exactly
quarter-wave symmetric, so a 257-entry (or 256-entry plus special case) ROM with
index/sign logic is a valid implementation. No interpolation is performed.
There is no −32768 in the table.

---

## 6. Envelope

### 6.1 Shape and why

All four stages are **linear** in the 20-bit level. Rationale: a linear stage is
one adder, one comparator and one constant per stage, is bit-exact with no
rounding decisions, and gives every stage a duration that can be stated in
closed form (6.5). Exponential stages would need either a multiplier per stage
(with a rounding rule to freeze) or a curve table, and would make "how long is
this stage" implementation-dependent. Linear decay/release sounds slightly less
natural than exponential; this is accepted for the baseline.

### 6.2 Registers and parameters

Per voice:

| Register | Width | Meaning |
|---|---|---|
| `state` | 3-bit | IDLE = 0, ATTACK = 1, DECAY = 2, SUSTAIN = 3, RELEASE = 4 |
| `level` | 20-bit unsigned | envelope level, 0..0xFFFF0 |
| `attack` | 16-bit unsigned | level increment per frame in ATTACK |
| `decay` | 16-bit unsigned | level decrement per frame in DECAY |
| `sustain` | 16-bit unsigned | DECAY target is `sustain << 4` |
| `release` | 16-bit unsigned | level decrement per frame in RELEASE |

Constants: `LEVEL_MAX = 0xFFFF0` (= 65535 << 4). The **envelope gain** used by
the scaler is the 16-bit value `env = level >> 4` (i.e. `level[19:4]`); it is
65535 when `level = LEVEL_MAX` and equals `sustain` while sustaining.

### 6.3 Update rule (step 3 of 4.2, once per frame, after the phase advance)

Exactly one of the following branches executes, chosen by the state at the start
of the update. **At most one state transition happens per frame.** All
comparisons are on unsigned integers computed without overflow (widen as needed).

```
IDLE:     nothing.  (level is 0 in IDLE.)

ATTACK:   t ← level + attack
          if t ≥ LEVEL_MAX:   level ← LEVEL_MAX ; state ← DECAY
          else:               level ← t

DECAY:    target ← sustain << 4
          if level ≤ target + decay:   level ← target ; state ← SUSTAIN
          else:                        level ← level − decay

SUSTAIN:  nothing.  (level holds. A later change of `sustain` does NOT move it.)

RELEASE:  if level ≤ release:   level ← 0 ; state ← IDLE
          else:                 level ← level − release
```

Notes that follow from the rule and are intentional:

* A rate of 0 makes its stage hold forever (ATTACK at rate 0 holds level 0;
  DECAY at rate 0 holds unless `level` already equals `target`; RELEASE at rate 0
  holds unless `level` is already 0, in which case it goes IDLE). Rate 0 is
  **not** "instant". See NOTES.md.
* In DECAY, if `target` is above the current level (the host raised `sustain`
  mid-decay), the level jumps **up** to `target` in one frame.
* `sustain = 65535` makes DECAY last exactly one update: the level is already
  `LEVEL_MAX = target`, so the first DECAY update lands on `target` and enters
  SUSTAIN.

### 6.4 Note-on and note-off

**NOTE_ON** (any state, including RELEASE and while already sounding) is a hard
restart of the voice, all in the same command application:
`inc ← NOTE_INC[note]`, `phase ← 0`, `velocity ← vel`, `level ← 0`,
`state ← ATTACK`. Consequently the output of a voice from a NOTE_ON onward is
identical regardless of what the voice was doing before, given the same parameters.

**NOTE_OFF** in ATTACK, DECAY or SUSTAIN sets `state ← RELEASE` and leaves
`level` unchanged; the release ramp starts from wherever the level is. So a
note-off mid-attack releases from the partial attack level; the attack does not
complete. NOTE_OFF in IDLE or RELEASE has no effect.

### 6.5 Stage durations (informative, derived from 6.3)

With rates ≥ 1, counting envelope *updates* (one per frame):

* ATTACK from 0: `ceil(LEVEL_MAX / attack)` updates. `attack = 65535` → 16
  updates (0.33 ms); `attack = 1` → 1 048 560 updates (21.8 s).
* DECAY from `LEVEL_MAX` to `T = sustain << 4`: `max(1, ceil((LEVEL_MAX − T) / decay))` updates.
* RELEASE from level `L`: `max(1, ceil(L / release))` updates.

Timeline of a NOTE_ON applied at the start of frame n with attack rate A < LEVEL_MAX:
sample n uses level 0; sample n+k uses level `min(k·A, LEVEL_MAX)`; the state
observed at the start of frame n+k is ATTACK for k < ceil(LEVEL_MAX/A) and DECAY
at k = ceil(LEVEL_MAX/A).

---

## 7. Voice scaler

Per voice, in step 2 of 4.2, from the registers at the start of the frame:

```
osc  = waveform(wave, phase)              signed 16-bit           (5.4)
env  = level >> 4                         unsigned 16-bit         (6.2)
g    = (env × velocity) >> 7              unsigned 16-bit, 0..65023
out  = (osc × g) >> 16                    signed 16-bit, arithmetic shift (3.2)
```

`env × velocity` is at most 65535 × 127 = 8 322 945 (23 bits). `osc × g` is
in −32768 × 65023 .. 32767 × 65023 (32 signed bits). The shifts are floors.

Consequences: unity gain is not exactly reachable (65535/65536 from the envelope
times 127/128 from velocity ≈ −0.07 dB); at `velocity = 127` and `level = LEVEL_MAX`,
`g = 65023` and a voice's output lies in **−32512..+32510** for all waveforms and
phases (`(32767 × 65023) >> 16 = 32510`; `(−32768 × 65023) >> 16 = floor(−32511.5) = −32512`). The
first sample after NOTE_ON is always 0 (level 0). NOTE_ON with `velocity = 0` is
a silent note, not a note-off.

---

## 8. Mixer

```
sum    = out_0 + out_1 + out_2 + out_3        exact, fits in 18 signed bits (|sum| ≤ 131072)
sample = +32767  if sum > +32767
         −32768  if sum < −32768
         sum     otherwise
```

There is no scaling and no rounding in the mixer; the only rounding operations
in the entire signal path are the two floors in section 7. Saturation is the
only overflow behaviour anywhere in the core. Four voices at full velocity and
full envelope can drive the sum to +130 040 (4 × 32510) and −130 048 (4 × −32512)
and therefore reach both limits; the host manages headroom through velocity and
envelope levels.

---

## 9. Reset and initialisation

On hardware reset (and on the RESET command, section 10.5, for the voice
registers only) every register takes the value below. There are no other
registers with observable state.

| Register | Reset value | Per voice? |
|---|---|---|
| `phase` | 0 | yes |
| `inc` | 0 | yes |
| `wave` | 0 (square) | yes |
| `state` | 0 (IDLE) | yes |
| `level` | 0 | yes |
| `attack` | 2048 (attack lasts 512 frames = 10.7 ms) | yes |
| `decay` | 256 | yes |
| `sustain` | 0xC000 (49152, 75 % of full scale) | yes |
| `release` | 128 | yes |
| `velocity` | 0 | yes |
| output sample register | 0 | no |
| frame counter (if any) | 0 | no |
| byte parser | idle: expecting a status byte, no partial command | no |
| pending command queue | empty | no |

Sample 0 after reset, and every sample until a NOTE_ON has been applied, is 0.

The reset values of the ADSR parameters are deliberately non-zero so that a
host that sends only NOTE_ON hears a note (a 0 attack rate would hold the voice
silent, per 6.3).

---

## 10. UART and command protocol

### 10.1 Physical layer

115 200 baud, 8 data bits, LSB first, no parity, one stop bit, idle high, no
flow control. The core only receives; it never transmits. *Informative:* from
12.288 MHz the nearest integer divisor is 107 (114 841 baud, −0.31 %), well
inside UART tolerance; alternatives are discussed in NOTES.md.

The UART receiver itself is not part of the numeric contract. Its sole
obligation is to deliver each received byte, intact and in order, to the core's
byte input (10.4). Bytes with framing errors MUST be dropped.

### 10.2 Byte framing

Every byte is either a **status byte** (bit 7 = 1) or a **data byte** (bit 7 = 0).

```
status byte:  1 o o o o o v v     o = opcode (5 bits, bits 6:2)   v = voice (2 bits, bits 1:0)
data byte:    0 d d d d d d d     d = 7 bits of payload
```

A command is one status byte followed by a fixed number of data bytes determined
by the opcode (10.3). Multi-byte values are sent **most-significant chunk
first** in 7-bit chunks:

* a 16-bit value `x` is 3 data bytes: `x[15:14]` (in the low 2 bits of the byte; the byte's bits 6:2 are ignored), `x[13:7]`, `x[6:0]`;
* a 24-bit value `x` is 4 data bytes: `x[23:21]` (low 3 bits; bits 6:3 ignored), `x[20:14]`, `x[13:7]`, `x[6:0]`.

### 10.3 Commands

| Opcode | Name | Data bytes | Payload |
|---:|---|---:|---|
| 0 | NOTE_OFF | 0 | — |
| 1 | NOTE_ON | 2 | note (7-bit, 0..127), velocity (7-bit, 0..127) |
| 2 | SET_WAVE | 1 | wave; only bits 1:0 are used |
| 3 | SET_ATTACK | 3 | 16-bit attack rate |
| 4 | SET_DECAY | 3 | 16-bit decay rate |
| 5 | SET_SUSTAIN | 3 | 16-bit sustain level |
| 6 | SET_RELEASE | 3 | 16-bit release rate |
| 7 | SET_PHASE_INC | 4 | 24-bit phase increment |
| 8 | RESET | 0 | — (voice bits ignored) |
| 9..31 | *unknown* | see 10.4 | — |

Status byte value = `0x80 | (opcode << 2) | voice`. Examples: NOTE_OFF voice 2 =
`0x82`; NOTE_ON voice 0 = `0x84 nn vv`; SET_SUSTAIN voice 3 = `0x97 b2 b1 b0`;
RESET = `0xA0`.

### 10.4 Parser rules and command timing

The parser is a state machine fed one byte at a time. Its rules, which together
make the stream self-synchronising:

1. A **status byte** always starts a new command. If a command was in progress
   (status received, not all data bytes yet), that partial command is discarded.
2. A status byte whose opcode has 0 data bytes (NOTE_OFF, RESET) is a **complete
   command** at the moment it is received.
3. A status byte with an **unknown opcode** (9..31) is accepted and puts the
   parser into a discard state: every following data byte is dropped until the
   next status byte. No command is generated.
4. A **data byte** received while a known command is in progress is appended to
   it. When the last data byte of the command arrives, the command is **complete**.
5. A data byte received when no command is in progress (parser idle, or in the
   discard state) is dropped.
6. Ignored bits (10.2, 10.3) are masked; no value is ever rejected for being out
   of range. Note and velocity bytes are 7-bit and therefore always in range.

**Timing.** A byte is *received during frame n* if the core accepts it in a clock
cycle c with `tick_n ≤ c < tick_{n+1}` (a byte accepted in the tick cycle
itself belongs to the frame that starts in that cycle). A command is *complete
during frame n* if its last byte was received during frame n. Every command
complete during frame n MUST be applied at the start of frame n+1, in order of
completion, before sample n+1 is computed (4.2 step 1), and MUST NOT affect
sample n. Each command is applied exactly once. A command MUST be applied
atomically: all of its register writes happen together; no sample is ever
computed from a partially applied command.

*Informative:* at 115 200 baud a byte takes 10 bit-times ≈ 87 µs ≈ 4.2 frames,
so through the UART at most one command completes per frame. The queue depth
needed to satisfy the ordering rule is therefore 1 in hardware. A test bench
that drives the byte input directly can complete several commands in one frame;
the rule above says they all apply, in order, at the next frame boundary.

### 10.5 Command semantics

Each command writes registers of the addressed voice v (or, for RESET, of all
voices) at the start of the next frame. No command has any other effect.

| Command | Effect |
|---|---|
| NOTE_OFF v | if `state[v]` ∈ {ATTACK, DECAY, SUSTAIN}: `state[v] ← RELEASE`. Otherwise nothing. |
| NOTE_ON v, note, vel | `inc[v] ← NOTE_INC[note]`; `phase[v] ← 0`; `velocity[v] ← vel`; `level[v] ← 0`; `state[v] ← ATTACK`. |
| SET_WAVE v, w | `wave[v] ← w & 3`. Takes effect from the next sample, even mid-note. |
| SET_ATTACK v, r | `attack[v] ← r`. |
| SET_DECAY v, r | `decay[v] ← r`. |
| SET_SUSTAIN v, s | `sustain[v] ← s`. Does not move `level` if already in SUSTAIN (6.3). |
| SET_RELEASE v, r | `release[v] ← r`. |
| SET_PHASE_INC v, i | `inc[v] ← i`. Nothing else: `phase`, `state`, `level` untouched. A subsequent NOTE_ON overwrites `inc`. |
| RESET | every per-voice register of every voice ← its reset value (section 9). The parser and the queue are not touched (the parser is idle by construction; commands queued behind the RESET in the same frame still apply, in order, after it). |

Parameter writes take effect immediately in the sense of 4.2: the envelope
update at the end of the frame in which the command was applied already uses
the new value.

---

## 11. Output and audio integration

**Mono.** The core produces one 16-bit sample per frame. Justification: the
contract is about the arithmetic core, and stereo adds nothing to it except a
per-voice pan parameter, a second multiplier per voice and a second mixer — all
of which would need their own rounding rules. A stereo version is an additive
extension (per-voice pan) that does not disturb anything specified here. The
DAC on the board (PCM5102A, I2S) is stereo; the I2S transmitter sends the same
sample on the left and right channels.

*Informative, outside the contract:* I2S, 16-bit sample left-justified in a
32-bit slot, MSB first, BCLK = 64 × fs = 3.072 MHz, LRCLK = 48 kHz, both integer
divisions of the 12.288 MHz core clock; PCM5102A with SCK tied low (internal
PLL from BCLK). Latency added by the I2S transmitter is fixed and does not
change the sample sequence.

---

## 12. Verification obligations

For an implementation to be checkable against `reference/synth_ref.py` it MUST
expose, in simulation:

1. **The sample stream.** A 16-bit signed output with a one-cycle "sample valid"
   strobe, asserted exactly once per frame. The k-th strobe after reset carries
   sample k. (The strobe may occur at any cycle of frame k or at the tick that
   starts frame k+1; only ordering matters.)
2. **The byte input.** A byte port with a one-cycle valid strobe, synchronous
   to the core clock, bypassing the UART receiver, so that the test bench
   controls exactly which frame each byte is received in (10.4). The UART
   receiver is verified separately by checking that it delivers bytes intact.
3. **The frame tick**, so the test bench can count frames and place bytes.

Recommended (not normative) signal names: `clk`, `rst_n`, `frame_tick`,
`cmd_valid`, `cmd_byte[7:0]`, `sample_valid`, `sample[15:0]`.

A test compares the implementation's sample k with the reference's sample k for
every k, for a scripted sequence of (frame, bytes) deliveries; the reference's
`SynthRef.render_script()` consumes exactly such a script. Any mismatch in any
sample is a failure; there is no tolerance.

---

## 13. Revision history

* **Rev 1 (2026-09-16)** — initial frozen draft. Judgement calls listed in NOTES.md.

---

### Appendix A -- NOTE_INC: MIDI note number -> 24-bit phase increment

Normative.  `NOTE_INC[n] = floor(440 * 2^((n-69)/12) * 2^24 / 48000 + 0.5)`.  Nominal frequency shown for reference only.

| note | inc (dec) | inc (hex) | nominal Hz | | note | inc (dec) | inc (hex) | nominal Hz |
|---:|---:|---:|---:|---|---:|---:|---:|---:|
| 0 | 2858 | 0x000B2A | 8.176 | | 64 | 115213 | 0x01C20D | 329.628 |
| 1 | 3028 | 0x000BD4 | 8.662 | | 65 | 122064 | 0x01DCD0 | 349.228 |
| 2 | 3208 | 0x000C88 | 9.177 | | 66 | 129322 | 0x01F92A | 369.994 |
| 3 | 3398 | 0x000D46 | 9.723 | | 67 | 137012 | 0x021734 | 391.995 |
| 4 | 3600 | 0x000E10 | 10.301 | | 68 | 145160 | 0x023708 | 415.305 |
| 5 | 3815 | 0x000EE7 | 10.913 | | 69 | 153791 | 0x0258BF | 440.000 |
| 6 | 4041 | 0x000FC9 | 11.562 | | 70 | 162936 | 0x027C78 | 466.164 |
| 7 | 4282 | 0x0010BA | 12.250 | | 71 | 172625 | 0x02A251 | 493.883 |
| 8 | 4536 | 0x0011B8 | 12.978 | | 72 | 182890 | 0x02CA6A | 523.251 |
| 9 | 4806 | 0x0012C6 | 13.750 | | 73 | 193765 | 0x02F4E5 | 554.365 |
| 10 | 5092 | 0x0013E4 | 14.568 | | 74 | 205287 | 0x0321E7 | 587.330 |
| 11 | 5395 | 0x001513 | 15.434 | | 75 | 217494 | 0x035196 | 622.254 |
| 12 | 5715 | 0x001653 | 16.352 | | 76 | 230426 | 0x03841A | 659.255 |
| 13 | 6055 | 0x0017A7 | 17.324 | | 77 | 244128 | 0x03B9A0 | 698.456 |
| 14 | 6415 | 0x00190F | 18.354 | | 78 | 258645 | 0x03F255 | 739.989 |
| 15 | 6797 | 0x001A8D | 19.445 | | 79 | 274025 | 0x042E69 | 783.991 |
| 16 | 7201 | 0x001C21 | 20.602 | | 80 | 290319 | 0x046E0F | 830.609 |
| 17 | 7629 | 0x001DCD | 21.827 | | 81 | 307582 | 0x04B17E | 880.000 |
| 18 | 8083 | 0x001F93 | 23.125 | | 82 | 325872 | 0x04F8F0 | 932.328 |
| 19 | 8563 | 0x002173 | 24.500 | | 83 | 345249 | 0x0544A1 | 987.767 |
| 20 | 9072 | 0x002370 | 25.957 | | 84 | 365779 | 0x0594D3 | 1046.502 |
| 21 | 9612 | 0x00258C | 27.500 | | 85 | 387529 | 0x05E9C9 | 1108.731 |
| 22 | 10184 | 0x0027C8 | 29.135 | | 86 | 410573 | 0x0643CD | 1174.659 |
| 23 | 10789 | 0x002A25 | 30.868 | | 87 | 434987 | 0x06A32B | 1244.508 |
| 24 | 11431 | 0x002CA7 | 32.703 | | 88 | 460853 | 0x070835 | 1318.510 |
| 25 | 12110 | 0x002F4E | 34.648 | | 89 | 488256 | 0x077340 | 1396.913 |
| 26 | 12830 | 0x00321E | 36.708 | | 90 | 517290 | 0x07E4AA | 1479.978 |
| 27 | 13593 | 0x003519 | 38.891 | | 91 | 548049 | 0x085CD1 | 1567.982 |
| 28 | 14402 | 0x003842 | 41.203 | | 92 | 580638 | 0x08DC1E | 1661.219 |
| 29 | 15258 | 0x003B9A | 43.654 | | 93 | 615165 | 0x0962FD | 1760.000 |
| 30 | 16165 | 0x003F25 | 46.249 | | 94 | 651744 | 0x09F1E0 | 1864.655 |
| 31 | 17127 | 0x0042E7 | 48.999 | | 95 | 690499 | 0x0A8943 | 1975.533 |
| 32 | 18145 | 0x0046E1 | 51.913 | | 96 | 731558 | 0x0B29A6 | 2093.005 |
| 33 | 19224 | 0x004B18 | 55.000 | | 97 | 775059 | 0x0BD393 | 2217.461 |
| 34 | 20367 | 0x004F8F | 58.270 | | 98 | 821146 | 0x0C879A | 2349.318 |
| 35 | 21578 | 0x00544A | 61.735 | | 99 | 869974 | 0x0D4656 | 2489.016 |
| 36 | 22861 | 0x00594D | 65.406 | | 100 | 921705 | 0x0E1069 | 2637.020 |
| 37 | 24221 | 0x005E9D | 69.296 | | 101 | 976513 | 0x0EE681 | 2793.826 |
| 38 | 25661 | 0x00643D | 73.416 | | 102 | 1034579 | 0x0FC953 | 2959.955 |
| 39 | 27187 | 0x006A33 | 77.782 | | 103 | 1096099 | 0x10B9A3 | 3135.963 |
| 40 | 28803 | 0x007083 | 82.407 | | 104 | 1161276 | 0x11B83C | 3322.438 |
| 41 | 30516 | 0x007734 | 87.307 | | 105 | 1230329 | 0x12C5F9 | 3520.000 |
| 42 | 32331 | 0x007E4B | 92.499 | | 106 | 1303488 | 0x13E3C0 | 3729.310 |
| 43 | 34253 | 0x0085CD | 97.999 | | 107 | 1380998 | 0x151286 | 3951.066 |
| 44 | 36290 | 0x008DC2 | 103.826 | | 108 | 1463116 | 0x16534C | 4186.009 |
| 45 | 38448 | 0x009630 | 110.000 | | 109 | 1550118 | 0x17A726 | 4434.922 |
| 46 | 40734 | 0x009F1E | 116.541 | | 110 | 1642292 | 0x190F34 | 4698.636 |
| 47 | 43156 | 0x00A894 | 123.471 | | 111 | 1739948 | 0x1A8CAC | 4978.032 |
| 48 | 45722 | 0x00B29A | 130.813 | | 112 | 1843411 | 0x1C20D3 | 5274.041 |
| 49 | 48441 | 0x00BD39 | 138.591 | | 113 | 1953026 | 0x1DCD02 | 5587.652 |
| 50 | 51322 | 0x00C87A | 146.832 | | 114 | 2069159 | 0x1F92A7 | 5919.911 |
| 51 | 54373 | 0x00D465 | 155.563 | | 115 | 2192197 | 0x217345 | 6271.927 |
| 52 | 57607 | 0x00E107 | 164.814 | | 116 | 2322552 | 0x237078 | 6644.875 |
| 53 | 61032 | 0x00EE68 | 174.614 | | 117 | 2460658 | 0x258BF2 | 7040.000 |
| 54 | 64661 | 0x00FC95 | 184.997 | | 118 | 2606977 | 0x27C781 | 7458.620 |
| 55 | 68506 | 0x010B9A | 195.998 | | 119 | 2761996 | 0x2A250C | 7902.133 |
| 56 | 72580 | 0x011B84 | 207.652 | | 120 | 2926232 | 0x2CA698 | 8372.018 |
| 57 | 76896 | 0x012C60 | 220.000 | | 121 | 3100235 | 0x2F4E4B | 8869.844 |
| 58 | 81468 | 0x013E3C | 233.082 | | 122 | 3284585 | 0x321E69 | 9397.273 |
| 59 | 86312 | 0x015128 | 246.942 | | 123 | 3479896 | 0x351958 | 9956.063 |
| 60 | 91445 | 0x016535 | 261.626 | | 124 | 3686822 | 0x3841A6 | 10548.082 |
| 61 | 96882 | 0x017A72 | 277.183 | | 125 | 3906052 | 0x3B9A04 | 11175.303 |
| 62 | 102643 | 0x0190F3 | 293.665 | | 126 | 4138318 | 0x3F254E | 11839.822 |
| 63 | 108747 | 0x01A8CB | 311.127 | | 127 | 4384395 | 0x42E68B | 12543.854 |

SHA-256 of the decimal values joined by commas (no spaces): `e771e6b7b39d3941c471b772bfb5cdca398b78ee7fa964c3c90388d2cc888ba4`

### Appendix B -- SINE_Q: quarter-wave sine table, i = 0..256

Normative.  `SINE_Q[i] = floor(32767 * sin(2*pi*i/1024) + 0.5)`.  The full 1024-entry table is derived by the symmetry rules in section 5.4.  Eight entries per row; the first column is the index of the first entry in the row.

| i | +0 | +1 | +2 | +3 | +4 | +5 | +6 | +7 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0 | 201 | 402 | 603 | 804 | 1005 | 1206 | 1407 |
| 8 | 1608 | 1809 | 2009 | 2210 | 2410 | 2611 | 2811 | 3012 |
| 16 | 3212 | 3412 | 3612 | 3811 | 4011 | 4210 | 4410 | 4609 |
| 24 | 4808 | 5007 | 5205 | 5404 | 5602 | 5800 | 5998 | 6195 |
| 32 | 6393 | 6590 | 6786 | 6983 | 7179 | 7375 | 7571 | 7767 |
| 40 | 7962 | 8157 | 8351 | 8545 | 8739 | 8933 | 9126 | 9319 |
| 48 | 9512 | 9704 | 9896 | 10087 | 10278 | 10469 | 10659 | 10849 |
| 56 | 11039 | 11228 | 11417 | 11605 | 11793 | 11980 | 12167 | 12353 |
| 64 | 12539 | 12725 | 12910 | 13094 | 13279 | 13462 | 13645 | 13828 |
| 72 | 14010 | 14191 | 14372 | 14553 | 14732 | 14912 | 15090 | 15269 |
| 80 | 15446 | 15623 | 15800 | 15976 | 16151 | 16325 | 16499 | 16673 |
| 88 | 16846 | 17018 | 17189 | 17360 | 17530 | 17700 | 17869 | 18037 |
| 96 | 18204 | 18371 | 18537 | 18703 | 18868 | 19032 | 19195 | 19357 |
| 104 | 19519 | 19680 | 19841 | 20000 | 20159 | 20317 | 20475 | 20631 |
| 112 | 20787 | 20942 | 21096 | 21250 | 21403 | 21554 | 21705 | 21856 |
| 120 | 22005 | 22154 | 22301 | 22448 | 22594 | 22739 | 22884 | 23027 |
| 128 | 23170 | 23311 | 23452 | 23592 | 23731 | 23870 | 24007 | 24143 |
| 136 | 24279 | 24413 | 24547 | 24680 | 24811 | 24942 | 25072 | 25201 |
| 144 | 25329 | 25456 | 25582 | 25708 | 25832 | 25955 | 26077 | 26198 |
| 152 | 26319 | 26438 | 26556 | 26674 | 26790 | 26905 | 27019 | 27133 |
| 160 | 27245 | 27356 | 27466 | 27575 | 27683 | 27790 | 27896 | 28001 |
| 168 | 28105 | 28208 | 28310 | 28411 | 28510 | 28609 | 28706 | 28803 |
| 176 | 28898 | 28992 | 29085 | 29177 | 29268 | 29358 | 29447 | 29534 |
| 184 | 29621 | 29706 | 29791 | 29874 | 29956 | 30037 | 30117 | 30195 |
| 192 | 30273 | 30349 | 30424 | 30498 | 30571 | 30643 | 30714 | 30783 |
| 200 | 30852 | 30919 | 30985 | 31050 | 31113 | 31176 | 31237 | 31297 |
| 208 | 31356 | 31414 | 31470 | 31526 | 31580 | 31633 | 31685 | 31736 |
| 216 | 31785 | 31833 | 31880 | 31926 | 31971 | 32014 | 32057 | 32098 |
| 224 | 32137 | 32176 | 32213 | 32250 | 32285 | 32318 | 32351 | 32382 |
| 232 | 32412 | 32441 | 32469 | 32495 | 32521 | 32545 | 32567 | 32589 |
| 240 | 32609 | 32628 | 32646 | 32663 | 32678 | 32692 | 32705 | 32717 |
| 248 | 32728 | 32737 | 32745 | 32752 | 32757 | 32761 | 32765 | 32766 |
| 256 | 32767 | | | | | | | |

SHA-256 of the 257 decimal values joined by commas: `72e3ab187d9c5e27be2a1dfbf209610aca3bf553eea8d15b0db53e05b240ef4f`
SHA-256 of the derived 1024-entry full table, same encoding: `04b8970a1d1e38c6c1052b91753b6860d1f7672f952dcdf03de0abd1f43c459f`

