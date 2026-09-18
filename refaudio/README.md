# refaudio — reference audio available to this project

A catalog of recorded reference material — classic synthesizers, samplers and
drum machines — that this project can draw on for **training and verifying the
design**: fitting voice parameters against real instruments, and checking what
the synthesizer produces against recordings of the machines it is modelled on.

**This directory holds the index, not the audio.** The recordings live on
operator-side storage; what is committed here is the list of what exists, so
that anyone working in this repo (agent or human) can find a recording and ask
for it by name.

## Status — the honesty rule applies here too

Nothing in this directory is evidence, and **no claim in this repository rests
on any of these recordings yet.** No sample has been used to fit, train or
verify anything. The frozen numeric contract (`spec/NUMERIC-CONTRACT.md`) and
its bit-exact reference model remain the only thing the RTL is verified
against. When a recording *is* used for a result, that result goes under
`sim/` or `measurements/` as a record in the usual way, naming the archive and
path it used.

## What is here

| File | What it is |
|---|---|
| [`CATALOG.md`](CATALOG.md) | Every pack, grouped by category, with source instrument, WAV count, hours, format, archive name |
| `catalog.json` | The same, machine-readable, plus per-pack detail: folder breakdown, sample-rate and bit-depth histograms, the pack's own notes on naming conventions, archive SHA-256 |
| `wav-index.tsv.gz` | All 172,182 WAV files in one table: `archive, path, bytes, sample_rate, bits, channels, seconds` |
| `fetch.sh` | Pulls one file (or one folder) out of an archive into `refaudio/cache/` |
| `cache/` | Where fetched audio lands. **Gitignored** — audio is working material, never a committed artifact |

89 packs, ~121 hours. Almost everything is 44.1 kHz; 154k files are 24-bit and
18k are 16-bit. This project renders at 48 kHz, so resample deliberately and
say so in any record that depends on it.

Most relevant to a subtractive/FM polysynth: the **synth** category (SH-101,
ARP 2600, Minimoog, Micromoog, Juno-60/106, MS-10, SH-5, System-100M, OB-SX,
Voyetra, Wasp, SID, DX100, VP-330, ARP Omni, Soviet synths) — multisampled
per patch across the keyboard, which is what parameter fitting wants.

`source` in the catalog comes from the pack's own notes where it has them and
is otherwise inferred from folder names (`source_basis` says which). Good for
browsing; verify before citing.

## Finding a recording

```sh
# every SID-chip WAV shorter than 2 s
gzcat refaudio/wav-index.tsv.gz | awk -F'\t' '$1=="sid_from_mars.zip" && $7<2'

# which packs contain anything Juno
gzcat refaudio/wav-index.tsv.gz | grep -i juno | cut -f1 | sort | uniq -c

# synth packs, from the JSON
jq -r '.packs[] | select(.category=="synth") | [.archive,.source,.wav_count] | @tsv' refaudio/catalog.json
```

Most packs repeat their samples in sampler-specific folders (Kontakt,
Maschine, MPC, Ableton…). The pack's `WAV/` folder is the canonical set.

## Requesting a recording

**On a host that can reach the storage** (the environment provides
`REFAUDIO_SSH` and `REFAUDIO_ROOT`):

```sh
refaudio/fetch.sh sid_from_mars.zip 'Sid From Mars/WAV/<path from the index>.wav'
refaudio/fetch.sh sid_from_mars.zip 'Sid From Mars/WAV/*'      # a whole folder
```

Files land under `refaudio/cache/<archive>/…`, which git ignores.

**Anywhere else** (including most fleet hosts): open an issue in this repo
labelled `reference-audio` that names the archive and path(s) from the index
and says what you need from them — the audio itself, or a measurement of it
(spectrum, envelope, tuning, harmonic levels). A host with access fulfils it.
Asking for the measurement rather than the file is usually the faster route.

## Rules

- Audio never gets committed. `refaudio/cache/` is ignored; keep it that way,
  and do not copy recordings elsewhere in the tree.
- A result that used a recording names it (`archive` + `path`), so it can be
  reproduced.
- This index is regenerated from the archives themselves, not edited by hand.
