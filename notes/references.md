# References

External facts and resources for the MINI. These are **not** verified on this
unit unless noted; several come from other scanners in the same family (POP /
POP2 / POP3 / POP4), which share the USB `2207:110c` identity and much of the
protocol.

## Official specs (MINI)

- Two cameras; blue (class 1) structured light.
- 0.02 mm precision, 0.05 mm single-frame accuracy, 0.05 mm point distance.
- Working distance 100–200 mm; capture area 64×118 mm; up to 10 fps.
- Dual-core Cortex-A7; 5 GHz WiFi; 160 g; scans objects down to ~10 mm.
- Source: 3DPrintingIndustry launch writeup —
  https://3dprintingindustry.com/news/revopoint-launches-the-mini-3d-scanner-on-kickstarter-technical-specifications-and-pricing-210483/
- Vendor page ("proprietary chip allows MINI to directly output 3D data") —
  https://www.revopoint3d.com/pages/industry-3d-scanner-mini

## Independent accuracy

- MicroForm3D vs a Medit T300 reference: deviations −0.267 to +0.376 mm, mostly
  ~0.2 mm — https://www.microform3d.com/revopoint_mini.html
- MetroX notes structured-light results plateau around ~0.15 mm "due to lack of
  accuracy and low capture resolution" — https://github.com/ifilipis/metrox
- 3D Scan Forum user: needed markers ~every cm, couldn't scan varnished wood,
  less accurate than a RangeVision — https://www.3dscanforum.org/viewtopic.php?t=2389
- A MINI 2 gauge-block test improved markedly with a newer Revo Scan fusion
  release → software matters a lot —
  https://forum.revopoint3d.com/t/mini-2-accuracy-check/25187

## SDK

- The public "3D Camera SDK" (C++, plus Halcon / OpenNI) is listed only for the
  industrial Surface cameras (v3.2.229 / v3.2.52) —
  https://3dcamera.revopoint3d.com/html/Areascan2/index.html
- Handheld scanners: a 1-month trial by emailing support with the serial; forum
  posts mention a paid unlock (~$2000) afterward —
  https://forum.revopoint3d.com/t/is-there-any-sdk-or-api/2410/36
- SDK headers (v3.2.229) are mirrored by community repos and are the source of
  several register/command meanings used in these notes:
  - https://github.com/rccn-dev/revopoint_camera
  - https://github.com/tycoon0804/revopoint_ros
  - Header highlights: camera types `MINI_NO_RGB` / `MINI_NORMAL` / `MINI_2`;
    stream formats `Z16`, `Z16Y8Y8`, `PAIR` (binocular), `RGB`; controls for
    intrinsics/extrinsics, depth scale/range, ROI, HDR, laser on/off+brightness,
    LED, trigger, and a fringe-pattern selector (incl. 3-frequency 4-step phase
    shift); gain 1–16 (keep ≤3); exposure 3000–60000 µs.

## Official viewer

- `Revopoint/3DViewer` — GPL-3.0, built on the closed 3DCamera SDK, last release
  v1.2.16 (2023-08-04), includes a **Linux .deb**; its udev rules list
  `2207:110a/110b/110c` (so it recognizes this MINI) —
  https://github.com/Revopoint/3DViewer

## Community reverse-engineering (protocol)

- POP3 Plus over WiFi — the main source for the `rk_preisp` register meanings,
  the compressed (`camera_id=21`, QuickLZ) stream, and calibration file paths —
  https://github.com/TamedTornado/revopoint-pop3-linux-wifi
- POP4 USB extension-unit notes —
  https://github.com/BR1ZB3AR/All3DScan/blob/main/docs/protocol/RE_NOTES.md
- OpenPop (first-gen POP over standard Windows UVC: hardware Z16 320x200,
  rectified 640x400 pair, factory calibration) —
  https://github.com/TheoBaudoinLighting/OpenPop

## Calibration files

*(from other scanners — paths to confirm on the MINI)* downloadable via
`zx_cmd.cgi?download=<path>`:

- `/data/camparam/mapparamL.bin`, `/data/camparam/mapparamR.bin` — per-camera rectification maps
- `camparamLR` / `Q.bin` — stereo extrinsics / reprojection matrix

`Q.bin` is what's needed to turn the raw depth/disparity values into a true
metric point cloud (see [depth-pipeline.md](depth-pipeline.md), "Metric scale is
unresolved").

## WiFi modes

- Host (hotspot) mode and Client mode, both selected from Revo Scan over USB;
  the scanner needs external power for WiFi. MINI/POP2 are reported to be
  **5 GHz only**. This unit was used in Client mode (joined the LAN).

## Linux / Wine

- No official Revo Scan build for Linux (vendor: "no plan", 2023-03).
- Wine: a POP2 over WiFi reportedly worked with Revo Scan 4 + vcrun runtimes;
  USB did not; Revo Scan 5/6 crash on Bluetooth APIs —
  https://forum.revopoint3d.com/t/running-revo-scan-on-linux/11961

## Revo Scan cache converters (host-side)

For pulling per-frame depth (`.dph`) + pose (`.inf`) + `Q.bin` out of Revo Scan
projects:

- https://gist.github.com/fxtentacle/d3002f2c4084b9758c4228d5aedb276a
- https://github.com/SphaeroX/Revopoint-Revoscan-5-frame-converter
- https://github.com/X3msnake/revoscan-frame-player
