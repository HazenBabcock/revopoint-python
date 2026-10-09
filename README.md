## revoscan-python ##
![depth and color images](images/image.png?raw=true "")

A python module for interfacing with a Revopoint scanner. Depth images, color
images, exposure and gain are all handled over WIFI via HTTP, which should work on
any OS.

The scanner should be powered on and connected to WIFI. In general it is easier to
configure the scanner to join your WIFI network instead of being it's own network.
You can do this in the Revoscan software by setting the scanner to be a client.
The scanner draws more power while scanning, if it reboots when a scan starts try
a USB power supply that is rated for more current.

The code has been tested with Python3.10 / Python3.12 and Revopoint MINI scanner running v7.6.9.0816.

## Sample Usage ##

This captures a depth image and the corresponding color image, as in the figure
above. [examples/readme_figure.py](examples/readme_figure.py) is the script that
made the figure.

```
import numpy
import revopoint_python.revopoint as rppy

rp = rppy.Revopoint(ipAddr = "192.168.1.14")

# get firmware(?) version.
print(rp.get_version())

# close any stream left open by an earlier session.
rp.close_streams()

# configure for MINI.
rp.config_MINI()

# set the gain and a manual exposure for the depth cameras. The exposure is the
# main depth-quality setting, ~3000-15000 is a good starting range.
rp.set_depth_gain(1)
rp.set_exposure(12000)

# acquire eight depth images and the color camera images at the same time,
# this returns a dictionary with the depth images, the images from the depth
# cameras and the color images. At lower exposures some depth frames come out
# nearly empty (the projector is dimmer on those frames), so keep the one with
# the most valid pixels.
images = rp.get_images(8, color = True)
depth = max(images["depth"], key = numpy.count_nonzero)
color = images["color"][-1]
rp.close_streams()

# return exposure control to the scanner.
rp.set_auto_exposure(True)
```

To capture only color images use `rp.get_color_image()`. This can also read the
color camera over USB (`usb = True`, Linux only).

## Known Issues ##

* The scan rate is about 4Hz, well below 10Hz. It is limited by how long the
  projector spends on each of its 12 patterns (~20ms), not by WIFI bandwidth, so
  the compressed stream does not help. See [notes/depth-pipeline.md](notes/depth-pipeline.md).
  The color camera also runs at about 4Hz over WIFI.
* The projector is on during color capture, because the color camera only
  streams while a depth stream is running.
* After the scanner powers up the color camera's auto-exposure takes about 5
  seconds to settle. By default (`settle = True`) the color capture waits for it.
* The color camera's white balance is automatic, under warm indoor lighting
  the images look quite yellow.
* The depth values are raw, conversion to millimeters is not done yet.

## Dependencies ##

* [numpy](https://www.numpy.org/)
* [requests](https://requests.readthedocs.io/)
* [OpenCV](https://opencv.org/) (only for decoding the color images)
* [matplotlib](https://matplotlib.org/) (only for examples/readme_figure.py)
