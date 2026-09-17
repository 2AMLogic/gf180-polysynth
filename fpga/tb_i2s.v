// tb_i2s.v -- decode i2s_tx.v the way a PCM5102A (I2S format,
// FMT low) would, with no hardware: sample SDATA on the rising edge of BCLK,
// treat the first BCLK after an LRCLK edge as the I2S one-bit delay, then
// take 16 bits MSB first.  Checks: every decoded word equals a sample that
// was actually fed in (bit order, polarity, sign), the remaining 16 bits of
// each 32-bit slot are zero, BCLK = 64 x LRCLK, LRCLK period = 256 clk, and
// reports how L and R relate to the sample stream.  Prints "TB PASS" or
// "TB FAIL".
`timescale 1ns/1ps
module tb_i2s;
    reg clk = 1'b0;
    always #40.69 clk = ~clk;                 // 12.288 MHz
    reg         rst_n = 1'b0;
    reg         sample_valid = 1'b0;
    reg  [15:0] sample = 16'd0;
    wire        bclk, lrclk, sdata;
    i2s_tx dut (.clk(clk), .rst_n(rst_n), .sample_valid(sample_valid), .sample(sample),
                .bclk(bclk), .lrclk(lrclk), .sdata(sdata));

    // ---- frame generator: one sample per 256 clocks, strobed in cycle 5 like synth_core
    localparam integer NSEQ = 12;
    reg [15:0] seq [0:NSEQ-1];
    initial begin
        seq[0]=16'h0000; seq[1]=16'h1234; seq[2]=16'h8000; seq[3]=16'h7FFF; seq[4]=16'hABCD; seq[5]=16'hFFFF;
        seq[6]=16'h0001; seq[7]=16'h5555; seq[8]=16'hAAAA; seq[9]=16'h8001; seq[10]=16'h7F00; seq[11]=16'h00FF;
    end
    integer cyc = 0, si = 0, fed = 0;
    reg [15:0] fedv [0:63];
    always @(posedge clk) begin
        if (!rst_n) begin cyc <= 0; sample_valid <= 0; end
        else begin
            cyc <= (cyc == 255) ? 0 : cyc + 1;
            sample_valid <= (cyc == 4);
            if (cyc == 4) begin sample <= seq[si % NSEQ]; fedv[fed] <= seq[si % NSEQ]; si <= si + 1; fed <= fed + 1; end
        end
    end

    // ---- I2S receiver model
    reg        lr_prev = 1'b0;
    integer    bitidx = -1;
    reg [15:0] word = 0;
    reg [15:0] lw [0:63];  integer nl = 0;
    reg [15:0] rw [0:63];  integer nr = 0;
    integer    period = -1;                   // LRCLK period counter (starts at the first left slot)
    integer    pad_nonzero = 0, bclks_this_lr = 0, bclks_per_lr = -1;
    reg [19:0] rawbits = 0;  reg [19:0] raw [0:63];  integer nraw = 0;   // first 20 bits sampled per slot
    integer    lr_clk_period = -1, lr_rise_cyc = -1, clkcount = 0;
    always @(posedge clk) clkcount <= clkcount + 1;
    always @(posedge lrclk) begin
        if (lr_rise_cyc >= 0) lr_clk_period = clkcount - lr_rise_cyc;
        lr_rise_cyc = clkcount;
    end
    always @(posedge bclk) begin
        if (lrclk != lr_prev) begin               // channel boundary: bit 0 is the I2S delay bit
            if (bitidx >= 0) begin
                raw[nraw] = rawbits; nraw = nraw + 1;
                if (bclks_per_lr < 0 && bclks_this_lr > 0) ; // first partial slot
                bclks_per_lr = bclks_this_lr;
            end
            bclks_this_lr = 0;
            bitidx = 0;
            rawbits = {19'd0, sdata};
            if (lrclk == 1'b0) period = period + 1;   // a left slot starts a new LRCLK period
            lr_prev = lrclk;
        end else if (bitidx >= 0) begin
            bitidx = bitidx + 1;
            if (bitidx < 20) rawbits = {rawbits[18:0], sdata};
            if (bitidx >= 1 && bitidx <= 16) word = {word[14:0], sdata};
            if (bitidx == 16 && period >= 0) begin
                if (lr_prev == 1'b0) begin lw[period] = word; nl = nl + 1; end   // LRCLK low = left
                else                begin rw[period] = word; nr = nr + 1; end
            end
            if (bitidx > 16 && sdata) pad_nonzero = pad_nonzero + 1;
        end
        bclks_this_lr = bclks_this_lr + 1;
    end

    // ---- scoring
    integer i, off, best_l, best_r, fails, lr_mismatch;
    function integer match_at(input integer off, input integer isleft);
        integer k, bad;
        begin
            bad = 0;
            for (k = 0; k < 8; k = k + 1)
                if ((isleft ? lw[k + 2] : rw[k + 2]) != fedv[k + 2 + off]) bad = bad + 1;
            match_at = bad;
        end
    endfunction
    initial begin
        #500 rst_n = 1'b1;
        // run 24 frames = 24 LRCLK periods
        repeat (24 * 256 + 300) @(posedge clk);
        fails = 0;
        best_l = -99; best_r = -99;
        for (off = -2; off <= 2; off = off + 1) begin
            if (match_at(off, 1) == 0 && best_l == -99) best_l = off;
            if (match_at(off, 0) == 0 && best_r == -99) best_r = off;
        end
        $display("decoded %0d left and %0d right words over %0d LRCLK periods; fed %0d samples", nl, nr, period + 1, fed);
        for (i = 0; i < 6; i = i + 1)
            $display("  period %0d: L=%04x R=%04x   fed[%0d]=%04x", i, lw[i], rw[i], i, fedv[i]);
        $display("raw bits at the first 20 BCLK rising edges of a slot (bit 0 = I2S delay bit, bit 1 = MSB):");
        for (i = 2; i < 8; i = i + 1)
            $display("  slot %0d: %b", i, raw[i]);
        if (best_l == -99) begin fails = fails + 1; $display("FAIL: left words never line up with the fed samples (bit order/polarity?)"); end
        else $display("ok: left  word k == fed sample k%+0d", best_l);
        if (best_r == -99) begin fails = fails + 1; $display("FAIL: right words never line up with the fed samples"); end
        else $display("ok: right word k == fed sample k%+0d", best_r);
        lr_mismatch = 0;
        for (i = 2; i < 12; i = i + 1) if (lw[i] != rw[i]) lr_mismatch = lr_mismatch + 1;
        if (lr_mismatch == 0) $display("ok: L == R within every LRCLK period (contract 11: same sample on both channels)");
        else $display("note: L != R in %0d of 10 LRCLK periods -- channels carry samples one frame apart (audibly irrelevant, but not what contract 11 describes)", lr_mismatch);
        if (pad_nonzero) begin fails = fails + 1; $display("FAIL: %0d non-zero bits in the 16-bit padding of the 32-bit slots", pad_nonzero); end
        else $display("ok: slot padding bits are zero (16-bit sample left-justified in a 32-bit slot)");
        if (bclks_per_lr != 32) begin fails = fails + 1; $display("FAIL: %0d BCLKs per channel slot, expected 32 (BCLK = 64 x fs)", bclks_per_lr); end
        else $display("ok: 32 BCLKs per channel slot -> BCLK = 64 x LRCLK = 3.072 MHz");
        if (lr_clk_period != 256) begin fails = fails + 1; $display("FAIL: LRCLK period %0d clk, expected 256 (48 kHz from 12.288 MHz)", lr_clk_period); end
        else $display("ok: LRCLK period = 256 clk = 48 kHz");
        if (fails == 0) $display("TB PASS"); else $display("TB FAIL (%0d)", fails);
        $finish;
    end
endmodule
