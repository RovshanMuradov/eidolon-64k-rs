/* Prepared adapter: explicitly loaded only by a future authorized target runner.
 * Configure EIDOLON_CAPTURE with helper, output, module, markerRva and retained.
 * Pixel/PCM bytes stay in synchronous native file writes, never Frida messages.
 */
'use strict';
const setup = globalThis.EIDOLON_CAPTURE;
if (!setup || Process.arch !== 'ia32') throw new Error('bound x86 capture configuration required');
const kernel = Process.getModuleByName('kernel32.dll');
const load = new NativeFunction(kernel.getExportByName('LoadLibraryA'), 'pointer', ['pointer'], 'stdcall');
const terminate = new NativeFunction(kernel.getExportByName('ExitProcess'), 'void', ['uint32'], 'stdcall');
if (load(Memory.allocUtf8String(setup.helper)).isNull()) throw new Error('helper load failed');
const helper = Process.getModuleByName(setup.helper.split(/[\\/]/).pop());
const initialize = new NativeFunction(helper.getExportByName('capture_init'), 'uint32', ['pointer','pointer'], 'cdecl');
const observe = new NativeFunction(helper.getExportByName('capture_event'), 'uint32', ['uint32','pointer','uint32'], 'cdecl');
const cursor = new NativeFunction(helper.getExportByName('capture_cursor'), 'uint32', [], 'cdecl');
const keep = Memory.alloc(27000); keep.writeByteArray(new Uint8Array(27000));
for (const n of setup.retained) { if (!Number.isInteger(n) || n < 0 || n >= 27000) throw new Error('retention'); keep.add(n).writeU8(1); }
if (initialize(Memory.allocUtf8String(setup.output), keep) !== 0) throw new Error('capture initialization failed');
const module = Process.getModuleByName(setup.module);
const marker = module.getExportByName('eidolon_runtime_event');
if (!marker.equals(module.base.add(setup.markerRva))) throw new Error('marker RVA differs');
Interceptor.attach(marker, { onEnter(args) {
    const result = observe(args[0].toUInt32(), args[1], args[2].toUInt32());
    if (result !== 0) { send({event:'capture_failure',code:result}); terminate(125); }
}});
const wave = Process.getModuleByName('winmm.dll');
Interceptor.attach(wave.getExportByName('waveOutGetPosition'), {
    onEnter(args) { this.owned = this.returnAddress.compare(module.base) >= 0 && this.returnAddress.compare(module.base.add(module.size)) < 0; this.time = args[1]; this.size = args[2].toUInt32(); },
    onLeave(result) {
        if (!this.owned) return;
        if (result.toUInt32() !== 0 || this.size !== 12 || this.time.readU32() !== 2) terminate(125);
        this.time.add(4).writeU32(cursor());
    }
});
send({event:'capture_armed',markerRva:setup.markerRva,mode:'play-controlled-sample-cursor'});
