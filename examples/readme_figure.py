#!/usr/bin/env python
"""
Capture a depth image and the matching color camera image from a Revopoint
scanner and save them one above the other. This is how images/image.png in the
README was made.

Everything comes over WiFi, the scanner only needs USB for power.

Usage (from the repository root):
    python examples/readme_figure.py --ip 192.168.1.14
"""
import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Allow running from a checkout without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import revopoint_python.revopoint as rppy


def capture(ipAddr, exposure, nImages):
    """
    Returns (depth, color): the densest of nImages depth frames and an RGB
    frame from the color camera, captured at the same time.
    """
    rp = rppy.Revopoint(ipAddr = ipAddr)
    rp.close_streams()
    try:
        rp.config_MINI()
        rp.set_depth_gain(1)
        rp.set_exposure(exposure)
        images = rp.get_images(nImages, color = True)
    finally:
        rp.set_auto_exposure(True)
        rp.close_streams()

    if (len(images["depth"]) == 0):
        raise RuntimeError("No depth frames were received.")

    # The scanner cycles through several exposure states, so some frames are
    # sparse. Keep the one with the most valid (non-zero) pixels.
    depth = max(images["depth"], key = np.count_nonzero)
    color = images["color"][-1]
    return depth, color


def make_figure(depth, color, fname):
    """
    Two vertical panels, color on top and depth (raw values, invalid pixels
    black) below. The colorbar gets its own column so both panels are the
    same width.
    """
    fig = plt.figure(figsize = (6.6, 8.2))
    gs = fig.add_gridspec(2, 2, width_ratios = [1, 0.04], wspace = 0.05, hspace = 0.15)
    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[1, 0])
    cax = fig.add_subplot(gs[1, 1])

    ax1.imshow(color)
    ax1.set_title("Color camera")

    valid = depth[depth > 0]
    [vmin, vmax] = np.percentile(valid, [1, 99])
    cmap = plt.get_cmap("magma").copy()
    cmap.set_bad("black")
    im = ax2.imshow(np.ma.masked_equal(depth, 0), cmap = cmap, vmin = vmin, vmax = vmax)
    fig.colorbar(im, cax = cax, label = "raw depth value")
    ax2.set_title("Depth")

    for ax in (ax1, ax2):
        ax.set_xticks([])
        ax.set_yticks([])

    fig.savefig(fname, dpi = 100, bbox_inches = "tight")
    plt.close(fig)


if (__name__ == "__main__"):
    parser = argparse.ArgumentParser(description = "Capture the README depth + color figure.")
    parser.add_argument("--ip", required = True, help = "Scanner IP address.")
    parser.add_argument("--exposure", type = int, default = 12000, help = "Depth exposure (default 12000).")
    parser.add_argument("--frames", type = int, default = 8, help = "Depth frames to choose from (default 8).")
    parser.add_argument("--out", default = "images/image.png", help = "Output file (default images/image.png).")
    args = parser.parse_args()

    (depth, color) = capture(args.ip, args.exposure, args.frames)
    print(f"depth: {np.count_nonzero(depth)/depth.size:.1%} valid, raw range {depth[depth > 0].min()}-{depth.max()}")
    make_figure(depth, color, args.out)
    print(f"saved {args.out}")
