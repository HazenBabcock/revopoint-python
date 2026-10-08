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
*supported*, **not** how many patterns there are or whether they form a
phase-shift sequence. The exact pattern count on this MINI is **unverified**; the
cleanest way to get it is high-speed video of the projector during a scan (e.g.
240 fps phone slow-motion), since the patterns never appear in the stream.

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
- No single exposure covers this HDR scene well; the sweet spot here was ~12000.
- This is why the out-of-the-box experience is poor: the default long/auto
  exposure blows out bright surfaces and drops them from the scan.

## The HDR capture cycle (period-4)

At exposures around 8000–10000 the per-frame depth coverage was **not** constant
— it followed a repeating period-4 pattern, e.g.:

```
[0.225, 0.226, 0.018, 0.013,  0.225, 0.226, 0.018, 0.013, ...]
```

Two of every four frames give good depth, two give almost none. The scanner
cycles through ~4 capture states (consistent with **HDR exposure bracketing**);
at a low base exposure, two of the states fall below the depth threshold. At
exposure ≥12000 all four states yield depth. Any consumer of the raw stream
should expect this interleave and select/fuse accordingly rather than trusting
every Nth frame.

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
  the HDR cycle, and multi-frame fusion. These are all addressable in host code.
- **There is a hardware floor.** Independent tests of this sensor class land
  around ~0.15 mm noise/resolution, and no third-party pipeline is known to beat
  Revo Scan's own fusion on a MINI. Better-than-stock is very achievable;
  metrology-grade is not.

## Reproducing

Scripts used for these measurements live outside the repo (scratchpad):
exposure sweep + settle/fringe-shift test. The capture logic mirrors
`revopoint.get_images` plus the register pokes above. Port them into the module
if this becomes a real capture tool.
