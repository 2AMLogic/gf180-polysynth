#!/usr/bin/env bash
# Install the pinned OSS CAD Suite build into $1 (default: $HOME/oss-cad-suite)
# and put its bin/ on $GITHUB_PATH when running under Actions.
#
# The version is pinned, not floating, because the README's engine versions are
# part of its claims: "12/12 on Icarus 14.0 and Verilator 5.053". CI that ran a
# different Icarus or a different Verilator would be checking something other
# than what the evidence says. This tarball is where both of those versions
# come from.
#
# It also exists because ubuntu-latest's apt Verilator is 5.020 (2024-01-01),
# whose VerilatedVpi has neither doInertialPuts() nor evalNeeded(); cocotb
# 2.1.0's Verilator shim calls both, so `apt install verilator` cannot build
# this bench at all -- it dies in verilator.o with "is not a member of
# 'VerilatedVpi'".
set -euo pipefail

OSS_CAD_DATE="2026-09-16"
OSS_CAD_STAMP="20260916"
DEST="${1:-$HOME/oss-cad-suite}"

if [ -x "$DEST/bin/verilator" ]; then
  echo "oss-cad-suite already present at $DEST (cache hit)"
else
  url="https://github.com/YosysHQ/oss-cad-suite-build/releases/download/${OSS_CAD_DATE}/oss-cad-suite-linux-x64-${OSS_CAD_STAMP}.tgz"
  echo "downloading $url"
  mkdir -p "$(dirname "$DEST")"
  curl -fsSL "$url" -o /tmp/oss-cad-suite.tgz
  tar -xzf /tmp/oss-cad-suite.tgz -C "$(dirname "$DEST")"
  rm -f /tmp/oss-cad-suite.tgz
fi

if [ -n "${GITHUB_PATH:-}" ]; then
  echo "$DEST/bin" >> "$GITHUB_PATH"
fi

"$DEST/bin/verilator" --version
"$DEST/bin/iverilog" -V | head -1
