"""Tests of the reference model against the contract (NUMERIC-CONTRACT.md rev 1).

These are the vectors that will later be replayed against the RTL: every test
that renders samples does so through the public API (feed / step / render /
render_script) and asserts exact integer values, so a cocotb bench can drive
the same byte scripts into the RTL and compare sample-for-sample.

Run:  python3 -m pytest -q test_synth_ref.py
"""
import hashlib
import math
from dataclasses import asdict
from decimal import Decimal, getcontext

import numpy as np
import pytest

import synth_ref as S
from synth_ref import (
    ENV_ATTACK, ENV_DECAY, ENV_IDLE, ENV_RELEASE, ENV_SUSTAIN,
    LEVEL_MAX, NOTE_INC, PHASE_MASK, SAMPLE_MAX, SAMPLE_MIN, SINE_Q, SINE_TABLE,
    WAVE_SAW, WAVE_SINE, WAVE_SQUARE, WAVE_TRI,
    SynthRef, Voice,
    cmd_note_off, cmd_note_on, cmd_reset, cmd_set_adsr, cmd_set_attack,
    cmd_set_decay, cmd_set_phase_inc, cmd_set_release, cmd_set_sustain,
    cmd_set_wave, saturate, voice_output, wave_sample,
)

# Frozen locks.  These pin the tables and one long scripted render so that any
# accidental edit of the model or the tables is caught.  They are printed by
# the corresponding test on failure so a *deliberate* contract revision can
# update them consciously.
FROZEN = {
    "note_inc_sha256": "e771e6b7b39d3941c471b772bfb5cdca398b78ee7fa964c3c90388d2cc888ba4",
    "sine_q_sha256": "72e3ab187d9c5e27be2a1dfbf209610aca3bf553eea8d15b0db53e05b240ef4f",
    "sine_full_sha256": "04b8970a1d1e38c6c1052b91753b6860d1f7672f952dcdf03de0abd1f43c459f",
    "golden_script_sha256": "8e0fc3cf518faa961a568098900a5b49192f3b028a9eefb41ff645d4559bc9e4",
}


def _sha(values):
    return hashlib.sha256(",".join(str(int(x)) for x in values).encode()).hexdigest()


def fresh(*cmds: bytes) -> SynthRef:
    m = SynthRef()
    for c in cmds:
        m.feed(c)
    return m


# ============================================================================
# Tables (contract 5.3, 5.4, appendices A and B)
# ============================================================================
class TestNoteTable:
    def test_matches_formula_float(self):
        for n in range(128):
            f = 440.0 * 2.0 ** ((n - 69) / 12.0)
            assert NOTE_INC[n] == math.floor(f * (1 << 24) / 48000 + 0.5), n

    def test_matches_formula_decimal_60_digits(self):
        getcontext().prec = 60
        for n in range(128):
            fd = Decimal(440) * (Decimal(2) ** (Decimal(n - 69) / Decimal(12)))
            xd = fd * Decimal(1 << 24) / Decimal(48000)
            frac = xd - int(xd)
            # no entry is anywhere near a rounding boundary (contract 5.3 claims 2.7e-3)
            assert abs(frac - Decimal("0.5")) > Decimal("0.0027"), n
            assert NOTE_INC[n] == int((xd + Decimal("0.5")).to_integral_value(rounding="ROUND_FLOOR")), n

    def test_named_values_and_properties(self):
        assert len(NOTE_INC) == 128
        assert NOTE_INC[69] == 153791       # A4 = 440 Hz
        assert NOTE_INC[0] == 2858
        assert NOTE_INC[127] == 4384395
        assert all(NOTE_INC[i] < NOTE_INC[i + 1] for i in range(127))
        assert all(0 < x < (1 << 23) for x in NOTE_INC)     # below Nyquist, fits u24
        for n in range(116):                # octave = ×2 within independent rounding
            assert abs(NOTE_INC[n + 12] - 2 * NOTE_INC[n]) <= 1, n

    def test_frozen_hash(self):
        assert _sha(NOTE_INC) == FROZEN["note_inc_sha256"]


class TestSineTable:
    def test_quarter_matches_formula(self):
        for i in range(257):
            assert SINE_Q[i] == math.floor(32767.0 * math.sin(2.0 * math.pi * i / 1024.0) + 0.5), i

    def test_quarter_matches_decimal_taylor(self):
        getcontext().prec = 60
        PI = Decimal("3.14159265358979323846264338327950288419716939937510582097494459")

        def dsin(x):
            term = x
            s = x
            k = 1
            while abs(term) > Decimal(10) ** -50:
                term = -term * x * x / ((2 * k) * (2 * k + 1))
                s += term
                k += 1
            return s

        for i in range(257):
            xd = Decimal(32767) * dsin(2 * PI * Decimal(i) / Decimal(1024))
            frac = xd - int(xd)
            assert abs(frac - Decimal("0.5")) > Decimal("0.0012"), i
            assert SINE_Q[i] == int((xd + Decimal("0.5")).to_integral_value(rounding="ROUND_FLOOR")), i

    def test_full_table_symmetry_and_landmarks(self):
        T = SINE_TABLE
        assert len(T) == 1024 and len(SINE_Q) == 257
        assert T[0] == 0 and T[256] == 32767 and T[512] == 0 and T[768] == -32767
        for i in range(257):
            assert T[i] == SINE_Q[i]
        for i in range(256):
            assert T[512 - i] == SINE_Q[i]
        for i in range(512):
            assert T[512 + i] == -T[i]
        assert all(SINE_Q[i] <= SINE_Q[i + 1] for i in range(256))
        assert max(T) == 32767 and min(T) == -32767      # never -32768
        assert all(SAMPLE_MIN < x <= SAMPLE_MAX for x in T)

    def test_frozen_hashes(self):
        assert _sha(SINE_Q) == FROZEN["sine_q_sha256"]
        assert _sha(SINE_TABLE) == FROZEN["sine_full_sha256"]


# ============================================================================
# Waveforms (contract 5.4)
# ============================================================================
class TestWaveforms:
    @pytest.mark.parametrize("phase,expected", [
        (0x000000, 32767), (0x7FFFFF, 32767), (0x800000, -32768), (0xFFFFFF, -32768)])
    def test_square(self, phase, expected):
        assert wave_sample(WAVE_SQUARE, phase) == expected

    @pytest.mark.parametrize("phase,expected", [
        (0x000000, -32768), (0x0000FF, -32768), (0x000100, -32767),
        (0x800000, 0), (0xFFFF00, 32767), (0xFFFFFF, 32767)])
    def test_saw(self, phase, expected):
        assert wave_sample(WAVE_SAW, phase) == expected

    @pytest.mark.parametrize("phase,expected", [
        (0x000000, -32768), (0x000080, -32767), (0x400000, 0), (0x7FFF80, 32767),
        (0x7FFFFF, 32767), (0x800000, 32767), (0x800080, 32766), (0xC00000, -1),
        (0xFFFF80, -32768), (0xFFFFFF, -32768)])
    def test_triangle(self, phase, expected):
        assert wave_sample(WAVE_TRI, phase) == expected

    @pytest.mark.parametrize("phase,expected", [
        (0x000000, 0), (0x003FFF, 0), (0x004000, 201), (0x400000, 32767),
        (0x800000, 0), (0xC00000, -32767), (0xFFC000, SINE_TABLE[1023]), (0xFFFFFF, -201)])
    def test_sine(self, phase, expected):
        assert wave_sample(WAVE_SINE, phase) == expected

    def test_bit_level_forms_match_formulas(self):
        """The contract's informative bit-level equivalents must be exactly equivalent."""
        def s16(x):
            x &= 0xFFFF
            return x - 0x10000 if x & 0x8000 else x
        phases = list(range(0, 1 << 24, 0x101)) + [0x7FFFFF, 0x800000, 0xFFFFFF, 0x3FFF, 0x4000]
        for p in phases:
            b23 = (p >> 23) & 1
            assert wave_sample(WAVE_SQUARE, p) == s16(0x8000 if b23 else 0x7FFF)
            assert wave_sample(WAVE_SAW, p) == s16(((p >> 8) & 0xFFFF) ^ 0x8000)
            b22_7 = (p >> 7) & 0xFFFF
            assert wave_sample(WAVE_TRI, p) == s16(((~b22_7 & 0xFFFF) if b23 else b22_7) ^ 0x8000)

    def test_all_waveforms_in_range(self):
        for p in range(0, 1 << 24, 1 << 10):
            for w in range(4):
                assert SAMPLE_MIN <= wave_sample(w, p) <= SAMPLE_MAX

    def test_bad_wave_rejected(self):
        with pytest.raises(ValueError):
            wave_sample(4, 0)


# ============================================================================
# Voice scaler (contract 7) and mixer (contract 8)
# ============================================================================
class TestScaler:
    def test_full_scale_square_extremes(self):
        v = Voice(wave=WAVE_SQUARE, level=LEVEL_MAX, velocity=127, phase=0)
        assert v.env_gain() == 65535 and v.effective_gain() == 65023
        assert 32767 * 65023 == 2130608641 and 2130608641 // 65536 == 32510
        assert voice_output(v) == 32510            # (32767*65023)>>16 = floor(32510.51)
        v.phase = 0x800000
        assert voice_output(v) == -32512           # floor(-32511.5)

    def test_floor_on_small_negative(self):
        v = Voice(wave=WAVE_SAW, level=LEVEL_MAX, velocity=127, phase=0x7FFF00)  # osc = -1
        assert wave_sample(WAVE_SAW, 0x7FFF00) == -1
        assert voice_output(v) == -1               # floor(-65023/65536) = -1, not 0

    def test_zero_gain_paths(self):
        for w in range(4):
            assert voice_output(Voice(wave=w, level=0, velocity=127, phase=0x123456)) == 0
            assert voice_output(Voice(wave=w, level=LEVEL_MAX, velocity=0, phase=0x123456)) == 0

    def test_effective_gain_formula(self):
        for level in (0, 0x10, 0x8000, 0x7FFF0, LEVEL_MAX):
            for vel in (0, 1, 64, 127):
                v = Voice(level=level, velocity=vel)
                assert v.effective_gain() == ((level >> 4) * vel) >> 7

    def test_range_at_full_velocity(self):
        for w in range(4):
            for p in range(0, 1 << 24, 1 << 12):
                o = voice_output(Voice(wave=w, level=LEVEL_MAX, velocity=127, phase=p))
                assert -32512 <= o <= 32510


class TestMixer:
    @pytest.mark.parametrize("x,expected", [
        (0, 0), (5, 5), (-5, -5), (32767, 32767), (32768, 32767), (131072, 32767),
        (-32768, -32768), (-32769, -32768), (-131072, -32768)])
    def test_saturate(self, x, expected):
        assert saturate(x) == expected

    def test_four_voices_hit_both_limits(self):
        """4 squares at full velocity: attack (rate 65535) completes after 16
        updates, so sample 16 is the first at LEVEL_MAX -> +32767.  Then a
        phase of 0x800000 flips all four to -32768 -> saturates to -32768."""
        m = SynthRef()
        for v in range(4):
            m.feed(cmd_set_attack(v, 65535) + cmd_set_sustain(v, 65535) + cmd_note_on(v, 60, 127))
        a = m.render(17)
        assert a[0] == 0                                   # level 0 at note-on frame
        # per-voice values at sample 16 are 32510 each -> sum 130040 -> saturate
        assert all(v.phase == 17 * NOTE_INC[60] < 0x800000 for v in m.voices)   # still first half-cycle
        assert m.voice_outputs() == [32510] * 4
        assert a[16] == SAMPLE_MAX
        # sample 1: level = 65535 (one attack update) -> re-derive from contract section 7
        env1 = 65535 >> 4
        g1 = (env1 * 127) >> 7
        out1 = (32767 * g1) >> 16
        assert a[1] == 4 * out1 and 0 < a[1] < SAMPLE_MAX  # rising, not yet saturating
        assert all(m.voices[v].state == ENV_SUSTAIN for v in range(4))
        # now put all voices into the second half-cycle
        for v in range(4):
            m.feed(cmd_set_phase_inc(v, 0x800000))
        m.step()                                           # phase 0 -> 0x800000 after this frame
        assert m.step() == SAMPLE_MIN                      # 4 * -32512 = -130048 -> -32768

    def test_non_saturating_sum_is_exact(self):
        m = SynthRef()
        for v in range(4):
            m.feed(cmd_set_attack(v, 65535) + cmd_set_sustain(v, 65535) + cmd_note_on(v, 60, 31))
        a = m.render(17)
        # g = (65535*31)>>7 = 15871 ; out = (32767*15871)>>16 = 7935 ; x4
        assert a[16] == 4 * 7935 == 31740
        for v in range(4):
            m.feed(cmd_set_phase_inc(v, 0x800000))
        m.step()
        assert m.step() == 4 * -7936 == -31744            # floor(-7935.5) = -7936

    def test_two_voices_saturate_one_does_not(self):
        m = SynthRef()
        for v in range(2):
            m.feed(cmd_set_attack(v, 65535) + cmd_note_on(v, 60, 127))
        assert m.render(17)[16] == SAMPLE_MAX              # 2*32510 = 65020 > 32767
        m = SynthRef()
        m.feed(cmd_set_attack(0, 65535) + cmd_note_on(0, 60, 127))
        assert m.render(17)[16] == 32510


# ============================================================================
# Envelope (contract 6)
# ============================================================================
def run_until(m: SynthRef, voice: int, state: int, limit: int) -> int:
    """Step until voices[voice].state == state (observed after the step's
    update, i.e. the state at the start of the following frame).  Returns the
    number of steps taken.  Fails if not reached within `limit`."""
    for k in range(1, limit + 1):
        m.step()
        if m.voices[voice].state == state:
            return k
    pytest.fail(f"state {state} not reached within {limit} steps: {m.describe()}")


class TestEnvelope:
    def test_attack_fastest_is_16_updates(self):
        m = fresh(cmd_set_attack(0, 65535), cmd_note_on(0, 69, 127))
        for k in range(1, 16):
            m.step()
            assert m.voices[0].state == ENV_ATTACK and m.voices[0].level == k * 65535, k
        m.step()
        assert m.voices[0].state == ENV_DECAY and m.voices[0].level == LEVEL_MAX

    def test_attack_default_rate_is_512_updates(self):
        m = fresh(cmd_note_on(0, 69, 127))      # default attack 2048
        assert run_until(m, 0, ENV_DECAY, 1000) == 512
        assert m.voices[0].level == LEVEL_MAX

    @pytest.mark.parametrize("rate", [1, 2, 3, 7, 100, 999, 2048, 4097, 65534, 65535])
    def test_attack_duration_closed_form(self, rate):
        m = fresh(cmd_set_attack(0, rate), cmd_note_on(0, 69, 127))
        expected = -(-LEVEL_MAX // rate)          # ceil(LEVEL_MAX / rate)
        limit = expected + 2
        # for the very slow rates assert the level arithmetic instead of running to completion
        if expected > 20000:
            for _ in range(1000):
                m.step()
            assert m.voices[0].state == ENV_ATTACK and m.voices[0].level == 1000 * rate
        else:
            assert run_until(m, 0, ENV_DECAY, limit) == expected

    def test_attack_rate_zero_holds_silent(self):
        m = fresh(cmd_set_attack(0, 0), cmd_note_on(0, 69, 127))
        a = m.render(200)
        assert not a.any()
        assert m.voices[0].state == ENV_ATTACK and m.voices[0].level == 0
        m.feed(cmd_note_off(0))
        m.step()                                  # applied: RELEASE with level 0 -> IDLE after update
        assert m.voices[0].state == ENV_IDLE

    def test_output_timeline_matches_section_6_5(self):
        """sample n uses level 0; sample n+k uses level min(k*A, MAX)."""
        A = 3000
        m = fresh(cmd_set_wave(0, WAVE_SQUARE), cmd_set_attack(0, A),
                  cmd_set_sustain(0, 65535), cmd_note_on(0, 69, 127))   # sustain=max keeps LEVEL_MAX after attack
        for k in range(0, 400):
            level = min(k * A, LEVEL_MAX)
            expected = voice_output(Voice(wave=WAVE_SQUARE, phase=m.voices[0].phase,
                                          level=level, velocity=127))
            assert m.step() == expected, k

    def test_decay_to_half(self):
        m = fresh(cmd_set_attack(0, 65535), cmd_set_decay(0, 65535),
                  cmd_set_sustain(0, 0x8000), cmd_note_on(0, 69, 127))
        run_until(m, 0, ENV_DECAY, 20)
        # LEVEL_MAX - 0x80000 = 524272 ; ceil(524272/65535) = 8
        assert run_until(m, 0, ENV_SUSTAIN, 20) == 8
        assert m.voices[0].level == 0x80000 and m.voices[0].env_gain() == 0x8000

    def test_decay_zero_length_when_sustain_is_max(self):
        m = fresh(cmd_set_attack(0, 65535), cmd_set_decay(0, 1),
                  cmd_set_sustain(0, 65535), cmd_note_on(0, 69, 127))
        run_until(m, 0, ENV_DECAY, 20)
        assert run_until(m, 0, ENV_SUSTAIN, 5) == 1
        assert m.voices[0].level == LEVEL_MAX

    def test_decay_to_zero_sustains_at_zero(self):
        m = fresh(cmd_set_attack(0, 65535), cmd_set_decay(0, 65535),
                  cmd_set_sustain(0, 0), cmd_note_on(0, 69, 127))
        run_until(m, 0, ENV_DECAY, 20)
        assert run_until(m, 0, ENV_SUSTAIN, 20) == 16
        assert m.voices[0].level == 0
        assert not m.render(50).any()            # silent but NOT idle
        assert m.voices[0].state == ENV_SUSTAIN
        m.feed(cmd_note_off(0))
        m.step()
        assert m.voices[0].state == ENV_IDLE     # release from 0 completes in one update

    def test_decay_rate_zero_holds(self):
        m = fresh(cmd_set_attack(0, 65535), cmd_set_decay(0, 0),
                  cmd_set_sustain(0, 0x1000), cmd_note_on(0, 69, 127))
        run_until(m, 0, ENV_DECAY, 20)
        m.render(100)
        assert m.voices[0].state == ENV_DECAY and m.voices[0].level == LEVEL_MAX

    def test_sustain_holds_and_ignores_sustain_writes(self):
        m = fresh(cmd_set_attack(0, 65535), cmd_set_decay(0, 65535),
                  cmd_set_sustain(0, 0x4000), cmd_note_on(0, 69, 127))
        run_until(m, 0, ENV_SUSTAIN, 50)
        m.render(1000)
        assert m.voices[0].level == 0x40000
        m.feed(cmd_set_sustain(0, 0xF000))
        m.render(10)
        assert m.voices[0].state == ENV_SUSTAIN and m.voices[0].level == 0x40000
        assert m.voices[0].sustain == 0xF000     # the parameter changed, the level did not

    def test_decay_jumps_up_if_target_raised(self):
        m = fresh(cmd_set_attack(0, 65535), cmd_set_decay(0, 65535),
                  cmd_set_sustain(0, 0x1000), cmd_note_on(0, 69, 127))
        run_until(m, 0, ENV_DECAY, 20)
        m.render(4)                              # level = LEVEL_MAX - 4*65535 = 786420
        assert m.voices[0].level == 786420 and m.voices[0].state == ENV_DECAY
        m.feed(cmd_set_sustain(0, 0xF000))       # target 0xF0000 = 983040 > level
        m.step()
        assert m.voices[0].state == ENV_SUSTAIN and m.voices[0].level == 0xF0000

    def test_release_from_sustain(self):
        m = fresh(cmd_set_attack(0, 65535), cmd_set_decay(0, 65535),
                  cmd_set_sustain(0, 0x8000), cmd_set_release(0, 65535), cmd_note_on(0, 69, 127))
        run_until(m, 0, ENV_SUSTAIN, 50)
        m.feed(cmd_note_off(0))
        # 0x80000 = 524288 ; ceil(524288/65535) = 9 ; after 8 updates level = 8 (>0)
        for k in range(1, 9):
            m.step()
            assert m.voices[0].state == ENV_RELEASE and m.voices[0].level == 524288 - k * 65535
        m.step()
        assert m.voices[0].state == ENV_IDLE and m.voices[0].level == 0

    def test_note_off_mid_attack_releases_from_partial_level(self):
        m = fresh(cmd_set_attack(0, 1000), cmd_set_release(0, 3000), cmd_note_on(0, 69, 127))
        m.render(10)                              # 10 updates -> level 10000, still ATTACK
        assert m.voices[0].state == ENV_ATTACK and m.voices[0].level == 10000
        m.feed(cmd_note_off(0))
        expected_levels = [7000, 4000, 1000, 0]
        for lvl in expected_levels:
            m.step()
            assert m.voices[0].level == lvl
        assert m.voices[0].state == ENV_IDLE
        # the attack never completed: level never reached LEVEL_MAX
        assert m.voices[0].level == 0

    def test_release_rate_zero_holds_unless_level_zero(self):
        m = fresh(cmd_set_attack(0, 65535), cmd_set_release(0, 0), cmd_note_on(0, 69, 127))
        m.render(5)
        m.feed(cmd_note_off(0))
        m.render(100)
        assert m.voices[0].state == ENV_RELEASE and m.voices[0].level == 5 * 65535

    def test_note_off_in_idle_and_release_is_ignored(self):
        m = fresh(cmd_note_off(0))
        m.step()
        assert m.voices[0].state == ENV_IDLE
        m = fresh(cmd_set_attack(0, 65535), cmd_set_release(0, 100), cmd_note_on(0, 69, 127))
        m.render(5)
        m.feed(cmd_note_off(0))
        m.step()
        lvl = m.voices[0].level
        m.feed(cmd_note_off(0))                   # second note-off must not disturb the ramp
        m.step()
        assert m.voices[0].state == ENV_RELEASE and m.voices[0].level == lvl - 100

    def test_note_on_then_note_off_same_frame_is_zero_length(self):
        m = fresh(cmd_note_on(0, 69, 127) + cmd_note_off(0))
        assert m.step() == 0
        assert m.voices[0].state == ENV_IDLE       # RELEASE at level 0 -> IDLE in one update
        assert not m.render(100).any()

    def test_retrigger_is_hard_restart(self):
        """Output after a NOTE_ON is identical regardless of prior history."""
        params = cmd_set_wave(0, WAVE_SAW) + cmd_set_adsr(0, 3000, 500, 0x6000, 700)
        a = fresh(params, cmd_note_on(0, 64, 100)).render(3000)
        # history 1: different note, mid-sustain, then retrigger
        m = fresh(params, cmd_note_on(0, 40, 127))
        m.render(1234)
        m.feed(cmd_note_on(0, 64, 100))
        assert np.array_equal(m.render(3000), a)
        # history 2: retrigger during release, with a phase far from 0
        m = fresh(params, cmd_note_on(0, 90, 50))
        m.render(777)
        m.feed(cmd_note_off(0))
        m.render(100)
        assert m.voices[0].state == ENV_RELEASE
        m.feed(cmd_note_on(0, 64, 100))
        assert m.voices[0].state == ENV_RELEASE     # not applied until the next frame
        assert np.array_equal(m.render(3000), a)
        assert m.voices[0].phase == (3000 * NOTE_INC[64]) & PHASE_MASK

    def test_velocity_zero_note_on_is_silent_not_off(self):
        m = fresh(cmd_set_attack(0, 65535), cmd_note_on(0, 69, 0))
        assert not m.render(40).any()
        assert m.voices[0].state == ENV_DECAY       # it attacked, silently

    def test_phase_advances_in_idle_and_wraps(self):
        m = fresh(cmd_set_phase_inc(0, 0xFFFFFF))
        m.step()
        assert m.voices[0].phase == 0xFFFFFF and m.voices[0].state == ENV_IDLE
        m.step()
        assert m.voices[0].phase == 0xFFFFFE      # (0xFFFFFF + 0xFFFFFF) mod 2^24
        assert not m.render(10).any()             # idle voice is silent regardless of phase


# ============================================================================
# Command timing and ordering (contract 4.2, 10.4)
# ============================================================================
class TestCommandTiming:
    def test_command_affects_next_sample_only(self):
        setup = cmd_set_wave(0, WAVE_SAW) + cmd_set_attack(0, 65535) + cmd_note_on(0, 69, 127)
        m = fresh(setup)
        twin = fresh(setup)
        a = m.render(20)
        b = twin.render(20)
        assert np.array_equal(a, b)
        m.feed(cmd_set_wave(0, WAVE_SQUARE))
        v = m.voices[0]
        expected = saturate(voice_output(Voice(wave=WAVE_SQUARE, phase=v.phase,
                                               level=v.level, velocity=127)))
        s20 = m.step()
        assert s20 == expected and s20 != twin.step()

    def test_render_script_equals_manual_feed(self):
        events = [(0, cmd_set_wave(1, WAVE_TRI) + cmd_note_on(1, 60, 90)),
                  (100, cmd_note_on(2, 64, 80)),
                  (250, cmd_note_off(1)),
                  (400, cmd_set_wave(2, WAVE_SINE)),
                  (700, cmd_reset())]
        a = SynthRef().render_script(events, 1000)
        m = SynthRef()
        parts = []
        last = 0
        for f, data in events:
            parts.append(m.render(f - last))
            m.feed(data)
            last = f
        parts.append(m.render(1000 - last))
        assert np.array_equal(a, np.concatenate(parts))
        assert a.dtype == np.int16 and len(a) == 1000

    def test_multiple_commands_in_one_frame_apply_in_order(self):
        m = fresh(cmd_set_phase_inc(0, 0x100) + cmd_note_on(0, 69, 127))
        m.step()
        assert m.voices[0].inc == NOTE_INC[69]
        m = fresh(cmd_note_on(0, 69, 127) + cmd_set_phase_inc(0, 0x100))
        m.step()
        assert m.voices[0].inc == 0x100 and m.voices[0].state == ENV_ATTACK
        m = fresh(cmd_note_off(0) + cmd_note_on(0, 69, 127))
        m.step()
        assert m.voices[0].state == ENV_ATTACK
        m = fresh(cmd_note_on(0, 69, 127) + cmd_note_off(0))
        m.step()
        assert m.voices[0].state == ENV_IDLE        # RELEASE at level 0 completed

    def test_parameter_write_used_by_same_frame_update(self):
        m = fresh(cmd_set_attack(0, 65535), cmd_note_on(0, 69, 127))
        m.step()                                   # level 65535
        m.feed(cmd_set_attack(0, 1))
        m.step()                                   # update uses the new rate immediately
        assert m.voices[0].level == 65536


# ============================================================================
# Parser (contract 10.2 - 10.4)
# ============================================================================
class TestParser:
    def test_status_byte_values(self):
        assert cmd_note_off(2) == b"\x82"
        assert cmd_note_on(0, 69, 127) == b"\x84\x45\x7f"
        assert cmd_set_sustain(3, 0) == b"\x97\x00\x00\x00"
        assert cmd_reset() == b"\xa0"
        assert cmd_set_wave(1, 3) == b"\x89\x03"

    def test_u16_encoding(self):
        assert cmd_set_attack(0, 0xABCD) == bytes((0x8C, 0x02, 0x57, 0x4D))
        assert cmd_set_release(0, 0xFFFF) == bytes((0x98, 0x03, 0x7F, 0x7F))
        for x in (0, 1, 0x7F, 0x80, 0x3FFF, 0x4000, 0xFFFF, 12345):
            m = fresh(cmd_set_decay(2, x))
            m.step()
            assert m.voices[2].decay == x

    def test_u24_encoding(self):
        assert cmd_set_phase_inc(0, 0xABCDEF) == bytes((0x9C, 0x05, 0x2F, 0x1B, 0x6F))
        for x in (0, 1, 0x7F, 0x80, 0x3FFF, 0x4000, 0x1FFFFF, 0x200000, 0x800000, 0xFFFFFF):
            m = fresh(cmd_set_phase_inc(3, x))
            m.step()
            assert m.voices[3].inc == x

    def test_ignored_high_bits_are_masked(self):
        m = fresh(bytes((0x8C, 0x7E, 0x57, 0x4D)))     # bits 6:2 of the first data byte set
        m.step()
        assert m.voices[0].attack == 0xABCD
        m = fresh(bytes((0x88, 0x7F)))                 # SET_WAVE with 0x7F -> wave 3
        m.step()
        assert m.voices[0].wave == 3
        m = fresh(bytes((0x9C, 0x7D, 0x2F, 0x1B, 0x6F)))   # bits 6:3 set -> masked to 5
        m.step()
        assert m.voices[0].inc == 0xABCDEF

    def test_status_byte_discards_partial_command(self):
        m = SynthRef()
        m.feed(bytes((0x84, 0x45)))                    # NOTE_ON v0, one of two data bytes
        assert m.pending_commands == 0
        m.feed(cmd_note_off(2))                        # resync
        assert m.pending_commands == 1
        m.feed(bytes((0x7F,)))                         # stray data byte
        assert m.pending_commands == 1
        m.step()
        assert m.voices[0].state == ENV_IDLE           # the NOTE_ON never happened

    def test_unknown_opcode_swallows_data(self):
        unknown = 0x80 | (20 << 2) | 1
        m = SynthRef()
        m.feed(bytes((unknown, 0x01, 0x02, 0x03, 0x7F)))
        assert m.pending_commands == 0
        m.feed(cmd_note_on(0, 69, 127))
        assert m.pending_commands == 1
        m.step()
        assert m.voices[0].state == ENV_ATTACK and m.voices[0].inc == NOTE_INC[69]
        for op in range(9, 32):
            m2 = SynthRef()
            m2.feed(bytes((0x80 | (op << 2), 0x00, 0x00, 0x00, 0x00, 0x00)))
            assert m2.pending_commands == 0

    def test_stray_data_bytes_ignored_when_idle(self):
        m = SynthRef()
        m.feed(bytes(range(0x00, 0x80)))
        assert m.pending_commands == 0
        m.feed(cmd_note_off(0) + bytes((0x11, 0x22)))  # data after a complete 0-byte command
        assert m.pending_commands == 1

    def test_builders_validate(self):
        with pytest.raises(ValueError):
            cmd_note_on(4, 60, 100)
        with pytest.raises(ValueError):
            cmd_note_on(0, 128, 100)
        with pytest.raises(ValueError):
            cmd_note_on(0, 60, 128)
        with pytest.raises(ValueError):
            cmd_set_attack(0, 65536)
        with pytest.raises(ValueError):
            cmd_set_phase_inc(0, 1 << 24)
        with pytest.raises(ValueError):
            cmd_set_wave(0, 4)


# ============================================================================
# Reset (contract 9, 10.5)
# ============================================================================
RESET_VOICE = dict(phase=0, inc=0, wave=0, state=0, level=0, attack=2048, decay=256,
                   sustain=0xC000, release=128, velocity=0)


class TestReset:
    def test_power_on_state(self):
        m = SynthRef()
        for v in m.voices:
            assert asdict(v) == RESET_VOICE
        assert m.frame == 0 and m.pending_commands == 0
        assert not m.render(100).any()
        assert m.frame == 100

    def test_reset_method_restores_everything(self):
        m = fresh(cmd_set_wave(0, 3), cmd_set_adsr(1, 1, 2, 3, 4), cmd_note_on(2, 100, 99))
        m.render(500)
        m.feed(bytes((0x84, 0x45)))                    # leave a partial command in the parser
        m.feed(cmd_note_on(3, 50, 50))                 # and a pending one
        m.reset()
        for v in m.voices:
            assert asdict(v) == RESET_VOICE
        assert m.frame == 0 and m.pending_commands == 0
        m.feed(bytes((0x7F,)))                         # would complete the partial NOTE_ON if parser survived
        assert m.pending_commands == 0
        assert not m.render(100).any()

    def test_reset_command_mid_note(self):
        m = fresh(cmd_set_wave(0, WAVE_SAW), cmd_set_attack(0, 65535), cmd_note_on(0, 69, 127),
                  cmd_set_adsr(1, 9, 9, 9, 9))
        a = m.render(50)
        assert a.any()
        m.feed(cmd_reset())
        assert m.step() == 0
        for v in m.voices:
            assert asdict(v) == RESET_VOICE
        assert m.frame == 51                           # RESET does not touch the frame count
        assert not m.render(100).any()

    def test_commands_behind_reset_in_same_frame_still_apply(self):
        m = fresh(cmd_set_adsr(0, 9, 9, 9, 9) + cmd_reset() + cmd_note_on(0, 69, 127))
        m.step()
        v = m.voices[0]
        assert v.state == ENV_ATTACK and v.inc == NOTE_INC[69] and v.attack == 2048


# ============================================================================
# Determinism and golden regression
# ============================================================================
def golden_events():
    ev = [(0, cmd_set_wave(0, WAVE_SAW) + cmd_set_adsr(0, 4000, 300, 0x7000, 200)
              + cmd_set_wave(1, WAVE_SQUARE) + cmd_set_adsr(1, 8000, 64, 0x5000, 100)
              + cmd_set_wave(2, WAVE_TRI) + cmd_set_adsr(2, 48, 32, 0xB000, 40)
              + cmd_set_wave(3, WAVE_SINE) + cmd_set_adsr(3, 48, 32, 0xB000, 40)),
          (1, cmd_note_on(0, 64, 100) + cmd_note_on(1, 48, 70) + cmd_note_on(2, 52, 45) + cmd_note_on(3, 55, 45)),
          (3000, cmd_note_off(0)), (3500, cmd_note_on(0, 66, 110)),
          (6000, cmd_set_phase_inc(0, 0x7FFFFF)), (6500, cmd_note_on(0, 127, 127)),
          (7000, cmd_note_on(0, 0, 127) + cmd_set_wave(0, WAVE_SQUARE)),
          (9000, cmd_note_off(1) + cmd_note_off(2) + cmd_note_off(3)),
          (9500, cmd_note_on(1, 40, 127) + cmd_note_on(2, 40, 127) + cmd_note_on(3, 40, 127)
                 + cmd_set_attack(1, 65535) + cmd_set_attack(2, 65535) + cmd_set_attack(3, 65535)),
          (11000, cmd_reset()), (11001, cmd_note_on(2, 69, 127)),
          (12000, bytes((0x84, 0x45)) + cmd_note_off(2)),  # partial command then resync
          ]
    return ev


class TestGolden:
    def test_deterministic(self):
        a = SynthRef().render_script(golden_events(), 14000)
        b = SynthRef().render_script(golden_events(), 14000)
        assert np.array_equal(a, b)

    def test_golden_script_hash(self):
        a = SynthRef().render_script(golden_events(), 14000)
        assert a.min() == SAMPLE_MIN and a.max() == SAMPLE_MAX, "golden script should exercise both limits"
        h = hashlib.sha256(a.astype("<i2").tobytes()).hexdigest()
        assert h == FROZEN["golden_script_sha256"], f"golden render hash is {h}"
