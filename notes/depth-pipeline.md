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
- **Projector pattern = a fixed vertical fringe.** With exposure low enough not
  to wash it out, both cameras show a crisp vertical fringe across the object.
- **Single-shot, not phase-shifting.** Cross-correlating the fringe between
  consecutive frames gave **0 px shift** every time — the pattern is static.
  So depth is single-shot fringe-assisted stereo, not multi-frame phase shift.
  (The SDK exposes a fringe-pattern selector that *includes* 3-frequency
  4-step phase shifting, but that is not what the MINI does in this mode.)
- **The projector is always on while streaming.** The POP3 `0xb00`/`0xb01`
  "LED/projector enable" registers are inert here (see
  [rk-preisp-registers.md](rk-preisp-registers.md)); depth appears with or
  without poking them.

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
