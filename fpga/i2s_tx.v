// i2s_tx.v -- minimal I2S transmitter for the PCM5102A: from the 12.288 MHz
// core clock, BCLK = clk/4 = 3.072 MHz (64 x fs), LRCLK = 48 kHz, 16-bit
// sample MSB first in a 32-bit slot, same sample on both channels, one BCLK
// delay after the LRCLK edge (standard I2S).  Informative section 11 only:
// not part of the numeric contract.
`default_nettype none
module i2s_tx (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        sample_valid,
    input  wire [15:0] sample,
    output wire        bclk,
    output wire        lrclk,
    output reg         sdata
);
    reg [15:0] held;                 // sample register, updated once per frame
    reg [7:0]  cnt;                  // 256 clocks per LRCLK period; bit 1 = BCLK, bit 7 = LRCLK
    reg [31:0] shifter;
    assign bclk  = cnt[1];
    assign lrclk = cnt[7];
    always @(posedge clk) begin
        if (!rst_n) begin
            held <= 16'd0; cnt <= 8'd0; shifter <= 32'd0; sdata <= 1'b0;
        end else begin
            if (sample_valid) held <= sample;
            cnt <= cnt + 8'd1;
            if (cnt[1:0] == 2'b11) begin                 // falling edge of BCLK: update SDATA
                if (cnt[6:2] == 5'd0)                    // first BCLK of a channel slot: load (1-bit I2S delay)
                    shifter <= {held, 16'd0};
                else
                    shifter <= {shifter[30:0], 1'b0};
                sdata <= (cnt[6:2] == 5'd0) ? 1'b0 : shifter[31];
            end
        end
    end
endmodule
`default_nettype wire
