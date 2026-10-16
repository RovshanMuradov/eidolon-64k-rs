/* Size scaffold only: decompresses a data blob, never executes native payload. */
#include "LzmaDec.h"
#include "payload.h"
#ifdef _WIN32
__declspec(dllimport) void __stdcall ExitProcess(unsigned int);
#else
#include <stdio.h>
#endif

static Byte output[OUTPUT_BYTES];
static Byte arena[131072];
static Byte sample_pcm[SAMPLE_BYTES + 1];
static void *alloc(ISzAllocPtr p, size_t n) { (void)p; return n <= sizeof(arena) ? arena : 0; }
static void release(ISzAllocPtr p, void *a) { (void)p; (void)a; }
static const ISzAlloc allocator = {alloc, release};

#ifdef _WIN32
void *memcpy(void *d, const void *s, size_t n) {
    Byte *a = d; const Byte *b = s;
    while (n--) *a++ = *b++;
    return d;
}
#endif

static int decode(void) {
    SizeT dst = sizeof(output), src = sizeof(payload) - 13;
    ELzmaStatus status;
    int result = LzmaDecode(output, &dst, payload + 13, &src, payload, 5,
                            LZMA_FINISH_END, &status, &allocator);
    if (result || dst != sizeof(output) || src != sizeof(payload) - 13
        || status != LZMA_STATUS_FINISHED_WITH_MARK) return 1;
    size_t pos = 0;
    for (unsigned wave = 0; wave < SAMPLE_COUNT; ++wave) {
        unsigned count = sample_table[wave][1] / 2, last = 0;
        if (sample_table[wave][0] >= 512) return 2;
        const Byte *encoded = output + SAMPLE_OFFSET + pos;
        for (unsigned i = 0; i < count; ++i) {
            last = (last + encoded[i] + ((unsigned)encoded[count + i] << 8)) & 65535;
            sample_pcm[pos + 2 * i] = (Byte)last;
            sample_pcm[pos + 2 * i + 1] = (Byte)(last >> 8);
        }
        pos += sample_table[wave][1];
    }
    if (pos != SAMPLE_BYTES) return 3;
    for (size_t i = 0; i < SAMPLE_BYTES; ++i) output[SAMPLE_OFFSET + i] = sample_pcm[i];
    return 0;
}

#ifdef _WIN32
void entry(void) { ExitProcess(decode()); }
#else
int main(int argc, char **argv) {
    if (argc != 2 || decode()) return 1;
    FILE *f = fopen(argv[1], "wb");
    if (!f) return 2;
    int ok = fwrite(output, 1, sizeof(output), f) == sizeof(output);
    return fclose(f) || !ok;
}
#endif
