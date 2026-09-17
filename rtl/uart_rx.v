// uart_rx.v -- 8N1 receiver, RX only, idle high, LSB first.  Bytes with a
// bad stop bit (framing error) are dropped (contract 10.1).  Output is a
// one-cycle `valid` strobe with `data`, synchronous to clk.
`default_nettype none
module uart_rx #(
    parameter integer CLKS_PER_BIT = 107      // 12.288 MHz / 115200 = 106.67
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       rx,
    output reg        valid,
    output reg  [7:0] data
);
    localparam integer CW = $clog2(CLKS_PER_BIT);
    localparam integer FULL_I = CLKS_PER_BIT - 1;
`ifdef INJECT_BUG_UART
    localparam integer HALF_I = CLKS_PER_BIT - 1;   // BUG: samples at the bit edge instead of mid-bit
`else
    localparam integer HALF_I = CLKS_PER_BIT / 2 - 1;
`endif
    localparam [CW-1:0] FULL_M1 = FULL_I[CW-1:0];
    localparam [CW-1:0] HALF_M1 = HALF_I[CW-1:0];
    localparam [1:0] S_IDLE = 2'd0, S_START = 2'd1, S_DATA = 2'd2, S_STOP = 2'd3;

    reg [2:0]    sync;                         // 2-FF synchroniser + previous sample
    wire         rxs     = sync[1];
    wire         rx_fall = sync[2] & ~sync[1]; // start bit = falling edge (a line held low after a
                                               // framing error does not restart reception)
    reg [1:0]    st;
    reg [CW-1:0] cnt;
    reg [2:0]    bit_idx;
    reg [7:0]    shift;

    always @(posedge clk) begin
        if (!rst_n) begin
            sync    <= 3'b111;
            st      <= S_IDLE;
            cnt     <= {CW{1'b0}};
            bit_idx <= 3'd0;
            shift   <= 8'd0;
            valid   <= 1'b0;
            data    <= 8'd0;
        end else begin
            sync  <= {sync[1:0], rx};
            valid <= 1'b0;
            case (st)
                S_IDLE: begin
                    cnt <= {CW{1'b0}};
                    if (rx_fall) st <= S_START;
                end
                S_START: begin                         // wait to the middle of the start bit
                    if (cnt == HALF_M1) begin
                        cnt     <= {CW{1'b0}};
                        bit_idx <= 3'd0;
                        st      <= rxs ? S_IDLE : S_DATA; // glitch: not a real start bit
                    end else
                        cnt <= cnt + {{(CW-1){1'b0}}, 1'b1};
                end
                S_DATA: begin                          // sample each data bit one bit-time later
                    if (cnt == FULL_M1) begin
                        cnt   <= {CW{1'b0}};
                        shift <= {rxs, shift[7:1]};
                        if (bit_idx == 3'd7) st <= S_STOP;
                        else bit_idx <= bit_idx + 3'd1;
                    end else
                        cnt <= cnt + {{(CW-1){1'b0}}, 1'b1};
                end
                default: begin                         // S_STOP: stop bit must be 1
                    if (cnt == FULL_M1) begin
                        cnt <= {CW{1'b0}};
                        st  <= S_IDLE;
                        if (rxs) begin
                            valid <= 1'b1;
                            data  <= shift;
                        end
                    end else
                        cnt <= cnt + {{(CW-1){1'b0}}, 1'b1};
                end
            endcase
        end
    end
endmodule
`default_nettype wire
