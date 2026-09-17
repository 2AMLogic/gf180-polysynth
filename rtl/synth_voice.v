// synth_voice.v -- one voice of the synth core (NUMERIC-CONTRACT.md sections
// 5, 6, 7, 9, 10.5).  Base scope: SQUARE wave only; the `wave` register is
// written by SET_WAVE but every wave renders as square (documented limit).
//
// Frame protocol (driven by synth_core):
//   tick        one cycle per frame: latch osc/env/vel from the CURRENT registers
//               (step 2 of contract 4.2) and advance phase + envelope (step 3),
//               all at the same clock edge.
//   apply       a complete command addressed to this voice is applied at this
//               edge (step 1 of the NEXT frame).  synth_core never asserts
//               apply and tick in the same cycle; if it did, the NBA order below
//               ("advance, then command") is the contract's order anyway.
//   soft_reset  RESET command: every voice register to its reset value.
//   out/out_valid  the voice's s16 output, 3 cycles after tick.
`default_nettype none
module synth_voice (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        tick,
    input  wire        apply,
    input  wire [4:0]  op,
    input  wire [6:0]  d0,
    input  wire [6:0]  d1,
    input  wire [6:0]  d2,
    input  wire [6:0]  d3,
    input  wire        soft_reset,
    output reg  [15:0] out,          // s16 (declared unsigned: OpenROAD's reader rejects 'signed')
    output reg         out_valid
);
    localparam [4:0] OP_NOTE_OFF = 5'd0, OP_NOTE_ON = 5'd1, OP_SET_WAVE = 5'd2,
                     OP_SET_ATTACK = 5'd3, OP_SET_DECAY = 5'd4, OP_SET_SUSTAIN = 5'd5,
                     OP_SET_RELEASE = 5'd6, OP_SET_PHASE_INC = 5'd7;
    localparam [2:0] ST_IDLE = 3'd0, ST_ATTACK = 3'd1, ST_DECAY = 3'd2, ST_SUSTAIN = 3'd3, ST_RELEASE = 3'd4;
    localparam [19:0] LEVEL_MAX = 20'hFFFF0;
    // reset values (contract section 9)
    localparam [15:0] DEF_ATTACK = 16'd2048, DEF_DECAY = 16'd256, DEF_SUSTAIN = 16'hC000, DEF_RELEASE = 16'd128;


    // ---- registers (contract 5.1, 6.2) ----------------------------------------
    reg [23:0] phase;
    reg [23:0] inc;
    reg [1:0]  wave;
    reg [2:0]  state;
    reg [19:0] level;
    reg [15:0] attack, decay, sustain, release_r;
    reg [6:0]  velocity;

    // ---- oscillator from the phase BEFORE advance (5.4, bit-level forms) ------
    // All s16 values are carried in unsigned vectors; the only signed operations
    // are the product and the mixer compare, which use $signed() explicitly.
    wire [15:0] osc_square = phase[23] ? 16'h8000 : 16'h7FFF;
    wire [15:0] osc_saw    = {~phase[23], phase[22:8]};                 // (p >> 8) - 32768
    wire [15:0] tri_q      = phase[23] ? ~phase[22:7] : phase[22:7];
    wire [15:0] osc_tri    = {~tri_q[15], tri_q[14:0]};                 // q - 32768 | 98303 - q
    // sine: i = phase[23:14]; T[i] = Q[i[7:0]] (quadrant 0), Q[256 - i[7:0]] (quadrant 1), -T[i-512] (i[9])
    wire [9:0]  si         = phase[23:14];
    wire [8:0]  sine_q_idx = si[8] ? (9'd256 - {1'b0, si[7:0]}) : {1'b0, si[7:0]};
    `include "sine_q_rom.vh"
    wire [15:0] osc_sine   = si[9] ? (16'd0 - sine_q_val) : sine_q_val;
    reg  [15:0] osc;
    always @* begin
        case (wave)
            2'd0:    osc = osc_square;
            2'd1:    osc = osc_saw;
            2'd2:    osc = osc_tri;
            default: osc = osc_sine;
        endcase
    end
    wire [6:0]  note_inc_idx = d0;                                       // NOTE_ON note number
    `include "note_inc_rom.vh"

    // ---- envelope arithmetic, widened to 21 bits (6.3) -------------------------
    wire [20:0] att_sum  = {1'b0, level} + {5'b0, attack};
    wire [19:0] target   = {sustain, 4'b0000};
    wire [20:0] dec_thr  = {1'b0, target} + {5'b0, decay};
    wire        att_done = (att_sum >= {1'b0, LEVEL_MAX});
`ifdef INJECT_BUG_ENV
    wire        dec_done = ({1'b0, level} <  dec_thr);   // BUG: off-by-one decay->sustain transition
`else
    wire        dec_done = ({1'b0, level} <= dec_thr);
`endif
    wire        rel_done = (level <= {4'b0, release_r});

    // ---- scaler pipeline (7): env -> g -> out -----------------------------------
    reg        [15:0] s1_osc;
    reg        [15:0] s1_env;
    reg        [6:0]  s1_vel;
    reg               s1_v;
    reg        [15:0] s2_osc;
    reg        [15:0] s2_g;
    reg               s2_v;
    /* verilator lint_off UNUSEDSIGNAL */
    wire        [22:0] envvel = s1_env * s1_vel;                 // u16*u7 = u23; g = [22:7]
    wire        [32:0] prod   = $signed(s2_osc) * $signed({1'b0, s2_g}); // s16*u16 -> s33; out = [31:16]
    /* verilator lint_on UNUSEDSIGNAL */

    always @(posedge clk) begin
        if (!rst_n) begin
            phase <= 24'd0; inc <= 24'd0; wave <= 2'd0; state <= ST_IDLE; level <= 20'd0;
            attack <= DEF_ATTACK; decay <= DEF_DECAY; sustain <= DEF_SUSTAIN; release_r <= DEF_RELEASE;
            velocity <= 7'd0;
            s1_osc <= 16'd0; s1_env <= 16'd0; s1_vel <= 7'd0; s1_v <= 1'b0;
            s2_osc <= 16'd0; s2_g <= 16'd0; s2_v <= 1'b0;
            out <= 16'd0; out_valid <= 1'b0;
        end else begin
            // ---- steps 2 and 3: compute from current registers, then advance ----
            s1_v      <= tick;
            s2_v      <= s1_v;
            out_valid <= s2_v;
            if (tick) begin
                s1_osc <= osc;
                s1_env <= level[19:4];
                s1_vel <= velocity;
                phase  <= phase + inc;                                  // mod 2^24
                case (state)
                    ST_ATTACK:
                        if (att_done) begin level <= LEVEL_MAX; state <= ST_DECAY; end
                        else               level <= att_sum[19:0];
                    ST_DECAY:
                        if (dec_done) begin level <= target; state <= ST_SUSTAIN; end
                        else               level <= level - {4'b0, decay};
                    ST_RELEASE:
                        if (rel_done) begin level <= 20'd0; state <= ST_IDLE; end
                        else               level <= level - {4'b0, release_r};
                    default: ;                                          // IDLE, SUSTAIN: hold
                endcase
            end
            s2_osc <= s1_osc;
`ifdef INJECT_BUG_GAIN
            s2_g   <= envvel[22:7] + 16'd1;                              // BUG: gain off by one
`else
            s2_g   <= envvel[22:7];
`endif
            if (s2_v) out <= prod[31:16];

            // ---- step 1 (of the next frame): apply one command --------------------
            if (apply) begin
                case (op)
                    OP_NOTE_OFF:
                        if (state == ST_ATTACK || state == ST_DECAY || state == ST_SUSTAIN)
                            state <= ST_RELEASE;
                    OP_NOTE_ON: begin
                        inc <= note_inc_val; phase <= 24'd0; velocity <= d1;
                        level <= 20'd0; state <= ST_ATTACK;
                    end
                    OP_SET_WAVE:      wave      <= d0[1:0];
                    OP_SET_ATTACK:    attack    <= {d0[1:0], d1, d2};
                    OP_SET_DECAY:     decay     <= {d0[1:0], d1, d2};
                    OP_SET_SUSTAIN:   sustain   <= {d0[1:0], d1, d2};
                    OP_SET_RELEASE:   release_r <= {d0[1:0], d1, d2};
                    OP_SET_PHASE_INC: inc       <= {d0[2:0], d1, d2, d3};
                    default: ;
                endcase
            end
            if (soft_reset) begin
                phase <= 24'd0; inc <= 24'd0; wave <= 2'd0; state <= ST_IDLE; level <= 20'd0;
                attack <= DEF_ATTACK; decay <= DEF_DECAY; sustain <= DEF_SUSTAIN; release_r <= DEF_RELEASE;
                velocity <= 7'd0;
            end
        end
    end
endmodule
`default_nettype wire
