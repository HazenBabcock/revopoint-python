#!/usr/bin/python
"""
Interface with a Revopoint scanner via WIFI.
"""

import json
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
        npix = 640*400
        
        # I only think this sequence of commands is necessary to start acquisition.

        # Configure the depth camera?
        tmp = "cam_type=mipi&set_display_reso=1&&set_display_width=640&&set_display_height=400&&set_display_type=4"
        self.check_response(requests.get(f"{self._zx_cmd()}{tmp}")),

        # Tell it run untriggered? Interesting that there might be a trigger? Software trigger?
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
            
        # Split resp byte stream into depth images.
        images = {"depth" : [],
                  "other" : []}

        o = 0
        sCode = [3,7,2,1]
        while (o < (len(resp)-4)):
            
            # Find start of next frame, this is the pattern '3,7,2,1'
            found = True
            for i in range(4):
                if (int(resp[o+i]) != sCode[i]):
                    found = False
                    break

            if not found:
                o += 1
                continue
            
            o += 4
            im1 = np.frombuffer(resp, dtype = np.uint16, count = npix, offset = o).reshape((400,640))
            im2 = np.frombuffer(resp, dtype = np.uint8, count = 2*npix, offset = o + 2*npix).reshape((400,2*640))
            images["depth"].append(im1)
            images["other"].append(im2)
            o += 4*npix-10   # Not sure why I need to wind this back slightly here.

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

    def set_depth_gain(self, gain):
        """
        Sets the 'gain' of the depth camera, valid values are 1-16 (integer).
        """
        if (gain > 16) or (gain < 1):
            print(f"Clipping {gain} to 1-16")
        gv = "{0:d}".format(16*max(1, min(gain, 16)))
        self.check_response(requests.get(f"{self._zx_cmd()}system_cmd=echo%20s%200x903%20{gv}%20>/dev/rk_preisp"))
        
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
    rp.set_depth_gain(5)

    nm = 2
    images = rp.get_images(nm)
    with tifffile.TiffWriter("depth.tif") as tf:
        for i in range(nm):
            tf.write(images["depth"][i])

    with tifffile.TiffWriter("other.tif") as tf:
        for i in range(nm):
            tf.write(images["other"][i])
