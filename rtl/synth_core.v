// synth_core.v -- top level of the hackathon synth core (NUMERIC-CONTRACT.md).
//
//   UART RX --+--> byte parser --> cmd FIFO --> apply (any cycle but the tick)
//   cmd port -+                                   |
//             voices[NV] (phase acc, square, ADSR, scaler) --> sum --> saturate --> sample
//
// Frame timing: `cyc` counts 0..255.  frame_tick is high during cycle 0.  The
// compute+advance edge ("tick" to the voices) is the END of cycle 1, so a
// command whose last byte was accepted in cycle 255 of frame n-1 (FIFO push at
// that edge, pop/apply at the end of cycle 0) is in the registers when sample n
// is computed, while a byte accepted in cycle 0 of frame n (pushed at the end
// of cycle 0) is held through the busy cycle and applied at the end of cycle 2,
// after the advance -- i.e. at the start of frame n+1 (contract 10.4).
// sample_valid strobes in cycle 5 of every frame with that frame's sample.
`default_nettype none
module synth_core #(
    parameter integer NV = 2,                 // voices implemented (contract has 4); base scope was 1
    parameter integer UART_CLKS_PER_BIT = 107
) (
    input  wire        clk,
    input  wire        rst_n,                 // synchronous, active low
    input  wire        uart_rx,               // 115200 8N1, idle high
    input  wire        cmd_valid,             // direct byte port (contract 12.2), wins over UART
    input  wire [7:0]  cmd_byte,
    output wire        frame_tick,            // high during cycle 0 of every frame
    output reg         sample_valid,          // one-cycle strobe, once per frame
    output reg  [15:0] sample,             // s16 two's complement (unsigned vector: OpenROAD rejects 'signed')
    output wire        dbg_uart_valid,        // UART receiver output (for the UART test)
    output wire [7:0]  dbg_uart_byte,
    output reg         dbg_fifo_overflow      // sticky: a complete command was dropped (never in normal use)
);
    // ---- frame counter ----------------------------------------------------------
    reg [7:0] cyc;
    assign frame_tick = (cyc == 8'd0);
`ifdef INJECT_BUG_TICK
    wire      tick    = (cyc == 8'd0);        // BUG: a command completed in cycle 255 is applied one frame late
`else
    wire      tick    = (cyc == 8'd1);        // compute + advance edge; no command applies here
`endif

    // ---- UART receiver + byte-port merge -----------------------------------------
    wire       rx_valid;
    wire [7:0] rx_byte;
    uart_rx #(.CLKS_PER_BIT(UART_CLKS_PER_BIT)) u_uart (
        .clk(clk), .rst_n(rst_n), .rx(uart_rx), .valid(rx_valid), .data(rx_byte));
    assign dbg_uart_valid = rx_valid;
    assign dbg_uart_byte  = rx_byte;

    wire       byte_valid = cmd_valid | rx_valid;
    wire [7:0] byte_in    = cmd_valid ? cmd_byte : rx_byte;

    // ---- byte parser (contract 10.2 - 10.4) ----------------------------------------
    // data bytes per opcode (10.3); 4'hF = unknown opcode.  (A Verilog function
    // here left a dangling X-assigned wire in the yosys netlist that OpenROAD
    // turned into an unroutable constant net -- hence a plain always @*.)
    reg [3:0] b_len;
    always @* begin
        case (byte_in[6:2])
            5'd0: b_len = 4'd0;  5'd1: b_len = 4'd2;  5'd2: b_len = 4'd1;
            5'd3: b_len = 4'd3;  5'd4: b_len = 4'd3;  5'd5: b_len = 4'd3;
            5'd6: b_len = 4'd3;  5'd7: b_len = 4'd4;  5'd8: b_len = 4'd0;
            default: b_len = 4'hF;
        endcase
    end

    reg        p_active;                      // a known command is in progress
    reg [4:0]  p_op;
    reg [1:0]  p_voice;
    reg [2:0]  p_need;                        // data bytes required
    reg [1:0]  p_have;                        // data bytes buffered so far
    reg [6:0]  p_s0, p_s1, p_s2;              // buffered data bytes (MSB chunk first)

    wire       is_status = byte_in[7];
    wire [4:0] b_op      = byte_in[6:2];
    wire       b_known   = (b_len != 4'hF);
    wire       complete_status = byte_valid &  is_status & b_known & (b_len == 4'd0);
    wire       complete_data   = byte_valid & ~is_status & p_active & ({1'b0, p_have} + 3'd1 == p_need);
    wire       cmd_push  = complete_status | complete_data;
    wire [4:0] c_op      = is_status ? b_op : p_op;
    wire [1:0] c_voice   = is_status ? byte_in[1:0] : p_voice;
    wire [6:0] c_s0      = (p_have == 2'd0) ? byte_in[6:0] : p_s0;
    wire [6:0] c_s1      = (p_have == 2'd1) ? byte_in[6:0] : p_s1;
    wire [6:0] c_s2      = (p_have == 2'd2) ? byte_in[6:0] : p_s2;
    wire [6:0] c_s3      = byte_in[6:0];

    always @(posedge clk) begin
        if (!rst_n) begin
            p_active <= 1'b0; p_op <= 5'd0; p_voice <= 2'd0; p_need <= 3'd0; p_have <= 2'd0;
            p_s0 <= 7'd0; p_s1 <= 7'd0; p_s2 <= 7'd0;
        end else if (byte_valid) begin
            if (is_status) begin                                  // rule 1-3: (re)start or discard
                if (b_known && b_len != 4'd0) begin
                    p_active <= 1'b1; p_op <= b_op; p_voice <= byte_in[1:0];
                    p_need <= b_len[2:0]; p_have <= 2'd0;
                end else
                    p_active <= 1'b0;                             // 0-data command (pushed) or unknown
            end else if (p_active) begin                          // rule 4
                case (p_have)
                    2'd0: p_s0 <= byte_in[6:0];
                    2'd1: p_s1 <= byte_in[6:0];
                    2'd2: p_s2 <= byte_in[6:0];
                    default: ;
                endcase
                if (complete_data) p_active <= 1'b0;
                else               p_have   <= p_have + 2'd1;
            end                                                   // rule 5: stray data dropped
        end
    end

    // ---- command FIFO (depth 8) ------------------------------------------------------
    // Entry: {op[4:0], voice[1:0], s0, s1, s2, s3} = 35 bits.
    reg [34:0] q_mem [0:7];
    reg [2:0]  q_wr, q_rd;
    reg [3:0]  q_cnt;
    wire       q_empty = (q_cnt == 4'd0);
    wire       q_full  = q_cnt[3];
    wire       q_push  = cmd_push & ~q_full;
    wire       q_pop   = ~q_empty & ~tick;
    wire [34:0] q_head = q_mem[q_rd];

    always @(posedge clk) begin
        if (!rst_n) begin
            q_wr <= 3'd0; q_rd <= 3'd0; q_cnt <= 4'd0; dbg_fifo_overflow <= 1'b0;
        end else begin
            if (q_push) begin
                q_mem[q_wr] <= {c_op, c_voice, c_s0, c_s1, c_s2, c_s3};
                q_wr <= q_wr + 3'd1;
            end
            if (q_pop) q_rd <= q_rd + 3'd1;
            case ({q_push, q_pop})
                2'b10:   q_cnt <= q_cnt + 4'd1;
                2'b01:   q_cnt <= q_cnt - 4'd1;
                default: ;
            endcase
            if (cmd_push & q_full) dbg_fifo_overflow <= 1'b1;
        end
    end

    wire        a_valid = q_pop;
    wire [4:0]  a_op    = q_head[34:30];
    wire [1:0]  a_voice = q_head[29:28];
    wire [6:0]  a_s0    = q_head[27:21];
    wire [6:0]  a_s1    = q_head[20:14];
    wire [6:0]  a_s2    = q_head[13:7];
    wire [6:0]  a_s3    = q_head[6:0];
    wire        a_reset = a_valid & (a_op == 5'd8);

    // ---- voices ------------------------------------------------------------------------
    wire        [15:0] v_out [0:NV-1];
    wire               v_valid [0:NV-1];
    genvar gi;
    generate
        for (gi = 0; gi < NV; gi = gi + 1) begin : g_voice
            wire hit = a_valid & ~a_reset & (a_voice == gi[1:0]);
            synth_voice u_voice (
                .clk(clk), .rst_n(rst_n), .tick(tick),
                .apply(hit), .op(a_op), .d0(a_s0), .d1(a_s1), .d2(a_s2), .d3(a_s3),
                .soft_reset(a_reset),
                .out(v_out[gi]), .out_valid(v_valid[gi]));
        end
    endgenerate

    // ---- mixer (contract 8): exact 18-bit sum, saturate to s16 --------------------------
    // fixed 4-input sum (contract 8; NV <= 4), voices beyond NV read as 0.
    // (An `integer` for-loop survived synthesis as a 32-bit tie-cell-fed wire,
    // and an unpacked-array accumulator chain trips Verilator's UNOPTFLAT.)
    wire [15:0] vo [0:3];
    generate
        for (gi = 0; gi < 4; gi = gi + 1) begin : g_pad
            if (gi < NV) begin : g_used
                assign vo[gi] = v_out[gi];
            end else begin : g_zero
                assign vo[gi] = 16'd0;
            end
        end
    endgenerate
    wire [17:0] mix = {{2{vo[0][15]}}, vo[0]} + {{2{vo[1][15]}}, vo[1]}
                    + {{2{vo[2][15]}}, vo[2]} + {{2{vo[3][15]}}, vo[3]};
    wire [15:0] mix_sat = ($signed(mix) > 18'sd32767)  ? 16'h7FFF :
                          ($signed(mix) < -18'sd32768) ? 16'h8000 : mix[15:0];

    always @(posedge clk) begin
        if (!rst_n) begin
            cyc          <= 8'd0;
            sample       <= 16'd0;
            sample_valid <= 1'b0;
        end else begin
            cyc          <= cyc + 8'd1;                            // wraps at 256
            sample_valid <= v_valid[0];
            if (v_valid[0]) sample <= mix_sat;
        end
    end
endmodule
`default_nettype wire
