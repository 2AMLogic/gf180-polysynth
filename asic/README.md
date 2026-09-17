# asic — the gf180mcu flow, and the fact that it has never run

> **Status: UNTESTED ON gf180mcu. Nothing in this directory has produced a
> single gf180mcu artifact.** No synthesis, no floorplan, no route, no GDS,
> no DRC, no LVS, no STA, no ERC. There is no `.klt/` output to look at
> because no run has ever completed. **Running this flow for the first time
> is this block's first work item**, and until it does, every number about
> this block's physical implementation belongs to a different PDK.

This is the graded leg — see
[`spec/decision-records/0001-pdk-selection-gf180mcu.md`](../spec/decision-records/0001-pdk-selection-gf180mcu.md).
`fpga/` is a demonstration and may never be cited as evidence for anything
here.

## What is in here

| File | Verb | Notes |
|---|---|---|
| `synthesize-polysynth.json` | `klt synthesize` | Yosys against `gf180mcu_fd_sc_mcu9t5v0`, corner `tt_025C_5v00`, 81.38 ns clock (12.288 MHz). |
| `par-polysynth.json` | `klt place-and-route` | floorplan → place → CTS → route, **with a `power` block** (see below). |
| `sta-polysynth.json` | `klt sta` | standalone OpenSTA over the routed DEF, nominal corner, 5 ns IO delays. |
| `lvs-polysynth.json` | `klt lvs` | abstracted layout netlist vs the as-built gate-level Verilog. |
| `run-signoff.sh` | — | drc → extract → lvs → sta over a routed GDS. Refuses to start on a 3LM/4LM PDK variant. |

## Cold start

```bash
# A 5LM gf180mcu install. gf180mcuA is 3LM and gf180mcuB is 4LM; both ship a
# complete gf180mcu_fd_sc_mcu9t5v0 liberty/LEF set and both fail this design.
volare enable --pdk gf180mcu <version-hash>
export PDK_ROOT=~/.volare PDK=gf180mcuC

cd asic
klt synthesize synthesize-polysynth.json --format json
klt place-and-route par-polysynth.json --format json     # prints gds_path
./run-signoff.sh <gds_path>
```

## Two things this configuration gets right on purpose

### 1. The `power` block is mandatory, and it is not optional prose

The prototype shipped a place-and-route request with **no `power` block** and
produced a routed layout with **no power grid at all**: no `tapcell`, no
`pdngen`, no filler cells, no `add_global_connection`. sky130's deck reported
that layout DRC-clean. It was not a good layout; it was a layout whose
defects that deck does not look for.

On gf180mcu the same omission is caught: klayout-tools' own gf180mcu
place-and-route run records that a routed GDS produced *without*
`request.power` fails `klt drc --deck gf180mcu` with **19 `nwell.space.1`
violations**, every one an identical 0.260 µm horizontal nwell gap — unfilled
standard-cell row gaps — and that the same design *with* `request.power`
routes just as cleanly and comes back DRC-clean with 0 violations. That
contrast is half of why decision record 0001 picked this PDK.

So `par-polysynth.json` carries a `power` block, and its strap geometry is not
invented. It is ORFS's own
`flow/platforms/gf180/openROAD/pdn/pdn_grid_strategy_9t_6M.cfg`, transcribed
field for field:

| ORFS line | Request field |
|---|---|
| `add_pdn_stripe -layer {Metal1} -width {0.900} -pitch {5.040} -offset {0} -followpins` | `straps[0]` |
| `add_pdn_stripe -layer {Metal4} -width {4.480} -spacing {0.56} -pitch {44.8} -offset {22.4}` | `straps[1]` |
| `add_pdn_stripe -layer {Metal5} -width {4.480} -pitch {89.6} -offset {44.8}` | `straps[2]` |
| `add_pdn_connect -layers {Metal1 Metal4} -max_columns {5} -ongrid {Metal2 Metal3 Metal4} -split_cuts {Metal3 0.128}` | `connects[0]` |
| `add_pdn_connect -layers {Metal4 Metal5}` | `connects[1]` |

`tapcell` masters come from the same platform's `tapcell.tcl` /`config.mk`
(`gf180mcu_fd_sc_mcu9t5v0__filltie` / `__endcap`, `-distance 100`) and are
chosen by `klt` from the `cell_library` name, so they are not restated here.

**Caveat, stated because it is load-bearing:** the Metal4 pitch is 44.8 µm and
the Metal5 pitch is 89.6 µm. A small die gets very few vertical straps, or
none. If the first real floorplan comes out under roughly 90 µm on a side,
this geometry needs revisiting — and that revisit is a measurement, not a
guess, so it waits for the first run.

### 2. Nothing here was produced by search-and-replacing the sky130 request

Every PDK-specific value is gf180mcu's own, taken from gf180mcu platform data
rather than translated from the sky130 equivalent:

| | sky130 prototype | this configuration | source |
|---|---|---|---|
| Cell library | `sky130_fd_sc_hd` | `gf180mcu_fd_sc_mcu9t5v0` | 9-track, 5 V |
| Liberty corner | `tt_025C_1v80` | `tt_025C_5v00` | ORFS `flow/platforms/gf180/lib/` |
| Floorplan site | `unithd` | `GF018hv5v_green_sc9` | ORFS `config.mk`, `PLACE_SITE` for `TRACK_OPTION = 9t` |
| IO layers (h/v) | `met3`/`met2` | `Metal3`/`Metal4` | ORFS `config.mk`, `IO_PLACER_H`/`_V` |
| Signal routing range | `met1`–`met4` | `Metal2`–`Metal5` | `klt place-and-route`'s own gf180mcu range |
| DRC deck | `sky130` | `gf180mcu` | `klt drc --deck` |
| Abstracted cells | `sky130_fd_sc_hd__*` | `gf180mcu_fd_sc_mcu9t5v0__*` | — |

## What *has* been checked here

Exactly one thing, and it is small. On a host with **no gf180mcu install**,
`klt synthesize synthesize-polysynth.json` parses the document, accepts every
field, and fails at liberty resolution with:

```
liberty not found for deck: standard-cell library 'gf180mcu_fd_sc_mcu9t5v0'
not found under resolved PDK install 'sky130A' at '<PDK_ROOT>'
```

That is the failure of a well-formed request meeting a missing PDK — it says
the schema and field names are right and nothing more. It is **not** evidence
that the floorplan is legal, that the design routes, that the strap geometry
fits, or that the corner name exists in the installed liberty set. The other
three request documents have not been executed at all.

## Antenna/ERC: the missing spec document

`klt erc` needs a stackup spec document naming the gate layer, each conductor
level and the vias between them, by GDS layer/datatype. This repository does
not ship one, because two of its entries cannot be written honestly without
reading the installed PDK.

The BEOL half **is** known — klayout-tools' curated gf180mcu stack-up,
transcribed from open_pdks' `libs.tech/magic/<variant>-GDS.tech` `calma`
statements:

| Level | LEF layer | GDS |
|---|---|---|
| met1 | `Metal1` | `34/0` |
| via1 | `Via1` | `35/0` |
| met2 | `Metal2` | `36/0` |
| via2 | `Via2` | `38/0` |
| met3 | `Metal3` | `42/0` |
| via3 | `Via3` | `40/0` |
| met4 | `Metal4` | `46/0` |
| via4 | `Via4` | `41/0` |
| met5 | `Metal5` | `81/0` |

The FEOL half — the `role: "gate"` poly layer that must be `stackup[0]`, its
optional `active_layer`, and the poly/diffusion-to-Metal1 contact cut — is
**not** written down here, because no source consulted states them with the
same confidence. Read them out of `$PDK_ROOT/$PDK/libs.tech/magic/<variant>-GDS.tech`
(the `calma` lines) on the actual install and add the spec file then, with a
note recording where the values came from. Inventing two layer numbers to
make a JSON file look complete is exactly the failure mode this repository
exists to avoid.

For context on what ERC would be looking for: the prototype's sky130 ERC run
found `erc_finding_count: 0` but **6 of 9434 gates violating the li1 antenna
ratio** (81–87 against a limit of 75), all on the tie-high net where the tie
cells' outputs fan out over a long low-level interconnect. That is a real
defect class this design has already demonstrated once, on a different node,
and nothing about the gf180mcu run is expected to make it go away by itself.

## Known upstream gap, from the prototype

`klt lvs` needs a SPICE reference netlist, and nothing in `klt` converts
`klt place-and-route`'s own as-built `verilog_path` into one — the prototype
worked around it by extracting the layout with `--abstract-cells` and pointing
`reference.form: "gate-level-verilog"` at the as-built netlist, which is what
`lvs-polysynth.json` does. Tracked upstream as klayout-tools#1336. Per the
friction protocol in `CLAUDE.md`, any *new* awkwardness found on the first
real run goes upstream as a generic tool-gap issue at
`2AMLogic/klayout-tools`, describing the gap and not this design.
