# USB interface

When plugged in over USB the MINI enumerates as a standard **UVC + HID**
composite device — no vendor driver needed to get the camera streams. This is a
separate path from the WiFi/HTTP control plane and exposes different things.

> Verified on this unit (2026-10-08) unless marked otherwise.

## Device

- VID:PID `2207:110c`, product `REVO_PRODUCT`, manufacturer `Chishine3d`,
  `bcdDevice 4.19`, serial `A22C22692A6F00A65`.
- The same VID:PID + extension-unit GUID is shared by the POP3 Plus and POP4
  *(from other scanners)*, so those projects' USB notes are a useful reference.
- 5 interfaces: two UVC functions (depth, color) + a HID interface.

## Depth function → `/dev/video2` (`DepthCamA22C...`)

Formats / sizes exposed:

- `YUYV` and `Y16 ` at 640x400 and 1280x800; `Y16` also at 640x800. Up to 15 fps.
- Only the **640x400** modes streamed raw via plain V4L2 here. 640x800 and
  1280x800 returned no frames without vendor-side setup first.
- The "640x400 YUYV" buffer is really a 640x**800** image = two stacked 640x400
  mono frames (left/right cameras) — same stacked stereo layout as the HTTP
  stream's mono planes.
- `Y16` at 640x400 is an on-device depth/disparity map. In raw UVC mode (no
  projector firing, no exposure setup) it is **sparse** (~97% zero) because
  without the projected pattern, stereo only matches on naturally-textured
  pixels. Dense depth requires the capture to be driven — which over this path
  is awkward, because the controls are locked (below).

Mode names reported over the HTTP API (`get_depth_reso`) line up with these:
`depth 1280x800 / 640x400 / 320x200`, `depth+ir 640x400x4 / 320x200x4`.

## Color function → `/dev/video4` (`RGBCamA22C...`)

- `MJPG` 1280x800 @ 30/20/15/10 fps. Clean color frames captured with nothing
  but `v4l2-ctl` / ffmpeg.
- **The color camera is USB-only.** It is *not* exposed anywhere on the
  WiFi/HTTP interface (which only carries the `mipi` depth path). This is why an
  HTTP-only client can never get color — a fully textured capture needs the
  scanner plugged in over USB for color *and* on WiFi (or USB) for depth.

## Controls are locked behind a vendor extension unit

- The UVC processing unit advertises the usual controls (brightness, exposure,
  gain, WB…), but setting exposure/gain is **rejected**: `auto_exposure` won't
  leave Auto, and manual exposure/gain return `Invalid argument` /
  `Permission denied`.
- Real control lives in a **vendor extension unit**, GUID
  `{c2211a6d-787e-3c4a-ac06-7e434b676f9a}`, unit 4, 14 controls, 3-byte control
  size. This is proprietary and undocumented by the vendor.
- *(from other scanners)* On the POP3/POP4 this extension unit uses `wIndex
  0x0400` with selectors for file read/write and device configuration; the
  vendor DLL also tunnels HID through it. The two projects disagree on some
  selector meanings. None of this was exercised here.
- **Practical consequence:** over USB you can freely grab both mono cameras, the
  color camera, and the sparse on-device depth, but you cannot drive exposure or
  the projector without reverse-engineering the extension unit. The **HTTP path
  is the easier control plane** (see [http-api.md](http-api.md) and
  [rk-preisp-registers.md](rk-preisp-registers.md)); USB is the easier way to get
  **color** and possibly higher-rate depth if the engine is already running.

## HID interface

- Interface 4, HID 1.01, with a 64-byte interrupt **OUT** endpoint (`0x01`) and a
  16-byte interrupt IN endpoint (`0x85`). Purpose not investigated here.
  *(from other scanners: HID traffic is tunnelled through the extension unit by
  the vendor software rather than used directly.)*
