#!/usr/bin/env bash
# The lint the CI `lint` job runs. Runnable locally, identically:
#
#   bash .github/scripts/lint.sh
#
# Needs python3 and (for step 4) verilator. Needs no PDK and no klt.
set -uo pipefail
cd "$(dirname "$0")/../.."

fail=0
step() { echo; echo "=== $*"; }
bad()  { echo "FAIL: $*" >&2; fail=1; }

step "1. Python sources compile"
python3 -m compileall -q \
  tb/run_tb.py rtl/gen_tables.py bench/render.py \
  spec/reference/synth_ref.py spec/reference/test_synth_ref.py \
  spec/reference/render_wav.py || bad "python compile"

step "2. Every JSON document is well-formed"
while IFS= read -r f; do
  python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$f" \
    || bad "malformed JSON: $f"
done < <(git ls-files '*.json')

step "3. Shell scripts parse"
while IFS= read -r f; do
  bash -n "$f" || bad "shell syntax: $f"
done < <(git ls-files '*.sh')

step "4. RTL is Verilator -Wall lint-clean"
if command -v verilator > /dev/null; then
  verilator --lint-only -Wall -Irtl --top-module synth_core \
    rtl/uart_rx.v rtl/synth_voice.v rtl/synth_core.v || bad "verilator lint"
else
  echo "skipped: no verilator on PATH"
fi

step "5. Generated ROMs match the frozen contract tables"
# rtl/*.vh are generated from spec/reference/synth_ref.py. Regenerating must
# be a no-op, and each file's embedded sha256 must still be the one printed in
# the contract's Appendix A / B -- that is what stops the RTL's tables and the
# reference model's tables from silently diverging.
python3 rtl/gen_tables.py > /dev/null || bad "gen_tables.py"
git diff --quiet -- rtl/note_inc_rom.vh rtl/sine_q_rom.vh \
  || bad "rtl/*.vh differ after regeneration -- the committed ROMs are stale"
for h in e771e6b7b39d3941c471b772bfb5cdca398b78ee7fa964c3c90388d2cc888ba4 \
         72e3ab187d9c5e27be2a1dfbf209610aca3bf553eea8d15b0db53e05b240ef4f; do
  grep -q "$h" spec/NUMERIC-CONTRACT.md || bad "contract no longer states hash $h"
  grep -rq "$h" rtl/ || bad "no generated ROM carries hash $h"
done

step "6. No absolute host paths leaked into committed sources"
# The prototype this repo came from had host-bound absolute paths in three
# scripts; this is the check that stops them coming back.
#
# The pattern deliberately requires a character class after the prefix rather
# than matching the bare prefix: a bare-prefix pattern matches THIS FILE,
# since the pattern and the failure message both contain the prefix
# literally. A real leak is always a prefix followed by a user name.
if git ls-files \
   | xargs grep -lIE '/Users/[a-z]|/home/[a-z]+/dev' 2>/dev/null | grep . ; then
  bad "the files above contain an absolute host path"
fi

echo
if [ "$fail" -ne 0 ]; then echo "lint FAILED"; exit 1; fi
echo "lint OK"
