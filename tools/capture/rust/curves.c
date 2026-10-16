/* Included by semantic.c; same raw GPU query schema as the bounded native oracle. */
static int curves_only;static BYTE curve_samples[27000];static FILE *curve_file;static DWORD curve_bytes;
static void curve_write(const void*p,DWORD bytes){if(bytes>3000000-curve_bytes)fail("curve storage guard");write_bytes(curve_file,p,bytes);curve_bytes+=bytes;}
static void curve_draw(DWORD caller, DWORD pass){
 if(!curve_samples[frame]||(pass!=9&&pass!=18))return;
 GLint program,before[6],after[6];glGetIntegerv(0x8b8d,&program);glGetIntegerv(0x8ca6,before);glGetIntegerv(GL_VIEWPORT,before+1);glGetIntegerv(0x84e0,before+5);
 void(APIENTRY*program_iv)(GLuint,GLenum,GLint*)=(void*)lookup("glGetProgramiv");
 void(APIENTRY*active_uniform)(GLuint,GLuint,GLsizei,GLsizei*,GLint*,GLenum*,char*)=(void*)lookup("glGetActiveUniform");
 if(!program_iv||!active_uniform||glGetError())fail("curve query setup");
 GLint count=0;program_iv(program,0x8b86,&count);if(count<0||count>256)fail("curve count");
 DWORD header[]={frame,frame*735,pass,caller,program,(DWORD)before[0],(DWORD)before[1],(DWORD)before[2],(DWORD)before[3],(DWORD)before[4],0};
 BYTE values[256][140];DWORD retained=0;
 for(GLint i=0;i<count;i++){
  char name[64]={0};GLsizei length;GLint size;GLenum type;active_uniform(program,i,64,&length,&size,&type,name);
  if(length<0||length>=63)fail("curve name");
  DWORD components=type==GL_FLOAT?1:type==0x8b50?2:type==0x8b51?3:type==0x8b52?4:type==0x8b5a?4:type==0x8b5b?9:type==0x8b5c?16:0;
  if(!components||!strcmp(name,"uTimeResolution"))continue;
  if(size!=1)fail("curve float array");
  GLint loc=location(program,name);if(loc<0)fail("curve location");
  BYTE*record=values[retained++];memset(record,0,140);memcpy(record,name,64);DWORD fields[]={components,type,(DWORD)loc};memcpy(record+64,fields,12);uniform_f(program,loc,(GLfloat*)(record+76));
 }
 header[10]=retained;curve_write(header,sizeof(header));curve_write(values,retained*140);
 glGetIntegerv(0x8ca6,after);glGetIntegerv(GL_VIEWPORT,after+1);glGetIntegerv(0x84e0,after+5);
 if(memcmp(before,after,sizeof(before))||glGetError())fail("curve GL state");
 if(fflush(curve_file))fail("curve flush");
}
