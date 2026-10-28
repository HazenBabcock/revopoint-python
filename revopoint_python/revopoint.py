#!/usr/bin/python
"""
Interface with a Revopoint scanner via WIFI.
"""

import glob
import json
import os
import struct
import threading
import time

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

    def get_color_image(self, n = 1, device = None, raw_jpeg = False, manage_engine = True, usb = False, settle = True):
        """
        Capture n frames from the color (RGB) camera.

        By default the frames come over WiFi/HTTP (an MJPEG stream from
        zx_media.cgi, camera_id=50), so no USB connection is needed. Pass
        usb = True to read the same camera as a USB webcam instead (Linux only,
        V4L2 through OpenCV).

        Either way the color camera only delivers frames while the scanner's
        depth engine is running. With manage_engine = True (default) a short
        depth stream is started (projector on), the color frame(s) are grabbed,
        and the stream is always torn down afterwards. Pass manage_engine = False
        if you already have a depth stream running.

        The color camera's exposure/white balance are locked to auto by the
        vendor, so these are auto-exposed frames (and the projector is lit during
        the capture, though its fringe is largely averaged out by the exposure).
        After the scanner powers up the auto-exposure starts dark and takes ~5
        seconds to settle, it then holds until the next power cycle.

        device        : (usb only) V4L2 device path, e.g. '/dev/video4'. If None
                        the color node is auto-detected by name ('RGBCam*').
        raw_jpeg      : if True return the undecoded JPEG bytes per frame (handy
                        to save '.jpg' with no re-encode); else decoded RGB arrays.
        manage_engine : start/stop a depth stream to power the camera (default),
                        or assume one is already running.
        usb           : read the frames over USB instead of WiFi.
        settle        : True (default) discards frames until the auto-exposure
                        has settled (at most 10 seconds), an integer discards that
                        many frames, False keeps the first frames.

        Decoding the frames, settle = True and usb = True all need OpenCV. With
        raw_jpeg = True and settle = False (or an integer) the WiFi path doesn't.

        Returns a list of length n.
        """
        if (self.ipAddr is None) and (manage_engine or not usb):
            raise RuntimeError("This needs the scanner's WiFi ipAddr; for USB without it, "
                               "run a depth stream yourself and pass manage_engine = False")

        if usb and (device is None):
            device = self._find_color_device()

        stopEngine = None
        engineThread = None
        try:
            if manage_engine:
                stopEngine = threading.Event()
                engineThread = threading.Thread(target = self._run_engine, args = (stopEngine,), daemon = True)
                engineThread.start()
                time.sleep(1.5)       # let the engine and the camera start

            if usb:
                jpegs = self._iter_color_usb(device)
            else:
                jpegs = self._iter_color_http()
            try:
                frames = self._take_color(jpegs, n, settle)
            finally:
                jpegs.close()

            if raw_jpeg:
                return frames
            return [self._decode_jpeg(f) for f in frames]
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

    def get_images(self, nImages, color = False, settle = True):
        """
        Returns nImages from the scanner. This will lock until complete, so maybe keep
        nImages on the small side.

        color  : if True also capture the color camera (over WiFi) at the same
                 time, the frames are returned as RGB arrays under "color".
                 This needs OpenCV.
        settle : as for get_color_image(). The depth stream is kept running
                 until the color auto-exposure has settled, and the depth images
                 returned are the most recent ones, so depth and color are from
                 the same time.

        Note: This assumes that images are 640x400x4 bytes.

        Note: The compressed stream ('camera_id=21') does not raise the frame
              rate, it is limited by the projector, see notes/depth-pipeline.md.

        Note: A new stream can begin with a frame left over from the previous
              stream, showing the scene as it was then (e.g. before the object
              was moved). The stream's first frame is always discarded.
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

        # There is a small amount of data between frames, thus the extra 10 bytes. One more
        # frame than asked for is read, as the first frame is discarded (see below).
        nBytes = (npix*4+10)*(nImages + 1)
        if color:
            # While waiting for the color camera we only keep the most recent
            # data, which may start part way through a frame, so allow one more.
            nBytes += npix*4+10
            colorState = {"jpegs" : [], "ready" : False, "error" : None}
            stopColor = threading.Event()
            colorThread = threading.Thread(target = self._collect_color,
                                           args = (stopColor, colorState, settle),
                                           daemon = True)
        resp = bytearray()
        trimmed = False
        try:
            with requests.get(f"{self._zx_media()}camera_id=22&type_id=20", stream = True) as r:

                # The color stream only works once the depth engine is running.
                if color:
                    colorThread.start()
                    t0 = time.time()

                for chunk in r.iter_content(chunk_size = 1024):
                    resp += chunk
                    if (len(resp) > nBytes):
                        if not color or colorState["ready"] or ((time.time() - t0) > 20):
                            break
                        if (len(resp) > 2*nBytes):
                            del resp[:len(resp) - nBytes]
                            trimmed = True
        finally:
            if color:
                stopColor.set()
                for _ in range(2):
                    try:
                        self.close_streams()
                    except Exception:
                        pass
                if colorThread.is_alive():
                    colorThread.join(timeout = 5)

        # Split resp byte stream into depth and 'other' images.
        images = {"depth" : [],
                  "other" : []}
        if color:
            if colorState["error"] is not None:
                raise RuntimeError(f"Color capture failed: {colorState['error']}")
            if (len(colorState["jpegs"]) == 0):
                raise RuntimeError("No color frames were received")
            images["color"] = [self._decode_jpeg(f) for f in list(colorState["jpegs"])]

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

        # The stream's first frame can be left over from the previous stream, so after
        # the object moves it shows the old pose. Drop it, unless the start of the
        # stream was already trimmed away above, and keep the most recent nImages.
        if not trimmed:
            images["depth"] = images["depth"][1:]
            images["other"] = images["other"][1:]
        images["depth"] = images["depth"][-nImages:]
        images["other"] = images["other"][-nImages:]

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

    def _brightness(self, jpeg):
        """
        Mean brightness of a JPEG frame, decoded at 1/8 size for speed.
        """
        import cv2
        im = cv2.imdecode(np.frombuffer(jpeg, dtype = np.uint8), cv2.IMREAD_REDUCED_GRAYSCALE_8)
        return 0.0 if im is None else float(im.mean())

    def _collect_color(self, stopEvent, state, settle):
        """
        Read the color stream (meant to run in a background thread while a depth
        stream runs). The frames from after the auto-exposure settled go in
        state["jpegs"], state["ready"] is set once the first of these arrives.
        """
        jpegs = self._iter_color_http(timeout = 15)
        try:
            state["jpegs"] = self._take_color(jpegs, 1, settle)
            state["ready"] = True
            for jpeg in jpegs:
                if stopEvent.is_set():
                    break
                state["jpegs"].append(jpeg)
        except Exception as e:
            # Closing the streams at the end can also end up here, that's fine.
            if not stopEvent.is_set():
                state["error"] = e
                state["ready"] = True
        finally:
            jpegs.close()

    def _decode_jpeg(self, jpeg):
        """
        Decode a JPEG frame to an RGB array.
        """
        import cv2
        im = cv2.imdecode(np.frombuffer(jpeg, dtype = np.uint8), cv2.IMREAD_COLOR)
        if im is None:
            raise RuntimeError("Could not decode a color frame")
        return cv2.cvtColor(im, cv2.COLOR_BGR2RGB)

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

    def _is_settled(self, means):
        """
        True once the color auto-exposure has settled, given the brightness of
        each frame so far. The frames are ~0.25 seconds apart. Once settled the
        brightness varies by up to ~3% over 3 frames (the projector), while it
        is still ramping up after power on the change is 7% or more.
        """
        return (len(means) > 3) and (abs(means[-1] - means[-4]) <= 0.05*max(means[-4], 1.0))

    def _iter_color_http(self, timeout = 10):
        """
        Yield JPEG frames from the color stream (zx_media.cgi, camera_id=50).

        Each frame is an 8 byte header, magic 0x11223344 and the payload length
        (both little-endian uint32), followed by the JPEG. The stream can start
        with a stale header left over from an earlier stream, so a header only
        counts if a JPEG follows it, otherwise we look for the next one.
        """
        magic = struct.pack("<I", 0x11223344)
        buf = bytearray()
        try:
            with requests.get(f"{self._zx_media()}camera_id=50", stream = True, timeout = timeout) as r:
                if (r.status_code != requests.codes.ok):
                    raise RuntimeError(f"Color stream failed with code {r.status_code}")
                for chunk in r.iter_content(chunk_size = 65536):
                    buf += chunk
                    while True:
                        o = buf.find(magic)
                        if (o == -1):
                            del buf[:max(0, len(buf) - 3)]     # keep a possible partial magic
                            break
                        if (len(buf) < (o + 10)):
                            del buf[:o]
                            break
                        if (buf[o+8:o+10] != b"\xff\xd8"):
                            del buf[:o+4]                       # stale header
                            continue
                        size = struct.unpack_from("<I", buf, o + 4)[0]
                        if (len(buf) < (o + 8 + size)):
                            del buf[:o]
                            break
                        jpeg = bytes(buf[o+8:o+8+size])
                        del buf[:o+8+size]

                        # The payload has a few bytes of padding after the
                        # end-of-image marker.
                        end = jpeg.rfind(b"\xff\xd9")
                        yield jpeg[:end + 2] if end != -1 else jpeg
        except requests.exceptions.RequestException as e:
            raise RuntimeError("No color frames (is the depth engine running?)") from e

    def _iter_color_usb(self, device):
        """
        Yield JPEG frames from the USB color camera (V4L2 through OpenCV).
        """
        import cv2

        cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
        if not cap.isOpened():
            raise RuntimeError(f"Could not open color camera {device}")
        try:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 800)

            # With CONVERT_RGB off the V4L2 backend hands back the raw MJPEG
            # buffer instead of a decoded BGR image.
            cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)

            while True:
                (ok, frame) = cap.read()
                if not ok:
                    raise RuntimeError(f"Failed to read a frame from {device} "
                                       "(is the depth engine running?)")

                # The mmap buffer is larger than the JPEG, so trim the trailing
                # padding back to the end-of-image marker.
                raw = frame.tobytes()
                end = raw.rfind(b"\xff\xd9")
                yield raw[:end + 2] if end != -1 else raw
        finally:
            cap.release()

    def _run_engine(self, stopEvent):
        """
        Start a depth stream and hold it open (meant to run in a background
        thread) so the camera subsystem is running -- required for color
        capture. The projector runs while this is active. The stream is
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

    def _take_color(self, jpegs, n, settle, timeout = 10.0):
        """
        Take n frames from an iterator of JPEG frames, first discarding frames
        while the color auto-exposure settles (see get_color_image()).
        """
        frames = []
        means = []
        t0 = time.time()
        for jpeg in jpegs:
            if settle is True:
                means.append(self._brightness(jpeg))
                if self._is_settled(means):
                    settle = 0
                elif ((time.time() - t0) > timeout):
                    print(f"Color auto-exposure did not settle in {timeout} seconds, using the frames anyway")
                    settle = 0
                else:
                    continue
            elif settle:
                settle -= 1
                continue
            frames.append(jpeg)
            if (len(frames) == n):
                return frames
        raise RuntimeError(f"Only got {len(frames)} of {n} color frames")

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

    # Grab a color frame over WiFi and save it. The color camera only streams
    # while a depth stream runs, so get_color_image briefly starts the engine
    # (projector on) and tears it down. raw_jpeg returns the camera's JPEG
    # bytes, so this writes a '.jpg' with no re-encode.
    jpg = rp.get_color_image(n = 1, raw_jpeg = True)[0]
    with open("color.jpg", "wb") as fp:
        fp.write(jpg)

    # Hand exposure control back to the scanner.
    rp.set_auto_exposure(True)
