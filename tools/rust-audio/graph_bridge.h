// Diagnostic-only ABI adapter; all graph algorithms and selected tick bodies are Rust.
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
struct RustGraphContext {
    SynthGlobalStateStruct* state;
    SynthFunction* ticks;
    SynthFunction* inits;
    void* (*alloc)(size_t);
    void (*free)(void*);
    unsigned long long created, destroyed, global_hits, voice_hits;
};
extern "C" {
void eidolon_layout(size_t*);
SynthNode* eidolon_create_node(RustGraphContext*, unsigned, unsigned, unsigned, unsigned);
SynthNode* eidolon_create_nodes(RustGraphContext*, unsigned, unsigned);
void eidolon_destroy_voice(RustGraphContext*, SynthNode*);
void eidolon_node_tick(SynthNode*, SynthGlobalStateStruct*, unsigned);
void eidolon_voice_tick(SynthNode*, RustGraphContext*);
void eidolon_note(RustGraphContext*, unsigned, unsigned, unsigned, unsigned);
void eidolon_fraction(SynthGlobalStateStruct*, const sample_t*, sample_t*);
void eidolon_arp_step(SynthNode*, SynthGlobalStateStruct*, unsigned);
void eidolon_effect_tick(SynthNode*, SynthGlobalStateStruct*, unsigned);
void eidolon_effect_init(SynthNode*, RustGraphContext*, unsigned);
}
void ArpeggiatorStep(SynthNode*, int);
inline sample_t GetDelayTimeFraction(const sample_t&);
static void* rust_alloc(size_t n) { return SynthMalloc((int)n); }
static void rust_free(void* p) { SynthFree(p); }
static RustGraphContext rust_graph = {&SynthGlobalState, NodeTickFunctions, NodeInitFunctions,
    rust_alloc, rust_free, 0, 0, 0, 0};
static void rust_check_layout() {
    static bool checked = false;
    if (checked) return;
    size_t actual[14];
    eidolon_layout(actual);
    const size_t expected[] = {sizeof(SynthNode), sizeof(VMVoice), sizeof(VMWork), sizeof(SynthGlobalStateStruct),
        offsetof(SynthNode,e), offsetof(SynthNode,v), offsetof(SynthNode,input), offsetof(SynthNode,id),
        offsetof(VMWork,Keys), offsetof(VMWork,ActiveVoices), offsetof(VMWork,Voice),
        offsetof(SynthGlobalStateStruct,CurrentBPM), offsetof(SynthGlobalStateStruct,CurrentVoice), offsetof(SynthGlobalStateStruct,CurrentNoteTick)};
    if (std::memcmp(actual,expected,sizeof(actual))) {
        for (int i=0;i<14;++i) std::fprintf(stderr,"layout[%d] Rust=%zu C++=%zu\n",i,actual[i],expected[i]);
        std::abort();
    }
    checked = true;
}
void eidolon_graph_report() {
    std::printf("RUST_GRAPH created=%llu destroyed=%llu global_hits=%llu voice_hits=%llu ABI=14/14\n",
        rust_graph.created,rust_graph.destroyed,rust_graph.global_hits,rust_graph.voice_hits);
}
void rust_note_event(unsigned channel, unsigned note, unsigned velocity, bool on) {
    eidolon_note(&rust_graph,channel,note,velocity,on);
}
