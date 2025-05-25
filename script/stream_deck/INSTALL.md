# Guide to install

https://github.com/jamesridgway/devdeck/wiki/Installation#pre-requisite-libusb-hidapi-backend

```
# For Ubuntu

sudo apt install -y libudev-dev libusb-1.0-0-dev libhidapi-libusb0

# Add your user to plugdev group
sudo usermod -a -G plugdev `whoami`

# udev rule to allow all users non-root access to Elgato StreamDeck devices:
sudo tee /etc/udev/rules.d/10-streamdeck.rules << EOF
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", ATTRS{idProduct}=="0060", MODE:="660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", ATTRS{idProduct}=="0063", MODE:="660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", ATTRS{idProduct}=="006c", MODE:="660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", ATTRS{idProduct}=="006d", MODE:="660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", ATTRS{idProduct}=="0080", MODE:="660", GROUP="plugdev"
EOF

# Reload udev rules to ensure the new permissions take effect
sudo udevadm control --reload-rules
```
