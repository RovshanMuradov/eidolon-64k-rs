/* D9: the only source edit is the hash/caller-bound GLSL profile directive.
 * All source buffers belong to this proxy; original memory remains untouched.
 * The original G1 readback/error guard and clock/PCM implementation are retained. */
#define core_wgl_lookup original_core_wgl_lookup
#define eidolon_core_initialize original_core_initialize
#include "../proxy-b/core.c"
#undef core_wgl_lookup
#undef eidolon_core_initialize

extern void compat_shader(void), compat_use(void), compat_rect(void), compat_teximage(void);
static FARPROC real_shader, real_use, real_rect, real_teximage;
static DWORD creations, substitutions, target_program, draws;
static BOOL compatibility, context_seen;
static const char expected_sha[] = "57cdc43590d369b0744da71530cf879b6099cc6d80797809b59abd0fa5cc2182";

static void check(const char *where) {
    GLenum error = get_error();
    if (error) {
        record("gl_error", ",\"where\":\"%s\",\"enum\":\"0x%04x\"", where, error);
        fail(where);
    }
}

static void save(const char *name, const void *data, DWORD size) {
    char path[32768];
    if (snprintf(path,sizeof(path),"%s/%s",folder,name)>=(int)sizeof(path)) fail("compat_path");
    file_write(path,data,size,FALSE);
}

static PROC extension(const char *name) {
    PROC result=((PROC (WINAPI *)(LPCSTR))(uintptr_t)real_wgl_lookup)(name);
    if (!result || (uintptr_t)result <= 3 || (uintptr_t)result == (uintptr_t)-1) fail(name);
    return result;
}

static void context_info(void) {
    if (context_seen) return;
    if (!gl_module) gl_initialize();
    check("compat_context_preexisting_error");
    const GLubyte *(APIENTRY *get_string)(GLenum)=(void *)GetProcAddress(gl_module,"glGetString");
    GLint profile=0, flags=0;
    get_integer(0x9126,&profile); get_integer(0x821e,&flags);
    record("compat_context",",\"version\":\"%s\",\"glsl\":\"%s\",\"vendor\":\"%s\",\"renderer\":\"%s\","
           "\"profile_mask\":%d,\"flags\":%d,\"hdc\":\"%p\",\"hglrc\":\"%p\",\"driver_debug\":false",
           get_string(GL_VERSION),get_string(0x8b8c),get_string(GL_VENDOR),get_string(GL_RENDERER),
           profile,flags,get_dc(),get_context());
    check("compat_context_query_error");
    if (profile != 2 || flags != 0 || !get_context() || GetCurrentThreadId()!=main_tid) fail("unexpected_compat_context");
    context_seen=TRUE;
}

DWORD compat_core_shader(DWORD *s) {
    context_info();
    check("shader_preexisting_error");
    GLenum type=s[1]; GLsizei count=(GLsizei)s[2];
    const char *const *sources=(void *)(uintptr_t)s[3];
    if (count<=0 || count>256) fail("shader_source_array_extent");
    DWORD creation=++creations;
    BOOL target=(DWORD)(uintptr_t)sources[0]==0x409918;
    if (target && (s[0]!=0x406dce || type!=0x8b30 || count!=1 || target_program)) fail("target_shader_call");
    const char **effective=calloc((size_t)count,sizeof(*effective));
    char *replacement=NULL;
    if (!effective) fail("shader_array_allocation");
    for (GLsizei i=0;i<count;++i) {
        size_t length=strnlen(sources[i],1048576);
        if (length==1048576) fail("unterminated_shader");
        char raw_sha[65], effective_sha[65], name[128];
        hash(sources[i],(DWORD)length,raw_sha);
        effective[i]=sources[i];
        if (target) {
            if (length!=1310 || strcmp(raw_sha,expected_sha) || memcmp(sources[i],"#version 450\n",13)) fail("shader_fingerprint");
            if (compatibility) {
                replacement=malloc(length+15);
                if (!replacement) fail("shader_replacement_allocation");
                memcpy(replacement,"#version 450 compatibility\n",27);
                memcpy(replacement+27,sources[i]+13,length-13+1);
                if (memcmp(replacement+27,sources[i]+13,length-13+1)) fail("shader_body_changed");
                effective[i]=replacement;
                substitutions++;
            }
        }
        size_t effective_length=strlen(effective[i]);
        hash(effective[i],(DWORD)effective_length,effective_sha);
        snprintf(name,sizeof(name),"shader-%03lu-%03d-raw.glsl",creation,i); save(name,sources[i],(DWORD)length);
        snprintf(name,sizeof(name),"shader-%03lu-%03d-effective.glsl",creation,i); save(name,effective[i],(DWORD)effective_length);
        record("shader_source",",\"creation\":%lu,\"index\":%d,\"count\":%d,\"stage\":%u,\"caller\":\"0x%08lx\","
               "\"pointer\":\"%p\",\"raw_bytes\":%lu,\"raw_sha256\":\"%s\",\"effective_bytes\":%lu,"
               "\"effective_sha256\":\"%s\",\"transformed\":%s",
               creation,i,count,type,s[0],sources[i],(DWORD)length,raw_sha,(DWORD)effective_length,effective_sha,
               target&&compatibility ? "true":"false");
    }
    GLuint program=((GLuint (APIENTRY *)(GLenum,GLsizei,const char *const *))(uintptr_t)real_shader)(type,count,effective);
    GLenum call_error=get_error();
    void (APIENTRY *program_iv)(GLuint,GLenum,GLint *)=(void *)extension("glGetProgramiv");
    void (APIENTRY *program_log)(GLuint,GLsizei,GLsizei *,char *)=(void *)extension("glGetProgramInfoLog");
    GLint linked=0, log_size=0;
    program_iv(program,0x8b82,&linked); program_iv(program,0x8b84,&log_size);
    if (log_size<0 || log_size>1048576) fail("shader_log_extent");
    char *text=calloc((size_t)log_size+1,1); GLsizei length=0;
    if (!text) fail("shader_log_allocation");
    if (log_size) program_log(program,log_size,&length,text);
    check("shader_link_query_error");
    if (length<0 || length>log_size) fail("shader_log_length");
    char name[128], digest[65];
    snprintf(name,sizeof(name),"shader-%03lu-program-%u-link.log",creation,program);
    save(name,text,(DWORD)length); hash(text,(DWORD)length,digest);
    record("shader_program",",\"creation\":%lu,\"program\":%u,\"link_status\":%d,\"api_error\":%u,"
           "\"log_bytes\":%d,\"log_sha256\":\"%s\",\"substitutions\":%lu",creation,program,linked,call_error,length,digest,substitutions);
    if (target) {
        target_program=program;
        hash(sources[0],1310,digest);
        if (strcmp(digest,expected_sha)) fail("original_shader_memory_changed");
    }
    free(text); free(replacement); free(effective);
    if (!program || call_error) fail("shader_creation_api_error");
    /* Preserve original-use failure evidence for the negative control. */
    if (!linked && compatibility) fail("compat_shader_link_failed");
    return program;
}

DWORD compat_core_use(DWORD *s) {
    check("use_preexisting_error");
    GLint before=-1, after=-1;
    get_integer(0x8b8d,&before); check("use_current_before_query");
    ((void (APIENTRY *)(GLuint))(uintptr_t)real_use)(s[1]);
    GLenum error=get_error();
    get_integer(0x8b8d,&after); check("use_current_after_query");
    record("program_use",",\"caller\":\"0x%08lx\",\"program\":%lu,\"before_program\":%d,\"after_program\":%d,"
           "\"pre_error\":0,\"post_error\":%u,\"hdc\":\"%p\",\"hglrc\":\"%p\"",s[0],s[1],before,after,error,get_dc(),get_context());
    if (error || after!=(GLint)s[1]) fail("application_program_use_failed");
    return 0;
}

DWORD compat_core_rect(DWORD *s) {
    check("draw_preexisting_error");
    if (s[0]==0x407967 && draws++==0) {
        GLint fbo=0, viewport[4]={0}, program=0, mask[4]={0}, buffers[8]={0};
        get_integer(0x8ca6,&fbo); get_integer(GL_VIEWPORT,viewport);
        get_integer(0x8b8d,&program); get_integer(GL_COLOR_WRITEMASK,mask);
        for(unsigned i=0;i<8;++i) get_integer(0x8825+i,&buffers[i]);
        GLenum (APIENTRY *status)(GLenum)=(void *)extension("glCheckFramebufferStatus");
        GLboolean (APIENTRY *enabled)(GLenum)=(void *)GetProcAddress(gl_module,"glIsEnabled");
        GLint clamp=0; get_integer(0x891b,&clamp);
        GLenum complete=status(0x8d40);
        record("first_draw_state",",\"caller\":\"0x%08lx\",\"program\":%d,\"fbo\":%d,\"fbo_status\":%u,"
               "\"viewport\":[%d,%d,%d,%d],\"color_mask\":[%d,%d,%d,%d],\"draw_buffers\":[%d,%d,%d,%d,%d,%d,%d,%d],"
               "\"blend\":%u,\"srgb\":%u,\"clamp_fragment_color\":%d,\"vertex_path\":\"glRecti\"",
               s[0],program,fbo,complete,viewport[0],viewport[1],viewport[2],viewport[3],mask[0],mask[1],mask[2],mask[3],
               buffers[0],buffers[1],buffers[2],buffers[3],buffers[4],buffers[5],buffers[6],buffers[7],
               enabled(GL_BLEND),enabled(0x8db9),clamp);
        check("first_draw_state_queries");
        if (!target_program || program!=(GLint)target_program || complete!=0x8cd5 ||
            substitutions!=(compatibility ? 1u:0u)) fail("first_draw_target_or_fbo");
    }
    ((void (APIENTRY *)(GLint,GLint,GLint,GLint))(uintptr_t)real_rect)(s[1],s[2],s[3],s[4]);
    check("original_glRecti_error");
    return 0;
}

DWORD compat_core_teximage(DWORD *s) {
    check("atlas_preexisting_error");
    ((void (APIENTRY *)(GLenum,GLint,GLenum,GLenum,void *))(uintptr_t)real_teximage)(s[1],s[2],s[3],s[4],(void *)(uintptr_t)s[5]);
    check("original_glGetTexImage_error");
    if (s[0]!=0x4079dc || s[1]!=GL_TEXTURE_2D || s[2] || s[3]!=GL_RGBA || s[4]!=GL_FLOAT) fail("atlas_call_identity");
    void (APIENTRY *tex_iv)(GLenum,GLint,GLenum,GLint *)=(void *)GetProcAddress(gl_module,"glGetTexLevelParameteriv");
    GLint width=0,height=0,format=0,pack[8]={0};
    const GLenum queries[]={GL_PACK_ALIGNMENT,GL_PACK_ROW_LENGTH,GL_PACK_SKIP_ROWS,GL_PACK_SKIP_PIXELS,
                           GL_PACK_SWAP_BYTES,GL_PACK_LSB_FIRST,0x806c,0x806b};
    tex_iv(GL_TEXTURE_2D,0,GL_TEXTURE_WIDTH,&width); tex_iv(GL_TEXTURE_2D,0,GL_TEXTURE_HEIGHT,&height);
    tex_iv(GL_TEXTURE_2D,0,GL_TEXTURE_INTERNAL_FORMAT,&format);
    for (unsigned i=0;i<8;++i) get_integer(queries[i],&pack[i]);
    check("atlas_layout_queries");
    if(width!=16384 || height!=128 || format!=0x8814 || pack[1] || pack[2] || pack[3] || pack[4] || pack[5] || pack[6] || pack[7]) fail("atlas_layout");
    DWORD bytes=16384*128*16; char digest[65];
    hash((void *)(uintptr_t)s[5],bytes,digest); save("noise-atlas.rgba32f",(void *)(uintptr_t)s[5],bytes);
    record("noise_atlas",",\"caller\":\"0x%08lx\",\"pointer\":\"0x%08lx\",\"bytes\":%lu,\"sha256\":\"%s\","
           "\"width\":%d,\"height\":%d,\"internal_format\":%d,\"pack\":[%d,%d,%d,%d,%d,%d,%d,%d]",
           s[0],s[5],bytes,digest,width,height,format,pack[0],pack[1],pack[2],pack[3],pack[4],pack[5],pack[6],pack[7]);
    return 0;
}

DWORD core_wgl_lookup(DWORD *s) {
    const char *name=(void *)(uintptr_t)s[1];
    FARPROC result=(FARPROC)(uintptr_t)original_core_wgl_lookup(s);
    if (!strcmp(name,"glCreateShaderProgramv")) { real_shader=result; return (DWORD)(uintptr_t)compat_shader; }
    if (!strcmp(name,"glUseProgram")) { real_use=result; return (DWORD)(uintptr_t)compat_use; }
    return (DWORD)(uintptr_t)result;
}

void eidolon_core_initialize(CONTEXT *context) {
    original_core_initialize(context);
    char mode[32]={0};
    GetEnvironmentVariableA("EIDOLON_B_COMPAT",mode,sizeof(mode));
    compatibility=!strcmp(mode,"450-compatibility");
    if (!compatibility && strcmp(mode,"unchanged")) fail("compat_mode");
    record("compatibility_experiment",",\"transformation\":\"%s\",\"expected_raw_sha256\":\"%s\",\"reference_eligible\":false",mode,expected_sha);
    slot(0x40905c,(FARPROC)compat_rect,&real_rect);
    slot(0x409044,(FARPROC)compat_teximage,&real_teximage);
}
