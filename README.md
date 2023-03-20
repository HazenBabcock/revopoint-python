## revoscan-python ##
![depth image](images/image.png?raw=true "")

A python module for interfacing with a Revopoint scanner. It should work on any OS
as all communcation with the scanner happens via HTTP.

The scanner should be powered on and connected to WIFI. In general it is easier to
configure the scanner to join your WIFI network instead of being it's own network.
You can do this in the Revoscan software by setting the scanner to be a client.

The code has been tested with Python3.10 and Revopoint MINI scanner running v7.6.9.0816.

## Sample Usage ##
```
import revopoint_python.revopoint as rppy

rp = rppy.Revopoint(ipAddr = "192.168.1.14")

# get firmware(?) version.
print(rp.get_version())

# configure for MINI.
rp.config_MINI()

# set the gain of the depth camera.
rp.set_depth_gain(1)

# acquire two depth images, this returns a dictionary with the
# depth images and the images from the depth cameras.
images = rp.get_images(2)
```

## Known Issues ##

* The scan rate is well below 10Hz.
* The images from the color USB camera are not available.

## Dependencies ##

* [numpy](https://www.numpy.org/)
* [requests](https://requests.readthedocs.io/)
