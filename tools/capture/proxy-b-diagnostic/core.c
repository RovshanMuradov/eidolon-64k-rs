/* D7/D8: retain the failed B implementation byte-for-byte; replace only its
 * pre-present diagnostic. No query substitution, error suppression or PASS. */
#define core_swap original_core_swap
#include "../proxy-b/core.c"
#undef core_swap

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
