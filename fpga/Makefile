# ECP5 build for the synth core. Never programs a board -- it stops at a
# bitstream file. Tools come from $PATH by default (an OSS CAD Suite install,
# or distro yosys/nextpnr-ecp5/prjtrellis); point TOOLS at a bin directory to
# use a specific install:
#
#   make build                                   # tools on $PATH
#   make build TOOLS=/path/to/oss-cad-suite/bin
#   make build PMOD_MCLK=1                       # + MCLK on header 23 (Pmod I2S2)
#   make sim                                     # I2S testbench + negative control
TOOLS ?=
BIN := $(if $(TOOLS),$(TOOLS)/,)
RTL := ../rtl
SRCS := top.v pll.v i2s_tx.v $(RTL)/uart_rx.v $(RTL)/synth_voice.v $(RTL)/synth_core.v
DEFS := $(if $(PMOD_MCLK),-DPMOD_MCLK,)

build: bitstream.bit

bitstream.json: $(SRCS)
	$(BIN)yosys -q -l synth.log -p 'read_verilog $(DEFS) -I$(RTL) $(SRCS); synth_ecp5 -top top -json $@'

bitstream.config: bitstream.json icepi-zero.lpf
	$(BIN)nextpnr-ecp5 --25k --package CABGA256 --lpf icepi-zero.lpf --json $< --textcfg $@ --log pnr.log

bitstream.bit: bitstream.config
	$(BIN)ecppack --compress $< $@

# tb_i2s.v decodes SDATA the way a DAC does. `sim` must pass; `sim-negative`
# rebuilds i2s_tx.v with INJECT_BUG_I2S and must FAIL -- the same
# watch-it-fail discipline the cocotb bench's INJECT_BUG_* controls use.
# `sim-check` is what CI runs: it asserts both outcomes.
sim: tb_i2s.vvp
	$(BIN)vvp -n tb_i2s.vvp
tb_i2s.vvp: tb_i2s.v i2s_tx.v
	$(BIN)iverilog -g2012 -o $@ tb_i2s.v i2s_tx.v

sim-negative: tb_i2s_bug.vvp
	-$(BIN)vvp -n tb_i2s_bug.vvp
tb_i2s_bug.vvp: tb_i2s.v i2s_tx.v
	$(BIN)iverilog -g2012 -DINJECT_BUG_I2S=1 -o $@ tb_i2s.v i2s_tx.v

sim-check: tb_i2s.vvp tb_i2s_bug.vvp
	@$(BIN)vvp -n tb_i2s.vvp | tee sim.log | grep -q '^TB PASS' \
	  || { echo "FAIL: tb_i2s did not pass against the committed i2s_tx.v"; cat sim.log; exit 1; }
	@echo "ok: tb_i2s passes against the committed i2s_tx.v"
	@$(BIN)vvp -n tb_i2s_bug.vvp | tee sim_bug.log | grep -q '^TB FAIL' \
	  || { echo "FAIL: INJECT_BUG_I2S survived the testbench"; cat sim_bug.log; exit 1; }
	@echo "ok: tb_i2s catches INJECT_BUG_I2S"

clean:
	rm -f bitstream.bit bitstream.config bitstream.json synth.log pnr.log \
	      tb_i2s.vvp tb_i2s_bug.vvp sim.log sim_bug.log

.PHONY: build sim sim-negative sim-check clean
