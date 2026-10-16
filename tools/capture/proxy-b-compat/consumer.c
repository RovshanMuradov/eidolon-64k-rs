/* Observations are limited to the actual program20 consumer draw, after every
 * preceding native frame. All observation-only state is queried and restored. */
static BOOL consumer_pending;
static DWORD consumer_count;
static const GLenum consumer_queries[]={0x84e0,0x8b8d,0x8ca6,0x8caa,GL_READ_BUFFER,
    GL_PACK_ALIGNMENT,GL_PACK_ROW_LENGTH,GL_PACK_SKIP_ROWS,GL_PACK_SKIP_PIXELS,GL_PACK_SWAP_BYTES,
    GL_PACK_LSB_FIRST,0x806c,0x806b,0x88ed,0x806a,GL_TEXTURE_BINDING_2D,0x8919};

static void consumer_state(GLint *state) {
    for(unsigned i=0;i<17;++i) get_integer(consumer_queries[i],&state[i]);
    for(unsigned i=0;i<8;++i) get_integer(0x8825+i,&state[17+i]);
    get_integer(GL_VIEWPORT,state+25);
}

static void consumer_pack(const GLint *state,BOOL restore) {
    bind_buffer(0x88eb,restore?state[13]:0);
    for(unsigned i=5;i<=12;++i) pixel_store(consumer_queries[i],restore?state[i]:(i==5?1:0));
}

static void consumer_restoration(const char *phase,const GLint *before) {
    GLint after[29]; consumer_state(after); check("consumer_restoration_query");
    char name[128],a[65],b[65];
    snprintf(name,sizeof(name),"consumer-%05lu-%s-before-state.bin",frame,phase); save(name,before,29*4);
    snprintf(name,sizeof(name),"consumer-%05lu-%s-after-state.bin",frame,phase); save(name,after,sizeof(after));
    hash(before,29*4,a); hash(after,sizeof(after),b);
    record("consumer_restoration",",\"n\":%lu,\"phase\":\"%s\",\"before_sha256\":\"%s\",\"after_sha256\":\"%s\",\"equal\":%s",
           frame,phase,a,b,memcmp(before,after,sizeof(after))?"false":"true");
    if(memcmp(before,after,sizeof(after))) fail("consumer_restoration");
}

static void consumer_before(DWORD *s) {
    if(frame<5760 || frame>5762 || s[0]!=0x4085d7) return;
    GLint program; get_integer(0x8b8d,&program);
    if(program!=22) return;
    if(consumer_pending) fail("consumer_duplicate");
    consumer_pending=TRUE; consumer_count++;
    GLint before[29]; consumer_state(before); check("consumer_before_state");
    GLint (APIENTRY *location)(GLuint,const char *)=(void *)extension("glGetUniformLocation");
    void (APIENTRY *uniform_i)(GLuint,GLint,GLint *)=(void *)extension("glGetUniformiv");
    void (APIENTRY *uniform_f)(GLuint,GLint,GLfloat *)=(void *)extension("glGetUniformfv");
    void (APIENTRY *active_texture)(GLenum)=(void *)extension("glActiveTexture");
    void (APIENTRY *tex_iv)(GLenum,GLint,GLenum,GLint *)=(void *)GetProcAddress(gl_module,"glGetTexLevelParameteriv");
    void (APIENTRY *tex_param)(GLenum,GLenum,GLint *)=(void *)GetProcAddress(gl_module,"glGetTexParameteriv");
    void (APIENTRY *sampler_param)(GLuint,GLenum,GLint *)=(void *)extension("glGetSamplerParameteriv");
    void (APIENTRY *tex_image)(GLenum,GLint,GLenum,GLenum,void *)=(void *)GetProcAddress(gl_module,"glGetTexImage");
    GLint loc=location(program,"uClouds"),unit=-1,texture,sampler,dimensions[4],parameters[5],time_loc=location(program,"uTimeResolution");
    union { GLfloat f[3]; DWORD bits[3]; } time={{0,0,0}};
    if(loc<0 || time_loc<0) fail("consumer_active_uniform");
    uniform_i(program,loc,&unit); uniform_f(program,time_loc,time.f);
    if(unit<0 || unit>=32) fail("consumer_unit");
    active_texture(0x84c0+unit); get_integer(0x806a,&texture); get_integer(0x8919,&sampler);
    const GLenum dimension_names[]={GL_TEXTURE_WIDTH,GL_TEXTURE_HEIGHT,0x8071,GL_TEXTURE_INTERNAL_FORMAT};
    const GLenum parameter_names[]={GL_TEXTURE_MIN_FILTER,GL_TEXTURE_MAG_FILTER,GL_TEXTURE_WRAP_S,GL_TEXTURE_WRAP_T,0x8072};
    for(unsigned i=0;i<4;++i) tex_iv(0x806f,0,dimension_names[i],&dimensions[i]);
    for(unsigned i=0;i<5;++i) {
        if(sampler) sampler_param(sampler,parameter_names[i],&parameters[i]);
        else tex_param(0x806f,parameter_names[i],&parameters[i]);
    }
    check("consumer_volume_queries");
    if(texture!=(GLint)volume_texture || dimensions[0]!=128 || dimensions[1]!=128 || dimensions[2]!=128 || dimensions[3]!=0x8814)
        fail("consumer_volume_layout");
    for(unsigned i=0;i<5;++i) if(parameters[i]!=(i<2?GL_LINEAR:GL_REPEAT)) fail("consumer_volume_parameters");
    void *volume=VirtualAlloc(NULL,33554432,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
    if(!volume) fail("consumer_volume_allocation");
    consumer_pack(before,FALSE);
    tex_image(0x806f,0,GL_RGBA,GL_FLOAT,volume); check("consumer_volume_readback");
    consumer_pack(before,TRUE); active_texture(before[0]);
    consumer_restoration("volume",before);
    char name[128],digest[65];
    snprintf(name,sizeof(name),"consumer-%05lu-volume.rgba32f",frame); save(name,volume,33554432); hash(volume,33554432,digest);
    VirtualFree(volume,0,MEM_RELEASE);
    record("consumer_volume",",\"n\":%lu,\"caller\":%lu,\"program\":%d,\"program_index\":20,\"source_creation\":22,"
           "\"cloud_location\":%d,\"unit\":%d,\"texture\":%d,\"sampler\":%d,\"dimensions\":[%d,%d,%d],\"internal_format\":%d,"
           "\"filter_wrap\":[%d,%d,%d,%d,%d],\"time_location\":%d,\"time_resolution_bits\":[%lu,%lu,%lu],"
           "\"draw_fbo\":%d,\"file\":\"%s\",\"bytes\":33554432,\"sha256\":\"%s\",\"upload_sha256\":\"%s\"",
           frame,s[0],program,loc,unit,texture,sampler,dimensions[0],dimensions[1],dimensions[2],dimensions[3],
           parameters[0],parameters[1],parameters[2],parameters[3],parameters[4],time_loc,time.bits[0],time.bits[1],time.bits[2],before[2],name,digest,upload_digest);
    if(strcmp(digest,upload_digest)) fail("consumer_volume_upload_mismatch");
}

static void consumer_after(DWORD *s) {
    if(!consumer_pending) return;
    if(s[0]!=0x4085d7) fail("consumer_after_route");
    consumer_pending=FALSE;
    GLint before[29]; consumer_state(before); check("consumer_attachment_before");
    void (APIENTRY *bind_fbo)(GLenum,GLuint)=(void *)extension("glBindFramebuffer");
    void (APIENTRY *bind_texture)(GLenum,GLuint)=(void *)GetProcAddress(gl_module,"glBindTexture");
    void (APIENTRY *tex_iv)(GLenum,GLint,GLenum,GLint *)=(void *)GetProcAddress(gl_module,"glGetTexLevelParameteriv");
    bind_fbo(0x8ca8,before[2]);
    GLint consumer_read; get_integer(GL_READ_BUFFER,&consumer_read);
    consumer_pack(before,FALSE);
    unsigned attachments=0;
    for(unsigned i=0;i<8;++i) {
        GLenum attachment=before[17+i];
        if(attachment==GL_NONE) continue;
        GLint type,texture,level,width,height,format,component,encoding;
        get_attachment(0x8ca9,attachment,0x8cd0,&type); get_attachment(0x8ca9,attachment,0x8cd1,&texture);
        get_attachment(0x8ca9,attachment,0x8cd2,&level); get_attachment(0x8ca9,attachment,0x8211,&component);
        get_attachment(0x8ca9,attachment,0x8210,&encoding);
        if(type!=GL_TEXTURE || level!=0 || !texture) fail("consumer_attachment_type");
        bind_texture(GL_TEXTURE_2D,texture);
        tex_iv(GL_TEXTURE_2D,level,GL_TEXTURE_WIDTH,&width); tex_iv(GL_TEXTURE_2D,level,GL_TEXTURE_HEIGHT,&height);
        tex_iv(GL_TEXTURE_2D,level,GL_TEXTURE_INTERNAL_FORMAT,&format);
        bind_texture(GL_TEXTURE_2D,before[15]); check("consumer_attachment_layout");
        if(width<=0 || width>1920 || height<=0 || height>1080 || (component!=GL_FLOAT && component!=0x8c17)) fail("consumer_attachment_extent");
        GLenum scalar=component==GL_FLOAT?GL_FLOAT:GL_UNSIGNED_BYTE;
        DWORD bytes=width*height*4*(scalar==GL_FLOAT?4:1);
        void *pixels=VirtualAlloc(NULL,bytes,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
        if(!pixels) fail("consumer_attachment_allocation");
        read_buffer(attachment); read_pixels(0,0,width,height,GL_RGBA,scalar,pixels); check("consumer_attachment_readback");
        char name[128],digest[65];
        snprintf(name,sizeof(name),"consumer-%05lu-attachment-%u.%s",frame,i,scalar==GL_FLOAT?"rgba32f":"rgba");
        save(name,pixels,bytes); hash(pixels,bytes,digest); VirtualFree(pixels,0,MEM_RELEASE);
        record("consumer_attachment",",\"n\":%lu,\"program\":%d,\"draw_fbo\":%d,\"draw_buffer_index\":%u,\"attachment\":%u,"
               "\"texture\":%d,\"level\":%d,\"dimensions\":[%d,%d],\"internal_format\":%d,\"component\":%d,\"encoding\":%d,"
               "\"read_format\":6408,\"read_type\":%u,\"row_order\":\"bottom-up\",\"file\":\"%s\",\"bytes\":%lu,\"sha256\":\"%s\"",
               frame,before[1],before[2],i,attachment,texture,level,width,height,format,component,encoding,scalar,name,bytes,digest);
        attachments++;
    }
    read_buffer(consumer_read); bind_fbo(0x8ca8,before[3]); read_buffer(before[4]); consumer_pack(before,TRUE);
    consumer_restoration("attachments",before);
    if(!attachments) fail("consumer_no_attachments");
    record("consumer_draw_complete",",\"n\":%lu,\"attachments\":%u,\"ordinal\":%lu",frame,attachments,consumer_count);
}
