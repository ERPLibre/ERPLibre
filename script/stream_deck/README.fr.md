
# ERPLibre Stream Deck

Suite d'outils et de jeux pour Elgato Stream Deck, intégrée au projet ERPLibre.

Tous les scripts s'adaptent automatiquement à n'importe quel modèle de Stream Deck (Mini, Original, MK.2, XL, Plus, Neo) via `deck.key_layout()`.

## Prérequis


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

Supporte le Stream Deck Plus (touchscreen, dials), la détection USB hotplug (pyudev), et les animations GIF. `-h` et `--help` affichent l'usage et les codes de sortie (1 : le pilote ne peut sonder, 2 : verrou du deck tenu ou option invalide, 143 : SIGTERM), puis sortent en 0 ; tout autre argument affiche l'usage sur la sortie d'erreur et sort en 2. Ni l'un ni l'autre ne prend le verrou du deck ni n'a besoin de cv2, de PIL ou de la bibliothèque Stream Deck.


```bash
make streamdeck
python script/stream_deck/erplibre_controller.py --help
```


## Programme du deck

`script/stream_deck/erplibre_streamdeck/` est le programme du deck d'ERPLibre Home (`DECK_PROGRAM=tiler`, `make streamdeck_erplibre`). C'est un paquet lancé comme un répertoire : un petit noyau possède le deck, le verrou, le flash, l'écran d'accueil et la distribution des touches, et chaque fonction est un plugin.


```bash
python script/stream_deck/erplibre_streamdeck
python script/stream_deck/erplibre_streamdeck --list-plugins
python script/stream_deck/erplibre_streamdeck --help
```


`--list-plugins` affiche ce que le chargeur trouve (une ligne par plugin : `active`, `off`, `replaced by user` ou `refused` avec sa raison ; `unreadable` pour un répertoire de plugins illisible) sans ouvrir le deck ni prendre son verrou. `-h` et `--help` affichent l'usage, le fichier de réglages et les codes de sortie (2 : verrou du deck tenu ou option invalide, 3 : aucun Stream Deck à écran, 143 : SIGTERM), puis sortent en 0 ; tout autre argument affiche l'usage sur la sortie d'erreur et sort en 2. Ni l'un ni l'autre ne prend le verrou ni n'a besoin de la bibliothèque Stream Deck. Disposition du paquet :


```
erplibre_streamdeck/
├── __main__.py   # entry point, --help, --list-plugins / point d'entrée
├── app.py        # build(): settings, plugins, kernel / assemblage
├── kernel.py     # deck, lock, flash, loop, dispatch / noyau
├── home.py       # home screen: buttons, fixtures, tiles / accueil
├── loader.py     # discovery of the plugins / découverte
├── plugin.py     # Plugin, Page, HomeButton, Fixture, TileProvider
├── context.py    # Context, the one object a plugin receives
├── paths.py, settings.py, dbus.py
├── ui/           # rendering, colours, i18n / rendu, couleurs, i18n
└── plugins/      # a11y, bluetooth, claude_sessions, dev_reload,
                  # layouts, mpv_sessions, sound, tiling, timers,
                  # todo_terminals, translate
```


### Couper des plugins

Le réglage `DECK_PLUGINS_OFF` de `streamdeck.conf` est une liste d'identifiants de plugins, séparés par des virgules, qui ne sont pas importés. Le régler depuis TODO › Stream Deck › Plugins on/off, ou à la main. Un plugin qui lève à l'import, n'a pas de `PLUGIN`, déclare un autre `api` que `PLUGIN_API`, prend un identifiant de page déjà pris ou échoue dans `setup` est refusé et les autres continuent ; le journal nomme le plugin et la raison.


```
DECK_PLUGINS_OFF=bluetooth,translate
```


### Écrire un plugin

Un plugin est un fichier `.py`. Son identifiant est le nom du fichier sans extension (`[a-z][a-z0-9_]*` ; les fichiers qui commencent par `_` sont ignorés) et il expose `PLUGIN = Plugin(api=PLUGIN_API, ...)`. Chaque fonction reçoit un `Context` (`ctx`) et s'exécute avec le verrou du noyau tenu. Ce plugin ajoute un bouton d'accueil et une page avec une touche retour :


```python
from erplibre_streamdeck.plugin import (
    PLUGIN_API, HomeButton, KeyFace, Page, Plugin,
)


def _keys(geo):
    return {"back": 0} if geo.cols >= 2 else None


def _render(ctx):
    for key in range(ctx.geo.total_keys):
        ctx.set_key(key, (20, 20, 30))
    ctx.set_key(0, (60, 60, 60), ctx.t("BACK"))


def _handle(ctx, key):
    if key == 0:
        ctx.home()


PLUGIN = Plugin(
    api=PLUGIN_API,
    pages=[Page("hello", _keys, _render, _handle)],
    home_button=HomeButton(
        90,
        face=lambda ctx: KeyFace((30, 90, 60), "HELLO"),
        press=lambda ctx: ctx.goto("hello"),
    ),
)
```


Un `Plugin` prend aussi `fixtures` (touches placées sur l'accueil), `tiles` (tuiles du tableau de bord), `home_tick`, `setup(ctx)` et `shutdown(ctx)` ; `plugin.py` documente chacun. `shutdown` s'exécute verrou tenu (sans lui quand une touche le tient encore après 5 s) : il ne doit ni prendre `ctx.locked()` ni attendre un fil qui le prend. Un fil lancé par un plugin prend le verrou par `with ctx.locked():`.

Un plugin de l'utilisateur va dans `$XDG_CONFIG_HOME/erplibre-home/deck-plugins/` (`~/.config/erplibre-home/deck-plugins/` si la variable est absente) et remplace le plugin du dépôt de même identifiant. **Confiance :** les plugins de l'utilisateur s'exécutent dans le service du deck avec les droits de l'utilisateur, comme un profil de shell ; n'y mettre que du code écrit ou relu par soi.


#### Actions lentes, sondages et réglages

Une fonction s'exécute verrou tenu : elle ne doit pas attendre un processus. `ctx.run_blocking(work, then=None)` exécute `work()` dans un fil, sans le verrou, et rend `True` :

- `work` ne prend aucun argument et ne touche que ce qu'elle a capturé avant l'appel, plus `ctx.dbus` et `ctx.log` ; jamais `ctx`.
- La touche pressée affiche « … » pendant la tâche et le reste du deck reste utilisable.
- Au prochain passage de la boucle, verrou tenu, le noyau appelle `then(ctx, result, error)` (`error` est l'exception levée par `work`, ou `None`). `then` fait son propre rendu, comme un gestionnaire. Sans `then`, le noyau fait clignoter OK quand `error` vaut `None` et que le résultat est vrai, ERR sinon, et rend.
- Un plugin n'a qu'une tâche à la fois : `run_blocking` pendant qu'une tâche tourne rend `False` et fait clignoter ERR. Une touche qui atteindrait un plugin occupé clignote en ERR sans l'appeler ; la touche 0 de sa page (RETOUR sur la plupart des pages) ramène à l'accueil. Ses sondages et ses ticks attendent.
- Une tâche qui lève est inscrite une fois au journal, avec sa trace, avant l'appel de `then`.

`Plugin.polls` est une liste de `Poll(period, active, read, store)`. Un rendu lit `ctx.state()` et ne lance aucun processus ; un sondage remplit cet état :

- `active(ctx)` (verrou tenu) dit si la donnée est utile maintenant, par exemple parce que la page du plugin est affichée.
- `read()` (sans verrou) lance les processus et rend la donnée. Il ne touche jamais `ctx` ; un `read` qui échoue garde la donnée précédente.
- Un `read` qui inscrit ses propres échecs enveloppe son passage dans `with repeat_log.watch() as log:`, où `repeat_log = RepeatLog(write, what)` est créé une fois avec le module : `log(msg)` consigne un échec, inscrit une fois tant qu'il se répète à chaque passage, de nouveau quand il change, et `what: recovered` est inscrit au premier passage sans échec. Un passage qui vient plus de `RepeatLog.FORGET_SEC` (10 s) après le précédent, le sondage ayant été inactif, repart de zéro : ses échecs sont inscrits de nouveau.
- `store(ctx, data)` (verrou tenu) garde la donnée dans `ctx.state()` et rend `True` pour demander un rendu.

`ctx.setting(name, default=None)` lit un réglage du deck donné au noyau au démarrage (`session_refresh_sec`, issu de `DECK_SESSION_REFRESH_SEC`), ou `default`. Un rendu peut avoir lieu avant la fin du premier sondage : poser l'état dans `setup(ctx)`. Ce plugin lance une tâche à l'appui d'une touche et affiche un compteur qu'un sondage rafraîchit :


```python
import subprocess

from erplibre_streamdeck.plugin import (
    PLUGIN_API, HomeButton, KeyFace, Page, Plugin, Poll,
)


def _setup(ctx):
    ctx.state().lines = 0


def _keys(geo):
    return {"back": 0, "run": 1} if geo.total_keys > 1 else None


def _render(ctx):
    for key in range(ctx.geo.total_keys):
        ctx.set_key(key, (20, 20, 30))
    ctx.set_key(0, (60, 60, 60), ctx.t("BACK"))
    ctx.set_key(1, (30, 90, 60), f"RUN\n{ctx.state().lines}")


def _work():
    # no ctx, no lock / ni ctx, ni verrou
    done = subprocess.run(["uptime"], capture_output=True, timeout=5)
    return done.returncode == 0


def _then(ctx, result, error):
    ctx.flash(error is None and result)
    ctx.render()


def _handle(ctx, key):
    if key == 0:
        ctx.home()
    elif key == 1:
        ctx.run_blocking(_work, _then)


def _read():
    done = subprocess.run(["uptime"], capture_output=True, timeout=5)
    return len(done.stdout.splitlines())


def _store(ctx, lines):
    changed = ctx.state().lines != lines
    ctx.state().lines = lines
    return changed


PLUGIN = Plugin(
    api=PLUGIN_API,
    pages=[Page("hello", _keys, _render, _handle)],
    home_button=HomeButton(
        90,
        face=lambda ctx: KeyFace((30, 90, 60), "HELLO"),
        press=lambda ctx: ctx.goto("hello"),
    ),
    polls=[Poll(2.0, lambda ctx: ctx.page == "hello", _read, _store)],
    setup=_setup,
)
```


### keyboard_talk.py

Script d'automatisation clavier. Utilise `wmctrl` pour cibler une fenêtre terminal, puis envoie une séquence de touches automatisée via la librairie `keyboard`.

### Extension GNOME Shell

Le répertoire `script/gnome-extension/erplibre_home/` fournit un panneau à six indicateurs (controller,
pencil, film, ERPLibre, network, device) ainsi que l'interface D-Bus de tuilage
utilisée par les helpers Python. Voir [`../gnome-extension/erplibre_home/README.fr.md`](../gnome-extension/erplibre_home/README.fr.md).

## Jeux

19 jeux jouables directement sur le Stream Deck. 11 supportent le mode 2 joueurs avec deux Stream Decks (auto-détection).

Les jeux et leur galerie vivent dans leur propre dépôt, [streamdeck_game](https://github.com/TechnoLibre/streamdeck_game), cloné dans `script/stream_deck/games/` par Google Repo ou par `make erplibre_home_streamdeck_install` ; [INSTALL.fr.md](INSTALL.fr.md) dit comment.

Chaque `game_*.py` lit sa ligne de commande par `games_cli.py`, avant d'importer PIL et la bibliothèque Stream Deck : `-h` et `--help` affichent l'usage et sortent en 0, tout argument inconnu l'affiche sur la sortie d'erreur et sort en 2, et ni l'un ni l'autre n'ouvre le deck. `--meta` affiche les métadonnées du jeu en JSON, que lit la galerie. Hangman ajoute `-l`/`--lang`, Minesweeper `-m` et `-v`. La galerie (`make streamdeck_gallery`, `gallery_server.py`) répond de même à `-h` et `--help`, sans écouter ni ouvrir de navigateur.

### Arcade

#### Snake

Classique. Le serpent grandit en mangeant la nourriture. Vitesse augmente avec le score. Wrap-around aux bords.

- **Contrôles** : appuie n'importe quel bouton pour tourner le serpent vers cette direction
- **2 joueurs** : deux serpents (vert/bleu) sur la même grille. Collision avec l'autre = mort


```bash
make streamdeck_snake
```


#### Breakout

Casse-briques pivoté 90°. Briques à gauche, paddle à droite, balle rebondit horizontalement.

- **Contrôles** : appuie sur la colonne de droite pour placer le paddle, ou n'importe où pour le déplacer


```bash
make streamdeck_breakout
```


#### Flappy Bird

L'oiseau avance de gauche à droite, les obstacles (tuyaux) défilent. Gravité tire l'oiseau vers le bas.

- **Contrôles** : appuie n'importe quel bouton pour monter d'une case


```bash
make streamdeck_flappy
```


#### Pong

Pong classique pivoté 90°. Paddle gauche vs paddle droite. Premier à 5 points gagne.

- **1 joueur** : colonne gauche = toi, droite = IA
- **2 joueurs** : chaque deck contrôle un paddle, appuie pour placer à cette ligne


```bash
make streamdeck_pong
```


#### Bomberman

Déplace ton personnage, pose des bombes, détruis les murs. Ne te fais pas exploser!

- **Contrôles** : appuie adjacent pour bouger, appuie sur ta position pour poser une bombe (3s de délai)
- **2 joueurs** : P1 (bleu) et P2 (orange) sur la même grille. Dernier vivant gagne


```bash
make streamdeck_bomberman
```


### Réflexe

#### Whack-a-Mole

Des taupes apparaissent aléatoirement pendant 30 secondes. Tape-les! La vitesse augmente avec le score. 3 secondes de cooldown en fin de partie pour voir le score.

- **2 joueurs** : mêmes taupes sur les deux decks, scores séparés. Le plus haut gagne


```bash
make streamdeck_whackamole
```


#### Reaction Time

Un bouton vert s'allume après un délai aléatoire. Tape-le le plus vite possible! 5 rounds, temps en millisecondes.

- **2 joueurs** : même cible, le plus rapide gagne chaque round. Moyenne comparée à la fin


```bash
make streamdeck_reaction
```


### Mémoire

#### Simon Says

Le deck joue une séquence lumineuse. Reproduis-la dans l'ordre. La séquence s'allonge à chaque tour.

- **2 joueurs** : même séquence sur les deux decks. Le premier à se tromper perd


```bash
make streamdeck_simon
```


#### Color Match

Jeu de mémoire de paires. Retourne deux cartes : si elles sont de la même couleur, elles restent révélées. Trouve toutes les paires.

- **2 joueurs** : même plateau, chacun retourne sur son deck. Le joueur avec le plus de paires gagne


```bash
make streamdeck_colormatch
```


### Puzzle

#### Minesweeper

Démineur classique avec animation de flag (barre jaune progressive en appui long).

- **Contrôles** : appui court = révéler, appui long (0.6s) = poser/retirer drapeau, appui sur chiffre = chord (révéler voisins si drapeaux corrects)
- **2 joueurs (VS Mine Hunter)** : règles inversées! Trouve les mines pour marquer. Mine = +1 + garde ton tour. Case safe = tour de l'adversaire. Flood-fill sur les cases vides. Le joueur avec le plus de mines trouvées gagne
- **Paramètres** : `-m N` pour changer le nombre de mines, `-v` pour afficher les paramètres


```bash
make streamdeck_minesweeper           # auto (25% solo, 35% VS)
./script/stream_deck/games/game_minesweeper.py -m 6      # 6 mines
./script/stream_deck/games/game_minesweeper.py -v         # show params / afficher paramètres
```


#### Lights Out

Appuie un bouton pour le toggle ainsi que ses 4 voisins. Éteins toutes les lumières pour gagner.

- **2 joueurs (coop)** : grille partagée! Les deux joueurs agissent sur le même plateau


```bash
make streamdeck_lightsout
```


#### 2048

Fusionne les tuiles de même valeur pour atteindre 2048. Couleurs distinctes par valeur.

- **Contrôles** : coins = directions (haut-gauche=haut, haut-droite=droite, bas-gauche=gauche, bas-droite=bas). Ou appuie la moitié gauche/droite pour aller dans cette direction


```bash
make streamdeck_2048
```


#### Taquin (Sliding Puzzle)

Tuiles numérotées à remettre en ordre (1→N) en les glissant vers la case vide. N = nombre de boutons - 1.

- **Contrôles** : appuie une tuile adjacente à la case vide pour la déplacer


```bash
make streamdeck_taquin
```


#### Sokoban

Pousse les boîtes (B) sur les cibles (X). Toutes les boîtes sur les cibles = victoire.

- **Contrôles** : appuie adjacent pour bouger. Si une boîte est devant, elle est poussée


```bash
make streamdeck_sokoban
```


#### Flood Fill

La grille a des couleurs aléatoires. Choisis une couleur dans la rangée du bas pour flood-fill depuis le coin haut-gauche. Remplis toute la grille en un nombre limité de coups.

- **2 joueurs** : même grille de départ, chacun joue indépendamment. Premier à remplir gagne


```bash
make streamdeck_floodfill
```


### Stratégie / Déduction

#### Battleship

Bataille navale. Les bateaux sont cachés. Tire pour les trouver.

- **1 joueur** : grille solo, trouve tous les bateaux
- **2 joueurs** : chaque deck = grille d'attaque privée. Touché = garde ton tour. Manqué = tour de l'adversaire. Bateaux coulés en rouge foncé. Bateaux révélés en fin de partie


```bash
make streamdeck_battleship
```


#### Mastermind

Devine le code secret de couleurs. Rangée du bas = ton essai (appuie pour cycler les couleurs). Haut-droite = soumettre. Feedback après chaque essai : E = exact (bonne couleur, bonne place), P = partiel (bonne couleur, mauvaise place).


```bash
make streamdeck_mastermind
```


#### Tic-Tac-Toe

Morpion classique sur une grille 3x3 centrée sur le deck.

- **1 joueur** : hot seat, les joueurs alternent sur le même deck
- **2 joueurs** : chaque deck = un joueur (X ou O). Seul le deck du joueur actif accepte les inputs. L'autre affiche "WAIT"


```bash
make streamdeck_tictactoe
```


#### Wordle

Devine un mot de 5 lettres. Rangée du bas = lettres (appuie pour cycler A-Z). Dernier bouton = soumettre. Vert = bonne lettre bonne place, jaune = bonne lettre mauvaise place, gris = absent. 6 essais.


```bash
make streamdeck_wordle
```


#### Checkers

Dames simplifiées. Sélectionne une pièce puis appuie la destination. Déplacements diagonaux. Saute pour capturer.

- **2 joueurs** : rouge vs bleu, chacun son deck


```bash
make streamdeck_checkers
```


#### Reversi / Othello

Place des pièces pour retourner celles de l'adversaire. Le plus de pièces à la fin gagne.

- **1 joueur** : vs IA (stratégie simple)
- **2 joueurs** : noir vs blanc


```bash
make streamdeck_reversi
```


### Arcade (suite)

#### Pac-Man

Mange tous les points. Évite le fantôme! Appuie pour changer de direction. Le fantôme te chasse.


```bash
make streamdeck_pacman
```


#### Space Invaders

Les aliens descendent. Tu es sur la rangée du bas. Appuie ta position pour tirer, appuie adjacent pour bouger.


```bash
make streamdeck_spaceinvaders
```


#### Frogger

Traverse la route. Les voitures défilent. Saute de case en case pour atteindre le haut!


```bash
make streamdeck_frogger
```


#### Tetris

Pièces tombent de droite à gauche (pivoté 90°). Rangée du haut = rotation, bas = drop, milieu = déplacer.


```bash
make streamdeck_tetris
```


#### Tower Defense

Les ennemis traversent la rangée du milieu. Place des tours au-dessus/en-dessous pour les éliminer. Survie 5 vagues!


```bash
make streamdeck_towerdefense
```


### Mot / Devinette

#### Hangman

Chaque bouton = une lettre. Appuie pour deviner. 6 erreurs = game over.


```bash
make streamdeck_hangman
```


#### Number Guess

Devine un nombre 1-100. Les boutons affichent des valeurs. Couleurs = chaud/froid. Moins d'essais = meilleur score.


```bash
make streamdeck_numberguess
```


#### Rock Paper Scissors

3 boutons : pierre, papier, ciseaux. Best of 5.

- **2 joueurs** : choix simultané, révélation!


```bash
make streamdeck_rps
```


### Puzzle (suite)

#### Sudoku 3x3

Grille 3x3 simplifiée centrée sur le deck. Appuie pour cycler les chiffres. Pas de répétitions en lignes/colonnes.


```bash
make streamdeck_sudoku
```


#### Maze Runner

Labyrinthe généré aléatoirement. Navigue du coin haut-gauche au bas-droite. Appuie les cases adjacentes pour bouger.


```bash
make streamdeck_maze
```


### Simulation

#### Game of Life

Automate cellulaire de Conway. Les cellules vivent ou meurent selon leurs voisins. Wrap-around aux bords.

- **Contrôles** : appuie pour toggle une cellule. Haut-gauche = play/pause. Haut-droite = randomize. Bas-droite = clear


```bash
make streamdeck_life
```


#### Langton's Ant

Automate cellulaire : une fourmi se déplace sur la grille. Sur blanc → tourne à droite + noir. Sur noir → tourne à gauche + blanc. Motifs émergents!


```bash
make streamdeck_langton
```


### Stream Deck + (dials + touchscreen)

#### Safe Cracker

Tourne les 4 dials pour deviner une combinaison 4 chiffres. Barres chaud/froid sur le touchscreen. Click = lock.


```bash
make streamdeck_safecracker
```


#### Slot Machine

Click un dial pour spinner toutes les roues. Click chaque dial pour stopper sa roue. 3 identiques = jackpot!


```bash
make streamdeck_slots
```


#### Color Mixer

3 dials = Rouge, Vert, Bleu. Mixe pour matcher la couleur cible affichée sur le touchscreen. Dial 4 = soumettre.


```bash
make streamdeck_colormixer
```


#### Pong+

Pong sur le touchscreen 800x100px! Dial = paddle. Balle rebondit. 2 Stream Deck+ = 2 joueurs!


```bash
make streamdeck_pong
```


#### DJ Scratch

Tourne les dials pour scratcher du vinyl. Waveforms animées sur le touchscreen. Click = changer de style (sine/square/saw/noise).


```bash
make streamdeck_djscratch
```


#### Fishing

Click dial = lancer. Quand le poisson mord (touchscreen flash), tourne pour mouliner! Trop vite = la ligne casse.


```bash
make streamdeck_fishing
```


#### Piano

Rangée du bas = touches de piano (C D E F G A B). Dial 1 = changer d'octave. Couleurs par note sur le touchscreen.


```bash
make streamdeck_piano
```


#### Thermometer

Tourne le dial pour deviner la température secrète. Barre thermomètre sur le touchscreen avec gradient chaud/froid.


```bash
make streamdeck_thermometer
```


## Récapitulatif des jeux (42 titres)

| Jeu | Commande | Type | Multi |
|-----|----------|------|-------|
| Snake | `make streamdeck_snake` | Arcade | 2P VS |
| Breakout | `make streamdeck_breakout` | Arcade | - |
| Flappy Bird | `make streamdeck_flappy` | Arcade | - |
| Pong | `make streamdeck_pong` | Arcade / SD+ | 2P VS |
| Bomberman | `make streamdeck_bomberman` | Arcade | 2P VS |
| Pac-Man | `make streamdeck_pacman` | Arcade | - |
| Space Invaders | `make streamdeck_spaceinvaders` | Arcade | - |
| Frogger | `make streamdeck_frogger` | Arcade | - |
| Tetris | `make streamdeck_tetris` | Arcade | - |
| Tower Defense | `make streamdeck_towerdefense` | Arcade | - |
| Whack-a-Mole | `make streamdeck_whackamole` | Réflexe | 2P VS |
| Reaction Time | `make streamdeck_reaction` | Réflexe | 2P VS |
| Simon Says | `make streamdeck_simon` | Mémoire | 2P VS |
| Color Match | `make streamdeck_colormatch` | Mémoire | 2P VS |
| Minesweeper | `make streamdeck_minesweeper` | Puzzle | 2P VS |
| Lights Out | `make streamdeck_lightsout` | Puzzle | 2P Coop |
| 2048 | `make streamdeck_2048` | Puzzle | - |
| Taquin | `make streamdeck_taquin` | Puzzle | - |
| Sokoban | `make streamdeck_sokoban` | Puzzle | - |
| Flood Fill | `make streamdeck_floodfill` | Puzzle | 2P VS |
| Sudoku 3x3 | `make streamdeck_sudoku` | Puzzle | - |
| Maze Runner | `make streamdeck_maze` | Puzzle | - |
| Battleship | `make streamdeck_battleship` | Stratégie | 2P VS |
| Mastermind | `make streamdeck_mastermind` | Déduction | - |
| Tic-Tac-Toe | `make streamdeck_tictactoe` | Stratégie | 2P VS |
| Connect 4 | `make streamdeck_connect4` | Stratégie | 2P VS |
| Checkers | `make streamdeck_checkers` | Stratégie | 2P VS |
| Reversi | `make streamdeck_reversi` | Stratégie | 2P VS |
| Wordle | `make streamdeck_wordle` | Mot | - |
| Hangman | `make streamdeck_hangman` | Mot | - |
| Number Guess | `make streamdeck_numberguess` | Devinette | - |
| Rock Paper Scissors | `make streamdeck_rps` | Rapide | 2P VS |
| Game of Life | `make streamdeck_life` | Simulation | - |
| Langton's Ant | `make streamdeck_langton` | Simulation | - |
| Safe Cracker | `make streamdeck_safecracker` | SD+ Puzzle | - |
| Slot Machine | `make streamdeck_slots` | SD+ Arcade | - |
| Color Mixer | `make streamdeck_colormixer` | SD+ Puzzle | - |
| DJ Scratch | `make streamdeck_djscratch` | SD+ Musique | - |
| Fishing | `make streamdeck_fishing` | SD+ Arcade | - |
| Piano | `make streamdeck_piano` | SD+ Musique | - |
| Thermometer | `make streamdeck_thermometer` | SD+ Devinette | - |

## Fichiers


```
script/stream_deck/
├── README.md                  # English / Anglais
├── README.fr.md               # French / Français
├── INSTALL.md                 # Dependency install guide / Guide d'installation
├── plan.md                    # StreamController integration plan / Plan d'intégration
├── requirements.txt           # Python dependencies / Dépendances Python
├── Assets/                    # Controller images and fonts / Images et polices
├── erplibre_controller.py     # Main ERPLibre controller / Contrôleur principal
├── erplibre_streamdeck/       # Deck program package (plugins) / Paquet du deck
├── keyboard_talk.py           # Keyboard automation / Automatisation clavier
└── games/                     # Games, gallery, saves / Jeux, galerie, sauvegardes
    ├── game_*.py              # 45 games / 45 jeux
    ├── games_cli.py           # Games' command line / Ligne de commande
    ├── gallery_server.py      # Game gallery / Galerie des jeux
    ├── index.html             # Gallery page / Page de la galerie
    └── save/                  # Game saves / Sauvegardes des jeux
```

The GNOME Shell extension lives in `script/gnome-extension/erplibre_home/`. /
L'extension GNOME Shell vit dans `script/gnome-extension/erplibre_home/`.


## Licence

AGPL-3.0 — [TechnoLibre](http://www.technolibre.ca)