# ECP5 build for the synth core. Never programs a board -- it stops at a
# bitstream file. Tools come from $PATH by default (an OSS CAD Suite install,
# or distro yosys/nextpnr-ecp5/prjtrellis); point TOOLS at a bin directory to
# use a specific install:
#
#   make build                                   # tools on $PATH
#   make build TOOLS=/path/to/oss-cad-suite/bin
TOOLS ?=
BIN := $(if $(TOOLS),$(TOOLS)/,)
RTL := ../rtl
SRCS := top.v pll.v i2s_tx.v $(RTL)/uart_rx.v $(RTL)/synth_voice.v $(RTL)/synth_core.v

build: bitstream.bit

bitstream.json: $(SRCS)
	$(BIN)yosys -q -l synth.log -p 'read_verilog -I$(RTL) $(SRCS); synth_ecp5 -top top -json $@'

bitstream.config: bitstream.json icepi-zero.lpf
	$(BIN)nextpnr-ecp5 --25k --package CABGA256 --lpf icepi-zero.lpf --json $< --textcfg $@ --log pnr.log

bitstream.bit: bitstream.config
	$(BIN)ecppack --compress $< $@

clean:
	rm -f bitstream.bit bitstream.config bitstream.json synth.log pnr.log

.PHONY: build clean
