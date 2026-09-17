// top.v -- Icepi Zero (ECP5 LFE5U-25F) wrapper: 50 MHz -> PLL -> 12.288 MHz
// core clock, UART from the FTDI (usb_rx), I2S out on gpio[0..2], LEDs show
// activity.  The direct byte port is tied off (simulation-only).
`default_nettype none
module top (
    input  wire        clk,        // 50 MHz
    input  wire        usb_rx,     // FTDI -> FPGA
    output wire [4:0]  led,
    output wire [2:0]  gpio        // 0: BCLK, 1: LRCLK, 2: SDATA
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
    synth_core #(.NV(1)) u_core (
        .clk(clk12), .rst_n(rst_n), .uart_rx(usb_rx),
        .cmd_valid(1'b0), .cmd_byte(8'd0),
        .frame_tick(frame_tick), .sample_valid(sample_valid), .sample(sample),
        .dbg_uart_valid(uart_valid), .dbg_uart_byte(uart_byte), .dbg_fifo_overflow(fifo_ovf));

    i2s_tx u_i2s (.clk(clk12), .rst_n(rst_n), .sample_valid(sample_valid), .sample(sample),
                  .bclk(gpio[0]), .lrclk(gpio[1]), .sdata(gpio[2]));

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
