#!/usr/bin/python
"""
Interface with a Revopoint scanner via WIFI.
"""

import glob
import json
import os

import numpy as np
import requests


class Revopoint(object):

    def __init__(self, ipAddr = None, **kwds):
        super().__init__(**kwds)

        self.ipAddr = ipAddr

    def close_streams(self):
        """
        This cleans up if a session is already open?
        """
        self.check_response(requests.get(f"{self._zx_cmd()}close_stream_all"))

    def check_response(self, r):
        """
        Checks that we got an 'OK' response.
        """
        if (r.status_code != requests.codes.ok):
            print(f"{r.url} failed with code {r.status_code}")
            return None
        return r

    def config_MINI(self):
        """
        Configure MINI to scan as expected? These may different for a different scanner?

        If you don't send these commands the scan appears to be slower and have a higher
        gain. Not really sure what these commands might actually be doing.
        """
        # 'system_cmd=echo s 0x904 0 > /dev/rk_preisp'
        # This has something to do with accuracy? Values seem to be 0 or 1.
        self.check_response(requests.get(f"{self._zx_cmd()}system_cmd=echo%20s%200x904%200%20>%20/dev/rk_preisp"))

        # 'system_cmd=echo s 0x702 640 400 > /dev/rk_preisp'
        # This sets the depth camera XY resolution? If you don't send this command you still get a 640x400 depth image
        # so not that clear.
        self.check_response(requests.get(f"{self._zx_cmd()}system_cmd=echo%20s%200x702%20640%20400%20>%20/dev/rk_preisp"))

        # 'system_cmd=echo s 0x707 90 280 >/dev/rk_preisp'
        # This sets the scanner pattern? Camera frame rate? I couldn't find any info about this one.
        self.check_response(requests.get(f"{self._zx_cmd()}system_cmd=echo%20s%200x707%2090%20280%20>/dev/rk_preisp"))

    def get_color_image(self, n = 1, device = None, raw_jpeg = False, manage_engine = True):
        """
        Capture n frames from the USB color (RGB) camera.

        The color camera streams over USB, but only while the scanner's depth
        engine is running -- the shared camera subsystem is unpowered otherwise.
        So this needs BOTH the USB connection (for the frames) and the WiFi/HTTP
        connection (to run the engine), and it briefly runs the projector.

        With manage_engine = True (default) a short depth stream is started to
        power the camera (projector on), the color frame(s) are grabbed, and the
        stream is always torn down afterwards. Pass manage_engine = False if you
        already have a depth stream running (e.g. grabbing depth and color
        together), in which case only the USB connection is used here.

        The color camera's exposure/white balance are locked to auto by the
        vendor, so these are auto-exposed frames (and the projector is lit during
        the capture, though its fringe is largely averaged out by the exposure).

        Requires OpenCV (imported here, not needed for the WiFi-only features).

        device        : V4L2 device path, e.g. '/dev/video4'. If None the color
                        node is auto-detected by name ('RGBCam*').
        raw_jpeg      : if True return the undecoded MJPEG bytes per frame (handy
                        to save '.jpg' with no re-encode); else decoded RGB arrays.
        manage_engine : start/stop a depth stream to power the camera (default),
                        or assume one is already running.

        Returns a list of length n.
        """
        import threading
        import time

        import cv2

        if device is None:
            device = self._find_color_device()

        stopEngine = None
        engineThread = None
        try:
            if manage_engine:
                if self.ipAddr is None:
                    raise RuntimeError("manage_engine needs the scanner's WiFi ipAddr; set it, or "
                                       "run a depth stream yourself and pass manage_engine = False")
                stopEngine = threading.Event()
                engineThread = threading.Thread(target = self._run_engine, args = (stopEngine,), daemon = True)
                engineThread.start()
                time.sleep(1.5)       # let the camera subsystem power up

            cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
            if not cap.isOpened():
                raise RuntimeError(f"Could not open color camera {device}")
            try:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 800)

                # With CONVERT_RGB off the V4L2 backend hands back the raw MJPEG
                # buffer instead of a decoded BGR image.
                if raw_jpeg:
                    cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)

                frames = []
                for _ in range(n):
                    (ok, frame) = cap.read()
                    if not ok:
                        raise RuntimeError(f"Failed to read a frame from {device} "
                                           "(is the depth engine running?)")
                    if raw_jpeg:
                        # The mmap buffer is larger than the JPEG, so trim the
                        # trailing padding back to the end-of-image marker.
                        raw = frame.tobytes()
                        end = raw.rfind(b"\xff\xd9")
                        frames.append(raw[:end + 2] if end != -1 else raw)
                    else:
                        frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                return frames
            finally:
                cap.release()
        finally:
            # Always tear the stream down -- a stream left open keeps the
            # projector/engine running.
            if stopEngine is not None:
                stopEngine.set()
                if engineThread is not None:
                    engineThread.join(timeout = 5)
                for _ in range(2):
                    try:
                        self.close_streams()
                    except Exception:
                        pass

    def get_depth_resolution(self):
        """
        Returns the current resolution, not sure what this means or if it can be changed.
        """
        r = self.check_response(requests.get(f"{self._zx_cmd()}?cam_type=mipi&get_depth_reso"))
        if r is not None:
            return json.loads(r.content.decode('utf-8').replace("}{", ","))

    def get_images(self, nImages):
        """
        Returns nImages from the scanner. This will lock until complete, so maybe keep
        nImages on the small side.

        Note: This assumes that images are 640x400x4 bytes.

        Possible TODO: If you instead start acquriring with 'http://192.168.1.14/cgi-bin/zx_media.cgi?camera_id=21'
                       you will get an LZ? compressed data stream. This might improve the bandwidth?
        """
        # This might be scanner dependent?
        sizeX = 640
        sizeY = 400
        npix = sizeX*sizeY

        # I only think this sequence of commands is necessary to start acquisition.

        # Configure the depth camera?
        tmp = "cam_type=mipi&set_display_reso=1&&set_display_width=640&&set_display_height=400&&set_display_type=4"
        self.check_response(requests.get(f"{self._zx_cmd()}{tmp}")),

        # Tell the scanner to return the pictures from the two depth cameras as well.
        self.check_response(requests.get(f"{self._zx_cmd()}cam_type=mipi&set_depth_output_fmt=3"))

        # Tell the scanner to run untriggered? Interesting that there might be a trigger? Software trigger?
        self.check_response(requests.get(f"{self._zx_cmd()}cam_type=mipi&set_trigger_mode=0"))

        # This actually starts the camera. You get the camera data back as a stream of bytes. It stops
        # when you break the connection (which happens when we drop out of the with statement).

        nBytes = (npix*4+10)*nImages    # There is a small amount of data between frames, thus the extra 10 bytes.
        resp = b''
        with requests.get(f"{self._zx_media()}camera_id=22&type_id=20", stream = True) as r:
            for chunk in r.iter_content(chunk_size = 1024):
                resp += chunk
                if (len(resp) > nBytes):
                    break

        # Split resp byte stream into depth and 'other' images.
        images = {"depth" : [],
                  "other" : []}

        o = 0
        sCode = [3,7,2,1]
        while (o < (len(resp)-(npix*4+4))):

            # Find start of next frame, this is the pattern '3,7,2,1'.
            found = True
            for i in range(4):
                if (int(resp[o+i]) != sCode[i]):
                    found = False
                    break

            if not found:
                o += 1
                continue

            o += 4

            # Depth images are 16 bit unsigned integer corresponding to depth. Low values and/or dropouts
            # presumably mean that there was no reading for this pixel.
            im1 = np.frombuffer(resp, dtype = np.uint16, count = npix, offset = o).reshape((sizeY,sizeX))
            images["depth"].append(im1)

            # I think these are the images from the two depth sensor cameras. They are 8 bit grey scale.
            im2 = np.frombuffer(resp, dtype = np.uint8, count = 2*npix, offset = o + 2*npix).reshape((2*sizeY,sizeX))
            images["other"].append(im2)

            # Update offset in the byte stream.
            o += 4*npix
            o -= 4       # Not sure why I need to wind this back slightly here.

            if (len(images["depth"]) == nImages):
                break

        return images

    def get_version(self):
        """
        Returns the current firmware version?
        """
        r = self.check_response(requests.get(f"{self._zx_cmd()}download=/tmp/inited"))
        if r is not None:
            return r.content.decode('utf-8')

    def set_auto_exposure(self, enabled = True):
        """
        Enable (True) or disable (False) the depth camera's auto-exposure
        (register 0x912). set_exposure() turns this off so a manual value holds;
        call this with True to hand control back to the scanner.
        """
        self._set_register("0x912", 1 if enabled else 0)

    def set_depth_gain(self, gain):
        """
        Sets the 'gain' of the depth camera, valid values are 1-16 (integer).
        The register (0x903) takes 16*gain; the SDK recommends keeping gain <= 3.
        """
        if (gain > 16) or (gain < 1):
            print(f"Clipping {gain} to 1-16")
        self._set_register("0x903", 16*max(1, min(gain, 16)))

    def set_exposure(self, exposure):
        """
        Set the depth-camera exposure (register 0x911) and switch to manual
        exposure (register 0x912 = 0) so the value holds.

        'exposure' is in the scanner's exposure units (approximately microseconds
        per the SDK; useful range ~3000-60000). This is the main image-quality
        lever: too short collapses the depth (the scene is too dark to match the
        projected fringe), too long saturates bright/near surfaces into holes. On
        a typical scene a value around 3000-12000 gives the best single-frame
        depth coverage.
        """
        if (exposure < 1000) or (exposure > 60000):
            print(f"Exposure {exposure} is outside the typical 1000-60000 range")
        self._set_register("0x912", 0)              # manual exposure
        self._set_register("0x911", int(exposure))

    def _find_color_device(self):
        """
        Find the USB color-camera V4L2 node by name. The color UVC function
        enumerates as 'RGBCam...'; the lowest-numbered matching node is the
        capture node (a higher one is the metadata node). Linux only.
        """
        best = None
        for namePath in glob.glob("/sys/class/video4linux/video*/name"):
            try:
                with open(namePath) as fp:
                    name = fp.read().strip()
            except OSError:
                continue
            if "RGBCam" in name:
                idx = int(os.path.basename(os.path.dirname(namePath))[len("video"):])
                if (best is None) or (idx < best):
                    best = idx
        if best is None:
            raise RuntimeError("Could not find a Revopoint color camera (RGBCam*). "
                               "Is the scanner connected over USB? You can also pass device= explicitly.")
        return f"/dev/video{best}"

    def _run_engine(self, stopEvent):
        """
        Start a depth stream and hold it open (meant to run in a background
        thread) so the shared camera subsystem is powered -- required for USB
        color capture. The projector runs while this is active. The stream is
        closed when 'stopEvent' is set; the caller must also call close_streams()
        to be sure the engine is stopped on the scanner side.
        """
        self.check_response(requests.get(f"{self._zx_cmd()}close_stream_all"))
        tmp = "cam_type=mipi&set_display_reso=1&&set_display_width=640&&set_display_height=400&&set_display_type=4"
        self.check_response(requests.get(f"{self._zx_cmd()}{tmp}"))
        self.check_response(requests.get(f"{self._zx_cmd()}cam_type=mipi&set_depth_output_fmt=3"))
        self.check_response(requests.get(f"{self._zx_cmd()}cam_type=mipi&set_trigger_mode=0"))
        try:
            with requests.get(f"{self._zx_media()}camera_id=22&type_id=20", stream = True, timeout = 15) as r:
                for chunk in r.iter_content(chunk_size = 65536):
                    if stopEvent.is_set():
                        break
        except Exception:
            pass

    def _set_register(self, reg, *values):
        """
        Write a register on the depth engine (RK pre-ISP) via the HTTP
        'system_cmd' endpoint, i.e. 'echo s <reg> <values...> > /dev/rk_preisp'.
        See notes/rk-preisp-registers.md for the known registers.
        """
        words = ["echo", "s", str(reg)] + [str(v) for v in values] + [">", "/dev/rk_preisp"]
        query = "system_cmd=" + "%20".join(words)
        return self.check_response(requests.get(f"{self._zx_cmd()}{query}"))

    def _zx_cmd(self):
        """
        Helper to simplify sending commands to zx_cmd.cgi"
        """
        return f"http://{self.ipAddr}/cgi-bin/zx_cmd.cgi?"

    def _zx_media(self):
        """
        Helper to simplify sending commands to zx_media.cgi"
        """
        return f"http://{self.ipAddr}/cgi-bin/zx_media.cgi?"


if(__name__ == "__main__"):
    import tifffile

    rp = Revopoint(ipAddr = "192.168.1.14")
    rp.close_streams()
    print(rp.get_version())
    print(rp.get_depth_resolution())
    rp.config_MINI()
    rp.set_depth_gain(1)

    # Set a manual exposure. Units are ~microseconds (SDK); ~3000-12000 is a good
    # starting range. This is the main depth-quality lever.
    rp.set_exposure(6000)

    nm = 2
    images = rp.get_images(nm)
    with tifffile.TiffWriter("depth.tif") as tf:
        for i in range(nm):
            tf.write(images["depth"][i])

    with tifffile.TiffWriter("other.tif") as tf:
        for i in range(nm):
            tf.write(images["other"][i])

    # Grab a color frame from the USB camera and save it. The scanner must be
    # plugged in over USB (for the frames) AND reachable over WiFi -- the color
    # sensor only streams while a depth stream runs, so get_color_image briefly
    # starts the engine (projector on) and tears it down. raw_jpeg returns the
    # camera's MJPEG bytes, so this writes a '.jpg' with no re-encode.
    jpg = rp.get_color_image(n = 1, raw_jpeg = True)[0]
    with open("color.jpg", "wb") as fp:
        fp.write(jpg)

    # Hand exposure control back to the scanner.
    rp.set_auto_exposure(True)
