#!/usr/bin/env python3
"""PDK-free runner for the cocotb testbench.

`klt functional-verification` (the requests under `tb/runs/`) is the primary,
evidence-producing way to run this suite -- it is what `sim/` records cite.
This script is the *same* testbench driven straight through cocotb's own
runner, so CI and a cold-start contributor need only `iverilog` / `verilator`
and `pip install cocotb`, with no klayout-tools install and no PDK.

    python3 tb/run_tb.py                      # icarus
    python3 tb/run_tb.py --sim verilator
    python3 tb/run_tb.py --sim icarus --define INJECT_BUG_ENV=1   # expect FAIL

Exit status is the test verdict, and the two failure codes are not
interchangeable:

    0  every test passed
    1  the suite ran and at least one test failed
    2  the suite did not run -- no results XML, or it contains no tests

Anything that asserts a run *should* fail (the injected-bug negative controls)
must require 1, never merely non-zero: a build or import error also exits
non-zero while proving nothing.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RTL = ROOT / "rtl"
TB = ROOT / "tb"
REFERENCE = ROOT / "spec" / "reference"

SOURCES = [RTL / "uart_rx.v", RTL / "synth_voice.v", RTL / "synth_core.v"]
TOPLEVEL = "synth_core"
TIMESCALE = ("1ns", "1ps")

EXIT_OK = 0
EXIT_FAILED = 1          # the suite ran, tests failed
EXIT_DID_NOT_RUN = 2     # no verdict exists: build error, import error, empty XML


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sim", default="icarus", choices=["icarus", "verilator"])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument(
        "--nv",
        type=int,
        default=None,
        help="override synth_core's NV (voices instantiated); the testbench is told "
             "the same number via $SYNTH_NV so it never addresses a voice that is "
             "not there. Default: the RTL's own parameter default.",
)
    ap.add_argument(
        "--define",
        action="append",
        default=[],
        metavar="NAME[=VALUE]",
        help="Verilog `define passed to the build (repeatable).",
    )
    ap.add_argument("--testcase", default=None, help="run a single named test")
    ap.add_argument("--waves", action="store_true")
    args = ap.parse_args(argv)

    # Imported here so --help works without cocotb installed.
    from cocotb_tools.runner import get_results, get_runner

    defines: dict[str, object] = {}
    for item in args.define:
        name, _, value = item.partition("=")
        defines[name] = value or 1

    parameters: dict[str, object] = {}
    env_nv: dict[str, str] = {}
    if args.nv is not None:
        parameters["NV"] = args.nv
        env_nv["SYNTH_NV"] = str(args.nv)

    build_dir = TB / "sim_build" / args.sim
    runner = get_runner(args.sim)
    try:
        runner.build(
            verilog_sources=SOURCES,
            includes=[RTL],
            defines=defines,
            hdl_toplevel=TOPLEVEL,
            parameters=parameters,
            build_dir=build_dir,
            timescale=TIMESCALE,
            waves=args.waves,
            always=True,
        )
    except Exception as exc:                      # compile/elaborate failure
        # Not a verdict: nothing was tested. Distinguishing this from a real
        # test failure is the whole point of EXIT_DID_NOT_RUN.
        print(f"{args.sim}: the design did not build: {exc}", file=sys.stderr)
        return EXIT_DID_NOT_RUN

    # synth_ref.py is the frozen reference model the testbench compares against
    # sample for sample; it lives with the contract it implements, in spec/.
    #
    # These go on *this* process's sys.path, not just into extra_env, because
    # cocotb's runner overwrites PYTHONPATH rather than extending it:
    # `_set_env_common()` ends with
    #
    #     self.env["PYTHONPATH"] = os.pathsep.join(sys.path)
    #
    # which runs after `self.env = dict(extra_env)` in `test()`, so anything
    # passed as extra_env["PYTHONPATH"] is silently discarded. Putting the two
    # directories on sys.path here is what actually reaches the simulator's
    # embedded interpreter. extra_env keeps them too, so this still works if a
    # future cocotb merges instead of overwriting.
    #
    # Without this the suite does not fail -- it does not RUN, dying at
    # `import synth_ref` before a single test executes. That is a far more
    # dangerous mode than a red test (see the injected-bug job's comment).
    for path in (REFERENCE, TB):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))

    pythonpath = os.pathsep.join(
        [str(REFERENCE), str(TB)] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else [])
    )

    try:
        results_xml = runner.test(
            hdl_toplevel=TOPLEVEL,
            test_module="test_synth_core",
            test_dir=TB,
            build_dir=build_dir,
            seed=args.seed,
            timescale=TIMESCALE,
            testcase=args.testcase,
            waves=args.waves,
            parameters=parameters or None,
            extra_env={"PYTHONPATH": pythonpath, "PYTHONDONTWRITEBYTECODE": "1", **env_nv},
            results_xml=str(build_dir / "results.xml"),
        )
    except Exception as exc:                      # simulator could not be launched
        print(f"{args.sim}: the simulator did not run: {exc}", file=sys.stderr)
        return EXIT_DID_NOT_RUN

    # cocotb's runner does NOT raise on a failing test -- it returns the
    # results XML and leaves the verdict to the caller. Reading it here is
    # what makes this script usable as a CI gate: without it, an injected-bug
    # run (see `--define INJECT_BUG_*`) would exit 0 with 11 failures, and a
    # green CI would mean nothing.
    #
    # The two non-zero exits are deliberately DIFFERENT, and callers are meant
    # to tell them apart: EXIT_FAILED means the suite ran and reported
    # failures, EXIT_DID_NOT_RUN means no verdict exists at all. A caller that
    # treats "non-zero" as "the testbench caught it" -- which is exactly what
    # a negative control does -- passes for the wrong reason when the suite
    # cannot start.
    try:
        num_tests, num_failed = get_results(Path(results_xml))
    except (RuntimeError, OSError) as exc:
        print(f"{args.sim}: the suite produced no results: {exc}", file=sys.stderr)
        return EXIT_DID_NOT_RUN
    print(f"{args.sim}: {num_tests - num_failed}/{num_tests} passed", file=sys.stderr)
    if num_tests == 0:
        print(f"{args.sim}: results XML contains no tests", file=sys.stderr)
        return EXIT_DID_NOT_RUN
    return EXIT_FAILED if num_failed else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
