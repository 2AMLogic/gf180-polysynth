#!/usr/bin/env bash
# Post-place-and-route signoff chain for the gf180mcu target:
#   drc -> extract (abstracted) -> lvs -> sta
#
# ##########################################################################
# # NOTHING BELOW HAS EVER BEEN RUN AGAINST gf180mcu. See asic/README.md.  #
# ##########################################################################
#
# Run from the asic/ directory, after `klt place-and-route par-polysynth.json`
# has produced a routed GDS. Requires a gf180mcu 5LM install (gf180mcuC or
# gf180mcuD -- NOT gf180mcuA, which is 3LM and cannot route this design) and
# an `openroad` reachable the way this repo's environment notes describe.
#
#   PDK_ROOT=<root> PDK=gf180mcuC ./run-signoff.sh <routed.gds>
#
# Exits non-zero if any stage fails. Each stage's JSON report is written to
# reports/ for copying into a sim/ evidence record -- this script produces
# reports, it does not mint records.
set -uo pipefail

GDS="${1:?usage: run-signoff.sh <routed.gds>   (klt place-and-route prints gds_path)}"
TOP=synth_core
LIB=gf180mcu_fd_sc_mcu9t5v0
OUT=reports
mkdir -p "$OUT"

: "${PDK_ROOT:?set PDK_ROOT to the directory holding the gf180mcu install}"
: "${PDK:?set PDK to a 5LM variant: gf180mcuC or gf180mcuD (gf180mcuA is 3LM and will fail in place)}"

case "$PDK" in
  gf180mcuC|gf180mcuD) ;;
  gf180mcuA|gf180mcuB)
    echo "refusing to run: PDK=$PDK is a ${PDK: -1}LM variant." >&2
    echo "This design routes Metal2-Metal5 and places IO on Metal3/Metal4;" >&2
    echo "a 3LM/4LM install fails in the place stage with PPL-0051." >&2
    exit 2 ;;
  *) echo "warning: PDK=$PDK is not a recognised gf180mcu variant name" >&2 ;;
esac

rc=0
# None of these verbs takes an --output flag -- the JSON report is stdout, so
# each stage redirects it. stderr is kept beside it; a failing stage's message
# is as much a part of the record as a passing stage's numbers.
stage() {  # stage <report-name> <command...>
  local name="$1"; shift
  local t0; t0=$(date +%s)
  echo "=== $name"
  if "$@" > "$OUT/$name.json" 2> "$OUT/$name.stderr"; then
    echo "--- $name ok ($(( $(date +%s) - t0 ))s)"
  else
    echo "--- $name FAILED ($(( $(date +%s) - t0 ))s); see $OUT/$name.stderr" >&2
    rc=1
  fi
}

stage drc klt drc "$GDS" --deck gf180mcu --top "$TOP" --format json

# Standard cells are abstracted rather than extracted device-by-device: the
# comparison that matters is instance-and-net level against the as-built
# gate-level netlist, and extracting every transistor in every cell is where
# the prototype's sky130 run spent 522 of its 623 signoff seconds.
stage extract klt extract "$GDS" --deck gf180mcu \
  --abstract-cells "${LIB}__*" --def-net-names \
  -o "${TOP}.gate.spice" --format json

stage lvs klt lvs lvs-polysynth.json --format json

stage sta klt sta sta-polysynth.json --format json

# ERC (antenna) is deliberately NOT run here: it needs a gf180mcu stackup
# spec document this repo does not ship, because two of its entries cannot be
# written honestly without reading the installed PDK. asic/README.md ->
# "Antenna/ERC: the missing spec document" has the verified BEOL half of the
# table and the exact file to read the FEOL half out of.

echo
echo "reports in $OUT/ -- copy them into a sim/ record; this script mints none."
exit "$rc"
