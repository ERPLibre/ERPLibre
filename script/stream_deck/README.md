# ERPLibre Stream Deck

Suite d'outils et de jeux pour Elgato Stream Deck, intégrée au projet ERPLibre.

Tous les scripts s'adaptent automatiquement à n'importe quel modèle de Stream Deck (Mini, Original, MK.2, XL, Plus, Neo) via `deck.key_layout()`.

## Prérequis

```bash
# Dépendances système
sudo apt install -y libudev-dev libusb-1.0-0-dev libhidapi-libusb0

# Règles udev (accès non-root)
sudo tee /etc/udev/rules.d/70-streamdeck.rules << 'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", TAG+="uaccess"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger

# Dépendances Python
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

Supporte le Stream Deck Plus (touchscreen, dials), la détection USB hotplug (pyudev), et les animations GIF.

```bash
make streamdeck
```

### keyboard_talk.py

Script d'automatisation clavier. Utilise `wmctrl` pour cibler une fenêtre terminal, puis envoie une séquence de touches automatisée via la librairie `keyboard`.

## Jeux

19 jeux jouables directement sur le Stream Deck. 11 supportent le mode 2 joueurs avec deux Stream Decks (auto-détection).

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
./script/stream_deck/game_minesweeper.py -m 6      # 6 mines
./script/stream_deck/game_minesweeper.py -v         # afficher paramètres
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

### Simulation

#### Game of Life

Automate cellulaire de Conway. Les cellules vivent ou meurent selon leurs voisins. Wrap-around aux bords.

- **Contrôles** : appuie pour toggle une cellule. Haut-gauche = play/pause. Haut-droite = randomize. Bas-droite = clear

```bash
make streamdeck_life
```

## Récapitulatif des jeux

| Jeu | Commande | Type | Multi |
|-----|----------|------|-------|
| Snake | `make streamdeck_snake` | Arcade | 2P VS |
| Breakout | `make streamdeck_breakout` | Arcade | - |
| Flappy Bird | `make streamdeck_flappy` | Arcade | - |
| Pong | `make streamdeck_pong` | Arcade | 2P VS |
| Bomberman | `make streamdeck_bomberman` | Arcade | 2P VS |
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
| Battleship | `make streamdeck_battleship` | Stratégie | 2P VS |
| Mastermind | `make streamdeck_mastermind` | Déduction | - |
| Tic-Tac-Toe | `make streamdeck_tictactoe` | Stratégie | 2P VS |
| Game of Life | `make streamdeck_life` | Simulation | - |

## Fichiers

```
script/stream_deck/
├── README.md                  # Ce fichier
├── INSTALL.md                 # Guide d'installation des dépendances
├── plan.md                    # Plan d'intégration StreamController
├── requirements.txt           # Dépendances Python
├── Assets/                    # Images et polices pour le contrôleur
├── erplibre_controller.py     # Contrôleur principal ERPLibre
├── keyboard_talk.py           # Automatisation clavier
└── game_*.py                  # 19 jeux (voir tableau ci-dessus)
```

## Licence

AGPL-3.0 — [TechnoLibre](http://www.technolibre.ca)
