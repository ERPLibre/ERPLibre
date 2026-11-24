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

It clones the deck program and the games, installs their
`requirements.txt` in `.venv.streamdeck`, writes the udev rule and the
systemd user service. The details, the settings and the TODO menu are in
[INSTALL.md](INSTALL.md).

## Make targets

<!-- [fr] -->

Elle clone le programme du deck et les jeux, installe leurs
`requirements.txt` dans `.venv.streamdeck`, écrit la règle udev et le
service systemd de l'utilisateur. Le détail, les réglages et le menu TODO
sont dans [INSTALL.fr.md](INSTALL.fr.md).

## Cibles make

<!-- [common] -->

```bash
make streamdeck_erplibre               # deck program / programme du deck
make streamdeck                        # classic controller / contrôleur
make streamdeck_tiler_unittest         # deck tests / tests du deck
make streamdeck_translator_doctor      # translator backends / moteurs
make streamdeck_gallery                # games gallery / galerie des jeux
```

<!-- [en] -->

Each runs a file of `script/stream_deck/deck/`, or of
`script/stream_deck/games/` for the gallery, under `.venv.streamdeck`, and
stops with the install command when the clone or the venv is missing.

### GNOME Shell extension

The GNOME extension, a repository of its own
([erplibre-home-gnome-extension](https://github.com/TechnoLibre/erplibre-home-gnome-extension)) cloned at
`script/gnome-extension/erplibre_home/`, ships a six-indicator panel button (controller,
pencil, film, ERPLibre, network, device) plus the tiling D-Bus interface used by
the deck program. See its `README.md` and
[the extension in ERPLibre](../../doc/erplibre_home_gnome_extension.md).

<!-- [fr] -->

Chacune lance un fichier de `script/stream_deck/deck/`, ou de
`script/stream_deck/games/` pour la galerie, sous `.venv.streamdeck`, et
s'arrête sur la commande d'installation quand le clone ou le venv manque.

### Extension GNOME Shell

L'extension GNOME, un dépôt à part
([erplibre-home-gnome-extension](https://github.com/TechnoLibre/erplibre-home-gnome-extension)) cloné dans
`script/gnome-extension/erplibre_home/`, fournit un panneau à six indicateurs (controller,
pencil, film, ERPLibre, network, device) ainsi que l'interface D-Bus de tuilage
qu'utilise le programme du deck. Voir son `README.fr.md` et
[l'extension dans ERPLibre](../../doc/erplibre_home_gnome_extension.fr.md).

<!-- [en] -->

## Games

The games and their gallery live in their own repository, [streamdeck_game](https://github.com/TechnoLibre/streamdeck_game), cloned at `script/stream_deck/games/` by Google Repo or by `make erplibre_home_streamdeck_install`; [doc/streamdeck_game.md](../../doc/streamdeck_game.md) says how, and the repository's own README says how to run them without ERPLibre. `make streamdeck_games` lists them. ERPLibre names none of them: every `game_<id>.py` of the clone is a game, so a game added there needs no change here.

Every `game_*.py` reads its command line through `games_cli.py`, before importing PIL and the Stream Deck library: `-h` and `--help` print the usage and exit 0, any unknown argument prints it on stderr and exits 2, and neither opens the deck. `--meta` prints the game's metadata as JSON, which the gallery reads; a game's own options are in its `--help`. The gallery (`make streamdeck_gallery`, `gallery_server.py`) answers `-h` and `--help` the same way, without listening or opening a browser.

<!-- [fr] -->

## Jeux

Les jeux et leur galerie vivent dans leur propre dépôt, [streamdeck_game](https://github.com/TechnoLibre/streamdeck_game), cloné dans `script/stream_deck/games/` par Google Repo ou par `make erplibre_home_streamdeck_install` ; [doc/streamdeck_game.fr.md](../../doc/streamdeck_game.fr.md) dit comment, et le README du dépôt dit comment les lancer sans ERPLibre. `make streamdeck_games` en donne la liste. ERPLibre n'en nomme aucun : chaque `game_<id>.py` du clone est un jeu, si bien qu'un jeu ajouté là-bas ne demande aucun changement ici.

Chaque `game_*.py` lit sa ligne de commande par `games_cli.py`, avant d'importer PIL et la bibliothèque Stream Deck : `-h` et `--help` affichent l'usage et sortent en 0, tout argument inconnu l'affiche sur la sortie d'erreur et sort en 2, et ni l'un ni l'autre n'ouvre le deck. `--meta` affiche les métadonnées du jeu en JSON, que lit la galerie ; les options propres à un jeu sont dans son `--help`. La galerie (`make streamdeck_gallery`, `gallery_server.py`) répond de même à `-h` et `--help`, sans écouter ni ouvrir de navigateur.

<!-- [common] -->

```bash
make streamdeck_games                  # game ids / id des jeux
make streamdeck_<id>                   # play game_<id>.py / jouer
make streamdeck_gallery                # games gallery / galerie des jeux
```

<!-- [en] -->

`make streamdeck_<id>` runs `game_<id>.py` under `.venv.streamdeck` through the deck hand-over, like TODO › ERPLibre Home › Games and the gallery: the deck service stops for the game and starts again after it. An id with no file stops with exit 2 and names `make streamdeck_games`.

<!-- [fr] -->

`make streamdeck_<id>` lance `game_<id>.py` sous `.venv.streamdeck` par la passation du deck, comme TODO › ERPLibre Home › Jeux et la galerie : le service du deck s'arrête le temps du jeu et repart après. Un id sans fichier s'arrête en code 2 et nomme `make streamdeck_games`.

<!-- [en] -->

## Files

<!-- [fr] -->

## Fichiers

<!-- [common] -->

```
script/stream_deck/
├── README.md                  # English / Anglais
├── README.fr.md               # French / Français
├── INSTALL.md                 # Install guide / Guide d'installation
├── deck_contract              # Deck contract version / Version du contrat
├── screenshots/               # Reference shots / Captures de référence
├── deck/                      # Deck program clone / Clone du deck
└── games/                     # streamdeck_game clone / Clone de streamdeck_game
    ├── game_*.py              # Games / Jeux
    ├── games_cli.py           # Games' command line / Ligne de commande
    ├── gallery_server.py      # Game gallery / Galerie des jeux
    └── index.html             # Gallery page / Page de la galerie
```

<!-- [en] -->

## License

AGPL-3.0 — [TechnoLibre](http://www.technolibre.ca)

<!-- [fr] -->

## Licence

AGPL-3.0 — [TechnoLibre](http://www.technolibre.ca)
