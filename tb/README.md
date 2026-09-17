# tb — the cocotb testbench

`test_synth_core.py` drives `rtl/synth_core.v` and compares **every output
sample against `spec/reference/synth_ref.py` with no tolerance**. That
comparison is the whole verification claim: "the RTL is correct" means this
bench passed, on a named engine, at a named commit, and nothing more.

## Two ways to run it, same testbench

**Through `klt` (the evidence-producing path).** One request document per
run under `runs/`; `klt functional-verification` emits a JSON report that a
`sim/` evidence record cites. The testbench imports the reference model, and
the request document has no field for a Python path, so `spec/reference/`
must be on `PYTHONPATH`:

```bash
export PYTHONPATH="$PWD/spec/reference:${PYTHONPATH:-}"
(cd tb/runs/verilator && klt functional-verification request.json --format json)
(cd tb/runs/icarus    && klt functional-verification request.json --format json)
```

`tb/run_tb.py` sets that itself, which is one reason it is the easier path.

**Through `tb/run_tb.py` (the PDK-free path).** The same sources, the same
testbench, driven straight through cocotb's own runner — needs only
`iverilog`/`verilator` and `pip install cocotb`, no klayout-tools and no PDK.
This is what CI runs. It produces **no evidence record**.

```bash
python3 tb/run_tb.py --sim icarus
python3 tb/run_tb.py --sim verilator --nv 4
```

`run_tb.py` reads the results XML and turns it into an exit status. cocotb's
runner does not do that by itself — without it, an injected-bug run would
exit 0 with eleven failures and a green CI would mean nothing.

Its three exit codes are **not** interchangeable, and anything asserting that
a run should fail must require exactly `1`:

| Exit | Meaning |
|---|---|
| `0` | every test passed |
| `1` | the suite ran and at least one test failed |
| `2` | the suite did not run — build error, simulator launch failure, no results XML, or an XML with no tests in it |

The distinction is not hypothetical. cocotb 2.1's runner ends
`_set_env_common()` with `self.env["PYTHONPATH"] = os.pathsep.join(sys.path)`,
which runs *after* `self.env = dict(extra_env)` in `test()` — so a
`PYTHONPATH` passed as `extra_env` is silently discarded. Until that was
found, this suite died at `import synth_ref` before executing a single test
on any machine that did not already export `PYTHONPATH`, which is to say on
CI. `run_tb.py` now puts `spec/reference` and `tb/` on its own `sys.path`,
which is what actually reaches the simulator's embedded interpreter.

## What the 12 tests cover

Reset silence; NOTE_ON with the default ADSR through attack/decay/sustain/
release; a fast ADSR crossing every transition (note-off mid-attack, retrigger
while sounding, note-on during release, note-off in release); envelope corners
(sustain 65535 → one-update decay, rate 0 holds, sustain raised mid-decay
jumps up, `SET_SUSTAIN` in SUSTAIN does not move, velocity 0 and 1, RESET
mid-note); parser rules (unknown opcode swallows its data, a status byte
abandons a partial command, stray data dropped, several commands in one frame
applied in order, RESET with commands queued behind it, voice bits on RESET
ignored); `SET_PHASE_INC` corners (0, Nyquist, all-ones, 1) and NOTE_ON over
the whole note table; a 3000-frame PRNG command stream with junk bytes;
cycle-exact frame-boundary command placement; the UART bit-banged at 107
clocks/bit with ±2 % baud error and a framing-error byte dropped; the exact
DECAY→SUSTAIN boundary; two voices with mixer saturation at both limits; and
all four waveforms including every sine-table index.

## Measured, in this repository

`python3 tb/run_tb.py`, Apple M5 / macOS 26.5.1, Icarus 14.0 (devel),
Verilator 5.053 (devel), cocotb 2.1.0:

| `NV` | Icarus | Verilator |
|---|---|---|
| 1 | 12/12 | 12/12 |
| 2 (RTL default) | 12/12 | 12/12 |
| 4 (contract voice count) | 12/12 | 12/12 |

At `NV = 1` the two-voice test passes with its body skipped (it logs
`NV < 2: skipping two-voice test body`) — it is a trivial pass at that
parameter, not additional coverage.

## The negative controls

A suite that passes proves nothing until you have watched it fail. Each
`runs/bug-*/request.json` re-runs the identical bench with one `INJECT_BUG_*`
define, and each must **fail**:

```bash
for b in GAIN TICK UART ENV; do
  python3 tb/run_tb.py --sim icarus --define INJECT_BUG_$b=1 && rc=0 || rc=$?
  case "$rc" in
    1) echo "caught $b" ;;
    0) echo "SURVIVED: $b" ;;
    *) echo "NO VERDICT for $b (exit $rc): the suite did not run" ;;
  esac
done
```

Do not shorten that to `|| echo "caught $b"`. Any non-zero status would then
read as a catch, including the exit-2 cases where nothing was tested — which
is precisely how CI reported all four bugs caught, in half a second each,
while the suite was failing to start.

| Define | The bug | Verified here (Icarus, `NV` default) |
|---|---|---|
| `INJECT_BUG_GAIN` | `g = (env*vel)>>7` off by one | exit 1, 11 of 12 tests fail |
| `INJECT_BUG_TICK` | compute edge moved to cycle 0, so a cycle-255 command applies a frame late | exit 1, only `test_frame_boundary_bytes` fails — exactly the intended signature |
| `INJECT_BUG_UART` | sample at the bit edge instead of mid-bit | exit 1, only `test_uart_rx` fails |
| `INJECT_BUG_ENV` | DECAY→SUSTAIN compare `<` instead of `<=` | exit 1, only `test_decay_exact_boundary` fails |

`INJECT_BUG_ENV` is the one worth reading about. On the prototype's first
bench it **survived** 9/9: its only observable effect is the state reading
DECAY instead of SUSTAIN for a single frame with an otherwise identical level
sequence, which reaches the samples only if a `SET_SUSTAIN`/`SET_DECAY` lands
in exactly that frame. `test_decay_exact_boundary` was written specifically to
find that frame, using the reference model to locate it. That is a finding
about the *bench*, not the RTL: a passing suite had a blind spot on a contract
sentence, and an injected bug is what exposed it.

`runs/mutations/request.json` is the same request with `klt
functional-verification --mutations`: on the prototype it proposed 4 mutants,
found all 4 valid, and **killed all 4 (score 1.00)**. That run has not been
repeated in this repository.
