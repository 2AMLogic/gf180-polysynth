"""synth_ref.py -- bit-exact reference model of the 2AM Logic hackathon synth core.

This module implements NUMERIC-CONTRACT.md (the frozen specification that lives
next to this file's parent directory).  It is the oracle the Verilog
implementation is checked against, so it is written to be *obviously* correct
rather than fast:

  * Every quantity in the signal path is a Python ``int``.  No floats are used
    anywhere between a received command byte and an output sample.  Python's
    ``>>`` on a negative int is an arithmetic (floor) shift, which is exactly
    the two's-complement behaviour the contract specifies.
  * The two lookup tables (MIDI note -> phase increment, quarter-wave sine)
    are FROZEN LITERALS.  They were generated once from the formulas in the
    contract; ``test_synth_ref.py`` re-derives them from the formulas and
    asserts equality.  Do not regenerate them in place.
  * Only the standard library and numpy are used; numpy only to hand back
    output sample arrays.

Public API (everything else is implementation detail):

    SynthRef()                      construct in the reset state
    SynthRef.reset()                hardware reset
    SynthRef.feed(data: bytes)      deliver UART bytes (received "during" the
                                    most recently rendered frame)
    SynthRef.step() -> int          render one frame, return the s16 sample
    SynthRef.render(n) -> ndarray   render n frames as np.int16
    SynthRef.render_script(events, n) -> ndarray
                                    render n frames, feeding bytes at given frames
    SynthRef.voices[v]              per-voice register state (Voice dataclass)
    SynthRef.frame                  number of frames rendered since reset
    cmd_*() helpers                 build command byte strings
    NOTE_INC, SINE_Q, SINE_TABLE    the frozen tables
    wave_sample(wave, phase)        the four oscillator formulas
    voice_output(voice)             the per-voice scaler
    saturate(x)                     the mixer clamp

Run ``python3 synth_ref.py --write-tables DIR`` to emit $readmemh-style hex
files of the tables, or ``--appendix`` to print the contract's appendix tables.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np

CONTRACT_REV = 1

# --------------------------------------------------------------------------
# Section 2 of the contract: fixed numbers
# --------------------------------------------------------------------------
SAMPLE_RATE = 48000                 # frames per second (nominal)
NUM_VOICES = 4
SAMPLE_MIN = -32768                 # s16 output range, inclusive
SAMPLE_MAX = 32767

PHASE_BITS = 24
PHASE_MASK = (1 << PHASE_BITS) - 1  # 0xFFFFFF
PHASE_HALF = 1 << (PHASE_BITS - 1)  # 0x800000, start of the second half-cycle

LEVEL_BITS = 20
LEVEL_MAX = 0xFFFF0                 # attack target = 65535 << 4
ENV_SHIFT = 4                       # envelope gain = level >> 4 (u16)

VELOCITY_BITS = 7                   # velocity 0..127, gain = (env*vel) >> 7
VELOCITY_MAX = 127

CYCLES_PER_FRAME = 256              # worst-case cycles-per-frame BUDGET
CORE_CLOCK_HZ = CYCLES_PER_FRAME * SAMPLE_RATE   # 12_288_000 (assumed clock)
UART_BAUD = 115200                  # 8N1, no flow control, RX only

TUNING_A4_HZ = 440
TUNING_A4_NOTE = 69

# Waveform selectors (SET_WAVE data byte & 3)
WAVE_SQUARE, WAVE_SAW, WAVE_TRI, WAVE_SINE = 0, 1, 2, 3
WAVE_NAMES = ("square", "saw", "tri", "sine")

# Envelope states
ENV_IDLE, ENV_ATTACK, ENV_DECAY, ENV_SUSTAIN, ENV_RELEASE = 0, 1, 2, 3, 4
ENV_NAMES = ("IDLE", "ATTACK", "DECAY", "SUSTAIN", "RELEASE")

# Command opcodes (bits [6:2] of a status byte)
OP_NOTE_OFF = 0
OP_NOTE_ON = 1
OP_SET_WAVE = 2
OP_SET_ATTACK = 3
OP_SET_DECAY = 4
OP_SET_SUSTAIN = 5
OP_SET_RELEASE = 6
OP_SET_PHASE_INC = 7
OP_RESET = 8
# Number of 7-bit data bytes that follow each status byte.  Opcodes not in
# this table are "unknown": the status byte is accepted and every data byte
# that follows it is discarded until the next status byte.
DATA_LEN = {
    OP_NOTE_OFF: 0,
    OP_NOTE_ON: 2,
    OP_SET_WAVE: 1,
    OP_SET_ATTACK: 3,
    OP_SET_DECAY: 3,
    OP_SET_SUSTAIN: 3,
    OP_SET_RELEASE: 3,
    OP_SET_PHASE_INC: 4,
    OP_RESET: 0,
}

# Reset values of the per-voice parameter registers (contract section 9)
DEFAULT_WAVE = WAVE_SQUARE
DEFAULT_ATTACK = 2048     # 0xFFFF0 / 2048 = 512 frames  = 10.7 ms
DEFAULT_DECAY = 256       # up to 0xFFFF0 / 256 = 4096 frames = 85 ms
DEFAULT_SUSTAIN = 0xC000  # 75 % of full scale
DEFAULT_RELEASE = 128     # up to 0xFFFF0 / 128 = 8192 frames = 171 ms

# --------------------------------------------------------------------------
# Frozen tables (contract appendices A and B).  DO NOT EDIT BY HAND.
# NOTE_INC[n] = floor(440 * 2**((n-69)/12) * 2**24 / 48000 + 0.5)
# SINE_Q[i]   = floor(32767 * sin(2*pi*i/1024) + 0.5),  i = 0..256
# --------------------------------------------------------------------------
NOTE_INC = (
        2858,     3028,     3208,     3398,     3600,     3815,     4041,     4282,  # 0
        4536,     4806,     5092,     5395,     5715,     6055,     6415,     6797,  # 8
        7201,     7629,     8083,     8563,     9072,     9612,    10184,    10789,  # 16
       11431,    12110,    12830,    13593,    14402,    15258,    16165,    17127,  # 24
       18145,    19224,    20367,    21578,    22861,    24221,    25661,    27187,  # 32
       28803,    30516,    32331,    34253,    36290,    38448,    40734,    43156,  # 40
       45722,    48441,    51322,    54373,    57607,    61032,    64661,    68506,  # 48
       72580,    76896,    81468,    86312,    91445,    96882,   102643,   108747,  # 56
      115213,   122064,   129322,   137012,   145160,   153791,   162936,   172625,  # 64
      182890,   193765,   205287,   217494,   230426,   244128,   258645,   274025,  # 72
      290319,   307582,   325872,   345249,   365779,   387529,   410573,   434987,  # 80
      460853,   488256,   517290,   548049,   580638,   615165,   651744,   690499,  # 88
      731558,   775059,   821146,   869974,   921705,   976513,  1034579,  1096099,  # 96
     1161276,  1230329,  1303488,  1380998,  1463116,  1550118,  1642292,  1739948,  # 104
     1843411,  1953026,  2069159,  2192197,  2322552,  2460658,  2606977,  2761996,  # 112
     2926232,  3100235,  3284585,  3479896,  3686822,  3906052,  4138318,  4384395,  # 120
)

SINE_Q = (
         0,    201,    402,    603,    804,   1005,   1206,   1407,  # 0
      1608,   1809,   2009,   2210,   2410,   2611,   2811,   3012,  # 8
      3212,   3412,   3612,   3811,   4011,   4210,   4410,   4609,  # 16
      4808,   5007,   5205,   5404,   5602,   5800,   5998,   6195,  # 24
      6393,   6590,   6786,   6983,   7179,   7375,   7571,   7767,  # 32
      7962,   8157,   8351,   8545,   8739,   8933,   9126,   9319,  # 40
      9512,   9704,   9896,  10087,  10278,  10469,  10659,  10849,  # 48
     11039,  11228,  11417,  11605,  11793,  11980,  12167,  12353,  # 56
     12539,  12725,  12910,  13094,  13279,  13462,  13645,  13828,  # 64
     14010,  14191,  14372,  14553,  14732,  14912,  15090,  15269,  # 72
     15446,  15623,  15800,  15976,  16151,  16325,  16499,  16673,  # 80
     16846,  17018,  17189,  17360,  17530,  17700,  17869,  18037,  # 88
     18204,  18371,  18537,  18703,  18868,  19032,  19195,  19357,  # 96
     19519,  19680,  19841,  20000,  20159,  20317,  20475,  20631,  # 104
     20787,  20942,  21096,  21250,  21403,  21554,  21705,  21856,  # 112
     22005,  22154,  22301,  22448,  22594,  22739,  22884,  23027,  # 120
     23170,  23311,  23452,  23592,  23731,  23870,  24007,  24143,  # 128
     24279,  24413,  24547,  24680,  24811,  24942,  25072,  25201,  # 136
     25329,  25456,  25582,  25708,  25832,  25955,  26077,  26198,  # 144
     26319,  26438,  26556,  26674,  26790,  26905,  27019,  27133,  # 152
     27245,  27356,  27466,  27575,  27683,  27790,  27896,  28001,  # 160
     28105,  28208,  28310,  28411,  28510,  28609,  28706,  28803,  # 168
     28898,  28992,  29085,  29177,  29268,  29358,  29447,  29534,  # 176
     29621,  29706,  29791,  29874,  29956,  30037,  30117,  30195,  # 184
     30273,  30349,  30424,  30498,  30571,  30643,  30714,  30783,  # 192
     30852,  30919,  30985,  31050,  31113,  31176,  31237,  31297,  # 200
     31356,  31414,  31470,  31526,  31580,  31633,  31685,  31736,  # 208
     31785,  31833,  31880,  31926,  31971,  32014,  32057,  32098,  # 216
     32137,  32176,  32213,  32250,  32285,  32318,  32351,  32382,  # 224
     32412,  32441,  32469,  32495,  32521,  32545,  32567,  32589,  # 232
     32609,  32628,  32646,  32663,  32678,  32692,  32705,  32717,  # 240
     32728,  32737,  32745,  32752,  32757,  32761,  32765,  32766,  # 248
     32767,  # 256
)


def _build_sine_table(quarter: Sequence[int]) -> Tuple[int, ...]:
    """Expand the 257-entry quarter table to the full 1024-entry table using
    the exact symmetry rules of contract section 5.4:
        T[i]       = Q[i]          for i in 0..256
        T[512 - i] = Q[i]          for i in 0..255   (i.e. T[257..512])
        T[512 + i] = -T[i]         for i in 0..511   (i.e. T[512..1023])
    """
    assert len(quarter) == 257
    t = [0] * 1024
    for i in range(257):
        t[i] = quarter[i]
    for i in range(256):
        t[512 - i] = quarter[i]
    for i in range(512):
        t[512 + i] = -t[i]
    return tuple(t)


SINE_TABLE: Tuple[int, ...] = _build_sine_table(SINE_Q)

assert len(NOTE_INC) == 128 and len(SINE_Q) == 257 and len(SINE_TABLE) == 1024


def note_frequency_hz(note: int) -> float:
    """Informative only (NOT in the signal path): f = 440 * 2**((n-69)/12)."""
    return TUNING_A4_HZ * 2.0 ** ((note - TUNING_A4_NOTE) / 12.0)


# --------------------------------------------------------------------------
# Oscillator (contract section 5)
# --------------------------------------------------------------------------
def wave_sample(wave: int, phase: int) -> int:
    """Oscillator output (s16) for a 24-bit phase value, BEFORE the phase is
    advanced.  ``wave`` is 0..3, ``phase`` is 0..0xFFFFFF."""
    assert 0 <= phase <= PHASE_MASK
    if wave == WAVE_SQUARE:
        # +32767 for the first half-cycle, -32768 for the second
        return SAMPLE_MAX if phase < PHASE_HALF else SAMPLE_MIN
    if wave == WAVE_SAW:
        # rising ramp: -32768 at phase 0, +32767 at phase 0xFFFF00..0xFFFFFF
        return (phase >> 8) - 32768
    if wave == WAVE_TRI:
        # rising for the first half-cycle, falling for the second
        q = phase >> 7                      # 0..131071
        return (q - 32768) if q < 65536 else (98303 - q)
    if wave == WAVE_SINE:
        return SINE_TABLE[phase >> 14]      # top 10 bits index the table
    raise ValueError("wave must be 0..3")


# --------------------------------------------------------------------------
# Per-voice state (contract section 9 lists the reset values)
# --------------------------------------------------------------------------
@dataclass
class Voice:
    phase: int = 0          # u24
    inc: int = 0            # u24 phase increment per frame
    wave: int = DEFAULT_WAVE
    state: int = ENV_IDLE
    level: int = 0          # u20 envelope level
    attack: int = DEFAULT_ATTACK      # u16 increment per frame
    decay: int = DEFAULT_DECAY        # u16 decrement per frame
    sustain: int = DEFAULT_SUSTAIN    # u16, target level = sustain << 4
    release: int = DEFAULT_RELEASE    # u16 decrement per frame
    velocity: int = 0       # u7

    def env_gain(self) -> int:
        """u16 envelope gain = level[19:4]."""
        return self.level >> ENV_SHIFT

    def effective_gain(self) -> int:
        """u16 g = (env_gain * velocity) >> 7."""
        return (self.env_gain() * self.velocity) >> VELOCITY_BITS


def voice_output(v: Voice) -> int:
    """Per-voice scaler (contract section 7): out = (osc * g) >> 16, where the
    shift is arithmetic (floor).  Since g <= 65023 the result lies in
    [-32512, 32510]."""
    osc = wave_sample(v.wave, v.phase)
    return (osc * v.effective_gain()) >> 16


def env_advance(v: Voice) -> None:
    """Envelope update rule (contract section 6.3), applied once per frame
    AFTER the frame's output has been computed.  At most one state transition
    per frame."""
    if v.state == ENV_ATTACK:
        t = v.level + v.attack
        if t >= LEVEL_MAX:
            v.level = LEVEL_MAX
            v.state = ENV_DECAY
        else:
            v.level = t
    elif v.state == ENV_DECAY:
        target = v.sustain << ENV_SHIFT
        if v.level <= target + v.decay:
            v.level = target
            v.state = ENV_SUSTAIN
        else:
            v.level -= v.decay
    elif v.state == ENV_SUSTAIN:
        pass                                # level holds; parameter changes do not move it
    elif v.state == ENV_RELEASE:
        if v.level <= v.release:
            v.level = 0
            v.state = ENV_IDLE
        else:
            v.level -= v.release
    # ENV_IDLE: level is 0 and stays 0


def saturate(x: int) -> int:
    """Mixer clamp (contract section 8)."""
    if x > SAMPLE_MAX:
        return SAMPLE_MAX
    if x < SAMPLE_MIN:
        return SAMPLE_MIN
    return x


# --------------------------------------------------------------------------
# Command builders (contract section 10).  These VALIDATE their arguments and
# raise ValueError on anything out of range; the parser, by contrast, masks.
# --------------------------------------------------------------------------
def _status(op: int, voice: int) -> int:
    if not 0 <= op <= 31:
        raise ValueError("opcode must be 0..31")
    if not 0 <= voice < NUM_VOICES:
        raise ValueError("voice must be 0..3")
    return 0x80 | (op << 2) | voice


def _u7(x: int, what: str) -> int:
    if not 0 <= x <= 127:
        raise ValueError(f"{what} must be 0..127")
    return x


def _u16_bytes(x: int, what: str) -> bytes:
    """16-bit value as three 7-bit data bytes, MSB first: [15:14], [13:7], [6:0]."""
    if not 0 <= x <= 0xFFFF:
        raise ValueError(f"{what} must be 0..65535")
    return bytes(((x >> 14) & 0x03, (x >> 7) & 0x7F, x & 0x7F))


def _u24_bytes(x: int, what: str) -> bytes:
    """24-bit value as four 7-bit data bytes, MSB first: [23:21], [20:14], [13:7], [6:0]."""
    if not 0 <= x <= 0xFFFFFF:
        raise ValueError(f"{what} must be 0..16777215")
    return bytes(((x >> 21) & 0x07, (x >> 14) & 0x7F, (x >> 7) & 0x7F, x & 0x7F))


def cmd_note_off(voice: int) -> bytes:
    return bytes((_status(OP_NOTE_OFF, voice),))


def cmd_note_on(voice: int, note: int, velocity: int) -> bytes:
    return bytes((_status(OP_NOTE_ON, voice), _u7(note, "note"), _u7(velocity, "velocity")))


def cmd_set_wave(voice: int, wave: int) -> bytes:
    if not 0 <= wave <= 3:
        raise ValueError("wave must be 0..3")
    return bytes((_status(OP_SET_WAVE, voice), wave))


def cmd_set_attack(voice: int, rate: int) -> bytes:
    return bytes((_status(OP_SET_ATTACK, voice),)) + _u16_bytes(rate, "attack rate")


def cmd_set_decay(voice: int, rate: int) -> bytes:
    return bytes((_status(OP_SET_DECAY, voice),)) + _u16_bytes(rate, "decay rate")


def cmd_set_sustain(voice: int, level: int) -> bytes:
    return bytes((_status(OP_SET_SUSTAIN, voice),)) + _u16_bytes(level, "sustain level")


def cmd_set_release(voice: int, rate: int) -> bytes:
    return bytes((_status(OP_SET_RELEASE, voice),)) + _u16_bytes(rate, "release rate")


def cmd_set_phase_inc(voice: int, inc: int) -> bytes:
    return bytes((_status(OP_SET_PHASE_INC, voice),)) + _u24_bytes(inc, "phase increment")


def cmd_reset() -> bytes:
    return bytes((_status(OP_RESET, 0),))


def cmd_set_adsr(voice: int, attack: int, decay: int, sustain: int, release: int) -> bytes:
    """Convenience: four SET_* commands back to back."""
    return (cmd_set_attack(voice, attack) + cmd_set_decay(voice, decay)
            + cmd_set_sustain(voice, sustain) + cmd_set_release(voice, release))


# --------------------------------------------------------------------------
# The core
# --------------------------------------------------------------------------
_DISCARD = -1   # parser sentinel: inside an unknown command, eat data bytes


class SynthRef:
    """Bit-exact model of the synth core.  See the module docstring."""

    def __init__(self) -> None:
        self.voices: List[Voice] = []
        self.frame: int = 0
        self._pending: List[Tuple[int, int, Tuple[int, ...]]] = []
        self._cur_op: Optional[int] = None
        self._cur_voice: int = 0
        self._cur_data: List[int] = []
        self._cur_need: int = 0
        self.reset()

    # ---- reset -----------------------------------------------------------
    def reset(self) -> None:
        """Hardware reset: every register to its reset value (contract 9).
        Also clears the command parser and the pending-command queue."""
        self.voices = [Voice() for _ in range(NUM_VOICES)]
        self.frame = 0
        self._pending = []
        self._parser_idle()

    def _soft_reset(self) -> None:
        """RESET command: voice registers to reset values.  The parser is
        necessarily idle (it just completed this command) and commands already
        queued behind it in the same frame still apply, in order."""
        self.voices = [Voice() for _ in range(NUM_VOICES)]

    def _parser_idle(self) -> None:
        self._cur_op = None
        self._cur_data = []
        self._cur_need = 0

    # ---- byte-level input (contract 10.2) -----------------------------------
    def feed(self, data: Iterable[int]) -> None:
        """Deliver UART bytes.  Bytes are parsed immediately; each command that
        becomes complete is queued and takes effect at the start of the next
        frame rendered (i.e. it was "received during" the most recently
        rendered frame, or before frame 0 if nothing has been rendered)."""
        for b in data:
            b &= 0xFF
            if b & 0x80:
                # status byte: abandons any command in progress (resync)
                op = (b >> 2) & 0x1F
                voice = b & 0x03
                need = DATA_LEN.get(op)
                if need is None:
                    self._cur_op = _DISCARD
                    self._cur_data = []
                    self._cur_need = 0
                elif need == 0:
                    self._pending.append((op, voice, ()))
                    self._parser_idle()
                else:
                    self._cur_op = op
                    self._cur_voice = voice
                    self._cur_data = []
                    self._cur_need = need
            else:
                # data byte
                if self._cur_op is None or self._cur_op == _DISCARD:
                    continue                         # stray data: ignored
                self._cur_data.append(b)
                if len(self._cur_data) == self._cur_need:
                    self._pending.append((self._cur_op, self._cur_voice, tuple(self._cur_data)))
                    self._parser_idle()

    @property
    def pending_commands(self) -> int:
        return len(self._pending)

    # ---- command semantics (contract 10.3) ------------------------------------
    def _apply(self, op: int, vi: int, d: Tuple[int, ...]) -> None:
        v = self.voices[vi]
        if op == OP_NOTE_OFF:
            if v.state in (ENV_ATTACK, ENV_DECAY, ENV_SUSTAIN):
                v.state = ENV_RELEASE
        elif op == OP_NOTE_ON:
            v.inc = NOTE_INC[d[0]]          # d[0] is 0..127 by construction
            v.phase = 0
            v.velocity = d[1]
            v.level = 0
            v.state = ENV_ATTACK
        elif op == OP_SET_WAVE:
            v.wave = d[0] & 0x03
        elif op in (OP_SET_ATTACK, OP_SET_DECAY, OP_SET_SUSTAIN, OP_SET_RELEASE):
            val = ((d[0] & 0x03) << 14) | (d[1] << 7) | d[2]
            if op == OP_SET_ATTACK:
                v.attack = val
            elif op == OP_SET_DECAY:
                v.decay = val
            elif op == OP_SET_SUSTAIN:
                v.sustain = val
            else:
                v.release = val
        elif op == OP_SET_PHASE_INC:
            v.inc = ((d[0] & 0x07) << 21) | (d[1] << 14) | (d[2] << 7) | d[3]
        elif op == OP_RESET:
            self._soft_reset()
        else:                                            # pragma: no cover
            raise AssertionError("unknown opcode reached _apply")

    def _apply_pending(self) -> None:
        pend, self._pending = self._pending, []
        for op, vi, d in pend:
            self._apply(op, vi, d)

    # ---- frame (contract section 4) ------------------------------------------
    def voice_outputs(self) -> List[int]:
        """Per-voice s16 outputs for the CURRENT register state (no side effects)."""
        return [voice_output(v) for v in self.voices]

    def step(self) -> int:
        """Render exactly one frame and return its s16 sample.
        Order: (1) apply queued commands, (2) compute output from the
        register state, (3) advance every voice's phase and envelope."""
        self._apply_pending()
        outs = self.voice_outputs()
        sample = saturate(sum(outs))
        for v in self.voices:
            v.phase = (v.phase + v.inc) & PHASE_MASK
            env_advance(v)
        self.frame += 1
        return sample

    def render(self, n: int) -> np.ndarray:
        """Render n frames; returns np.int16 array of length n."""
        out = np.empty(n, dtype=np.int16)
        step = self.step
        for i in range(n):
            out[i] = step()
        return out

    def render_script(self, events: Sequence[Tuple[int, bytes]], n: int) -> np.ndarray:
        """Render n frames, feeding ``data`` immediately before frame ``f`` is
        computed for every (f, data) in ``events`` (f counted from the current
        ``self.frame``; events must be sorted by f; f >= n is never fed).
        "Fed immediately before frame f" == "received during frame f-1", so the
        command takes effect in frame f's sample."""
        out = np.empty(n, dtype=np.int16)
        base = self.frame
        ev = sorted(events, key=lambda e: e[0])
        k = 0
        step = self.step
        for i in range(n):
            while k < len(ev) and ev[k][0] <= i:
                self.feed(ev[k][1])
                k += 1
            out[i] = step()
        assert self.frame == base + n
        return out

    # ---- debugging aids ------------------------------------------------------
    def describe(self) -> str:
        rows = []
        for i, v in enumerate(self.voices):
            rows.append(f"v{i}: {ENV_NAMES[v.state]:7s} lvl={v.level:6x} ph={v.phase:06x} "
                        f"inc={v.inc:06x} {WAVE_NAMES[v.wave]:6s} vel={v.velocity:3d} "
                        f"A={v.attack} D={v.decay} S={v.sustain:#06x} R={v.release}")
        return f"frame {self.frame}\n" + "\n".join(rows)


# --------------------------------------------------------------------------
# Table export
# --------------------------------------------------------------------------
def write_tables(directory: str) -> None:
    import os
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, "note_inc.hex"), "w") as f:
        f.write("// MIDI note -> 24-bit phase increment, one entry per line, index = note number\n")
        for n, inc in enumerate(NOTE_INC):
            f.write(f"{inc:06X}\n")
    with open(os.path.join(directory, "sine_q.hex"), "w") as f:
        f.write("// quarter-wave sine, 257 entries, s16 two's complement, index i = 0..256\n")
        for x in SINE_Q:
            f.write(f"{x & 0xFFFF:04X}\n")
    with open(os.path.join(directory, "sine_full.hex"), "w") as f:
        f.write("// full-wave sine, 1024 entries, s16 two's complement, index = phase[23:14]\n")
        for x in SINE_TABLE:
            f.write(f"{x & 0xFFFF:04X}\n")


def appendix_markdown() -> str:
    import hashlib
    lines = []
    lines.append("### Appendix A -- NOTE_INC: MIDI note number -> 24-bit phase increment\n")
    lines.append("Normative.  `NOTE_INC[n] = floor(440 * 2^((n-69)/12) * 2^24 / 48000 + 0.5)`.  "
                 "Nominal frequency shown for reference only.\n")
    lines.append("| note | inc (dec) | inc (hex) | nominal Hz | | note | inc (dec) | inc (hex) | nominal Hz |")
    lines.append("|---:|---:|---:|---:|---|---:|---:|---:|---:|")
    for n in range(64):
        m = n + 64
        lines.append(f"| {n} | {NOTE_INC[n]} | 0x{NOTE_INC[n]:06X} | {note_frequency_hz(n):.3f} | "
                     f"| {m} | {NOTE_INC[m]} | 0x{NOTE_INC[m]:06X} | {note_frequency_hz(m):.3f} |")
    h = hashlib.sha256(",".join(str(x) for x in NOTE_INC).encode()).hexdigest()
    lines.append(f"\nSHA-256 of the decimal values joined by commas (no spaces): `{h}`\n")
    lines.append("### Appendix B -- SINE_Q: quarter-wave sine table, i = 0..256\n")
    lines.append("Normative.  `SINE_Q[i] = floor(32767 * sin(2*pi*i/1024) + 0.5)`.  "
                 "The full 1024-entry table is derived by the symmetry rules in section 5.4.  "
                 "Eight entries per row; the first column is the index of the first entry in the row.\n")
    lines.append("| i | +0 | +1 | +2 | +3 | +4 | +5 | +6 | +7 |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for i in range(0, 257, 8):
        chunk = SINE_Q[i:i + 8]
        lines.append(f"| {i} | " + " | ".join(str(x) for x in chunk) + " |" + (" |" * (8 - len(chunk))))
    h = hashlib.sha256(",".join(str(x) for x in SINE_Q).encode()).hexdigest()
    lines.append(f"\nSHA-256 of the 257 decimal values joined by commas: `{h}`")
    h2 = hashlib.sha256(",".join(str(x) for x in SINE_TABLE).encode()).hexdigest()
    lines.append(f"SHA-256 of the derived 1024-entry full table, same encoding: `{h2}`\n")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--write-tables":
        write_tables(sys.argv[2])
        print("wrote note_inc.hex, sine_q.hex, sine_full.hex to", sys.argv[2])
    elif len(sys.argv) == 2 and sys.argv[1] == "--appendix":
        print(appendix_markdown())
    else:
        print("usage: synth_ref.py --write-tables DIR | --appendix")
        sys.exit(2)
