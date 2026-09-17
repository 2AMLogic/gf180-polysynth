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

Exit status is the test verdict: 0 all tests passed, non-zero otherwise.
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

    # synth_ref.py is the frozen reference model the testbench compares against
    # sample for sample; it lives with the contract it implements, in spec/.
    pythonpath = os.pathsep.join(
        [str(REFERENCE), str(TB)] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else [])
    )

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

    # cocotb's runner does NOT raise on a failing test -- it returns the
    # results XML and leaves the verdict to the caller. Reading it here is
    # what makes this script usable as a CI gate: without it, an injected-bug
    # run (see `--define INJECT_BUG_*`) would exit 0 with 11 failures, and a
    # green CI would mean nothing.
    num_tests, num_failed = get_results(Path(results_xml))
    print(f"{args.sim}: {num_tests - num_failed}/{num_tests} passed", file=sys.stderr)
    return 1 if (num_failed or num_tests == 0) else 0


if __name__ == "__main__":
    sys.exit(main())
