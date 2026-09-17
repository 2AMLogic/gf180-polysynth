// top.v -- Icepi Zero (ECP5 LFE5U-25F, CABGA256, board v1.3) wrapper:
// 50 MHz board clock -> PLL -> 12.288 MHz core clock, UART in from the FTDI
// (`usb_rx`), I2S out on the Raspberry Pi header's PCM pins, five status LEDs.
// The direct byte port is tied off -- it is a simulation-only interface.
//
// I2S is on the PCM pins so that a PCM5102A pHAT plugs straight onto the
// 40-pin header with no jumpers:
//
//   gpio[18] = site N4 = header pin 12 = BCM18 PCM_CLK  -> DAC BCK
//   gpio[19] = site E4 = header pin 35 = BCM19 PCM_FS   -> DAC LRCK
//   gpio[21] = site F2 = header pin 40 = BCM21 PCM_DOUT -> DAC DIN
//   gpio[20] = site F1 = header pin 38 = BCM20 PCM_DIN  (data INTO a Pi, not
//                                        used by a DAC) -- driven low
//
// Do not move these to gpio[0..2]: that is header 27/28/3, which is where a
// HAT's ID EEPROM (BCM0/BCM1 = ID_SD/ID_SC) and I2C1 SDA live. A pHAT with an
// ID EEPROM has those two lines wired to the EEPROM, so the clocks would be
// fighting it and no PCM pin would be driven at all.
//
// `make build PMOD_MCLK=1` additionally drives the 12.288 MHz master clock on
// `pi_sclk` (site G2 = header pin 23, BCM11) for a Digilent Pmod I2S2, whose
// CS4344 requires MCLK. The PCM5102A does not: it derives its clocks from
// BCLK with SCK tied low, which is how the pHAT is wired.
//
// LEDs (active high, schematic D1..D5):
//   led[0] heartbeat: frame counter bit 16 -> toggles every 1.365 s
//   led[1] UART byte received (held ~85 ms)
//   led[2] output sample non-zero (a note is sounding)
//   led[3] command FIFO overflow
//   led[4] PLL locked
`default_nettype none
module top (
    input  wire         clk,        // 50 MHz oscillator, site M1
    input  wire         usb_rx,     // FTDI TXD -> FPGA, site K16
    output wire [4:0]   led,
`ifdef PMOD_MCLK
    output wire         pi_sclk,    // 12.288 MHz MCLK for a Pmod I2S2 (header pin 23)
`endif
    output wire [21:18] gpio        // [18] BCLK, [19] LRCLK, [20] low, [21] SDATA
);
    wire clk12, locked;
    pll u_pll (.clkin(clk), .clkout0(clk12), .locked(locked));

    // power-on / PLL-lock reset, synchronous to clk12
    reg [7:0] por = 8'd0;
    wire rst_n = por[7];
    always @(posedge clk12) begin
        if (!locked) por <= 8'd0;
        else if (!por[7]) por <= por + 8'd1;
    end

    wire        sample_valid, frame_tick, uart_valid, fifo_ovf;
    wire [15:0] sample;
    wire [7:0]  uart_byte;
    synth_core #(.NV(4)) u_core (        // all four contract voices (trial1 built NV=1 on the FPGA)
        .clk(clk12), .rst_n(rst_n), .uart_rx(usb_rx),
        .cmd_valid(1'b0), .cmd_byte(8'd0),
        .frame_tick(frame_tick), .sample_valid(sample_valid), .sample(sample),
        .dbg_uart_valid(uart_valid), .dbg_uart_byte(uart_byte), .dbg_fifo_overflow(fifo_ovf));

    i2s_tx u_i2s (.clk(clk12), .rst_n(rst_n), .sample_valid(sample_valid), .sample(sample),
                  .bclk(gpio[18]), .lrclk(gpio[19]), .sdata(gpio[21]));
    assign gpio[20] = 1'b0;
`ifdef PMOD_MCLK
    assign pi_sclk = clk12;         // i2s mclk -> pi_sclk
`endif

    // LEDs: heartbeat (frame counter bit), UART activity, output non-silent, fifo overflow, lock
    reg [16:0] fcnt = 17'd0;
    reg        act = 1'b0;
    reg [19:0] act_hold = 20'd0;
    always @(posedge clk12) begin
        if (frame_tick) fcnt <= fcnt + 17'd1;
        if (uart_valid) act_hold <= 20'hFFFFF; else if (act_hold != 0) act_hold <= act_hold - 20'd1;
        act <= (act_hold != 0);
    end
    assign led = {locked, fifo_ovf, (sample != 16'd0), act, fcnt[16]};
endmodule
`default_nettype wire
