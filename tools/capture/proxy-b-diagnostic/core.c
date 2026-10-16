/* D7/D8: retain the failed B implementation byte-for-byte; replace only its
 * pre-present diagnostic. No query substitution, error suppression or PASS. */
#define core_swap original_core_swap
#define core_wgl_lookup original_core_wgl_lookup
#include "../proxy-b/core.c"
#undef core_swap
#undef core_wgl_lookup

static BOOL debug_enabled, debug_error;
static DWORD debug_caller;
static DWORD debug_program;
static HDC debug_dc;
static HGLRC debug_context;

static void APIENTRY diagnostic_message(GLenum source, GLenum type, GLuint id,
        GLenum severity, GLsizei length, const char *message, const void *user) {
    (void)user;
    if (type != 0x824c || debug_error) return; /* GL_DEBUG_TYPE_ERROR */
    debug_error = TRUE;
    char hex[2049];
    unsigned n = length < 0 ? 0 : (unsigned)length;
    if (n > 1024) n = 1024;
    for (unsigned i=0;i<n;++i) sprintf(hex+2*i,"%02x",(unsigned char)message[i]);
    hex[2*n]=0;
    record("driver_error",",\"source\":\"0x%04x\",\"type\":\"0x%04x\",\"id\":%u,"
           "\"severity\":\"0x%04x\",\"message_hex\":\"%s\",\"original_length\":%d,"
           "\"last_lookup_caller\":\"0x%08lx\",\"hdc\":\"%p\",\"hglrc\":\"%p\"",
           source,type,id,severity,hex,length,debug_caller,debug_dc,debug_context);
    /* Native debugger captures the live callback stack while the actual
     * producing GL call has not returned. No GL error is consumed here. */
    DebugBreak();
}

DWORD core_wgl_lookup(DWORD *s) {
    char setting[8];
    if (!GetEnvironmentVariableA("EIDOLON_B_DRIVER_DEBUG",setting,sizeof(setting)))
        return original_core_wgl_lookup(s);
    if (!gl_module) gl_initialize();
    if (debug_error) {
        GLenum error=get_error();
        record("driver_error_returned",",\"enum\":\"0x%04x\",\"next_lookup_caller\":\"0x%08lx\"",error,s[0]);
        GLboolean (APIENTRY *is_program)(GLuint)=(void *)
            ((PROC (WINAPI *)(LPCSTR))(uintptr_t)real_wgl_lookup)("glIsProgram");
        void (APIENTRY *program_iv)(GLuint,GLenum,GLint *)=(void *)
            ((PROC (WINAPI *)(LPCSTR))(uintptr_t)real_wgl_lookup)("glGetProgramiv");
        void (APIENTRY *program_log)(GLuint,GLsizei,GLsizei *,char *)=(void *)
            ((PROC (WINAPI *)(LPCSTR))(uintptr_t)real_wgl_lookup)("glGetProgramInfoLog");
        if (!is_program || !program_iv || !program_log) fail("program_diagnostic_unavailable");
        GLboolean exists=is_program(debug_program);
        GLenum check=get_error();
        record("program_is_program",",\"program\":%lu,\"value\":%u,\"enum\":\"0x%04x\"",debug_program,exists,check);
        if (!exists || check) fail("program_diagnostic_invalid_object");
        const GLenum queries[]={0x8b82,0x8b84,0x8b85}; /* LINK_STATUS, INFO_LOG_LENGTH, ATTACHED_SHADERS */
        GLint lengths[3]={0};
        for(unsigned i=0;i<3;++i) {
            program_iv(debug_program,queries[i],&lengths[i]);check=get_error();
            record("program_query",",\"program\":%lu,\"parameter\":\"0x%04x\",\"value\":%d,\"enum\":\"0x%04x\"",debug_program,queries[i],lengths[i],check);
            if(check) fail("program_diagnostic_query_error");
        }
        if(lengths[1]>0 && lengths[1]<65536) {
            char *text=malloc(lengths[1]); GLsizei length=0;
            if(!text) fail("program_log_allocation");
            program_log(debug_program,lengths[1],&length,text);check=get_error();
            record("program_log",",\"program\":%lu,\"length\":%d,\"enum\":\"0x%04x\"",debug_program,length,check);
            if(check || length<0 || length>=lengths[1]) fail("program_log_error");
            char path[32768];
            if(snprintf(path,sizeof(path),"%s/program-%lu-link.log",folder,debug_program)>=(int)sizeof(path)) fail("program_log_path");
            file_write(path,text,length,FALSE);free(text);
        }
        fail("GL_driver_attributed_application_error");
    }
    if (!debug_enabled) {
        GLenum prior=get_error();
        debug_dc=get_dc(); debug_context=get_context();
        record("driver_debug_entry",",\"enum\":\"0x%04x\",\"hdc\":\"%p\",\"hglrc\":\"%p\"",prior,debug_dc,debug_context);
        if (prior || !debug_context) fail("driver_debug_preexisting_error");
        void (APIENTRY *callback)(void *,const void *)=(void *)
            ((PROC (WINAPI *)(LPCSTR))(uintptr_t)real_wgl_lookup)("glDebugMessageCallback");
        void (APIENTRY *enable)(GLenum)=(void *)GetProcAddress(gl_module,"glEnable");
        if (!callback || !enable) fail("driver_debug_unavailable");
        callback((void *)diagnostic_message,NULL);
        enable(0x92e0); enable(0x8242); /* DEBUG_OUTPUT, DEBUG_OUTPUT_SYNCHRONOUS */
        GLenum error=get_error();
        record("driver_debug_enabled",",\"enum\":\"0x%04x\",\"diagnostic_state_change\":true",error);
        if (error) fail("driver_debug_setup_error");
        debug_enabled=TRUE;
    }
    debug_caller=s[0];
    if(!strcmp((const char *)(uintptr_t)s[1],"glUseProgram")) {
        debug_program=s[2];
        GLenum prior=get_error();
        record("application_glUseProgram_before",",\"call_pc\":\"0x%08lx\",\"program\":%lu,\"enum\":\"0x%04x\"",s[0],debug_program,prior);
        if(prior) fail("application_error_before_glUseProgram");
    }
    return original_core_wgl_lookup(s);
}

extern void APIENTRY diagnostic_get_integer(GLenum, GLint *);
extern char diagnostic_gl_call, diagnostic_gl_return;
/* A named instruction and return PC bind the producing call to disassembly.
 * The incoming Win32/stdcall arguments are forwarded unchanged. */
__asm__(".text\n"
        ".globl _diagnostic_get_integer@8\n_diagnostic_get_integer@8:\n"
        "pushl 8(%esp)\npushl 8(%esp)\n"
        ".globl _diagnostic_gl_call\n_diagnostic_gl_call:\n"
        "call *_get_integer\n"
        ".globl _diagnostic_gl_return\n_diagnostic_gl_return:\n"
        "ret $8\n");

static GLenum diagnostic_check(const char *phase, const char *call, GLenum parameter,
                               const GLint *value, DWORD caller) {
    GLenum error = get_error();
    record("gl_check", ",\"phase\":\"%s\",\"call\":\"%s\",\"parameter\":\"0x%04x\","
           "\"output_pointer\":\"%p\",\"output_value\":%ld,\"enum\":\"0x%04x\","
           "\"n\":%lu,\"app_return\":\"0x%08lx\",\"hdc\":\"%p\",\"hglrc\":\"%p\"",
           phase, call, parameter, value, value ? (long)*value : 0,
           error, frame, caller, get_dc(), get_context());
    return error;
}

/* Context characterization happens AFTER the first error has been identified;
 * these extra GL calls cannot have produced the earlier failed query. */
static void diagnostic_context(DWORD caller) {
    const GLubyte *(APIENTRY *get_string)(GLenum) = (void *)GetProcAddress(gl_module,"glGetString");
    if (!get_string) fail("diagnostic_glGetString_missing");
    const GLenum strings[] = {GL_VERSION, GL_VENDOR, GL_RENDERER};
    for (unsigned i=0;i<3;++i) {
        const char *value = (const char *)get_string(strings[i]);
        if (diagnostic_check("context_after_failure","glGetString",strings[i],NULL,caller))
            fail("diagnostic_context_string_error");
        record("gl_context_string",",\"parameter\":\"0x%04x\",\"value\":\"%s\"",strings[i],value ? value : "");
    }
    const GLenum queries[] = {0x821b,0x821c,0x9126,0x821e};
    for (unsigned i=0;i<4;++i) {
        GLint value = -1;
        diagnostic_get_integer(queries[i],&value);
        if (diagnostic_check("context_after_failure","glGetIntegerv",queries[i],&value,caller))
            fail("diagnostic_context_query_error");
    }
}

DWORD core_swap(DWORD *s) {
    if (s[0] != 0x406374 && s[0] != 0x408603) fail("unknown_present_route");
    if (s[0] == 0x406374) return original_core_swap(s);
    if (!timeline || !acquired) fail("present_before_clock_or_pcm");
    if (!gl_module) gl_initialize();
    HDC dc = (void *)(uintptr_t)s[1];
    if (!get_context() || get_dc()!=dc) fail("GL_owning_context");
    MEMORY_BASIC_INFORMATION info;
    if (!VirtualQuery((void *)core_swap,&info,sizeof(info))) fail("diagnostic_module_mapping");
    record("gl_diagnostic_site",",\"app_call\":\"0x004085fd\",\"app_return\":\"0x%08lx\","
           "\"proxy_base\":\"%p\",\"call_pc\":\"%p\",\"return_pc\":\"%p\","
           "\"backend_module\":\"%p\",\"backend_glGetIntegerv\":\"%p\",\"hdc\":\"%p\",\"hglrc\":\"%p\"",
           s[0],info.AllocationBase,&diagnostic_gl_call,&diagnostic_gl_return,
           gl_module,get_integer,dc,get_context());
    if (diagnostic_check("preexisting","glGetError_before_state_queries",0,NULL,s[0])) {
        diagnostic_context(s[0]);
        fail("GL_preexisting_error");
    }
    /* Exact original B order and pnames, including any invalid legacy query. */
    const GLenum queries[] = {0x8ca6,0x8caa,GL_READ_BUFFER,GL_PACK_ALIGNMENT,GL_PACK_ROW_LENGTH,
        GL_PACK_SKIP_ROWS,GL_PACK_SKIP_PIXELS,GL_PACK_SWAP_BYTES,GL_PACK_LSB_FIRST,
        0x806c,0x806b,0x88ed,GL_RED_BITS,GL_GREEN_BITS,GL_BLUE_BITS,GL_ALPHA_BITS,0x80a9,0x8db9};
    for (unsigned i=0;i<sizeof(queries)/sizeof(*queries);++i) {
        GLint value = 0x12345678;
        diagnostic_get_integer(queries[i],&value);
        if (diagnostic_check("original_state_query","glGetIntegerv",queries[i],&value,s[0])) {
            record("gl_first_producer",",\"query_index\":%u,\"call_pc\":\"%p\",\"return_pc\":\"%p\","
                   "\"attribution\":\"acquisition\",\"preexisting_error\":false,\"readback_started\":false",
                   i,&diagnostic_gl_call,&diagnostic_gl_return);
            diagnostic_context(s[0]);
            fail("GL_acquisition_induced_error");
        }
    }
    fail("diagnostic_original_initial_guard_not_reproduced");
    return FALSE;
}
