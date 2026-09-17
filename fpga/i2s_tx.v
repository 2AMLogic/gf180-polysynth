// i2s_tx.v -- I2S transmitter for a PCM5102A-class DAC. From the 12.288 MHz
// core clock: BCLK = clk/4 = 3.072 MHz (64 x fs), LRCLK = 48 kHz, one 16-bit
// sample MSB first, left-justified in a 32-bit slot, standard I2S one-BCLK
// delay after the LRCLK edge, same sample on both channels.
//
// `tb_i2s.v` decodes this the way a DAC does and is the only thing standing
// behind the file -- the cocotb bench's boundary is `synth_core`'s sample
// port, so nothing downstream of it is covered there. Two defects that the
// bench could not have seen were found here by that testbench, with no
// hardware; `INJECT_BUG_I2S` below reintroduces both so CI can watch the
// testbench catch them:
//
//  1. Loading the shifter on the FIRST BCLK of a slot puts the MSB out one
//     BCLK late -- the I2S delay bit is already produced by the last SDATA
//     update of the PREVIOUS slot, so the MSB lands two BCLKs after the
//     LRCLK edge. A DAC then reads every word shifted right by one with bit
//     15 = 0: negative samples come out positive, and a square wave becomes
//     near-DC. Loading at the LAST BCLK of the previous slot (which is where
//     the delay bit is output) is what puts the MSB on the first BCLK.
//  2. Latching a new sample per half-frame sends sample n on left and n+1 on
//     right. `cur` is taken once per LRCLK period so both channels carry the
//     same sample, as NUMERIC-CONTRACT section 11 describes.
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
    reg [15:0] held;                 // latest sample from the core (once per frame)
    reg [15:0] cur;                  // sample being sent this LRCLK period (L and R)
    reg [7:0]  cnt;                  // 256 clocks per LRCLK period; bit 1 = BCLK, bit 7 = LRCLK
    reg [31:0] shifter;
    assign bclk  = cnt[1];
    assign lrclk = cnt[7];           // low = left, high = right
    always @(posedge clk) begin
        if (!rst_n) begin
            held <= 16'd0; cur <= 16'd0; cnt <= 8'd0; shifter <= 32'd0; sdata <= 1'b0;
        end else begin
            if (sample_valid) held <= sample;
            cnt <= cnt + 8'd1;
            if (cnt[1:0] == 2'b11) begin                 // falling edge of BCLK: SDATA changes here
`ifdef INJECT_BUG_I2S
                // Negative control: late load (MSB one BCLK late) and a fresh
                // sample per half-frame (L = n, R = n+1). tb_i2s.v MUST fail.
                if (cnt[6:2] == 5'd0)
                    shifter <= {held, 16'd0};
                else
                    shifter <= {shifter[30:0], 1'b0};
                sdata <= (cnt[6:2] == 5'd0) ? 1'b0 : shifter[31];
`else
                if (cnt[6:2] == 5'd31) begin             // last BCLK of a slot = delay bit of the next slot
                    sdata <= 1'b0;
                    if (cnt[7]) begin                    // right slot ends: next LRCLK period, fresh sample
                        cur     <= held;
                        shifter <= {held, 16'd0};
                    end else                             // left slot ends: right repeats the same sample
                        shifter <= {cur, 16'd0};
                end else begin
                    sdata   <= shifter[31];
                    shifter <= {shifter[30:0], 1'b0};
                end
`endif
            end
        end
    end
endmodule
`default_nettype wire
