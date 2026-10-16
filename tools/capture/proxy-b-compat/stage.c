/* Included in core.c: runtime observations for the staged G5 candidate.
 * Every original frame is rendered; only retained raw payloads are sparse. */
typedef struct Canary {
    DWORD registers[9], entry, return_pc, argbytes, api, expected;
    BYTE fp[512];
    struct Canary *previous;
} Canary;
static DWORD canary_tls;
static DWORD canary_counts[18];
static GLuint volume_texture;
static char fault[64];
static BOOL fault_used;
static LARGE_INTEGER first_present_wall, wall_frequency;
static BOOL loaded_observed;
static BY_HANDLE_FILE_INFORMATION observation_file;
static BOOL observation_file_known;
static BOOL retain_frames[27000];
static void native_completion_arm(CONTEXT *context);
extern DWORD WINAPI stage_tick(void) __asm__("_eidolon_gettick");
extern DWORD WINAPI stage_time(void) __asm__("_eidolon_timegettime");
extern BOOL WINAPI stage_qpc(LARGE_INTEGER *) __asm__("_eidolon_qpc");
extern BOOL WINAPI stage_qpf(LARGE_INTEGER *) __asm__("_eidolon_qpf");

static BOOL stage_flush(HANDLE file) {
    BY_HANDLE_FILE_INFORMATION current;
    if(!GetFileInformationByHandle(file,&current)) return FALSE;
    /* The first file_write is bootstrap_before_synth, after log_path is set. */
    if(!observation_file_known) { observation_file=current; observation_file_known=TRUE; }
    if(current.dwVolumeSerialNumber==observation_file.dwVolumeSerialNumber &&
       current.nFileIndexHigh==observation_file.nFileIndexHigh &&
       current.nFileIndexLow==observation_file.nFileIndexLow) return TRUE;
    return FlushFileBuffers(file);
}

static void stage_flush_log(void) {
    HANDLE file=CreateFileA(log_path,GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_WRITE,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL);
    if(file==INVALID_HANDLE_VALUE || !FlushFileBuffers(file) || !CloseHandle(file)) ExitProcess(126);
}

static VOID WINAPI stage_exit(UINT code) {
    if(observation_file_known) stage_flush_log();
    ExitProcess(code);
}

static BOOL inject(const char *name) {
    if (!fault_used && !strcmp(fault,name)) {
        fault_used=TRUE;
        record("fault_injected",",\"name\":\"%s\"",name);
        return TRUE;
    }
    return FALSE;
}

/* Called from assembly before the core, and AFTER its real RET imm16.
 * before/after come from independent PUSHAD/PUSHFD/FXSAVE instructions. */
void stage_canary_begin(DWORD *registers, BYTE *fp, DWORD api, DWORD argbytes) {
    Canary *c=HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,sizeof(*c));
    if(!c || api>=18) fail("canary_allocation_or_api");
    memcpy(c->registers,registers,36); memcpy(c->fp,fp,512);
    c->entry=(DWORD)(uintptr_t)(registers+9); c->return_pc=registers[9];
    c->api=api; c->argbytes=argbytes; c->previous=TlsGetValue(canary_tls);
    if (!TlsSetValue(canary_tls,c)) fail("canary_tls");
    if (GetCurrentThreadId()!=main_tid) fail("wrong_hook_thread");
}

DWORD stage_canary_arm(DWORD result) {
    Canary *c=TlsGetValue(canary_tls);
    if(!c) fail("canary_arm_without_entry");
    c->expected=result;
    return result;
}

DWORD stage_canary_return(DWORD *registers, BYTE *fp) {
    Canary *c=TlsGetValue(canary_tls);
    if(!c) fail("canary_return_without_entry");
    BOOL equal=TRUE;
    for(unsigned i=0;i<9;++i)
        if(i!=3 && i!=7 && registers[i]!=c->registers[i]) equal=FALSE;
    DWORD observed_esp=(DWORD)(uintptr_t)(registers+10);
    if(observed_esp!=c->entry+4+c->argbytes || registers[7]!=c->expected ||
       memcmp(c->fp,fp,512)) equal=FALSE;
    DWORD ordinal=++canary_counts[c->api];
    if(ordinal==1 || !equal || (c->api==14 && frame>=5760 && frame<=5762) ||
       (full_run && c->api==4 && frame==27000)) {
        char name[128], before_hash[65], after_hash[65];
        snprintf(name,sizeof(name),"abi-%02lu-%lu-before-gpr.bin",c->api,ordinal); save(name,c->registers,36);
        snprintf(name,sizeof(name),"abi-%02lu-%lu-after-gpr.bin",c->api,ordinal); save(name,registers,36);
        snprintf(name,sizeof(name),"abi-%02lu-%lu-before-fx.bin",c->api,ordinal); save(name,c->fp,512);
        snprintf(name,sizeof(name),"abi-%02lu-%lu-after-fx.bin",c->api,ordinal); save(name,fp,512);
        hash(c->fp,512,before_hash); hash(fp,512,after_hash);
        record("abi_canary",",\"api\":%lu,\"ordinal\":%lu,\"n\":%lu,\"argbytes\":%lu,\"entry_esp\":%lu,"
               "\"return_esp\":%lu,\"return_pc\":%lu,\"expected_eax\":%lu,\"observed_eax\":%lu,"
               "\"before_fx_sha256\":\"%s\",\"after_fx_sha256\":\"%s\",\"equal\":%s",
                c->api,ordinal,frame,c->argbytes,c->entry,observed_esp,c->return_pc,c->expected,registers[7],
               before_hash,after_hash,equal?"true":"false");
    }
    if(!equal) fail("live_abi_canary");
    DWORD ret=c->return_pc;
    TlsSetValue(canary_tls,c->previous); HeapFree(GetProcessHeap(),0,c);
    return ret;
}

static void stage_route(const char *name, DWORD *s) {
    if(GetCurrentThreadId()!=main_tid) fail("wrong_hook_thread");
    if(inject("unknown-route")) s[0]=0;
    BOOL known=FALSE;
    if(!strcmp(name,"shader")) known=s[0]==0x406442 || s[0]==0x406dce;
    if(!strcmp(name,"use")) known=s[0]==0x4062ff || s[0]==0x4076aa || s[0]==0x408310;
    if(!strcmp(name,"rect")) known=s[0]==0x406368 || s[0]==0x407967 || (s[0]>=0x407c40 && s[0]<0x408603);
    if(!strcmp(name,"atlas")) known=s[0]==0x4079dc;
    if(!strcmp(name,"swap")) known=s[0]==0x406374 || s[0]==0x408603;
    if(!known) fail("unknown_hook_route");
    if(context_seen && (get_dc()!=owning_dc || get_context()!=owning_context)) fail("changed_hook_context");
}

static DWORD WINAPI wrong_thread_control(void *unused) {
    (void)unused;
    DWORD s[]={0x406442}; stage_route("shader",s);
    fail("wrong_thread_control_did_not_reject");
    return 0;
}

static void stage_initialize(CONTEXT *context) {
    canary_tls=TlsAlloc();
    if(canary_tls==TLS_OUT_OF_INDEXES) fail("canary_tls_allocate");
    GetEnvironmentVariableA("EIDOLON_B_FAULT",fault,sizeof(fault));
    QueryPerformanceFrequency(&wall_frequency);
    char initial_resources[65];
    hash((void *)0x409100,0x43edc0-0x409100,initial_resources);
    record("initial_resources",",\"base\":\"0x00409100\",\"exclusive_end\":\"0x0043edc0\","
           "\"sha256\":\"%s\",\"initial_synth_tick\":%lu,\"priority_class\":%lu,"
           "\"rng_scope\":\"fresh native process; explicit RNG-state ownership requires Reverse review\"",
           initial_resources,*(DWORD *)0xb16bd20,GetPriorityClass(GetCurrentProcess()));
    record("stage_runtime",",\"schema\":2,\"diagnostic_breakpoints\":false,\"driver_callbacks\":false,"
           "\"completion_trap\":\"one-shot software INT3 at 0x401765\",\"fault\":\"%s\","
           "\"log_policy\":\"ordered checked WriteFile and close per event; OS-cache flush per completed frame; payload flush per file\"",fault);
    if(inject("wrong-thread")) {
        HANDLE thread=CreateThread(NULL,0,wrong_thread_control,NULL,0,NULL);
        if(!thread || WaitForSingleObject(thread,10000)!=WAIT_OBJECT_0) fail("wrong_thread_control_timeout");
        fail("wrong_thread_control_unexpected_return");
    }
    native_initialize(context);
    char retention_path[32768];
    if(!GetEnvironmentVariableA("EIDOLON_B_RETENTION",retention_path,sizeof(retention_path))) fail("retention_path");
    FILE *retention=fopen(retention_path,"r");
    if(!retention) fail("retention_open");
    unsigned n;
    while(fscanf(retention,"%u",&n)==1) {
        if(n>=27000 || retain_frames[n]) fail("retention_index");
        retain_frames[n]=TRUE;
    }
    if(!feof(retention) || fclose(retention)) fail("retention_read");
}

BOOL eidolon_completion(EXCEPTION_POINTERS *exception) {
    if(exception->ExceptionRecord->ExceptionCode!=EXCEPTION_BREAKPOINT ||
       exception->ExceptionRecord->ExceptionAddress!=(void *)0x401765) return FALSE;
    CONTEXT before=*exception->ContextRecord;
    BOOL result=original_completion(exception);
    save("completion-context-before.bin",&before,sizeof(before));
    save("completion-context-after.bin",exception->ContextRecord,sizeof(before));
    CONTEXT expected=before; expected.Eip=0x401765;
    if(memcmp(&expected,exception->ContextRecord,sizeof(expected))) fail("completion_context_canary");
    char a[65],b[65]; hash(&before,sizeof(before),a); hash(exception->ContextRecord,sizeof(before),b);
    record("completion_canary",",\"before_sha256\":\"%s\",\"after_sha256\":\"%s\","
            "\"only_allowed_change\":\"EIP rewind to displaced instruction\",\"equal_except_eip\":true",a,b);
    native_completion_arm(exception->ContextRecord);
    return result;
}

static void stage_summary(void) {
    for(unsigned i=0;i<18;++i) record("abi_summary",",\"api\":%u,\"returned_calls\":%lu",i,canary_counts[i]);
    LARGE_INTEGER wall; QueryPerformanceCounter(&wall);
    record("throughput",",\"frames\":%lu,\"wall_ticks\":%lld,\"frequency\":%lld",
           frame,wall.QuadPart-first_present_wall.QuadPart,wall_frequency.QuadPart);
    if(!full_run) record("planned_partial_stop",",\"frames\":%lu,\"exit_code\":0,\"finalized\":false,"
                        "\"dropped_frames\":0,\"dropped_audio_sample_frames\":0,\"errors\":[]",frame);
    stage_flush_log();
}

static void loaded_file(const char *role, HMODULE module) {
    char path[MAX_PATH],digest[65];
    if(!module || !GetModuleFileNameA(module,path,sizeof(path))) fail("loaded_module_path");
    HANDLE file=CreateFileA(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL);
    if(file==INVALID_HANDLE_VALUE) fail("loaded_module_open");
    DWORD size=GetFileSize(file,NULL),read=0;
    if(size==INVALID_FILE_SIZE || size>16777216) fail("loaded_module_extent");
    void *bytes=malloc(size);
    if(!bytes || !ReadFile(file,bytes,size,&read,NULL) || read!=size) fail("loaded_module_read");
    hash(bytes,size,digest); free(bytes); CloseHandle(file);
    /* Forward slashes preserve the exact Win32 path without JSON escaping. */
    for(char *p=path;*p;++p) if(*p=='\\') *p='/';
    record("loaded_module_bytes",",\"role\":\"%s\",\"module\":\"%p\",\"path\":\"%s\","
           "\"file_bytes\":%lu,\"file_sha256\":\"%s\"",role,module,path,size,digest);
}

static void stage_loaded(void) {
    if(loaded_observed) return;
    loaded_observed=TRUE;
    HMODULE self=NULL;
    GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                      (const char *)(uintptr_t)stage_loaded,&self);
    loaded_file("opengl32-shim",self); loaded_file("opengl32-backend",gl_module);
    loaded_file("winmm-shim",GetModuleHandleA("winmm.dll"));
    WCHAR path[MAX_PATH]; GetSystemDirectoryW(path,MAX_PATH); lstrcatW(path,L"\\winmm.dll");
    HMODULE wave=LoadLibraryW(path); loaded_file("winmm-backend",wave); FreeLibrary(wave);
}

DWORD core_position(DWORD *s) {
    if(GetCurrentThreadId()!=main_tid || s[0]!=0x407b97) fail("position_route_or_thread");
    if(!full_run && frame==stop_frames) { stage_summary(); ExitProcess(0); }
    if(full_run && (frame>27000 || native_queries!=frame)) fail("native_query_sequence");
    native_queries++;
    if(!frame) {
        native_physics("first-query");
        Canary *canary=TlsGetValue(canary_tls);
        if(!canary || canary->api!=4) fail("first_query_canary");
        save("native-first-query-main-fx.bin",canary->fp,512);
        DWORD ebp=s[-7];
        native_bytes("first-query","previous-seconds",ebp-0x38,4);
        record("native_first_query",",\"caller\":%lu,\"previous_seconds_bits\":%lu,\"x87_cw\":%u,\"mxcsr\":%lu",
               s[0],*(DWORD *)(uintptr_t)(ebp-0x38),*(WORD *)canary->fp,*(DWORD *)(canary->fp+24));
    }
    native_join();
    stage_loaded();
    DWORD result=original_core_position(s);
    /* Repeated calls to the actual routed wrappers, under their live ABI
     * canaries, observe one epoch without advancing the application's frame. */
    DWORD tick[2],time[2]; LARGE_INTEGER counter[2],frequency[2];
    for(unsigned i=0;i<2;++i) {
        tick[i]=stage_tick(); time[i]=stage_time();
        stage_qpc(&counter[i]); stage_qpf(&frequency[i]);
    }
    DWORD ms=epoch+(DWORD)((uint64_t)frame*1000/60);
    LONGLONG qpc=(uint64_t)epoch*60000+(uint64_t)frame*1000000;
    if(tick[0]!=ms || tick[1]!=ms || time[0]!=ms || time[1]!=ms ||
       counter[0].QuadPart!=qpc || counter[1].QuadPart!=qpc ||
       frequency[0].QuadPart!=60000000 || frequency[1].QuadPart!=60000000) fail("clock_epoch_canary");
    record("clock_routes_checked",",\"n\":%lu,\"epoch_ms\":%lu,\"milliseconds\":%lu,\"qpc\":%lld,"
           "\"qpf\":60000000,\"repeats\":2,\"sample_cursor\":%lu",frame,epoch,ms,qpc,frame*735);
    return result;
}

DWORD compat_core_volume(DWORD *s) {
    if(GetCurrentThreadId()!=main_tid || s[0]!=0x407a5a || s[1]!=0x806f || s[2] || s[3]!=0x8814 ||
       s[4]!=128 || s[5]!=128 || s[6]!=128 || s[7] || s[8]!=GL_RGBA || s[9]!=GL_FLOAT) fail("volume_upload_route");
    check("volume_preexisting_error");
    GLint unpack[9]; const GLenum names[]={GL_UNPACK_ALIGNMENT,GL_UNPACK_ROW_LENGTH,GL_UNPACK_SKIP_ROWS,
        GL_UNPACK_SKIP_PIXELS,GL_UNPACK_SWAP_BYTES,GL_UNPACK_LSB_FIRST,0x806e,0x806d,0x88ef};
    for(unsigned i=0;i<9;++i) get_integer(names[i],&unpack[i]);
    GLint texture; get_integer(0x806a,&texture); volume_texture=texture;
    char digest[65]; hash((void *)(uintptr_t)s[10],33554432,digest);
    memcpy(upload_digest,digest,sizeof(upload_digest));
    ((void (APIENTRY *)(GLenum,GLint,GLint,GLsizei,GLsizei,GLsizei,GLint,GLenum,GLenum,const void *))
       (uintptr_t)real_volume)(s[1],s[2],s[3],s[4],s[5],s[6],s[7],s[8],s[9],(void *)(uintptr_t)s[10]);
    check("volume_upload_error");
    void (APIENTRY *tex_iv)(GLenum,GLint,GLenum,GLint *)=(void *)GetProcAddress(gl_module,"glGetTexLevelParameteriv");
    GLint w,h,d,f; tex_iv(0x806f,0,GL_TEXTURE_WIDTH,&w); tex_iv(0x806f,0,GL_TEXTURE_HEIGHT,&h);
    tex_iv(0x806f,0,0x8071,&d); tex_iv(0x806f,0,GL_TEXTURE_INTERNAL_FORMAT,&f);
    check("volume_layout_error");
    record("volume_upload",",\"caller\":\"0x%08lx\",\"texture\":%d,\"source\":%lu,\"source_sha256\":\"%s\","
           "\"dimensions\":[%d,%d,%d],\"internal_format\":%d,\"unpack\":[%d,%d,%d,%d,%d,%d,%d,%d,%d]",
           s[0],texture,s[10],digest,w,h,d,f,unpack[0],unpack[1],unpack[2],unpack[3],unpack[4],unpack[5],unpack[6],unpack[7],unpack[8]);
    if(w!=128 || h!=128 || d!=128 || f!=0x8814 || !texture) fail("volume_layout");
    return 0;
}

static void stage_scene(DWORD *s) {
    DWORD ebp=s[-7];
    /* Query actual sampler unit bindings without changing the active unit on return. */
    GLint active, texture, program;
    get_integer(0x84e0,&active);
    void (APIENTRY *active_texture)(GLenum)=(void *)extension("glActiveTexture");
    active_texture(0x84c0); get_integer(0x806a,&texture); active_texture(active);
    get_integer(0x8b8d,&program); check("scene_state_queries");
    record("scene_state",",\"n\":%lu,\"seconds_f32_bits\":%lu,\"delta_f32_bits\":%lu,"
           "\"scene_local_beat_f32_bits\":%lu,\"scene_token\":%lu,\"last_program\":%d,"
           "\"unit0_texture3d\":%d,\"uploaded_volume\":%u,\"active_texture\":%d",
           frame,*(DWORD *)(uintptr_t)(ebp-0x34),*(DWORD *)(uintptr_t)(ebp-0x2c),
           *(DWORD *)(uintptr_t)(ebp-0x14),*(DWORD *)(uintptr_t)(ebp-0x18),program,texture,volume_texture,active);
}

static void stage_draw(DWORD *s) {
    GLint program,active,unit=-1,texture=0,fbo,viewport[4];
    get_integer(0x8b8d,&program); get_integer(0x84e0,&active);
    get_integer(0x8ca6,&fbo); get_integer(GL_VIEWPORT,viewport);
    GLint (APIENTRY *location)(GLuint,const char *)=(void *)extension("glGetUniformLocation");
    void (APIENTRY *uniform_i)(GLuint,GLint,GLint *)=(void *)extension("glGetUniformiv");
    void (APIENTRY *uniform_f)(GLuint,GLint,GLfloat *)=(void *)extension("glGetUniformfv");
    void (APIENTRY *active_texture)(GLenum)=(void *)extension("glActiveTexture");
    GLint clouds=location(program,"uClouds"),time_location=location(program,"uTimeResolution");
    union { GLfloat f[3]; DWORD bits[3]; } time={{0,0,0}};
    if(clouds>=0) {
        uniform_i(program,clouds,&unit);
        if(unit<0 || unit>=32) fail("cloud_sampler_unit");
        active_texture(0x84c0+unit); get_integer(0x806a,&texture); active_texture(active);
        if((GLuint)texture!=volume_texture) fail("cloud_sampler_volume_identity");
    }
    if(time_location>=0) uniform_f(program,time_location,time.f);
    check("scene_pass_query_error");
    record("scene_pass",",\"n\":%lu,\"caller\":\"0x%08lx\",\"program\":%d,\"draw_fbo\":%d,"
           "\"viewport\":[%d,%d,%d,%d],\"cloud_location\":%d,\"cloud_unit\":%d,\"cloud_texture\":%d,"
           "\"time_location\":%d,\"time_resolution_bits\":[%lu,%lu,%lu]",
           frame,s[0],program,fbo,viewport[0],viewport[1],viewport[2],viewport[3],clouds,unit,texture,
           time_location,time.bits[0],time.bits[1],time.bits[2]);
}

static void stage_capture(HDC dc) {
    if (!gl_module) gl_initialize();
    if(inject("wrong-hdc")) dc=NULL;
    if(inject("wrong-hglrc")) {
        BOOL (WINAPI *make_current)(HDC,HGLRC)=(void *)GetProcAddress(gl_module,"wglMakeCurrent");
        if(!make_current(NULL,NULL)) fail("wrong_context_control_setup");
    }
    if(!get_context() || get_dc()!=dc ||
       get_context()!=owning_context || dc!=owning_dc) fail("GL_owning_context");
    const GLenum queries[]={0x8ca6,0x8caa,GL_READ_BUFFER,GL_PACK_ALIGNMENT,GL_PACK_ROW_LENGTH,
        GL_PACK_SKIP_ROWS,GL_PACK_SKIP_PIXELS,GL_PACK_SWAP_BYTES,GL_PACK_LSB_FIRST,0x806c,0x806b,0x88ed,
        GL_RED_BITS,GL_GREEN_BITS,GL_BLUE_BITS,GL_ALPHA_BITS,0x80a9,0x8db9};
    GLint before[18],after[18];
    if(inject("preexisting-error")) {
        void (APIENTRY *enable)(GLenum)=(void *)GetProcAddress(gl_module,"glEnable"); enable(0xffffffff);
    }
    GLenum prior=get_error();
    for(unsigned i=0;i<18;++i) get_integer(queries[i],&before[i]);
    if(prior || get_error()) fail("GL_initial_error");
    if(before[0] || before[1]) fail("nondefault_final_framebuffer");
    if(before[12]!=8 || before[13]!=8 || before[14]!=8 || before[15]!=8 || before[16]) fail("unsupported_final_components_or_samples");
    GLint encoding,component;
    get_attachment(0x8d40,GL_BACK_LEFT,0x8210,&encoding); get_attachment(0x8d40,GL_BACK_LEFT,0x8211,&component);
    if(get_error() || component!=0x8c17) fail("unsupported_final_component_type");
    DWORD width=*(DWORD *)0xb17bf2c,height=*(DWORD *)0xb17bfac;
    if(width!=1920 || height!=1080) fail("final_dimensions");
    if(!pixels) { pixel_bytes=width*height*4; pixels=VirtualAlloc(NULL,pixel_bytes,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE); }
    if(!pixels) fail("frame_allocation");
    if(before[11]) bind_buffer(0x88eb,0);
    read_buffer(GL_BACK); pixel_store(GL_PACK_ALIGNMENT,1);
    for(unsigned i=4;i<=10;++i) pixel_store(queries[i],0);
    read_pixels(0,0,width,height,inject("readback-error")?0xffffffff:GL_RGBA,GL_UNSIGNED_BYTE,pixels);
    GLenum read_error=get_error();
    read_buffer(before[2]); for(unsigned i=3;i<=10;++i) pixel_store(queries[i],before[i]);
    if(before[11]) bind_buffer(0x88eb,before[11]);
    if(inject("restore-error")) pixel_store(GL_PACK_ALIGNMENT,before[3]==1?4:1);
    for(unsigned i=0;i<18;++i) get_integer(queries[i],&after[i]);
    char a[65],b[65],digest[65],path[32768]; hash(before,sizeof(before),a); hash(after,sizeof(after),b);
    record("frame_state",",\"n\":%lu,\"hdc\":\"%p\",\"hglrc\":\"%p\","
           "\"before\":[%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d],"
           "\"after\":[%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d]",
           frame,dc,get_context(),before[0],before[1],before[2],before[3],before[4],before[5],before[6],before[7],before[8],
           before[9],before[10],before[11],before[12],before[13],before[14],before[15],before[16],before[17],
           after[0],after[1],after[2],after[3],after[4],after[5],after[6],after[7],after[8],
           after[9],after[10],after[11],after[12],after[13],after[14],after[15],after[16],after[17]);
    if(read_error || get_error() || memcmp(before,after,sizeof(before)) || get_context()!=owning_context || get_dc()!=dc)
        fail("GL_readback_state_or_error");
    hash(pixels,pixel_bytes,digest);
    if(frame>=27000) fail("bounded_frame_extent");
    if(retain_frames[frame]) {
        if(snprintf(path,sizeof(path),"%s/frame-%05lu.rgba",folder,frame)>=(int)sizeof(path)) fail("frame_path");
        file_write(path,pixels,pixel_bytes,FALSE);
    }
    if(!frame) QueryPerformanceCounter(&first_present_wall);
    record("pre_present",",\"n\":%lu,\"clock_tick\":%lu,\"audio_position\":%lu,\"sha256\":\"%s\","
           "\"width\":%lu,\"height\":%lu,\"row_order\":\"bottom-up\",\"format\":\"rgba8\","
           "\"encoding\":%ld,\"component\":%ld,\"samples\":%ld,\"sRGB_enabled\":%ld,"
           "\"before_state_sha256\":\"%s\",\"after_state_sha256\":\"%s\",\"state_equal\":true",
           frame,frame,frame*735,digest,width,height,encoding,component,before[16],before[17],a,b);
}
