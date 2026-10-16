/* A uses B's frozen clock/PCM implementation, never its proxy loader or GL
 * acquisition. Keep that source unchanged so B evidence remains auditable. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <string.h>
static DWORD a_environment(const char *name,char *buffer,DWORD size) {
    char renamed[128];
    if(!strncmp(name,"EIDOLON_B_",10)) {
        strcpy(renamed,"EIDOLON_A_"); strcat(renamed,name+10); name=renamed;
    }
    return GetEnvironmentVariableA(name,buffer,size);
}
#define GetEnvironmentVariableA a_environment
#include "../proxy-b/core.c"
#undef GetEnvironmentVariableA

static LONG CALLBACK completion_handler(EXCEPTION_POINTERS *e) {
    return eidolon_completion(e) ? EXCEPTION_CONTINUE_EXECUTION : EXCEPTION_CONTINUE_SEARCH;
}

/* Every error is sampled before acquisition and immediately after each GL
 * operation. Win32 last-error is never reported as the GL error enum. */
static void gl_check(const char *phase,const char *call,GLenum parameter) {
    GLenum error; unsigned count=0;
    while((error=get_error())!=GL_NO_ERROR) {
        record("gl_error",",\"phase\":\"%s\",\"call\":\"%s\",\"parameter\":\"0x%04x\","
               "\"enum\":\"0x%04x\",\"n\":%lu,\"hdc\":\"%p\",\"hglrc\":\"%p\"",
               phase,call,parameter,error,frame,get_dc(),get_context());
        if(++count==32) break;
    }
    if(count) fail(!strcmp(phase,"preexisting") ? "GL_preexisting_error" : "GL_acquisition_induced_error");
}

static void capture_a(HDC dc) {
    if(!gl_module) gl_initialize();
    HGLRC context=get_context();
    if(!context || get_dc()!=dc) fail("GL_owning_context");
    gl_check("preexisting","glGetError_before_acquisition",0);
    const GLenum queries[]={0x8ca6,0x8caa,GL_READ_BUFFER,GL_PACK_ALIGNMENT,GL_PACK_ROW_LENGTH,
        GL_PACK_SKIP_ROWS,GL_PACK_SKIP_PIXELS,GL_PACK_SWAP_BYTES,GL_PACK_LSB_FIRST,
        0x806c,0x806b,0x88ed,0x80a9,0x8db9};
    GLint before[14]={0},after[14]={0};
    for(unsigned i=0;i<14;i++) {
        get_integer(queries[i],&before[i]);gl_check("state_query","glGetIntegerv",queries[i]);
    }
    if(before[0] || before[1]) fail("nondefault_final_framebuffer");
    /* GL_{RED,GREEN,BLUE,ALPHA}_BITS are removed from core profiles.
     * Attachment queries identify the actual native default framebuffer. */
    const GLenum aq[]={0x8212,0x8213,0x8214,0x8215,0x8210,0x8211};
    GLint attachment[6]={0};
    for(unsigned i=0;i<6;i++) {
        get_attachment(0x8ca8,GL_BACK_LEFT,aq[i],&attachment[i]);
        gl_check("layout_query","glGetFramebufferAttachmentParameteriv",aq[i]);
    }
    record("gl_layout",",\"n\":%lu,\"draw_fbo\":%d,\"read_fbo\":%d,\"read_buffer\":%d,"
           "\"rgba_bits\":[%d,%d,%d,%d],\"encoding\":%d,\"component_type\":%d,\"samples\":%d,\"sRGB_enabled\":%d",
           frame,before[0],before[1],before[2],attachment[0],attachment[1],attachment[2],attachment[3],attachment[4],attachment[5],before[12],before[13]);
    if(attachment[0]!=8 || attachment[1]!=8 || attachment[2]!=8 || attachment[3]!=8 ||
       attachment[5]!=0x8c17 || before[12]) fail("unsupported_native_final_layout");
    DWORD width=*(DWORD *)0xb17bf2c,height=*(DWORD *)0xb17bfac;
    if(width!=1920 || height!=1080) fail("final_dimensions");
    if(!pixels) {
        pixel_bytes=width*height*4;
        pixels=VirtualAlloc(NULL,pixel_bytes,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
        if(!pixels) fail("frame_allocation");
    }
    if(before[11]) {bind_buffer(0x88eb,0);gl_check("readback_setup","glBindBuffer",0x88eb);}
    read_buffer(GL_BACK);gl_check("readback_setup","glReadBuffer",GL_BACK);
    for(unsigned i=3;i<=10;i++) {
        pixel_store(queries[i],i==3?1:0);gl_check("readback_setup","glPixelStorei",queries[i]);
    }
    read_pixels(0,0,width,height,GL_RGBA,GL_UNSIGNED_BYTE,pixels);
    gl_check("readback","glReadPixels",GL_RGBA);
    read_buffer(before[2]);gl_check("restore","glReadBuffer",before[2]);
    for(unsigned i=3;i<=10;i++) {
        pixel_store(queries[i],before[i]);gl_check("restore","glPixelStorei",queries[i]);
    }
    if(before[11]) {bind_buffer(0x88eb,before[11]);gl_check("restore","glBindBuffer",0x88eb);}
    for(unsigned i=0;i<14;i++) {
        get_integer(queries[i],&after[i]);gl_check("restored_state_query","glGetIntegerv",queries[i]);
    }
    if(memcmp(before,after,sizeof(before)) || get_context()!=context || get_dc()!=dc) fail("GL_state_leak");
    char state[65],digest[65],path[32768];hash(before,sizeof(before),state);hash(pixels,pixel_bytes,digest);
    if(snprintf(path,sizeof(path),"%s/frame-%05lu.rgba",folder,frame)>=(int)sizeof(path)) fail("frame_path");
    file_write(path,pixels,pixel_bytes,FALSE);
    record("pre_present",",\"n\":%lu,\"clock_tick\":%lu,\"audio_position\":%lu,\"sha256\":\"%s\","
           "\"width\":%lu,\"height\":%lu,\"format\":\"rgba8\",\"row_order\":\"bottom-up\","
           "\"state_equal\":true,\"before_state_sha256\":\"%s\",\"after_state_sha256\":\"%s\","
           "\"hdc\":\"%p\",\"hglrc\":\"%p\"",frame,frame,frame*735,digest,width,height,state,state,dc,context);
}

DWORD core_swap_a(DWORD *s) {
    if(s[0]!=0x406374 && s[0]!=0x408603) fail("unknown_present_route");
    BOOL is_timeline=s[0]==0x408603;
    if(is_timeline) {
        if(!timeline || !acquired) fail("present_before_clock_or_pcm");
        capture_a((void *)(uintptr_t)s[1]);
    }
    BOOL result=((BOOL(WINAPI *)(HDC))(uintptr_t)real_swap)((void *)(uintptr_t)s[1]);
    if(!result) fail("SwapBuffers_failed");
    if(is_timeline) {
        record("post_present",",\"n\":%lu,\"result\":true",frame);
        if(++frame==stop_frames) {
            record("planned_partial_stop",",\"frames\":%lu,\"exit_code\":0,\"finalized\":false",frame);
            ExitProcess(0);
        }
    }
    return result;
}

__declspec(dllexport) void WINAPI EidolonInitialize(BYTE *arena) {
    if(GetCurrentThreadId()!=*(DWORD *)(arena+32) || *(DWORD *)arena!=0x41324f4b) ExitProcess(125);
    /* This runs from a Frida-written IA32 trampoline, after LoadLibrary returns. */
    replace(0x406379,arena+16,9);
    if(!AddVectoredExceptionHandler(1,completion_handler)) ExitProcess(125);
    CONTEXT c={0}; c.ContextFlags=CONTEXT_ALL; RtlCaptureContext(&c);
    eidolon_core_initialize(&c);
    record("frida_helper_initialized",",\"arena\":\"%p\",\"entry_restored\":true,\"outside_DllMain\":true,\"snapshot_scope\":\"helper_RtlCaptureContext_not_original_entry\"",arena);
}
BOOL WINAPI DllMain(HINSTANCE instance,DWORD reason,LPVOID reserved) {
    (void)instance;(void)reason;(void)reserved;return TRUE;
}
