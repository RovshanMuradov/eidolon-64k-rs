/* Host Frida controls only injection; all payload acquisition is native file I/O.
 * Wine WoW64 is an x64 host with IA32 guest code. Never use x64 Interceptor on it. */
rpc.exports = {
  inject(config) {
    const site = ptr(config.site), arena = ptr(config.allocation);
    const expected = [0x55,0x8b,0xec,0x81,0xec,0x24,0x04,0x00,0x00];
    const actual = Array.from(new Uint8Array(site.readByteArray(expected.length)));
    if (config.badFingerprint) expected[0] ^= 1;
    if (actual.some((v,i) => v !== expected[i]))
      throw new Error('entry_fingerprint_rejected_before_patch: ' + actual);
    const modules = [];
    for (const base of config.modules) {
      const p = ptr(base);
      try {
        if (p.readU16() !== 0x5a4d) continue;
        const pe = p.add(p.add(0x3c).readU32());
        if (pe.readU32() !== 0x4550 || pe.add(4).readU16() !== 0x14c) continue;
        const ex = p.add(pe.add(24+96).readU32());
        const name = p.add(ex.add(12).readU32()).readCString();
        modules.push({base:p,name,ex,size:pe.add(24+100).readU32()});
      } catch (_) { /* Non-PE modules are outside the guest export surface. */ }
    }
    function resolve(moduleName,name,depth=0) {
      if(depth>8) throw new Error('forwarder loop');
      const m=modules.find(m=>m.name.toLowerCase()===moduleName.toLowerCase());
      if(!m) throw new Error('guest module missing: '+moduleName);
      const count=m.ex.add(24).readU32(), names=m.base.add(m.ex.add(32).readU32());
      for(let i=0;i<count;i++) {
        if(m.base.add(names.add(4*i).readU32()).readCString()!==name) continue;
        const ordinal=m.base.add(m.ex.add(36).readU32()).add(2*i).readU16();
        const address=m.base.add(m.base.add(m.ex.add(28).readU32()).add(4*ordinal).readU32());
        if(address.compare(m.ex)>=0 && address.compare(m.ex.add(m.size))<0) {
          const forward=address.readCString(), dot=forward.indexOf('.');
          return resolve(forward.slice(0,dot)+'.dll',forward.slice(dot+1),depth+1);
        }
        return address;
      }
      throw new Error('guest export missing: '+moduleName+'!'+name);
    }
    const load=resolve('kernel32.dll','LoadLibraryA'), lookup=resolve('kernel32.dll','GetProcAddress');
    const exit=resolve('kernel32.dll','ExitProcess');
    const code=arena.add(0x1000), path=arena.add(0x100), symbol=arena.add(0x800);
    path.writeUtf8String(config.helper); symbol.writeUtf8String('EidolonInitialize');
    const bytes=[];
    const emit=(...b)=>bytes.push(...b);
    const u32=n=>{n=typeof n==='number'?n>>>0:n.toUInt32();emit(n&255,(n>>>8)&255,(n>>>16)&255,n>>>24);};
    const push=p=>{emit(0x68);u32(p);};
    const call=p=>{emit(0xb8);u32(p);emit(0xff,0xd0);};
    // Save exact entry GPR/EFLAGS and FXSAVE state before invoking any helper.
    emit(0x9c,0x60,0x89,0xe5,0x81,0xec);u32(528);emit(0x83,0xe4,0xf0,0x0f,0xae,0x04,0x24);
    push(path);call(load);emit(0x85,0xc0,0x75,0x0c);push(125);call(exit);
    push(symbol);emit(0x50);call(lookup);emit(0x85,0xc0,0x75,0x0c);push(125);call(exit);
    push(arena);emit(0xff,0xd0);
    emit(0x0f,0xae,0x0c,0x24,0x89,0xec,0x61,0x9d);
    // Helper restores the original site; resume the original instructions.
    emit(0xe9);u32(site.sub(code.add(bytes.length+4)));
    code.writeByteArray(bytes);
    arena.add(16).writeByteArray(actual);
    arena.add(32).writeU32(config.main_tid);
    if(!Memory.protect(site,expected.length,'rwx')) throw new Error('site protect failed');
    const jump=[0xe9], delta=code.sub(site.add(5)).toUInt32();
    jump.push(delta&255,(delta>>>8)&255,(delta>>>16)&255,delta>>>24);
    site.writeByteArray(jump);
    arena.writeU32(0x41324f4b);
    return {host_arch:Process.arch,host_pid:Process.id,guest_arch:'ia32',site:site.toString(),
      trampoline:code.toString(),trampoline_bytes:bytes,original_bytes:actual,
      load_library:load.toString(),get_proc_address:lookup.toString(),
      modules:modules.map(m=>({base:m.base.toString(),name:m.name})),
      patch_readback:Array.from(new Uint8Array(site.readByteArray(5)))};
  }
};
