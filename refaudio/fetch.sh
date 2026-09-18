#!/usr/bin/env bash
# Pull reference audio out of an archive on operator-side storage into
# refaudio/cache/ (gitignored). See refaudio/README.md.
#
#   refaudio/fetch.sh <archive.zip> '<path or glob inside the archive>'
#
# Needs REFAUDIO_SSH (user@host) and REFAUDIO_ROOT (library directory on that
# host) in the environment. Hosts without them cannot reach the storage: open
# a `reference-audio` issue instead.
set -euo pipefail

archive="${1:?usage: fetch.sh <archive.zip> '<path or glob inside the archive>'}"
member="${2:?usage: fetch.sh <archive.zip> '<path or glob inside the archive>'}"
: "${REFAUDIO_SSH:?REFAUDIO_SSH is not set - this host has no route to the reference-audio storage; open a reference-audio issue instead}"
: "${REFAUDIO_ROOT:?REFAUDIO_ROOT is not set - see refaudio/README.md}"

case "$archive" in */*|*..*) echo "archive must be a bare file name from the catalog" >&2; exit 2 ;; esac

here="$(cd "$(dirname "$0")" && pwd)"
dest="$here/cache/${archive%.zip}"
mkdir -p "$dest"

# Stream the selected members as a tar so nested paths survive; the remote side
# unpacks into a throwaway directory and removes it afterwards.
q() { printf "%q" "$1"; }
ssh -o BatchMode=yes -o ConnectTimeout=10 "$REFAUDIO_SSH" "
  set -e
  t=\$(mktemp -d)
  trap 'rm -rf \"\$t\"' EXIT
  unzip -q -o $(q "$REFAUDIO_ROOT")/packs/$(q "$archive") $(q "$member") -d \"\$t\"
  tar -C \"\$t\" -cf - .
" | tar -C "$dest" -xf -

echo "refaudio/cache/${archive%.zip}: $(find "$dest" -type f | wc -l | tr -d ' ') file(s)"
