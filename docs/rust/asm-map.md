# Original binary → Rust modules

Addresses are virtual addresses in the unpacked original (base `0x400000`); see [docs/en](../en/README.md) for what each part does.

The Rust column names modules in the regular `src/` tree. The compact variant's
source locations and packer changes are listed [below](#compact-build-and-modified-assembly).

## Engine and graphics

| Original | Address | Rust |
|---|---|---|
| Application entry, startup order | `0x406379` | `runtime.rs` `run` |
| Window, pixel format, WGL context | `0x4063b9..0x40640d` | `runtime.rs` `Window::new` |
| One-second loading screen | `0x406430..0x40648d` | `graphics.rs` `loading` |
| Physics parameter copies | `0x40648f..0x4064c0` | `physics.rs` `initial_records` |
| Shader source arrays, 30 programs | `0x4064e7..0x406ded` | `generated.rs` `PROGRAM_SOURCES`, `graphics.rs` `compile` |
| 13 FBOs, 15 textures | `0x406e01..0x406f7a` | `graphics.rs` `build` |
| Initialization passes, atlas → 128³ volume | `0x406f9c..0x407a58` | `graphics.rs` `build` |
| waveOut open / prepare / write | `0x407ae9..0x407b0c` | `runtime.rs` `Playback::start` |
| Sample cursor → seconds → beat | `0x407b91..0x407be5` | `contract.rs` `Clock::from_samples` |
| Row selection | `0x407bee` | `timeline.rs` `select` |
| Curve evaluation | `0x407c64..0x407f9c` | `timeline.rs` `evaluate`, `evaluate_track` |
| Track loop, physics dispatch by name | `0x407f9c..0x408291` | `engine.rs` `evaluate` |
| Character physics | `0x406019..0x4062d0` | `physics.rs` `Record::update` |
| x87 `acos`, `atan2`, `sqrt` | `0x408620..0x408646` | `fp.rs` |
| Pass loop, uniform upload, `glRecti` | `0x4082c4..0x4085fd` | `engine.rs` `draw_schedule`, `graphics.rs` `draw` |
| `SwapBuffers`, Escape, exit at beat 600 | `0x4085fd..0x408618` | `runtime.rs` frame loop |
| Imports (IAT) | `0x409000..0x40909c` | `windows.rs` |

## Data

| Original | Address | Rust |
|---|---|---|
| GLSL fragments | `0x409918…` | `shaders/*.glsl` (named by address) |
| Curve pool | `0x426de0` | `src/data/curve_pool.bin` |
| Timeline ranges, tokens, track ranges | `0x42fc50`, `0x42fde0`, `0x42fea8` | `src/data/timeline_*.bin` |
| Uniform descriptors | `0x430038` | `src/data/uniform_descriptors.bin` |
| Program recipes | `0x4357e0` | `src/data/program_recipes.bin` |
| FBO records, pass routes, pass lists | `0x4358d0`, `0x4359d0`, `0x435e2c` | `src/data/framebuffers.bin`, `pass_routes.bin`, `scene_pass_lists.bin` |
| Score, patch | `0x437040`, `0x43edf0` | `audio/data.rs` `SCORE`, `PATCH` |
| 15 used `gm.dls` samples | external file | `audio/gmdls_samples.rs` |

## Synthesizer

| Original | Address | Rust |
|---|---|---|
| Init: delta decode, graph, bank | `0x4010e3` | `audio/runtime.rs`, `audio/score.rs` |
| Synth thread, 64-frame blocks | `0x401636` | `audio/runtime.rs` `render_prefix` |
| Score streams, event dispatch | `0x40141a`, `0x4012eb` | `audio/score.rs`, `audio/voice.rs` |
| Node creation, cache, destruction | `0x405de9`, `0x405e78`, `0x405f4e` | `audio/graph.rs` |
| Voice manager, arpeggiator | `0x401d6a..0x40206f`, `0x40190e..0x401a67` | `audio/voice.rs`, `audio/arp.rs` |
| `s_rand`, `s_exp2`, sine/log helpers | `0x401038`, `0x401066` | `audio/math.rs` |
| Oscillator, LFO | `0x40265c`, `0x402aa8`, `0x402c12` | `audio/oscillator.rs` |
| Noise, random, sampler, GMDLS | `0x402db1`, `0x4044a0`, `0x404dd0`, `0x405b12` | `audio/sources.rs` |
| Filters, delays, reverb, distortion, compressor | `0x403008..0x40477a`, `0x405986` | `audio/effects.rs` |
| Formant filter | `0x405b62` | `audio/formants.rs` |
| Trigger sequencer | `0x404a9d` | `audio/sequencer.rs` |
| Glitch | `0x40514d` | `audio/glitch.rs` |
| ADSR, arithmetic and routing nodes | `0x40226d`, … | `audio/nodes.rs` |

## Compact build and modified assembly

The compact PE is linked anew; the original virtual addresses above identify
the reverse-engineered routines, not addresses to patch in the Rust EXE.

| Source | Low-level change |
|---|---|
| [`size/packer/model_asm.asm`](../../size/packer/model_asm.asm) | Encoder model expanded from 11 contexts / 3 mixers to 14 / 8; adds word, position and 4 KiB-region contexts and tuned update rates |
| [`size/packer/depacker.asm`](../../size/packer/depacker.asm) | Matching decoder; frequently accessed work fields placed near `EBP` for signed-byte displacements, compact initialization, x87-generated squash table |
| [`size/packer/model_config.inc`](../../size/packer/model_config.inc) | Shared generated dimensions, masks and context macros keep encoder and decoder synchronized |
| [`size/packer/exepacker.cpp`](../../size/packer/exepacker.cpp) | Emits compact PE imports: `OriginalFirstThunk = 0`, one thunk array and overlapping terminator/hint bytes; checks the model's stream-size bound |
| [`size/crate/tools/rust/minimal-linker`](../../size/crate/tools/rust/minimal-linker) | Renames anonymous COFF constants before linking; checks section membership/digests against the frozen layout |
| [`size/crate/tools/rust/merge-constants`](../../size/crate/tools/rust/merge-constants) | After linking, redirects allowlisted absolute SSE reads to equal immutable values, checking width, alignment and relocations; retains every constant byte |
| [`size/crate/src/audio/`](../../size/crate/src/audio/) | Compact data decoders, selected out-of-line DSP functions and exact constant folding; compiler/backend options are recorded in `size/build.py` |

For example, a valid absolute FP read can be redirected from one copy of a
constant to another equal, suitably aligned copy. More instructions then use
the same address bytes, which can improve compression without deleting table
data. Indexed accesses, writes and unrecognized encodings are left alone.

Link-order proposals are scored by the **complete trimmed EXE**, including
the decoder and headers. Code size alone is not that metric. See
[the frozen layout](../../size/INTEGRATED-LAYOUT.md),
[packer recovery](../../size/packer/RECOVERY.md) and
[integrated results](../../size/RESULTS.md) for reproduction and evidence.
