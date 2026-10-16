// Linux CPU-only source probe. No original executable code is loaded/executed.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "Synth.h"
#include "SynthNode.h"
#include "SynthAllocator.h"
static const char *bank_path;
static std::vector<void *> deferred;
unsigned char source_seen[4096];

void* SynthMalloc(int n) {
    void *p = nullptr;
    if (posix_memalign(&p, 16, (size_t)n) || !p) std::abort();
    std::memset(p, 0, (size_t)n);
    return p;
}
void SynthFree(void *p) { deferred.push_back(p); }
void SynthDeferredFree() { for (void *p : deferred) std::free(p); deferred.clear(); }
void SynthMemSet(void *p, int n, int value) { std::memset(p, value, (size_t)n); }
void SynthMemCopy(void *d, void *s, int n) { std::memcpy(d, s, (size_t)n); }
unsigned GetSystemDirectoryA(char *out, unsigned n) { if (n) out[0]=0; return 0; }
HANDLE CreateFileA(const char *, unsigned, unsigned, void *, unsigned, unsigned, void *) {
    return std::fopen(bank_path, "rb");
}
int ReadFile(HANDLE f, void *out, unsigned n, DWORD *read, void *) {
    if (!f) return 0;
    *read = (DWORD)std::fread(out, 1, n, (FILE *)f);
    return 1;
}
int CloseHandle(HANDLE f) { return std::fclose((FILE *)f) == 0; }

static std::vector<unsigned char> load(const char *name) {
    FILE *f = std::fopen(name, "rb");
    if (!f) std::abort();
    std::fseek(f, 0, SEEK_END); long n = std::ftell(f); std::rewind(f);
    std::vector<unsigned char> b((size_t)n);
    if (std::fread(b.data(), 1, b.size(), f) != b.size()) std::abort();
    std::fclose(f); return b;
}
int main(int argc, char **argv) {
    if (argc != 7) return 2;
    auto score = load(argv[1]), patch = load(argv[2]); bank_path = argv[3];
    unsigned frames = (unsigned)std::strtoul(argv[5], nullptr, 0);
    if (!frames || frames % 64) return 3;
    std::memcpy(score.data() + 4, &frames, 4);
    static_assert(sizeof(sample_t)==16 && sizeof(VMVoice)==256, "source vector/voice stride");
    _mm_setcsr(0x1f80);
    _64klang_Init(score.data(), patch.data(), 3328, 3728, 3836);
    std::vector<float> output((size_t)frames * 2);
    _64klang_Render(output.data());
    FILE *f = std::fopen(argv[4], "wb");
    if (!f || std::fwrite(output.data(), 8, frames, f) != frames) return 4;
    std::fclose(f);
    f = std::fopen(argv[6], "wb");
    if (!f || std::fwrite(source_seen, 1, sizeof(source_seen), f) != sizeof(source_seen)) return 5;
    std::fclose(f);
    std::printf("SOURCE_RENDERED frames=%u tick=%u\n", frames, SynthGlobalState.CurrentTick);
    return 0;
}
