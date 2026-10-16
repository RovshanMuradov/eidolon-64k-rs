#!/usr/bin/env python3
"""Build proxy-only G1a prerequisite under .tools, pin complete export surfaces."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def exports(path):
    data = Path(path).read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[pe:pe + 4] == b"PE\0\0"
    machine, count = struct.unpack_from("<HH", data, pe + 4)
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    assert machine == 0x14C and struct.unpack_from("<H", data, opt)[0] == 0x10B
    sections = []
    for i in range(count):
        s = opt + opt_size + 40 * i
        vs, va, rs, rp = struct.unpack_from("<IIII", data, s + 8)
        sections.append((va, max(vs, rs), rp))

    def offset(rva):
        for va, length, raw in sections:
            if va <= rva < va + length:
                return rva - va + raw
        raise ValueError(f"unmapped RVA {rva:x}")

    export_rva = struct.unpack_from("<I", data, opt + 96)[0]
    table = offset(export_rva)
    base, functions, names, f_rva, n_rva, o_rva = struct.unpack_from("<IIIIII", data, table + 16)
    entries = {base + i: [] for i in range(functions)
               if struct.unpack_from("<I", data, offset(f_rva) + 4 * i)[0]}
    for i in range(names):
        pos = offset(struct.unpack_from("<I", data, offset(n_rva) + 4 * i)[0])
        name = data[pos:data.index(0, pos)].decode("ascii")
        ordinal = base + struct.unpack_from("<H", data, offset(o_rva) + 2 * i)[0]
        entries[ordinal].append(name)
    return entries


def main():
    root = Path(os.environ["EIDOLON_ROOT"])
    source = Path("tools/capture/proxy-b")
    compiler = subprocess.check_output(["i686-w64-mingw32-gcc", "--version"], text=True).splitlines()[0]
    sources = {str(p): sha(p) for p in sorted(source.glob("*")) if p.is_file()}
    backends = {name: Path(f"/usr/lib/wine/i386-windows/{name}.dll")
                for name in ("opengl32", "winmm")}
    identity = {"sources": sources, "compiler": compiler,
                "backends": {name: {"path": str(p), "sha256": sha(p)}
                             for name, p in backends.items()},
                "flags": ["-O2", "-Wall", "-Wextra", "-Werror", "-Wl,--no-insert-timestamp"]}
    build_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    out = root / ".tools/capture/B" / build_id
    out.mkdir(parents=True, exist_ok=True)
    commands = []
    static_checks = {}
    for name, path in backends.items():
        entries = exports(path)
        directory = out / name
        directory.mkdir(exist_ok=True)
        (directory / "exports.json").write_text(json.dumps(entries, indent=2) + "\n")
        definitions = [f"LIBRARY {name}", "EXPORTS"]
        assembly = [".text"]
        ordinals = []
        for i, (ordinal, names) in enumerate(entries.items()):
            ordinals.append(ordinal)
            for entry in names or [f"ordinal_{ordinal}"]:
                assert all(c.isalnum() or c in "_@?" for c in entry), entry
                definitions.append(f"{entry}=eidolon_stub_{i} @{ordinal}" + ("" if names else " NONAME"))
            assembly += [f".globl _eidolon_stub_{i}", f"_eidolon_stub_{i}:",
                         f"pushl ${i}", "jmp _eidolon_dispatch"]
        definitions.append(f"EidolonProbeBackend=EidolonProbeBackend@0 @{max(entries) + 1}")
        assembly += ["_eidolon_dispatch:", "pushfl", "pushal", "movl %esp,%ebp",
                     "subl $528,%esp", "andl $-16,%esp", "fxsave (%esp)",
                     "subl $16,%esp", "movl 36(%ebp),%eax", "movl %eax,(%esp)",
                     "call _eidolon_resolve", "movl %eax,36(%ebp)", "addl $16,%esp",
                     "fxrstor (%esp)", "movl %ebp,%esp", "popal", "popfl", "ret"]
        (directory / "proxy.def").write_text("\n".join(definitions) + "\n")
        (directory / "forward.S").write_text("\n".join(assembly) + "\n")
        symbol = "wglGetProcAddress" if name == "opengl32" else "timeGetTime"
        (directory / "exports.h").write_text(
            f'#define DLL_NAME "{name}.dll"\n#define DLL_WNAME L"{name}.dll"\n'
            f'#define CANARY_SYMBOL "{symbol}"\n#define EXPORT_COUNT {len(entries)}\n'
            'static const unsigned short export_ordinals[] = {' + ','.join(map(str, ordinals)) + '};\n')
        bootstrap = []
        if name == "opengl32":
            wrappers = [".text"]
            for api, argbytes in {"gettick":0,"timegettime":0,"qpc":4,"qpf":4,
                    "position":12,"swap":4,"create_thread":24,"wave_open":24,
                    "wave_prepare":12,"wave_write":12,"lookup":8,"wgl_lookup":4}.items():
                wrappers += [f".globl _eidolon_{api}", f"_eidolon_{api}:",
                             "pushfl", "pushal", "movl %esp,%ebp", "subl $528,%esp",
                             "andl $-16,%esp", "fxsave (%esp)", "subl $16,%esp",
                             "leal 36(%ebp),%eax", "movl %eax,(%esp)", f"call _core_{api}",
                             "movl %eax,28(%ebp)", "addl $16,%esp", "fxrstor (%esp)",
                             "movl %ebp,%esp", "popal", "popfl", f"ret ${argbytes}"]
            (directory / "wrappers.S").write_text("\n".join(wrappers) + "\n")
            bootstrap = ["-DHAS_BOOTSTRAP", str(source / "bootstrap.c"),
                         str(source / "core.c"), str(directory / "wrappers.S")]
        command = ["i686-w64-mingw32-gcc", *identity["flags"], "-shared", *bootstrap, "-I", str(directory),
                   str(source / "proxy.c"), str(directory / "forward.S"),
                   str(directory / "proxy.def"), "-ladvapi32", "-o", str(out / f"{name}.dll")]
        subprocess.run(command, check=True)
        commands.append(command)
        actual = exports(out / f"{name}.dll")
        assert all(actual[k] == v for k, v in entries.items()), "export mismatch"
        assert actual[max(entries) + 1] == ["EidolonProbeBackend"]
        static_checks[name] = {"machine": "i386", "backend_export_ordinals": len(entries),
                               "name_ordinal_map_equal": True, "probe_export_stdcall_bytes": 0}
    command = ["i686-w64-mingw32-gcc", *identity["flags"], str(source / "canary.c"),
               "-o", str(out / "canary.exe")]
    subprocess.run(command, check=True)
    commands.append(command)
    manifest = dict(identity, build_id=build_id, build_directory=str(out), commands=commands,
                    static_checks=static_checks,
                    outputs={str(p.relative_to(out)): sha(p) for p in sorted(out.rglob("*"))
                             if p.is_file() and p.name != "build.json"})
    (out / "build.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(out)


if __name__ == "__main__":
    main()
