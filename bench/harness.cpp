// harness.cpp -- BARE Verilator C++ harness for synth_core (no cocotb/VPI).
//   ./synth_bare <frames> <script.bin> <out.bin>
// script.bin: records of {u32 frame, u8 nbytes, bytes...}, sorted by frame.
// The bytes for frame f are delivered on the direct byte port during frame
// f-1 (one per clock from cycle 10), exactly like SynthRef.render_script()
// feeds them "immediately before frame f".  Samples are dumped as LE int16.
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <vector>

#include "Vsynth_core.h"
#include "verilated.h"

struct Rec { uint32_t frame; std::vector<uint8_t> bytes; };

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    if (argc < 4) { fprintf(stderr, "usage: %s <frames> <script.bin> <out.bin>\n", argv[0]); return 2; }
    long frames = atol(argv[1]);
    std::vector<Rec> script;
    {
        FILE* f = fopen(argv[2], "rb");
        if (!f) { perror("script"); return 2; }
        for (;;) {
            uint32_t fr; uint8_t n;
            if (fread(&fr, 4, 1, f) != 1) break;
            if (fread(&n, 1, 1, f) != 1) break;
            Rec r; r.frame = fr; r.bytes.resize(n);
            if (n && fread(r.bytes.data(), 1, n, f) != n) break;
            script.push_back(r);
        }
        fclose(f);
    }
    Vsynth_core* top = new Vsynth_core;
    std::vector<int16_t> out;
    out.reserve(frames);

    top->clk = 0; top->rst_n = 0; top->uart_rx = 1; top->cmd_valid = 0; top->cmd_byte = 0;
    for (int i = 0; i < 4; i++) { top->clk = 1; top->eval(); top->clk = 0; top->eval(); }
    top->rst_n = 1;
    top->eval();

    auto t0 = std::chrono::steady_clock::now();
    std::deque<uint8_t> pending;
    size_t si = 0;
    uint64_t cycles = 0;
    long got = 0;
    // iteration i = the clock edge that ends cycle (i % 256) of frame (i / 256)
    for (uint64_t i = 0; got < frames; i++) {
        uint32_t frame = (uint32_t)(i >> 8), cyc = (uint32_t)(i & 255);
        if (cyc == 0)
            while (si < script.size() && script[si].frame == frame + 1) {
                for (uint8_t b : script[si].bytes) pending.push_back(b);
                si++;
            }
        if (cyc >= 10 && !pending.empty()) { top->cmd_valid = 1; top->cmd_byte = pending.front(); pending.pop_front(); }
        else { top->cmd_valid = 0; }
        top->clk = 1; top->eval();
        if (top->sample_valid) { out.push_back((int16_t)top->sample); got++; }
        top->clk = 0; top->eval();
        cycles++;
    }
    auto t1 = std::chrono::steady_clock::now();
    double el = std::chrono::duration<double>(t1 - t0).count();
    FILE* f = fopen(argv[3], "wb");
    if (!f) { perror("out"); return 2; }
    fwrite(out.data(), 2, out.size(), f);
    fclose(f);
    printf("{\"frames\": %ld, \"cycles\": %llu, \"loop_s\": %.3f, \"cycles_per_s\": %.0f, \"samples_per_s\": %.0f, "
           "\"fifo_overflow\": %d, \"script_records\": %zu, \"records_consumed\": %zu}\n",
           got, (unsigned long long)cycles, el, cycles / el, got / el, (int)top->dbg_fifo_overflow, script.size(), si);
    top->final();
    delete top;
    return 0;
}
