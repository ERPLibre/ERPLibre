
# ERPLibre Stream Deck

Suite of tools and games for the Elgato Stream Deck, integrated into the ERPLibre project.

All scripts auto-adapt to any Stream Deck model (Mini, Original, MK.2, XL, Plus, Neo) via `deck.key_layout()`.

## Prerequisites


```bash
# System dependencies / Dépendances système
sudo apt install -y libudev-dev libusb-1.0-0-dev libhidapi-libusb0

# udev rules (non-root access) / Règles udev (accès non-root)
sudo tee /etc/udev/rules.d/70-streamdeck.rules << 'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", TAG+="uaccess"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger

# Python dependencies / Dépendances Python
pip install -r script/stream_deck/requirements.txt
```


## Utility scripts

### erplibre_controller.py

Main Stream Deck controller for ERPLibre. Handles physical buttons with assigned actions:

| Button | Action |
|--------|--------|
| 0 | Launch `todo.py` (interactive ERPLibre CLI) |
| 1 | Brightness + |
| 2 | Brightness - |
| 3 | Launch `keyboard_talk.py` (keyboard automation) |
| 4 | Reset Stream Deck |
| 5 | Cycle display mode: Animation -> Big image -> Webcam |

Supports the Stream Deck Plus (touchscreen, dials), USB hotplug detection (pyudev), and GIF animations.


```bash
make streamdeck
```


### keyboard_talk.py

Keyboard automation script. Uses `wmctrl` to target a terminal window, then sends an automated key sequence via the `keyboard` library.

## Files


```
script/stream_deck/
├── README.md                  # English / Anglais
├── README.fr.md               # French / Français
├── INSTALL.md                 # Dependency install guide / Guide d'installation
├── plan.md                    # StreamController integration plan / Plan d'intégration
├── requirements.txt           # Python dependencies / Dépendances Python
├── Assets/                    # Controller images and fonts / Images et polices
├── erplibre_controller.py     # Main ERPLibre controller / Contrôleur principal
└── keyboard_talk.py           # Keyboard automation / Automatisation clavier
```


## License

AGPL-3.0 — [TechnoLibre](http://www.technolibre.ca)
