
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


```bash
make erplibre_home_streamdeck_install
```


Elle clone le programme du deck, installe son `requirements.txt` dans
`.venv.streamdeck`, écrit la règle udev et le service systemd de
l'utilisateur. Le détail, les réglages et le menu TODO sont dans
[INSTALL.fr.md](INSTALL.fr.md).

## Cibles make


```bash
make streamdeck_erplibre               # deck program / programme du deck
make streamdeck                        # classic controller / contrôleur
make streamdeck_tiler_unittest         # deck tests / tests du deck
make streamdeck_translator_doctor      # translator backends / moteurs
```


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


```
script/stream_deck/
├── README.md                  # English / Anglais
├── README.fr.md               # French / Français
├── INSTALL.md                 # Install guide / Guide d'installation
├── deck_contract              # Deck contract version / Version du contrat
├── screenshots/               # Reference shots / Captures de référence
└── deck/                      # Deck program clone / Clone du deck
```


## Licence

AGPL-3.0 — [TechnoLibre](http://www.technolibre.ca)