/* Raw machine-state witnesses after actual exception dispatch, and after the
 * unchanged native 401765..40176a epilogue/RET. No native RNG/physics writes. */
extern void native_bootstrap(void), native_interior(void), native_synth_return(void);
extern FARPROC WINAPI native_lookup(HMODULE,LPCSTR) __asm__("_eidolon_lookup");
static CONTEXT resume_expected[3];
static DWORD resume_pc[3], resume_seen[3];
static BYTE interior_original;
static PVOID native_handler;
static HANDLE native_synth_handle;
static BOOL native_synth_joined;

static void native_bytes(const char *phase,const char *role,DWORD base,DWORD bytes) {
    char name[128],digest[65];
    snprintf(name,sizeof(name),"native-%s-%s.bin",phase,role);
    save(name,(void *)(uintptr_t)base,bytes); hash((void *)(uintptr_t)base,bytes,digest);
    record("native_state",",\"phase\":\"%s\",\"role\":\"%s\",\"base\":%lu,\"bytes\":%lu,\"file\":\"%s\",\"sha256\":\"%s\"",
           phase,role,base,bytes,name,digest);
}

static void native_physics(const char *phase) {
    native_bytes(phase,"physics",0xb17bdf0,256);
}

static BOOL native_fx_equal(const BYTE *a,const BYTE *b) {
    /* FXSAVE reserved byte5 and 6 padding bytes per x87 slot are undefined. */
    if(memcmp(a,b,5) || memcmp(a+6,b+6,26) || memcmp(a+160,b+160,128)) return FALSE;
    for(unsigned i=0;i<8;++i) if(memcmp(a+32+16*i,b+32+16*i,10)) return FALSE;
    return TRUE;
}

DWORD native_resumed(DWORD *gpr,BYTE *fp,DWORD kind) {
    if(kind>2 || resume_seen[kind]++) fail("native_resume_count");
    CONTEXT *c=&resume_expected[kind];
    /* RF is an exception-dispatch flag cleared by the first resumed CPU
     * instruction; arithmetic/DF/IF flags must still match exactly. */
    DWORD expected[]={c->Edi,c->Esi,c->Ebp,0,c->Ebx,c->Edx,c->Ecx,c->Eax,c->EFlags&~0x10000u};
    BOOL equal=TRUE;
    for(unsigned i=0;i<9;++i) if(i!=3 && expected[i]!=gpr[i]) equal=FALSE;
    DWORD esp=(DWORD)(uintptr_t)(gpr+10);
    if(esp!=c->Esp || !native_fx_equal(c->ExtendedRegisters,fp)) equal=FALSE;
    char name[128],digest[65];
    snprintf(name,sizeof(name),"resume-%lu-gpr.bin",kind); save(name,gpr,36);
    snprintf(name,sizeof(name),"resume-%lu-fx.bin",kind); save(name,fp,512);
    snprintf(name,sizeof(name),"resume-%lu-expected-context.bin",kind); save(name,c,sizeof(*c));
    hash(fp,512,digest);
    record("native_resumed",",\"kind\":%lu,\"target\":%lu,\"expected_esp\":%lu,\"observed_esp\":%lu,"
           "\"fx_sha256\":\"%s\",\"x87_cw\":%u,\"mxcsr\":%lu,\"equal\":%s,\"allowed_eflags_clear\":65536,\"observation\":\"independent PUSHFD/PUSHAD/FXSAVE after physical resumption\"",
           kind,resume_pc[kind],c->Esp,esp,digest,*(WORD *)fp,*(DWORD *)(fp+24),equal?"true":"false");
    if(!equal) fail("physical_exception_resume_canary");
    return resume_pc[kind];
}

static void native_bootstrap_arm(CONTEXT *context) {
    resume_expected[0]=*context; resume_pc[0]=context->Eip;
    context->Eip=(DWORD)(uintptr_t)native_bootstrap;
    record("native_resume_arm",",\"kind\":0,\"native_pc\":%lu,\"observer_pc\":%lu",resume_pc[0],context->Eip);
}

static LONG CALLBACK native_exception(EXCEPTION_POINTERS *exception) {
    if(exception->ExceptionRecord->ExceptionCode!=EXCEPTION_BREAKPOINT ||
       exception->ExceptionRecord->ExceptionAddress!=(void *)0x40166a) return EXCEPTION_CONTINUE_SEARCH;
    CONTEXT *c=exception->ContextRecord;
    if(resume_pc[1]) fail("interior_trap_duplicate");
    save("interior-context-before.bin",c,sizeof(*c));
    replace(0x40166a,&interior_original,1);
    resume_expected[1]=*c; resume_expected[1].Eip=0x40166a; resume_pc[1]=0x40166a;
    c->Eip=(DWORD)(uintptr_t)native_interior;
    save("interior-context-after.bin",c,sizeof(*c));
    record("native_resume_arm",",\"kind\":1,\"native_pc\":%lu,\"observer_pc\":%lu",resume_pc[1],c->Eip);
    return EXCEPTION_CONTINUE_EXECUTION;
}

static void native_completion_arm(CONTEXT *context) {
    resume_expected[2]=*context;
    CONTEXT *expected=&resume_expected[2];
    expected->Edi=*(DWORD *)(uintptr_t)context->Esp;
    expected->Esi=*(DWORD *)(uintptr_t)(context->Esp+4);
    expected->Ebp=*(DWORD *)(uintptr_t)context->Ebp;
    expected->Esp=context->Ebp+8;
    DWORD *ret=(DWORD *)(uintptr_t)(context->Ebp+4);
    resume_pc[2]=*ret;
    *ret=(DWORD)(uintptr_t)native_synth_return;
    record("native_epilogue_arm",",\"native_pc\":%lu,\"return_slot\":%lu,\"original_return\":%lu,\"observer_return\":%lu,"
           "\"saved_edi\":%lu,\"saved_esi\":%lu,\"saved_ebp\":%lu,\"expected_esp\":%lu",
           (DWORD)0x401765,context->Ebp+4,resume_pc[2],*ret,expected->Edi,expected->Esi,expected->Ebp,expected->Esp);
    if(inject("exception-gpr")) context->Eax^=1;
    if(inject("exception-fp")) *(DWORD *)(context->ExtendedRegisters+24)^=0x2000;
}

static WORD native_ordinal(HMODULE module,const char *name) {
    BYTE *base=(BYTE *)module;
    IMAGE_DOS_HEADER *dos=(void *)base;
    IMAGE_NT_HEADERS32 *nt=(void *)(base+dos->e_lfanew);
    IMAGE_EXPORT_DIRECTORY *exports=(void *)(base+nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_EXPORT].VirtualAddress);
    DWORD *names=(void *)(base+exports->AddressOfNames);
    WORD *ordinals=(void *)(base+exports->AddressOfNameOrdinals);
    for(DWORD i=0;i<exports->NumberOfNames;++i)
        if(!strcmp((char *)(base+names[i]),name)) return (WORD)(exports->Base+ordinals[i]);
    fail("resolver_control_ordinal"); return 0;
}

static void native_resolvers(void) {
    HMODULE module=GetModuleHandleA("kernel32.dll");
    const char *name="GetCurrentThreadId";
    WORD ordinal=native_ordinal(module,name);
    FARPROC expected=GetProcAddress(module,name);
    FARPROC by_name=native_lookup(module,name),by_ordinal=native_lookup(module,(const char *)(uintptr_t)ordinal);
    FARPROC routed=native_lookup(module,"GetTickCount");
    FARPROC missing_name=native_lookup(module,"EidolonDeliberatelyMissingExport");
    FARPROC missing_ordinal=native_lookup(module,(const char *)65535);
    if(!expected || by_name!=expected || by_ordinal!=expected || routed!=(FARPROC)eidolon_gettick || missing_name || missing_ordinal)
        fail("resolver_control_result");
    record("resolver_control",",\"name\":\"%s\",\"ordinal\":%u,\"expected\":%lu,\"by_name\":%lu,\"by_ordinal\":%lu,"
           "\"routed_name\":\"GetTickCount\",\"routed\":%lu,\"expected_routed\":%lu,\"missing_name\":0,\"missing_ordinal\":0,\"calls\":5",
           name,ordinal,(DWORD)(uintptr_t)expected,(DWORD)(uintptr_t)by_name,(DWORD)(uintptr_t)by_ordinal,
           (DWORD)(uintptr_t)routed,(DWORD)(uintptr_t)eidolon_gettick);
}

static void native_initialize(CONTEXT *context) {
    native_physics("entry");
    native_bytes("entry","rng",0xb16b800,0x520);
    native_bytes("entry","tick",0xb16bd20,4);
    save("native-entry-main-fx.bin",context->ExtendedRegisters,512);
    static const BYTE expected[]={0xa1,0xd0,0xbd,0x17,0x0b};
    if(memcmp((void *)0x40166a,expected,sizeof(expected))) fail("interior_fingerprint");
    interior_original=expected[0]; BYTE trap=0xcc; replace(0x40166a,&trap,1);
    native_handler=AddVectoredExceptionHandler(1,native_exception);
    if(!native_handler) fail("native_handler");
    native_resolvers();
    node_initialize();
}

DWORD core_create_thread(DWORD *s) {
    if(s[0]!=0x4063a5 || s[3]!=0x401636 || GetCurrentThreadId()!=main_tid) fail("native_prethread_route");
    native_bytes("prethread","rng",0xb16b800,0x520);
    native_bytes("prethread","tick",0xb16bd20,4);
    Canary *canary=TlsGetValue(canary_tls);
    if(!canary || canary->api!=6) fail("native_prethread_canary");
    save("native-prethread-main-fx.bin",canary->fp,512);
    record("native_prethread",",\"caller\":%lu,\"tick\":%lu,\"x87_cw\":%u,\"mxcsr\":%lu",
           s[0],*(DWORD *)0xb16bd20,*(WORD *)canary->fp,*(DWORD *)(canary->fp+24));
    DWORD result=original_core_create_thread(s);
    if(!DuplicateHandle(GetCurrentProcess(),(HANDLE)(uintptr_t)result,GetCurrentProcess(),&native_synth_handle,0,FALSE,DUPLICATE_SAME_ACCESS))
        fail("native_synth_duplicate_handle");
    return result;
}

static void native_join(void) {
    if(native_synth_joined) return;
    if(!native_synth_handle || WaitForSingleObject(native_synth_handle,240000)!=WAIT_OBJECT_0) fail("native_synth_return_timeout");
    DWORD code;
    if(!GetExitCodeThread(native_synth_handle,&code) || !CloseHandle(native_synth_handle) || resume_seen[2]!=1 || code!=resume_expected[2].Eax)
        fail("native_synth_return_code");
    native_synth_joined=TRUE;
    node_summary();
    record("native_thread_exit",",\"synth_tid\":%lu,\"exit_code\":%lu,\"expected_eax\":%lu,\"resumed_epilogue_observed\":true",
           synth_tid,code,resume_expected[2].Eax);
}
