<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# ERPLibre Stream Deck

Suite of tools and games for the Elgato Stream Deck, integrated into the ERPLibre project.

All scripts auto-adapt to any Stream Deck model (Mini, Original, MK.2, XL, Plus, Neo) via `deck.key_layout()`.

## Prerequisites

<!-- [fr] -->
# ERPLibre Stream Deck

Suite d'outils et de jeux pour Elgato Stream Deck, intégrée au projet ERPLibre.

Tous les scripts s'adaptent automatiquement à n'importe quel modèle de Stream Deck (Mini, Original, MK.2, XL, Plus, Neo) via `deck.key_layout()`.

## Prérequis

<!-- [common] -->

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

<!-- [en] -->

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

<!-- [fr] -->

## Scripts utilitaires

### erplibre_controller.py

Contrôleur principal du Stream Deck pour ERPLibre. Gère les boutons physiques avec des actions assignées :

| Bouton | Action |
|--------|--------|
| 0 | Lance `todo.py` (CLI interactif ERPLibre) |
| 1 | Luminosité + |
| 2 | Luminosité - |
| 3 | Lance `keyboard_talk.py` (automatisation clavier) |
| 4 | Reset du Stream Deck |
| 5 | Cycle mode d'affichage : Animation → Big image → Webcam |

Supporte le Stream Deck Plus (touchscreen, dials), la détection USB hotplug (pyudev), et les animations GIF.

<!-- [common] -->

```bash
make streamdeck
```

<!-- [en] -->

### keyboard_talk.py

Keyboard automation script. Uses `wmctrl` to target a terminal window, then sends an automated key sequence via the `keyboard` library.

## Files

<!-- [fr] -->

### keyboard_talk.py

Script d'automatisation clavier. Utilise `wmctrl` pour cibler une fenêtre terminal, puis envoie une séquence de touches automatisée via la librairie `keyboard`.

## Fichiers

<!-- [common] -->

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

<!-- [en] -->

## License

AGPL-3.0 — [TechnoLibre](http://www.technolibre.ca)

<!-- [fr] -->

## Licence

AGPL-3.0 — [TechnoLibre](http://www.technolibre.ca)
