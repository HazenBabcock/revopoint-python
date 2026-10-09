# HTTP / WiFi control plane

The scanner joins WiFi (client mode) and runs **lighttpd/1.4.48** on port 80. All
control, depth and color streaming goes through two CGIs. This is the interface the
`revopoint_python` module uses.

- Command endpoint: `http://<ip>/cgi-bin/zx_cmd.cgi?<query>`
- Media/stream endpoint: `http://<ip>/cgi-bin/zx_media.cgi?<query>`
- A third CGI, `zx_upload.cgi`, exists on this scanner family (not used here).

> **Verified on this MINI** (firmware `v7.6.9.0816`, 2026-10-08) unless marked
> otherwise. Items marked *(from other scanners)* are from the POP3/POP4
> reverse-engineering projects and were **not** confirmed here — see
> [references.md](references.md).

## Commands seen working on the MINI

| Query to `zx_cmd.cgi?` | Effect | Notes |
|---|---|---|
| `download=/tmp/inited` | returns firmware version string | returned `v7.6.9.0816 ` |
| `cam_type=mipi&get_depth_reso` | returns supported resolutions (JSON-ish) | see below |
| `close_stream_all` | tears down any open stream | returns `{result:0}`; call before (re)starting |
| `system_cmd=<urlencoded shell>` | runs a shell command on the device | returns `[<cmd>][ok]`; this is how register pokes are sent |
| `cam_type=mipi&set_display_reso=1&&set_display_width=640&&set_display_height=400&&set_display_type=4` | configure the display/output stream | note the doubled `&&` is what the app sends |
| `cam_type=mipi&set_depth_output_fmt=3` | include both mono camera planes in the stream (depth + L + R) | fmt 3 = depth+IR |
| `cam_type=mipi&set_trigger_mode=0` | free-run (untriggered) | a software-trigger mode presumably exists |

`get_depth_reso` on this unit returned:

```
{"curr-resolution":"640x800x2"}
{"depth-resolution":"1280x800x2-640x400x2-320x200x2"}
{"cali-resolution":"1280x800x2-640x400x2"}
{"depth+ir-resolution":"640x400x4-320x200x4"}
```

So full-res depth (1280x800) and calibration at 1280x800 are advertised, even
though the default capture used here is 640x400.

Register pokes (`system_cmd=echo s <reg> <val> > /dev/rk_preisp`) are documented
separately in [rk-preisp-registers.md](rk-preisp-registers.md).

## Streaming

Start a stream by GETting (with HTTP streaming / chunked reads):

```
http://<ip>/cgi-bin/zx_media.cgi?camera_id=22&type_id=20
```

The stream runs until the connection is dropped. `close_stream_all` cleans up a
session that was left open.

- `camera_id=22` — **raw** stream (used here).
- `camera_id=21` — **compressed** stream. **Confirmed working on the MINI**:
  framing is magic `0x11223344` (on the wire little-endian: `44 33 22 11`) +
  4-byte little-endian payload length + QuickLZ payload, **~349 KB/frame**
  (~2.9× smaller than raw). *(POP3: ~235 KB/frame, ~21 fps.)* **It does NOT raise
  the MINI's frame rate** — raw and compressed both deliver ~4.2 fps; the depth
  rate is acquisition-limited, not WiFi-bandwidth-limited (see
  [depth-pipeline.md](depth-pipeline.md), "Frame rate is capped at ~4 fps").
  Compression still cuts the link load ~3× (useful at higher resolution, on a
  weaker link, or with multiple clients), and *would* be needed to deliver
  >~4.4 fps if acquisition were ever sped up, since raw saturates the link there.

### Raw frame layout (`camera_id=22`, `set_depth_output_fmt=3`, 640x400)

Each frame in the byte stream is:

```
magic  : 4 bytes = 03 07 02 01
depth  : 640*400 * uint16   (little-endian)   = 512000 bytes
mono   : 640*800 * uint8    (two 640x400 planes stacked: cam L then cam R) = 512000 bytes
```

Total = 4 + 1,024,000 bytes, matching `curr-resolution 640x800x2` and
`depth+ir-resolution 640x400x4` (4 bytes/pixel = 2 depth + 1 + 1 mono).

Parsing: scan for the `03 07 02 01` magic, then read `depth` as `uint16[256000]`
reshaped `(400,640)` and `mono` as `uint8[512000]` reshaped `(800,640)`
immediately after. (This is what `revopoint.get_images` does; the small
`o -= 4` fudge in that code is because the magic overlaps the frame accounting.)

> **Caveat:** at some exposures the stream interleaves a period-4 cycle of
> capture states (see [depth-pipeline.md](depth-pipeline.md)); consecutive
> frames are not all equivalent.

## Color stream

The color camera is served by `zx_media.cgi` too. These are the `camera_id`
values the CGI accepts (read from its dispatch code):

| `camera_id` | Stream |
|---|---|
| 21 | compressed depth (above) |
| 22 | raw depth (above) |
| 32 | depth, a second mode of the same handler as 22 (not tried) |
| 50 | **color, MJPEG** |
| 60 | color, single JPEG snapshot |
| 80 | color, H.264 |

Verified on the MINI:

- `camera_id=50`: 1280x800 JPEG frames, ~4.4 fps, ~30-50 KB/frame. The framing
  is the same as the compressed depth stream: magic `0x11223344` (little-endian)
  + little-endian uint32 length + payload. The payload is a JPEG followed by a few
  bytes of padding after the `FF D9` end marker. The response headers only arrive
  with the first frame.
- It works with the USB cable unplugged (WiFi only), but **only while a depth
  stream (`camera_id=22`) is running**, as over USB. With no depth stream the
  request gets no frames at all, so the projector is on during color capture.
- A new color stream can start with a stale header left over from an earlier
  stream, with no payload behind it. Only accept a header if `FF D8` follows it,
  otherwise search for the next magic.
- After power up the color auto-exposure starts dark and takes ~5 s (~20 frames)
  to settle. It then holds across streams until the next power cycle.
- Opening a new color stream ends an older one, and `close_stream_all` ends it.
- `camera_id=60` returned `Content-Type: image/jpeg` with an empty body every
  time, with or without the depth and color streams running.
- `camera_id=80`: H.264 Main profile, 1280x800, ~4.5 fps, with the same framing
  (SPS/PPS + IDR first, then ~4 KB P-frames). It decodes with ffmpeg, but the low
  bitrate leaves visible block artifacts, so `camera_id=50` is better for stills.
- The depth and color streams run at the same time, and depth coverage was the
  same as with depth alone, so the two can be captured together
  (`Revopoint.get_images(color = True)`).

## HTTP server behavior (incidental)

- `GET /` → 403; unknown paths → 404; `OPTIONS /` → `Allow: OPTIONS, GET, HEAD, POST`.
- `zx_cmd.cgi` / `zx_media.cgi` with no query → HTTP 500.
