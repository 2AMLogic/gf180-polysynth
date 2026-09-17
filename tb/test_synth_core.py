"""cocotb testbench for rtl/synth_core.v, checked bit-exactly (no tolerance)
against the frozen reference model prep/synth/reference/synth_ref.py.

Harness shape (per prep/funcverif/REPORT.md): C++ (gpi) clock; wake once per
frame on the sample_valid strobe; `await ReadOnly()` before reading `sample`
(Icarus NBA race); `await RisingEdge(clk)` before writing; bytes go in through
the direct byte port (contract 12.2) one per clock, right after the strobe, so
they are received in the frame whose sample was just read.

Base scope: NV=1 voice, square wave only -> every script addresses voice 0
and never sends SET_WAVE (the DUT's other waves are not implemented yet).
"""
from __future__ import annotations

import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge

import synth_ref as S

CLK_PERIOD_NS = 10
UART_CLKS_PER_BIT = 107
V = 0                                        # voice used by the single-voice tests
NV = int(os.environ.get("SYNTH_NV", "2"))    # voices implemented in the DUT (rtl/synth_core.v NV); tests never address others


def start_clock(dut):
    Clock(dut.clk, CLK_PERIOD_NS, "ns", impl="gpi").start()


async def reset(dut):
    dut.rst_n.value = 0
    dut.cmd_valid.value = 0
    dut.cmd_byte.value = 0
    dut.uart_rx.value = 1
    await ClockCycles(dut.clk, 4)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1              # frame 0 starts at the next edge


async def send_bytes(dut, data):
    """One byte per clock on the direct port.  Caller is past a RisingEdge(clk)."""
    for b in data:
        dut.cmd_valid.value = 1
        dut.cmd_byte.value = b
        await RisingEdge(dut.clk)
    dut.cmd_valid.value = 0


async def run_script(dut, events, n, tag=""):
    """Reset, then render n frames; for every (f, data) in events the bytes are
    delivered during frame f-1 (so they take effect in frame f, exactly like
    SynthRef.render_script feeding them "before frame f").  f must be >= 1.
    Compares every sample with the reference.  Returns the DUT samples."""
    ev = sorted(events, key=lambda e: e[0])
    for f, data in ev:
        assert f >= 1, "the DUT cannot receive bytes before frame 0"
        assert len(data) < 200, "too many bytes for one frame"
    ref = S.SynthRef()
    exp = ref.render_script(ev, n)
    await reset(dut)
    got = []
    k = 0
    for i in range(n):
        await RisingEdge(dut.sample_valid)
        await ReadOnly()
        s = dut.sample.value.to_signed()
        got.append(s)
        if s != exp[i]:
            raise AssertionError(f"{tag} frame {i}: DUT sample {s}, reference {exp[i]}  ({ref.describe()})")
        await RisingEdge(dut.clk)
        while k < len(ev) and ev[k][0] == i + 1:
            await send_bytes(dut, ev[k][1])
            k += 1
    assert dut.dbg_fifo_overflow.value == 0, "command FIFO overflowed"
    return got


# --------------------------------------------------------------------------
@cocotb.test()
async def test_reset_is_silent(dut):
    """Contract 9: every sample until a NOTE_ON has been applied is 0."""
    start_clock(dut)
    got = await run_script(dut, [], 16, "silent")
    assert got == [0] * 16


@cocotb.test()
async def test_note_on_default_adsr(dut):
    """NOTE_ON A4 vel 127 with reset ADSR (attack 2048 -> 512 frames), then
    NOTE_OFF; the whole ADSR shape with the default parameters."""
    start_clock(dut)
    events = [(1, S.cmd_note_on(V, 69, 127)), (900, S.cmd_note_off(V))]
    await run_script(dut, events, 1400, "default-adsr")


@cocotb.test()
async def test_full_adsr_fast(dut):
    """Fast ADSR so every stage and transition is crossed in ~600 frames:
    attack 8192 (128 fr), decay 2048, sustain 0x8000, release 4096 (128 fr)."""
    start_clock(dut)
    events = [(1, S.cmd_set_adsr(V, 8192, 2048, 0x8000, 4096)),
              (2, S.cmd_note_on(V, 60, 100)),
              (400, S.cmd_note_off(V)),
              (600, S.cmd_note_on(V, 72, 127)),     # retrigger from IDLE
              (650, S.cmd_note_off(V)),             # note-off mid-attack
              (700, S.cmd_note_on(V, 48, 64)),      # note-on during release
              (760, S.cmd_note_on(V, 50, 127)),     # note-on while attacking (hard restart)
              (1000, S.cmd_note_off(V)),
              (1001, S.cmd_note_off(V)),            # note-off in RELEASE: no effect
              ]
    await run_script(dut, events, 1300, "fast-adsr")


@cocotb.test()
async def test_envelope_corners(dut):
    """sustain=65535 (decay lasts one update), rates of 0 hold, sustain raised
    mid-decay (level jumps up), velocity 0 (silent note), SET_SUSTAIN while
    sustaining does not move the level, RESET mid-note."""
    start_clock(dut)
    events = [(1, S.cmd_set_adsr(V, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF)),
              (2, S.cmd_note_on(V, 69, 127)),          # attack 16 frames, decay 1 update
              (40, S.cmd_note_off(V)),                 # release 65535/frame: 16 frames
              (70, S.cmd_set_adsr(V, 0, 100, 0x1000, 0)),
              (71, S.cmd_note_on(V, 69, 127)),         # attack rate 0: holds level 0 forever
              (90, S.cmd_set_attack(V, 0xFFFF)),       # now it climbs
              (120, S.cmd_set_sustain(V, 0xF000)),     # decay target above level -> jump up
              (140, S.cmd_set_sustain(V, 0x2000)),     # in SUSTAIN: level must not move
              (160, S.cmd_note_off(V)),                # release 0: holds forever
              (180, S.cmd_set_release(V, 0x4000)),
              (230, S.cmd_note_on(V, 69, 0)),          # velocity 0: silent but running
              (260, S.cmd_set_attack(V, 0x7FFF)),
              (261, S.cmd_note_on(V, 69, 1)),          # velocity 1
              (300, S.cmd_reset()),                    # RESET mid-note: silence, defaults back
              (301, S.cmd_note_on(V, 69, 127)),        # default ADSR again
              ]
    await run_script(dut, events, 400, "env-corners")


@cocotb.test()
async def test_parser_rules(dut):
    """Contract 10.4: unknown opcode swallows its data bytes; a status byte
    abandons a partial command; stray data is dropped; several commands in
    one frame apply in order; RESET followed by commands in the same frame."""
    start_clock(dut)
    on = S.cmd_note_on(V, 69, 127)
    events = [
        (1, bytes([0x80 | (9 << 2)]) + bytes([0x45, 0x7F, 0x01]) + on),   # unknown op 9 + 3 data bytes, then NOTE_ON
        (30, bytes([0x84, 0x3C]) + S.cmd_set_sustain(V, 0x4000)),        # partial NOTE_ON abandoned by SET_SUSTAIN
        (31, bytes([0x10, 0x7F, 0x00])),                                 # stray data bytes: dropped
        (60, S.cmd_set_sustain(V, 0x1000) + S.cmd_set_sustain(V, 0xE000)),  # two in one frame: last wins
        (61, S.cmd_note_on(V, 40, 20) + S.cmd_note_off(V)),              # on then off in one frame: releases from 0
        (90, S.cmd_note_on(V, 40, 120) + S.cmd_set_attack(V, 0xFFFF)),   # attack rate applies to this frame's update
        (150, S.cmd_reset() + S.cmd_set_attack(V, 0x2000) + S.cmd_note_on(V, 81, 90)),   # queued behind RESET
        (200, bytes([0x80 | (31 << 2) | 3]) + bytes(range(0, 0x7F, 7)) + S.cmd_note_off(V)),  # unknown op 31 eats 19 data bytes
        (260, bytes([0xA0 | 3])),                                        # RESET with voice bits set
        (261, S.cmd_note_on(V, 69, 127)),
    ]
    await run_script(dut, events, 350, "parser")


@cocotb.test()
async def test_set_phase_inc_and_notes(dut):
    """SET_PHASE_INC corner values (0, Nyquist, all-ones, small) and NOTE_ON
    across the whole table (every 4th note) to verify the NOTE_INC ROM wiring."""
    start_clock(dut)
    events = [(1, S.cmd_set_adsr(V, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF)),
              (2, S.cmd_note_on(V, 69, 127)),
              (20, S.cmd_set_phase_inc(V, 0)),
              (40, S.cmd_set_phase_inc(V, 0x800000)),
              (60, S.cmd_set_phase_inc(V, 0xFFFFFF)),
              (80, S.cmd_set_phase_inc(V, 1)),
              (100, S.cmd_set_phase_inc(V, 0x7FFFFF)),
              (120, S.cmd_set_phase_inc(V, 0x123456))]
    f = 140
    for note in list(range(0, 128, 4)) + [127]:
        events.append((f, S.cmd_note_on(V, note, 127)))
        f += 24
    await run_script(dut, events, f + 30, "inc-notes")


@cocotb.test()
async def test_prng_command_stream(dut):
    """3000 frames of a deterministic random byte stream: valid commands
    (voice 0 only), unknown opcodes, stray data, RESETs, a few bytes per frame."""
    start_clock(dut)
    rng = random.Random(0x2A11)
    events = []
    for f in range(1, 3000):
        if rng.random() < 0.15 * NV:
            data = b""
            for _ in range(rng.choice((1, 1, 1, 2, 3))):
                r = rng.random()
                v = rng.randrange(NV)
                if r < 0.30:
                    data += S.cmd_note_on(v, rng.randrange(128), rng.randrange(128))
                elif r < 0.45:
                    data += S.cmd_note_off(v)
                elif r < 0.55:
                    data += S.cmd_set_attack(v, rng.choice((0, 1, 0x100, 0x2000, 0xFFFF, rng.randrange(65536))))
                elif r < 0.63:
                    data += S.cmd_set_decay(v, rng.choice((0, 0x100, 0x1000, 0xFFFF, rng.randrange(65536))))
                elif r < 0.71:
                    data += S.cmd_set_sustain(v, rng.randrange(65536))
                elif r < 0.79:
                    data += S.cmd_set_release(v, rng.choice((0, 0x80, 0x1000, 0xFFFF, rng.randrange(65536))))
                elif r < 0.83:
                    data += S.cmd_set_phase_inc(v, rng.randrange(1 << 24))
                elif r < 0.85:
                    data += bytes([0x80 | (2 << 2) | v, rng.randrange(128)])   # SET_WAVE with junk upper bits
                elif r < 0.88:
                    data += S.cmd_reset()
                elif r < 0.94:
                    data += bytes([rng.randrange(128)])                       # stray data byte
                else:
                    data += bytes([0x80 | (rng.randrange(9, 32) << 2)]) + bytes(rng.randrange(128) for _ in range(rng.randrange(4)))
            events.append((f, data))
    await run_script(dut, events, 3000, "prng")


@cocotb.test()
async def test_frame_boundary_bytes(dut):
    """Contract 10.4 timing: a command whose last byte lands in cycle 255 of
    frame n, or in cycle 0 of frame n (the tick cycle), applies at frame n+1
    in both cases; cycle 0 of frame n+1 applies at n+2.  Byte placement is
    cycle-exact here (RisingEdge(frame_tick) = start of cycle 0)."""
    start_clock(dut)
    await reset(dut)
    samples = []

    async def collect():
        while True:
            await RisingEdge(dut.sample_valid)
            await ReadOnly()
            samples.append(dut.sample.value.to_signed())
    cocotb.start_soon(collect())

    events = []
    # frame 0 is running now.  Wait for the start of frame 1.
    await RisingEdge(dut.frame_tick)                     # cycle 0 of frame 1
    await send_bytes(dut, S.cmd_set_adsr(V, 0xFFFF, 0xFFFF, 0xC000, 0x1000))   # cycles 0..11 of frame 1
    events.append((2, S.cmd_set_adsr(V, 0xFFFF, 0xFFFF, 0xC000, 0x1000)))
    await RisingEdge(dut.frame_tick)                     # cycle 0 of frame 2
    await ClockCycles(dut.clk, 253)                      # -> cycle 253
    await send_bytes(dut, S.cmd_note_on(V, 69, 127))     # bytes in cycles 253, 254, 255 of frame 2 -> applies at 3
    events.append((3, S.cmd_note_on(V, 69, 127)))
    # now in cycle 0 of frame 3
    await send_bytes(dut, S.cmd_note_off(V))             # cycle 0 of frame 3 -> applies at 4
    events.append((4, S.cmd_note_off(V)))
    await ClockCycles(dut.clk, 254)                      # -> cycle 255 of frame 3
    await send_bytes(dut, S.cmd_note_on(V, 72, 100))     # cycles 255 (f3), 0, 1 (f4): completes in frame 4 -> applies at 5
    events.append((5, S.cmd_note_on(V, 72, 100)))
    await RisingEdge(dut.frame_tick)                     # start of frame 5
    await ClockCycles(dut.clk, 255)                      # cycle 255 of frame 5
    await send_bytes(dut, S.cmd_note_off(V))             # cycle 255 of frame 5 -> applies at 6
    events.append((6, S.cmd_note_off(V)))
    await send_bytes(dut, S.cmd_note_on(V, 60, 127))     # cycles 0,1,2 of frame 6 -> applies at 7
    events.append((7, S.cmd_note_on(V, 60, 127)))
    n = 60
    while len(samples) < n:
        await RisingEdge(dut.sample_valid)
    exp = S.SynthRef().render_script(events, n).tolist()
    got = samples[:n]
    for i, (g, e) in enumerate(zip(got, exp)):
        assert g == e, f"boundary frame {i}: DUT {g}, reference {e}; got={got[:12]} exp={exp[:12]}"
    assert dut.dbg_fifo_overflow.value == 0


@cocotb.test()
async def test_uart_rx(dut):
    """UART receiver: bytes bit-banged at 107 clocks/bit arrive intact and in
    order (checked on dbg_uart_valid/dbg_uart_byte); a byte with a bad stop bit
    is dropped; the samples match the reference with each byte attributed to
    the frame the DUT received it in."""
    start_clock(dut)
    await reset(dut)
    frame = [0]
    rx_log = []          # (frame, byte)
    samples = []

    async def count_frames():
        while True:
            await RisingEdge(dut.frame_tick)
            frame[0] += 1

    async def watch_uart():
        while True:
            await RisingEdge(dut.dbg_uart_valid)
            await ReadOnly()
            rx_log.append((frame[0], int(dut.dbg_uart_byte.value)))

    async def collect():
        while True:
            await RisingEdge(dut.sample_valid)
            await ReadOnly()
            samples.append(dut.sample.value.to_signed())

    cocotb.start_soon(count_frames())
    cocotb.start_soon(watch_uart())
    cocotb.start_soon(collect())

    async def uart_byte(b, stop_bit=1, bit_clks=UART_CLKS_PER_BIT):
        dut.uart_rx.value = 0
        await ClockCycles(dut.clk, bit_clks)
        for i in range(8):
            dut.uart_rx.value = (b >> i) & 1
            await ClockCycles(dut.clk, bit_clks)
        dut.uart_rx.value = stop_bit
        await ClockCycles(dut.clk, bit_clks)
        dut.uart_rx.value = 1
        await ClockCycles(dut.clk, 20)

    stream = S.cmd_set_adsr(V, 0xFFFF, 0x800, 0x9000, 0x400) + S.cmd_note_on(V, 64, 110)
    await ClockCycles(dut.clk, 300)
    for b in stream:
        await uart_byte(b)
    await uart_byte(0x85, stop_bit=0)          # framing error: must be dropped (would be NOTE_ON v1)
    await ClockCycles(dut.clk, 400)
    for b in S.cmd_note_off(V):
        await uart_byte(b)
    for b in stream:                            # again at a slightly fast baud (-2 %)
        await uart_byte(b, bit_clks=105)
    for b in S.cmd_note_off(V):                 # and slow (+2 %)
        await uart_byte(b, bit_clks=109)
    n = frame[0] + 200
    while len(samples) < n:
        await RisingEdge(dut.sample_valid)

    got_bytes = [b for _, b in rx_log]
    want_bytes = list(stream) + list(S.cmd_note_off(V)) + list(stream) + list(S.cmd_note_off(V))
    assert got_bytes == want_bytes, f"UART bytes {got_bytes} != sent {want_bytes}"
    events = [(f + 1, bytes([b])) for f, b in rx_log]   # received in frame f -> applies at f+1
    exp = S.SynthRef().render_script(events, n).tolist()
    got = samples[:n]
    for i, (g, e) in enumerate(zip(got, exp)):
        assert g == e, f"uart frame {i}: DUT {g}, reference {e} (rx_log={rx_log})"
    dut._log.info(f"UART: {len(rx_log)} bytes received intact over {n} frames; framing-error byte dropped")


@cocotb.test()
async def test_decay_exact_boundary(dut):
    """Pins the DECAY->SUSTAIN comparison to '<=' (contract 6.3), which is
    only observable when level == target + decay exactly and a SET_SUSTAIN /
    SET_DECAY lands in the very frame the state changes.  (a) attack 0xFFFF,
    decay 0x1000, sustain 0xF7FF: LEVEL_MAX - target = 8 * decay, so the 8th
    decay update lands exactly on the boundary; SET_SUSTAIN(0xFFFF) is applied
    in the first SUSTAIN frame (found with the reference): in SUSTAIN the level
    must not move; a late transition would jump it up.  (b) decay 0 with
    sustain 0xFFFF: DECAY must end in one update; then a lower SET_SUSTAIN +
    nonzero SET_DECAY must not start a decay."""
    start_clock(dut)
    probe = S.SynthRef()
    probe.feed(S.cmd_set_adsr(V, 0xFFFF, 0x1000, 0xF7FF, 0x100) + S.cmd_note_on(V, 69, 127))
    f_sus = None
    for i in range(200):
        probe.step()
        if probe.voices[V].state == S.ENV_SUSTAIN:
            f_sus = probe.frame           # state changed at the end of frame f_sus-1 -> SUSTAIN from frame f_sus
            break
    assert f_sus is not None and probe.voices[V].level == 0xF7FF0
    events = [(1, S.cmd_set_adsr(V, 0xFFFF, 0x1000, 0xF7FF, 0x100) + S.cmd_note_on(V, 69, 127)),
              (f_sus, S.cmd_set_sustain(V, 0xFFFF)),
              (f_sus + 20, S.cmd_set_adsr(V, 0xFFFF, 0, 0xFFFF, 0x100)),
              (f_sus + 21, S.cmd_note_on(V, 69, 127)),
              (f_sus + 60, S.cmd_set_sustain(V, 0x8000)),
              (f_sus + 61, S.cmd_set_decay(V, 0x1000)),
              ]
    await run_script(dut, events, f_sus + 160, "decay-boundary")


@cocotb.test()
async def test_two_voices_and_saturation(dut):
    """Second voice (contract 8 mixer): chords on voices 0 and 1, per-voice
    parameters independent, RESET clears both, and the sum saturates at both
    limits (two full-scale squares in phase: +65020 -> +32767, -65024 -> -32768;
    Nyquist increments keep the squares aligned)."""
    start_clock(dut)
    if NV < 2:
        dut._log.info("NV < 2: skipping two-voice test body")
        return
    fast = lambda v: S.cmd_set_adsr(v, 0xFFFF, 0xFFFF, 0xFFFF, 0x4000)
    events = [(1, fast(0) + fast(1)),
              (2, S.cmd_note_on(0, 60, 127) + S.cmd_note_on(1, 67, 127)),      # chord, full velocity
              (80, S.cmd_note_off(1)),
              (120, S.cmd_set_phase_inc(0, 0x800000) + S.cmd_set_phase_inc(1, 0x800000)),   # both at Nyquist
              (121, S.cmd_note_on(0, 69, 127) + S.cmd_note_on(1, 69, 127)),   # restart in phase -> saturates +/-
              (160, S.cmd_set_phase_inc(1, 0)),                              # v1 stalls, v0 keeps flipping
              (200, S.cmd_set_sustain(1, 0x4000) + S.cmd_set_decay(1, 0x800)),  # independent params
              (201, S.cmd_note_on(1, 40, 100)),
              (260, S.cmd_reset()),
              (261, S.cmd_note_on(1, 72, 90)),                                # after RESET: default ADSR on v1 only
              (262, S.cmd_note_on(0, 48, 30)),
              ]
    got = await run_script(dut, events, 420, "two-voices")
    assert 32767 in got and -32768 in got, "saturation at both limits was expected in this script"


@cocotb.test()
async def test_waveforms(dut):
    """Contract 5.4: saw, tri and sine at full scale for several increments
    (A4, MIDI 0, MIDI 127, stalled, Nyquist, all-ones), sine at inc = 2^14 so
    phase[23:14] walks every one of the 1024 table entries (both mirror
    halves, both signs), SET_WAVE mid-note, and SET_WAVE data bits 6:2 ignored."""
    start_clock(dut)
    events = [(1, S.cmd_set_adsr(V, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF))]
    f = 2
    for wave in (S.WAVE_SAW, S.WAVE_TRI, S.WAVE_SINE, S.WAVE_SQUARE):
        events.append((f, S.cmd_set_wave(V, wave) + S.cmd_note_on(V, 69, 127)))
        f += 40
        for inc in (S.NOTE_INC[0], S.NOTE_INC[127], 0, 0x800000, 0xFFFFFF, 0x7FFFFF, 0x123456):
            events.append((f, S.cmd_set_phase_inc(V, inc)))
            f += 24
    events.append((f, bytes([0x80 | (2 << 2) | V, 0x7C | S.WAVE_SINE]) + S.cmd_note_on(V, 60, 127) + S.cmd_set_phase_inc(V, 1 << 14)))
    f += 1030                                              # all 1024 sine indices
    events.append((f, S.cmd_set_wave(V, S.WAVE_TRI) + S.cmd_set_phase_inc(V, 1 << 12)))   # mid-note wave change
    f += 300
    events.append((f, S.cmd_set_wave(V, S.WAVE_SAW)))
    f += 300
    await run_script(dut, events, f + 20, "waveforms")
