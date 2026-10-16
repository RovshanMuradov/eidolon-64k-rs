/* Included in the hash-checked copy of the accepted native observer.
 * New oracle: post-update physics and active floating uniforms
 * only at the predeclared scene-edge samples. No candidate values enter here. */
static FILE *physics_file,*curve_file;
static DWORD vector_frames,vector_draws,vector_pass,curve_words;
static DWORD vector_bytes;
static BOOL vector_samples[27000];
static void vector_write(FILE*f,const void*p,size_t bytes){if(bytes>3000000-vector_bytes)fail("vector_storage_guard");if(fwrite(p,1,bytes,f)!=bytes)fail("vector_write");vector_bytes+=bytes;}
static void vector_open(void){
    if(physics_file)return;
    char path[32832];snprintf(path,sizeof(path),"%s/physics.bin",folder);physics_file=fopen(path,"wb");
    snprintf(path,sizeof(path),"%s/curves.bin",folder);curve_file=fopen(path,"wb");
    snprintf(path,sizeof(path),"%s/samples.txt",folder);FILE*f=fopen(path,"r");
    if(!physics_file||!curve_file||!f)fail("vector_open");
    unsigned n;while(fscanf(f,"%u",&n)==1){if(n>=27000||vector_samples[n])fail("vector_sample");vector_samples[n]=TRUE;}
    if(!feof(f)||fclose(f))fail("vector_samples_read");
}
static void vector_draw(DWORD*s){
    vector_open();DWORD ordinal=vector_pass++;
    if(ordinal>=19)fail("vector_draw_extent");
    if(!vector_samples[frame]||(ordinal!=9&&ordinal!=18))return;
    GLint program,active,before[6],after[6];get_integer(0x8b8d,&program);get_integer(0x84e0,&active);
    get_integer(0x8ca6,before);get_integer(GL_VIEWPORT,before+1);before[5]=active;
    void(APIENTRY*program_iv)(GLuint,GLenum,GLint*)=(void*)extension("glGetProgramiv");
    void(APIENTRY*active_uniform)(GLuint,GLuint,GLsizei,GLsizei*,GLint*,GLenum*,char*)=(void*)extension("glGetActiveUniform");
    GLint(APIENTRY*location)(GLuint,const char*)=(void*)extension("glGetUniformLocation");
    void(APIENTRY*uniform_f)(GLuint,GLint,GLfloat*)=(void*)extension("glGetUniformfv");
    GLint count=0;program_iv(program,0x8b86,&count);if(count<0||count>256)fail("vector_uniform_count");
    DWORD header[]={frame,frame*735,ordinal,s[0],program,(DWORD)before[0],(DWORD)before[1],(DWORD)before[2],(DWORD)before[3],(DWORD)before[4],0};
    /* Fixed per-uniform records: name[64], scalar count, type, live location,
     * then16 raw f32 words (unused words are explicitly outside comparison). */
    BYTE values[256][140];DWORD retained=0;
    for(GLint i=0;i<count;i++){
        char name[64]={0};GLsizei length;GLint size;GLenum type;
        active_uniform(program,i,64,&length,&size,&type,name);if(length<0||length>=63)fail("vector_uniform_name");
        DWORD components=type==GL_FLOAT?1:type==0x8b50?2:type==0x8b51?3:type==0x8b52?4:type==0x8b5a?4:type==0x8b5b?9:type==0x8b5c?16:0;
        if(!components||!strcmp(name,"uTimeResolution"))continue;
        if(size!=1)fail("vector_float_array_shape");
        GLint loc=location(program,name);if(loc<0)fail("vector_uniform_location");
        BYTE*record=values[retained++];memset(record,0,140);memcpy(record,name,64);
        DWORD fields[]={components,type,(DWORD)loc};memcpy(record+64,fields,12);uniform_f(program,loc,(GLfloat*)(record+76));curve_words+=components;
    }
    header[10]=retained;vector_write(curve_file,header,sizeof(header));vector_write(curve_file,values,retained*140);vector_draws++;
    get_integer(0x8ca6,after);get_integer(GL_VIEWPORT,after+1);get_integer(0x84e0,after+5);
    if(memcmp(before,after,sizeof(before)))fail("vector_query_state");
    check("vector_query_error");
}
static void vector_capture(HDC dc){
    vector_open();if(!get_context()||get_context()!=owning_context||get_dc()!=dc||dc!=owning_dc||vector_pass!=19||frame!=vector_frames)fail("vector_phase");
    if(vector_samples[frame]){DWORD header[]={frame,frame*735,*(DWORD*)0x437024};vector_write(physics_file,header,sizeof(header));vector_write(physics_file,(void*)0xb17bdf0,256);}
    if(fflush(physics_file)||fflush(curve_file))fail("vector_flush");
    vector_frames++;vector_pass=0;
    if(frame==26999)record("vector_summary",",\"physics_frames\":%lu,\"sampled_draws\":%lu,\"float_words\":%lu",vector_frames,vector_draws,curve_words);
}
