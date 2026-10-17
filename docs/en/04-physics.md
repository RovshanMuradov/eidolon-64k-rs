# 4. Character physics

A curve gives a character its target, and the position chases it like a mass on a damped spring. This produces inertia, banking in turns and spin. The shader receives the physics position, not the curve value.

## Records

Four 64-byte records; only characters have physics, the camera and the boss do not.

| Address | Character | Position track | Parameters `(spinDivisor, stiffness, damping, bankGain)` |
|---|---|---|---|
| `0x0b17bdf0` | main | `uMainCharacterPos` | `(0.25, 3.5, 2, 320)` |
| `0x0b17be30` | evil1 | `uEvilCharacterPos1` | `(1, 1.5, 2, 400)` |
| `0x0b17be70` | evil2 | `uEvilCharacterPos2` | `(1, 2.5, 1, 400)` |
| `0x0b17beb0` | evil3 | `uEvilCharacterPos3` — used by no row | `(1, 1.5, 1, 400)` |

The boss is not the fourth record but an ordinary curve, `uEolBossPosition`.

| Offset | Field |
|---|---|
| `+0x00` | position P, SIMD `[0, z, y, x]` |
| `+0x10` | velocity V, SIMD `[0, z, y, x]` |
| `+0x20..+0x2c` | `spinDivisor`, `stiffness`, `damping`, `bankGain` |
| `+0x30` / `+0x34` / `+0x38` | spin / yaw / roll |
| `+0x3c` | unused |

Everything except the parameters starts at zero.

## When it runs

Physics runs right after a position track is evaluated, inside the loop over the row's descriptors.

1. The descriptor is a character position track (matched by string name, `0x407f9c..0x408023`).
2. Target `T` = curve at `localBeat`; lookahead `L` = curve at `f32(localBeat + 0.01)`.
3. Physics is called and overwrites `T` with its position.
4. Uniforms are uploaded after all descriptors. Rotations (`uMainCharacterRotation`, `uEvilCharacterRotation1..3`) are always uploaded from the current records.

Details:
- The lookahead is in **beats** while `dt` is in **seconds**, with no conversion.
- If a row has no track for a record, the record stays unchanged. Scene changes do not reset it.
- On frame 0 and at initialization `dt = 0`: the function returns at once and the shader gets the raw curve.

## Algorithm (`0x406019`)

ABI: `ECX` = record, `XMM1.low` = dt, `[esp+4]` = target T (overwritten), `[esp+8]` = lookahead L, `ret 8`. All operations are SSE float32, rounded after each one, no FMA.

```
if dt == +0 or dt == -0: return             // NaN does not return

E    = T - P
err2 = (Ex·Ex + Ey·Ey) + Ez·Ez
if err2 > 25:                               // large gap — reset (strictly >)
    E = 0
    R = damping / stiffness
    V = (L - T) / 0.01
    P = T - R·V

Vold = V
Vnew = (V - (damping·dt)·V) + (stiffness·dt)·E
P    = dt·Vnew + P                          // semi-implicit Euler
V    = Vnew

speed    = sqrt(Vnew·Vnew)                  // x87; sum X, Y, Z in order
spinInc  = (speed / spinDivisor) · dt
yaw      = atan2(Vnew.x, Vnew.z)            // x87 FPATAN
roll     = 0
oldSpeed = sqrt(Vold·Vold)

if speed != 0 and oldSpeed != 0:
    cross = Vnew.x·Vold.z - Vnew.z·Vold.x
    sign  = cross < 0 ? -1 : +1
    c     = clamp((Vnew/speed)·(Vold/oldSpeed), -1, 1)
    angle = acos(c)                         // x87: atan2(sqrt(1 - c²), c)
    roll  = ((((angle·sign)·speed)·bankGain) / dt) · 0.001

spin += spinInc
T.xyz = P.xyz
```

## Precision

The result depends on operation order and on the x87 helpers:
- `sqrt`, `atan2`, `acos` are helpers `0x408640`, `0x408634`, `0x408620`. The result is rounded to float32 by `FSTP`; library functions may differ in the last bit.
- Velocities are normalized per component first, then multiplied. This is not the same as `dot / (speed·oldSpeed)`.
- `damping·dt·V` is subtracted separately, not computed as `(1 - damping·dt)·V`.
