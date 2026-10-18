# 7. How it all fits in 60 928 bytes

Almost all content is generated at startup: the 261 KB unpacked image produces 160 MB of audio, hundreds of megabytes of textures and 27 000 frames. GLSL sources take the most space.

## Unpacked image contents

The image `[0x401000, 0x440c5c)` is 261 212 bytes. The xz column shows each component compressed on its own.

| Component | Raw, bytes | xz -9e, bytes |
|---|---:|---:|
| GLSL sources | 117 040 | 24 816 |
| Graphics tables (curves, descriptors, routes) | 63 260 | 16 588 |
| Score (delta-coded) | 32 143 | 6 232 |
| Synth code | 20 320 | 9 408 |
| Other data, padding | 10 746 | 2 272 |
| Engine code | 9 959 | 3 408 |
| Patch and trailer | 7 744 | 3 892 |
| **Total** | **261 212** | **65 416** |

In the EXE this image, together with the inner loader, is the 58 844-byte kkrunchy stream.

## Generated at startup

| Result | In memory | Source |
|---|---|---|
| PCM | 159 716 352 bytes | ~40 KB of score and patch + 15 samples from the system `gm.dls` |
| Textures | ~590 MB RGBA32F | 9 generator shaders |
| Geometry | none | distance functions in shaders |
| Animation | — | 758 Hermite curves and physics |

## Techniques

| Technique | Effect |
|---|---|
| Procedural graphics | no meshes or images: scenes are SDFs, textures are noise, Voronoi, hashes |
| Shared shader fragments | 93 fragments for 30 programs, one SDF / lighting / raymarcher library |
| Keyframe animation | short cubic curves; physics adds inertia without stored trajectories |
| Synthesis instead of audio | graph with shared nodes and constants; only the node types used are in the EXE |
| Planar, delta-coded score | 6 232 bytes compressed instead of 10 216 |
| System `gm.dls` | samples are not in the EXE; otherwise +72–85 KB even compressed |
| kkrunchy | x86 filter into 20 streams, context mixing; 35 imports by name through two outer ones |

## Packer in numbers

```
60 928 = 2 084  wrapper: headers 212 + decoder 1 596 + imports 108 + padding 168
       + 58 844 compressed stream: loader 1 501 + code 30 198 + data
```

## The 32 KiB target

32 KiB has not been reached. The shaders and graphics tables above total about
41 KB when compressed separately with xz, but that is not a lower bound for
a different representation or a jointly compressed executable.

- Reaching 32 768 bytes requires removing 28 160 bytes, i.e. 46%.
- Repacking the finished EXE gives ~60.5 KB.
- Removing dead code and nodes, and factoring shaders and curves, could save some bytes. No savings of this scale have been demonstrated.

The Rust rewrite has since produced a reproducible 44 139-byte integrated
candidate using compact data, shader transformations, a modified packer and
retuned layout. Its verification status and comparisons are recorded in
[size/README.md](../../size/README.md#verification). The original-binary measurements above
describe the 60 928-byte file.
