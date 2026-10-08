# `/dev/rk_preisp` registers

The depth engine is configured by writing registers on the Rockchip pre-ISP
coprocessor. Over WiFi this is done through the HTTP `system_cmd` endpoint:

```
http://<ip>/cgi-bin/zx_cmd.cgi?system_cmd=<urlencode("echo s <reg> <val...> > /dev/rk_preisp")>
```

Every write returns `[<cmd>][ok]` on success. `s` = set; there is presumably a
corresponding get.

## Status legend

- **✅ verified** — observed to have the described effect on this MINI (fw `v7.6.9.0816`, 2026-10-08).
- **accepted** — the write returns `[ok]` on the MINI but the effect was not independently confirmed.
- **inert** — the write returns `[ok]` but produced **no** observable change on the MINI.
- **(POP3)** — meaning comes from the POP3 reverse-engineering project / SDK headers, not confirmed here. See [references.md](references.md).

## Register table

| Reg | Meaning | MINI status | Notes |
|---|---|---|---|
| `0x702` | stream resolution (`0x702 640 400`) | accepted | part of `config_MINI`; raw stream stays 640x400 regardless, so effect unclear |
| `0x707` | depth range, mm (`0x707 90 280`) | accepted | 90–280 mm; matches the 100–200 mm spec |
| `0x903` | depth-camera gain | ✅ verified (accepted) | `set_depth_gain(g)` writes `16*g`; valid g = 1–16; keep **≤ 3** for accuracy (SDK) |
| `0x904` | "fake mode" (`SET_FAKE_MODE`) | accepted | part of `config_MINI`; 0 or 1 |
| `0x910` | frame time | not tried | (POP3) |
| `0x911` | **exposure** | ✅ verified | mono brightness tracked it directly (median 79→4 as 60000→1500); the real image-quality lever |
| `0x912` | auto-exposure mode (0 = manual, 1 = auto) | ✅ verified | had to set `0x912 0` for manual `0x911` to hold; restored to `1` after testing |
| `0x918` | depth-scale divisor | **unresolved** | (POP3) says divisor = 10 (0.1 mm/unit). On the MINI that gives ~2.17 m for a near object — wrong. Metric scale is NOT established; use `Q.bin` reprojection instead (see [depth-pipeline.md](depth-pipeline.md)). |
| `0xb00` | LED master enable | **inert** | (POP3). Toggling 0/1 gave byte-identical frames on the MINI |
| `0xb01` | projector enable | **inert** | (POP3). Also byte-identical. On the MINI the projector is **always on** while streaming — see [depth-pipeline.md](depth-pipeline.md) |

## Practical defaults that worked

```
0x904 0            # config_MINI
0x702 640 400      # config_MINI
0x707 90 280       # config_MINI (depth range 90-280 mm)
0x903 16           # gain 1
0x912 0            # manual exposure
0x911 12000        # exposure sweet spot for a bright near object in this test scene
```

Exposure `12000` gave the best single-frame depth coverage in the test scene
(~23% of the 640x400 frame = most of the in-range object). The optimum is
scene-dependent; this is the knob to tune per subject.

> **Important:** `0xb00`/`0xb01`/`0x918` are carried over from the POP3 and do
> **not** behave as documented on this MINI. Treat any other POP3 register as
> unverified until checked here.
