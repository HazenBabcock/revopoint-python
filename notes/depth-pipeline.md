# Depth pipeline — how the MINI makes depth, and what limits quality

Findings from a controlled experiment on this unit (fw `v7.6.9.0816`,
2026-10-08). Scene: a white 3D-printed bust ~150–200 mm from the scanner on a
desk (a high-dynamic-range target: bright object, dark background).

## How depth is produced

- **Binocular (two-camera) blue structured light.** The stream carries a depth
  map plus the two mono camera images (`set_depth_output_fmt=3`). The two mono
  views show clear parallax → a real stereo pair.
- **Depth is computed on the device.** The Y16/Z16 map comes out of the scanner
  already; the host (Revo Scan) does registration, fusion and meshing. *(For the
  POP3, the PC app reportedly requests the raw PAIR and computes depth on the
  host instead — unverified for the MINI, which clearly streams on-device depth.)*
- **Projector = multiple structured-light patterns.** Watching the projector
  during a scan (by eye) shows it cycling through a *series of stripe patterns
  with different periods* — multi-pattern structured light, the fingerprint of a
  multi-frequency / phase-shift method, not a single static fringe. The single
  crisp vertical fringe seen in a *stream* mono frame is one sampled instant, not
  the whole projection (see "What the stream shows" below).
- **The projector is always on while streaming.** The POP3 `0xb00`/`0xb01`
  "LED/projector enable" registers are inert here (see
  [rk-preisp-registers.md](rk-preisp-registers.md)); depth appears with or
  without poking them.

## What the stream shows about the pattern (and what it can't)

The raw stream is **not** a window onto the projection. Per computed depth frame
it carries the finished on-device depth map plus a single mono image from each
camera; the scanner runs its whole multi-pattern sequence internally and emits
only the result. So consecutive stream frames can't be used to count or time the
projected patterns — an earlier "0 px fringe shift between stream frames" reading
measured the *output* cadence, not the projector, and wrongly looked like a
static single-shot pattern.

The depth engine reports its capability flags (exported to `/tmp/algo.ini`),
which on this unit read `change_pattern = 1` and `auto_expoosure = 1` *[sic]*.
`change_pattern` is a **boolean capability flag** — it says pattern changing is
*supported*, **not** how many patterns there are. The count was measured directly
with an external high-speed camera (next section), since the patterns never
appear in the stream.

## Pattern count, measured externally: 12 = 3 frequencies × 4 phases

A Basler acA1440-220uc (color, 901 fps) was aimed at the projected fringe on a
flat white target while an HTTP depth stream kept the projector running, to catch
the sequence the stream hides. 1800 frames at 901 fps gave ~18 camera frames per
projected pattern (heavily oversampled). From the fringe profiles:

- **3 spatial frequencies** — periods roughly 20, 81 and 360 px *as imaged by the
  external camera* (relative, not projector line counts; spacing ≈ ×4).
- **4 phase steps per frequency**, evenly spaced **90°**, confirmed at all three
  frequencies (each frequency's fringe phase clusters cleanly into 4 groups).
- → **12 patterns = 3 frequencies × 4 phases**, exactly matching the SDK's
  "3-frequency 4-step phase shift".
- Projected **sequentially** (95% of frames show one dominant frequency),
  ~20 ms per pattern, in the order fine → mid → fine → coarse (the fine set
  appears re-shot before the coarse one). The *order* is held loosely — the camera
  was unsynchronized so the sequence drifts slightly between cycles — but the
  **count (12)** and the **90° phase quantization** are unambiguous.

Textbook multi-frequency 4-step phase-shifting, confirmed from outside the
device. This supersedes the earlier "single-shot" guess and the earlier
"count unverified".

## Projector mechanism (inferred)

The projector is a **scanned blue-laser** source with a single resonant axis —
not a 2-D image modulator (no DMD/LCoS). Evidence:

- The firmware stores a **resonant-frequency** parameter of ~3.45 kHz (raw value
  3451). A resonant frequency only makes sense for a mechanically oscillating
  element — a scanning mirror or a piezo; a framebuffer-style projector would
  have no such number. ~3.45 kHz is far faster than the per-pattern exposure
  (~ms), consistent with the element sweeping many times per captured frame to
  build up each pattern.
- Only **one** resonant frequency is stored → one oscillating (horizontal) axis.
- Physical + economic bounds point the same way: the projector is physically
  tiny (~1–2 cm on a side) and the scanner is inexpensive. That rules out a
  bulky, costly DMD/LCoS and favors the simplest programmable option — a single
  small resonant mirror sweeping a laser line (fanned vertically by a cylindrical
  lens or DOE), with the laser intensity-modulated during the sweep to synthesize
  fringes.

**Capability this implies:**

- *Along the horizontal (scan) axis:* arbitrary 1-D profiles — stripe patterns of
  any period, phase-shifted, sinusoidal or binary/Gray-coded. This is exactly the
  toolkit for a multi-frequency phase-shift scheme, and why the projector can
  show "stripes of different periods."
- *Vertically / true 2-D:* effectively none. With one controllable axis it cannot
  project horizontal stripes, checkerboards, dot grids, or arbitrary images — the
  vertical direction is just a laser line.

**Confidence:** high that it is a 1-D scanned-laser projector (single resonant
axis + only-ever-vertical fringes + small/cheap hardware all agree). The exact
element (resonant MEMS mirror vs piezo-shifted grating) is **not** determined
from the outside. A hidden *slow* second axis (e.g. a DC galvo, which would not
be stored as a "resonant" frequency) cannot be ruled out in principle, but
nothing points to one, so genuine 2-D projection is very unlikely.

## Exposure is the real quality lever

Exposure sweep (`0x911`, gain 1, measuring mono saturation and depth
valid-pixel fraction over the full 640x400 frame):

| exposure | mono median | mono sat (≥250) | depth valid frac |
|---:|---:|---:|---:|
| 60000 | 79 | 0.32 | 0.12 |
| 40000 | 56 | 0.30 | 0.12 |
| 20000 | 27 | 0.27 | 0.18 |
| **12000** | — | — | **0.23** |
| 10000 | 10 | 0.003 | 0.23 good frames / 0.01 dark frames |
| ≤8000 | ≤7 | 0.00 | mostly too dark |

- Too long → the bright/near object **saturates**, and saturated pixels become
  **holes** in the depth map (no pattern to match).
- Too short → the whole scene is too dark to match → depth collapses.
- No single exposure covers this high-dynamic-range scene well; the sweet spot
  here was ~12000.
- This is why the out-of-the-box experience is poor: the default long/auto
  exposure blows out bright surfaces and drops them from the scan.

## Dim-projector frames at lower exposure

At exposures up to ~10000 the per-frame depth coverage is **not** constant: some
frames give good depth and some almost none, in pairs. At 12000 and above every
frame is good. Per-frame depth coverage on the bust scene:

```
 8000 (2026-10-08): 0.225 0.225 0.020 0.017 0.224 0.225 0.020 0.017 ...
 8000 (2026-10-09): 0.175 0.175 0.004 0.003 0.175 0.175 0.004 0.002 0.175 0.175 0.005 0.002
 8000 (2026-10-09): 0.175 0.175 0.004 0.003 0.175 0.175 0.175 0.175 0.005 0.002 0.175 0.175
12000 (2026-10-09): 0.176 on every frame
```

The cadence is not fixed: usually 2 good / 2 bad, but one run went 2 good,
2 bad, 4 good, 2 bad, 2 good.

**It is the projector, not the camera exposure** (measured 2026-10-09 from the
mono planes, exposure fixed at 8000 in manual mode). On a bad frame the
projector-lit pixels are about half as bright, while pixels lit only by ambient
light do not change:

| pixel brightness on a good frame | 12000 vs 8000 (1.5× exposure) | bad vs good frame at 8000 |
|---|---:|---:|
| darkest (ambient only) | 1.18× | 1.00× |
| mid | 1.35–1.42× | 0.70–0.63× |
| bright (projector-lit) | 1.53× | 0.52× |

The 12000 column shows the darkest pixels do respond to exposure, so a shorter
exposure would have dimmed them too. Instead about half of the projector light
is missing on the bad frames, which at 8000 drops the fringe below what the
depth decoder needs. At 12000 the projector brightness was the same on every
frame.

What causes it is not known. The SDK's HDR mode (`0x914`) and multi-frame
fusion (`0xa04`) settings were both set to 0 with no change, see
[rk-preisp-registers.md](rk-preisp-registers.md). Possibilities are an automatic
projector-brightness control, a laser power or thermal limit, or a timing
interaction between the camera exposure and the projector that a long enough
exposure covers. Any consumer of the raw stream should check each frame rather
than trusting every frame, or use an exposure high enough that it doesn't happen.

The mono planes also come in **byte-identical pairs** (frames 0/1, 2/3, ...)
while each depth frame is different, so the mono images update at about half
the depth rate. The SDK's fringe-pattern list includes modes that output two
depth frames per pattern cycle (`0xa05`, `..._MULTI_DEPTH`), which may be what
the MINI runs; not checked.

## Frame rate is capped at ~4 fps (acquisition-limited, not bandwidth)

Over the WiFi/HTTP interface the delivered depth rate is **~4.2 fps**, and three
measurements show the limit is **pattern acquisition**, not the link or exposure:

- **Compression doesn't help.** Raw (`camera_id=22`, ~1024 KB/frame) and the
  QuickLZ-compressed stream (`camera_id=21`, ~349 KB/frame, 2.9× smaller) both
  deliver **~4.25 fps** — raw at ~35 Mbit/s, compressed at ~12 Mbit/s. Cutting the
  data 2.9× moved the rate <1%, so WiFi bandwidth is **not** the limiter. (This
  corrects the earlier claim in [http-api.md](http-api.md) that compression was
  "the likely fix for the < 10 Hz problem".)
- **Exposure doesn't help.** Sweeping `0x911` from 800 µs to 12 ms leaves the rate
  flat at ~4.2 fps; it only drops once exposure exceeds ~20 ms:

  | exposure | raw fps | comp fps | depth valid | mono mean |
  |---:|---:|---:|---:|---:|
  | 800 µs | 4.19 | 4.21 | 0.21 | 16 |
  | 1500 µs | 4.21 | 4.21 | 0.71 | 27 |
  | 3000 µs | 4.20 | 4.19 | 0.82 | 61 |
  | 6000 µs | 4.30 | 3.97 | 0.82 | 118 |
  | 12000 µs | 4.20 | 4.21 | 0.82 | 217 |
  | 24000 µs | 3.44 | 3.44 | 0.82 | 233 |

- **The limiter is a ~20 ms/pattern fixed overhead.** 12 patterns × ~20 ms ≈
  240 ms ≈ 4.2 fps, matching the external-camera dwell. Per-pattern time behaves
  like `max(~20 ms overhead, exposure)` — exposure only bites once it exceeds the
  overhead (hence the 24 ms drop). The overhead is not exposure and not streaming
  (the projector itself dwells ~20 ms/pattern); likely fixed pattern-sequencing /
  on-chip compute pacing.

Consequences:

- **10 fps is not reachable** over this interface by compression or exposure. The
  spec'd 10 fps presumably uses a different mode (USB, or fewer patterns).
- Depth coverage plateaus at exposure ≥ 3 ms (~0.82 valid) — *inside* the
  overhead-limited regime — so best quality and max rate coincide at ~3–12 ms;
  there is no speed-for-quality trade via exposure here.
- The one untested lever that could reach ~10 fps is **fewer patterns** (via the
  `change_pattern` capability): e.g. 1 frequency × 4 phases = 4 patterns →
  ~80 ms → ~12 fps, trading multi-frequency unwrapping robustness for speed.
- Even if acquisition were sped up, **raw** streaming saturates the link
  (~35 Mbit/s ≈ ~4.4 fps at ~1 MB/frame), so delivering >~4.4 fps would then
  require the compressed stream after all.

## Metric scale is unresolved

Raw depth values were ~21000 (median). The POP3's `0x918` divisor of 10
(0.1 mm/unit) would imply ~2.17 m, which is wrong for a ~150 mm object. So the
raw values are **not** directly mm at that scale. Converting to a true metric
point cloud needs the factory calibration (`Q.bin` reprojection) rather than a
scalar — see [references.md](references.md) for where the calibration files live.

## Hardware vs software — the verdict

- **Hardware is good.** Clean fringe, clean stereo, and a smooth, nearly
  complete single-frame depth surface of the object once exposure is right.
- **The poor results are mostly software/workflow:** exposure control, handling
  the dim-projector frames, and multi-frame fusion. These are all addressable in host code.
- **There is a hardware floor.** Independent tests of this sensor class land
  around ~0.15 mm noise/resolution, and no third-party pipeline is known to beat
  Revo Scan's own fusion on a MINI. Better-than-stock is very achievable;
  metrology-grade is not.

## Reproducing

Scripts used for these measurements live outside the repo (scratchpad):
exposure sweep + settle/fringe-shift test. The capture logic mirrors
`revopoint.get_images` plus the register pokes above. Port them into the module
if this becomes a real capture tool.
