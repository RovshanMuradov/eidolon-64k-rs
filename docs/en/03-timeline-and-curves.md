# 3. Timeline and animation curves

The timeline is 50 rows covering beats `[0, 600)` with no gaps. Each row selects a scene (a pass list) and a set of curves that turn the local beat into uniform values.

## Tables

| Address | Format | Meaning |
|---|---|---|
| `0x42fc50` | 50 × `(f32 start, f32 end)` | Row intervals in beats |
| `0x42fde0` | 50 × u32 | Scene token |
| `0x42fea8` | 50 × `(wordOffset, count)` | Uniform descriptors animated by the row |
| `0x435e2c` | length-prefixed lists | Pass list; the token is a DWORD offset |
| `0x4359d0` | `(programIndex, fboSelector)` | Pass route; `fboSelector` is one-based, 0 = screen |

The row is the first one with `end > beat`. On a row change `localBeat` and tracks reset, even when the scene token stays the same.

## Scenes

Twelve scene programs are spread over 15 row groups. Three scenes return in the credits.

| Rows | Beats | Token | Program | Contents |
|---|---|---:|---:|---|
| 0–4 | [0, 96) | 0 | 9 | habitat room, galaxy display |
| 5 | [96, 128) | 20 | 19 | habitat exterior, satellite dishes |
| 6–9 | [128, 176) | 40 | 20 | coast, monorail, clouds |
| 10–11 | [176, 224) | 60 | 21 | road, alien base, clouds |
| 12–14 | [224, 264) | 80 | 22 | hangar |
| 15–24 | [264, 336) | 100 | 23 | maze corridor, pursuing robots |
| 25–32 | [336, 400) | 140 | 25 | cargo maze, doors |
| 33–37 | [400, 448) | 160 | 26 | maintenance tunnel, shaft |
| 38–42 | [448, 512) | 180 | 27 | walkway, animated boss |
| 43 | [512, 520) | 60 | 21 | outdoors again |
| 44–45 | [520, 528) | 200 | 28 | sphere, beam |
| 46 | [528, 556) | 220 | 29 | control room, galaxy display |
| 47 | [556, 572) | 40 | 20 | credits: coast |
| 48 | [572, 584) | 100 | 23 | credits: corridor |
| 49 | [584, 600) | 60 | 21 | credits: outdoors |

- Program 24 (token 120, cable tunnel) is compiled but no row selects it.
- Shaders have their own events on global time: program 25 switches at 264 and 282 s, program 26 changes geometry at 312 s.
- Every scene's pass list has the same shape: initialization descriptors 0–8, the scene pass, post-processing 10–18 (see [05-rendering.md](05-rendering.md)).

## Uniform descriptors

A descriptor is 10 u32 words at `0x430038 + 4·rowOffset + 40·j`:

```
(nameIndex, components, xOff, xLen, yOff, yLen, zOff, zLen, wOff, wLen)
```

- Uniform name: `*(0x4361f0 + 4·nameIndex)`, e.g. `uOrigin`, `uAngles`, `uMainCharacterPos`.
- Each channel is a curve at `0x426de0 + 4·off`, `len` float32 words long.
- 561 descriptors and 758 curves in total. 1 to 3 components: 295 scalars, 5 vec2, 261 vec3.
- Uploaded with `glUniform{1,2,3,4}fv` by component count (`0x405fdd`).

The fourth-channel check (`0x407ecc`) reads a field two records ahead. It fires only on the last `uAngles` of row 49: an extra W is computed, but `glUniform3fv` drops it.

## Curve

A curve is a cubic Hermite spline over keys `(m0_in, time, value, m1_out)`, all float32. Tangents are already scaled by segment length. Code: `0x407c64..0x407d25`.

```
if one key or q <= t[0]:  return v[0]
q = min(q, t[last])
i = first key with t[i] >= q              // on equal t the earlier segment wins
s = (q - t0) / (t1 - t0)
d = v1 - v0
a = 3·d - 2·m0 - m1
b = m0 + m1 - 2·d
return v0 + s·(m0 + s·(a + s·b))           // float32, in this order
```

20 curves have keys with equal times — these are intentional jumps. Sorting keys or removing duplicates changes the animation.

## Camera

The camera ray is built in the shader (`0x4184b8`) from `uOrigin`, `uAngles`, `uFisheye`, `uFovBias`:

```
uv   = (2·pixel - resolution) / height
uv  *= 1 - (1 - dot(uv, uv)/4) · uFisheye
dir  = rotate xz by uv.x·uFovBias, then yz by uv.y·uFovBias,
       then xy (roll), yz (pitch), xz (yaw)
pR(p, a) = p·cos(a) + vec2(p.y, -p.x)·sin(a)
```

The camera and the boss (`uEolBossPosition`) are driven by curves directly, without physics.
