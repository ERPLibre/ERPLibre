<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
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

<!-- [fr] -->
# ERPLibre Stream Deck

L'Elgato Stream Deck dans ERPLibre Home. Le programme du deck lui-même, le
paquet `erplibre_streamdeck` et ses plugins, le contrôleur classique, le
verrou du deck et le traducteur parole-texte, vit dans son propre dépôt,
[erplibre_streamdeck](https://github.com/TechnoLibre/erplibre_streamdeck),
cloné dans `script/stream_deck/deck/` par Google Repo ou par le niveau
Stream Deck de l'installateur. Son `README.fr.md` décrit le programme, ses
plugins et comment en écrire un ; son `CONTRACT.md` dit ce que lui et
ERPLibre attendent l'un de l'autre, et `deck_contract` porte la version
qu'ERPLibre attend. Voir
[le programme du deck dans ERPLibre](../../doc/erplibre_streamdeck_deck.fr.md).

## Installation

<!-- [common] -->

```bash
make erplibre_home_streamdeck_install
```

<!-- [en] -->

It clones the deck program, installs its `requirements.txt` in
`.venv.streamdeck`, writes the udev rule and the systemd user service. The
details, the settings and the TODO menu are in [INSTALL.md](INSTALL.md).

## Make targets

<!-- [fr] -->

Elle clone le programme du deck, installe son `requirements.txt` dans
`.venv.streamdeck`, écrit la règle udev et le service systemd de
l'utilisateur. Le détail, les réglages et le menu TODO sont dans
[INSTALL.fr.md](INSTALL.fr.md).

## Cibles make

<!-- [common] -->

```bash
make streamdeck_erplibre               # deck program / programme du deck
make streamdeck                        # classic controller / contrôleur
make streamdeck_tiler_unittest         # deck tests / tests du deck
make streamdeck_translator_doctor      # translator backends / moteurs
```

<!-- [en] -->

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

<!-- [fr] -->

Chacune lance un fichier de `script/stream_deck/deck/` sous
`.venv.streamdeck`, et s'arrête sur la commande d'installation quand le
clone ou le venv manque.

### Extension GNOME Shell

L'extension GNOME, un dépôt à part
([erplibre-home-gnome-extension](https://github.com/TechnoLibre/erplibre-home-gnome-extension)) cloné dans
`script/gnome-extension/erplibre_home/`, fournit un panneau à six indicateurs (controller,
pencil, film, ERPLibre, network, device) ainsi que l'interface D-Bus de tuilage
qu'utilise le programme du deck. Voir son `README.fr.md` et
[l'extension dans ERPLibre](../../doc/erplibre_home_gnome_extension.fr.md).

## Fichiers

<!-- [common] -->

```
script/stream_deck/
├── README.md                  # English / Anglais
├── README.fr.md               # French / Français
├── INSTALL.md                 # Install guide / Guide d'installation
├── deck_contract              # Deck contract version / Version du contrat
├── screenshots/               # Reference shots / Captures de référence
└── deck/                      # Deck program clone / Clone du deck
```

<!-- [en] -->

## License

AGPL-3.0 — [TechnoLibre](http://www.technolibre.ca)

<!-- [fr] -->

## Licence

AGPL-3.0 — [TechnoLibre](http://www.technolibre.ca)
