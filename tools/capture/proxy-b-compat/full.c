/* Observe the native endpoint without replacing its branch or exit decision. */
extern void full_exit(void);
FARPROC full_exit_target;
static DWORD exit_registers[9];
static BYTE exit_fp[512];

static void full_initialize(void) {
    static const BYTE branch[]={0x83,0xf8,0xff,0x0f,0x84,0xf1,0x09,0x00,0x00};
    static const BYTE exit_call[]={0x57,0xff,0x15,0x30,0x90,0x40,0x00,0xcc};
    if(memcmp((void *)0x407c1d,branch,sizeof(branch)) ||
       memcmp((void *)0x408617,exit_call,sizeof(exit_call))) fail("native_end_fingerprint");
    slot(0x409030,(FARPROC)full_exit,&full_exit_target);
    record("full_run",",\"presents\":27000,\"queries\":27001,\"wrapper_stop_enabled\":false,"
           "\"exit_call\":4228632,\"exit_slot\":4231216");
}

void full_exit_observe(DWORD *registers,BYTE *fp) {
    DWORD *s=registers+9, ebp=registers[2];
    if(!full_run || GetCurrentThreadId()!=main_tid || s[0]!=0x40861e || s[1]!=0 ||
       frame!=27000 || native_queries!=27001 || registers[7]!=0xffffffff || registers[0]!=0 ||
       !acquired || *(DWORD *)0x437024!=19845000 ||
       *(DWORD *)(uintptr_t)(ebp-0x34)!=0x43e10000 ||
       *(DWORD *)(fp+176)!=0x44160000 || *(DWORD *)(fp+192)!=0x43e10000)
        fail("native_endpoint_mismatch");
    memcpy(exit_registers,registers,sizeof(exit_registers)); memcpy(exit_fp,fp,sizeof(exit_fp));
    save("native-exit-before-gpr.bin",registers,36); save("native-exit-before-fx.bin",fp,512);
    save("native-exit-locals.bin",(void *)(uintptr_t)(ebp-0x38),0x38);
    char source_sha[65]; hash((void *)0x409918,1310,source_sha);
    if(strcmp(source_sha,expected_sha)) fail("native_exit_source_changed");
    record("native_endpoint",",\"caller\":%lu,\"exit_call\":4228632,\"exit_code\":%lu,\"frames\":%lu,"
           "\"queries\":%lu,\"last_present\":26999,\"terminal_query\":27000,\"sample_cursor\":%lu,"
           "\"eax\":%lu,\"edi\":%lu,\"seconds_f32_bits\":%lu,\"beat_f32_bits\":%lu,"
           "\"original_source_sha256\":\"%s\",\"dropped_frames\":0,\"dropped_audio_sample_frames\":0,\"errors\":[]",
           s[0],s[1],frame,native_queries,*(DWORD *)0x437024,registers[7],registers[0],
           *(DWORD *)(uintptr_t)(ebp-0x34),*(DWORD *)(fp+176),source_sha);
    stage_summary();
}

void full_exit_restored(DWORD *registers,BYTE *fp) {
    save("native-exit-after-gpr.bin",registers,36); save("native-exit-after-fx.bin",fp,512);
    if(memcmp(exit_registers,registers,36) || memcmp(exit_fp,fp,512)) fail("native_exit_restoration");
    record("native_exit_forward",",\"caller\":%lu,\"exit_code\":%lu,\"registers_fp_equal\":true,"
           "\"tail_jump_original_slot\":true",registers[9],registers[10]);
    stage_flush_log();
}
