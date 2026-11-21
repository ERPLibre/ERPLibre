
# ERPLibre Stream Deck

The Elgato Stream Deck in ERPLibre Home. The deck program itself, the
`erplibre_streamdeck` package with its plugins, the classic controller,
the deck lock and the speech-to-text translator, lives in its own
repository,
[erplibre_streamdeck](https://github.com/TechnoLibre/erplibre_streamdeck),
cloned at `script/stream_deck/deck/` by Google Repo or by the Stream Deck
level of the installer. Its `README.md` describes the program, its
plugins and how to write one; its `CONTRACT.md` states what it and
ERPLibre rely on, and `deck_contract` holds the version ERPLibre expects.
See [the deck program in ERPLibre](../../doc/erplibre_streamdeck_deck.md).

## Install


```bash
make erplibre_home_streamdeck_install
```


It clones the deck program, installs its `requirements.txt` in
`.venv.streamdeck`, writes the udev rule and the systemd user service. The
details, the settings and the TODO menu are in [INSTALL.md](INSTALL.md).

## Make targets


```bash
make streamdeck_erplibre               # deck program / programme du deck
make streamdeck                        # classic controller / contrôleur
make streamdeck_tiler_unittest         # deck tests / tests du deck
make streamdeck_translator_doctor      # translator backends / moteurs
```


Each runs a file of `script/stream_deck/deck/` under `.venv.streamdeck`,
and stops with the install command when the clone or the venv is
missing.

### GNOME Shell extension

The GNOME extension, a repository of its own
([erplibre-home-gnome-extension](https://github.com/TechnoLibre/erplibre-home-gnome-extension)) cloned at
`script/gnome-extension/erplibre_home/`, ships a six-indicator panel button (controller,
pencil, film, ERPLibre, network, device) plus the tiling D-Bus interface used by
the deck program. See its `README.md` and
[the extension in ERPLibre](../../doc/erplibre_home_gnome_extension.md).

## Files


```
script/stream_deck/
├── README.md                  # English / Anglais
├── README.fr.md               # French / Français
├── INSTALL.md                 # Install guide / Guide d'installation
├── deck_contract              # Deck contract version / Version du contrat
├── screenshots/               # Reference shots / Captures de référence
└── deck/                      # Deck program clone / Clone du deck
```


## License

AGPL-3.0 — [TechnoLibre](http://www.technolibre.ca)
