/* S2: native initialization/first executed swap per activation. Observations
 * do not reset global or node RNG; pointer identity is local to each run. */
extern void node_initialize_thunk(void) __asm__("_node_site_initialize");
extern void node_before_thunk(void) __asm__("_node_site_before");
extern void node_after_thunk(void) __asm__("_node_site_after");
typedef struct NodeObservation {
    DWORD pointer,order,activation,before_hits,after_hits;
    BYTE outer[16];
} NodeObservation;
static NodeObservation nodes[4096];
static DWORD node_count,node_activations,node_visits[3],node_retained[3],node_pending;
static BOOL node_observed;
static DWORD node_saved_gpr[9],node_saved_kind,node_saved_activation;
static BYTE node_saved_fx[512];
static DWORD node_payload_offset,node_canary_offset;

static void node_append(const char *name,const void *data,DWORD bytes) {
    char path[32768];
    if(snprintf(path,sizeof(path),"%s/%s",folder,name)>=(int)sizeof(path)) fail("node_path");
    file_write(path,data,bytes,TRUE);
}

static void node_coverage(NodeObservation *node) {
    record("node_coverage",",\"node_order\":%lu,\"activation\":%lu,\"esi\":%lu,\"first_swap_before\":%lu,\"first_swap_after\":%lu",
           node->order,node->activation,node->pointer,node->before_hits,node->after_hits);
    if(node->before_hits!=node->after_hits) fail("node_unpaired_swap");
}

void node_probe(DWORD *gpr,BYTE *fp,DWORD kind) {
    node_observed=FALSE;
    if(kind>2) fail("node_kind");
    node_visits[kind]++;
    DWORD pointer=gpr[1];
    NodeObservation *node=NULL;
    for(unsigned i=0;i<node_count;++i) if(nodes[i].pointer==pointer) { node=&nodes[i]; break; }
    if(kind==0) {
        if(node) node_coverage(node);
        else {
            if(node_count==4096) fail("node_capacity");
            node=&nodes[node_count++]; node->order=node_count; node->pointer=pointer;
        }
        node->activation=++node_activations; node->before_hits=node->after_hits=0;
    } else {
        /* after-site also executes the no-swap branch; only pair an observed
         * executed before-site, never infer a swap from the common join PC. */
        if(kind==2 && !node_pending) return;
        if(!node) fail("node_swap_without_initialization");
        if(kind==1) {
            if(node->before_hits) return;
            if(node_pending) fail("node_nested_swap");
            node_pending=node->activation; node->before_hits=1;
            memcpy(node->outer,(void *)0xb16b810,16);
        } else {
            if(node_pending!=node->activation || node->after_hits) fail("node_swap_pair");
            node->after_hits=1; node_pending=0;
            if(memcmp(node->outer,(void *)0xb16b810,16)) fail("node_outer_rng_restore");
        }
    }
    if(GetCurrentThreadId()!=synth_tid) fail("node_thread");
    DWORD input=*(DWORD *)(uintptr_t)(pointer+0x24c);
    BYTE payload[48];
    memcpy(payload,(void *)(uintptr_t)input,16);
    memcpy(payload+16,(void *)0xb16b810,16);
    memcpy(payload+32,(void *)(uintptr_t)(pointer+0x190),16);
    char digest[65]; hash(payload,sizeof(payload),digest);
    node_append("node-state.bin",payload,sizeof(payload));
    record("node_rng",",\"kind\":%lu,\"native_pc\":%lu,\"node_order\":%lu,\"activation\":%lu,\"esi\":%lu,\"input_pointer\":%lu,"
           "\"tick\":%lu,\"file\":\"node-state.bin\",\"offset\":%lu,\"bytes\":48,\"layout\":\"input16,global16,node16\",\"sha256\":\"%s\"",
           kind,kind==0?(DWORD)0x40543e:kind==1?(DWORD)0x40563e:(DWORD)0x40573e,node->order,node->activation,pointer,input,
           *(DWORD *)0xb16bd20,node_payload_offset,digest);
    node_payload_offset+=sizeof(payload); node_retained[kind]++;
    memcpy(node_saved_gpr,gpr,36); memcpy(node_saved_fx,fp,512);
    node_saved_kind=kind; node_saved_activation=node->activation; node_observed=TRUE;
}

void node_return(DWORD *gpr,BYTE *fp,DWORD kind) {
    if(!node_observed) return;
    BOOL equal=kind==node_saved_kind && !memcmp(node_saved_gpr,gpr,36) && !memcmp(node_saved_fx,fp,512);
    BYTE payload[1096];
    memcpy(payload,node_saved_gpr,36); memcpy(payload+36,gpr,36);
    memcpy(payload+72,node_saved_fx,512); memcpy(payload+584,fp,512);
    node_append("node-canaries.bin",payload,sizeof(payload));
    char digest[65]; hash(payload,sizeof(payload),digest);
    record("node_probe_restoration",",\"kind\":%lu,\"activation\":%lu,\"file\":\"node-canaries.bin\",\"offset\":%lu,\"bytes\":1096,"
           "\"layout\":\"before-gpr36,after-gpr36,before-fx512,after-fx512\",\"sha256\":\"%s\",\"equal\":%s",
           kind,node_saved_activation,node_canary_offset,digest,equal?"true":"false");
    node_canary_offset+=sizeof(payload);
    if(!equal) fail("node_probe_restoration");
    node_observed=FALSE;
}

static void node_hook(DWORD pc,void (*thunk)(void),const BYTE *expected,DWORD bytes) {
    if(bytes<5 || bytes>16 || memcmp((void *)(uintptr_t)pc,expected,bytes)) fail("node_hook_fingerprint");
    BYTE patch[16]; memset(patch,0x90,sizeof(patch)); patch[0]=0xe9;
    DWORD relative=(DWORD)(uintptr_t)thunk-(pc+5); memcpy(patch+1,&relative,4);
    char name[64]; snprintf(name,sizeof(name),"native-hook-%08lx-original.bin",pc); save(name,expected,bytes);
    snprintf(name,sizeof(name),"native-hook-%08lx-effective.bin",pc); save(name,patch,bytes);
    replace(pc,patch,bytes);
    record("node_hook",",\"native_pc\":%lu,\"observer_pc\":%lu,\"displaced_bytes\":%lu,\"continuation_pc\":%lu",
           pc,(DWORD)(uintptr_t)thunk,bytes,pc+bytes);
}

static void node_initialize(void) {
    static const BYTE initialize[]={0x0f,0x28,0x46,0x40,0x0f,0x29,0x46,0x50};
    static const BYTE before[]={0x0f,0x28,0x86,0x90,0x01,0x00,0x00};
    static const BYTE after[]={0x0f,0x28,0x07,0x66,0x0f,0x58,0x46,0x60};
    node_hook(0x40543e,node_initialize_thunk,initialize,sizeof(initialize));
    node_hook(0x40563e,node_before_thunk,before,sizeof(before));
    node_hook(0x40573e,node_after_thunk,after,sizeof(after));
}

static void node_summary(void) {
    if(node_pending) fail("node_pending_at_completion");
    for(unsigned i=0;i<node_count;++i) node_coverage(&nodes[i]);
    record("node_summary",",\"nodes\":%lu,\"activations\":%lu,\"visits\":[%lu,%lu,%lu],\"retained\":[%lu,%lu,%lu],\"pending\":0",
           node_count,node_activations,node_visits[0],node_visits[1],node_visits[2],node_retained[0],node_retained[1],node_retained[2]);
}
