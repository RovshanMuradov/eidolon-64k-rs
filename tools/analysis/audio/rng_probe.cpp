// CPU-only check of pinned public source against immutable saved native states.
#include <cstdio>
#include <cstring>
#include "sample_t.cpp"
static_assert(sizeof(sample_t) == 16 && alignof(sample_t) == 16, "SSE lane layout");

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    FILE *f = std::fopen(argv[1], "rb");
    if (!f) return 3;
    sample_t::init();
    const unsigned previous = _mm_getcsr();
    _mm_setcsr(0xffc0);
    unsigned char record[24][48];
    if (std::fread(record, 48, 24, f) != 24 || std::fgetc(f) != EOF) return 4;
    std::fclose(f);
    for (int i = 0; i != 22; ++i) {
        sample_t input, global, expected, actual;
        std::memcpy(&input, record[i], 16);
        std::memcpy(&global, record[i] + 16, 16);
        std::memcpy(&expected, record[i] + 32, 16);
        sample_t rands = s_dupright(input);
        if (!_mm_testz_si128(rands.pi, rands.pi))
            actual.pi = _mm_add_epi32(_mm_shuffle_epi32(s_toInt(rands * SC[S_32768_0]),
                                        _MM_SHUFFLE(3, 1, 2, 0)), SC[S_EXP2_OFFSET].pi);
        else actual = global;
        if (std::memcmp(&actual, &expected, 16)) return 10 + i;
    }
    sample_t outer, local, expected;
    std::memcpy(&outer, record[22] + 16, 16);
    std::memcpy(&local, record[22] + 32, 16);
    SC[S_RAND_SEED] = local;
    s_rand(); s_rand(); // SynthNode.cpp GLITCH_SHUFFLE has exactly two calls.
    std::memcpy(&expected, record[23] + 32, 16);
    if (std::memcmp(&SC[S_RAND_SEED], &expected, 16)) return 40;
    if (std::memcmp(&outer, record[23] + 16, 16)) return 41;
    _mm_setcsr(previous);
    std::puts("PASS: source seed initialization 22/22; two-step node RNG 1/1; outer preservation 1/1");
    return 0;
}
