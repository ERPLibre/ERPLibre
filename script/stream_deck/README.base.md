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

### GNOME Shell extension

The `gnome-extension/` directory ships a six-indicator panel button (controller,
pencil, film, ERPLibre, network, device) plus the tiling D-Bus interface used by
the Python helpers. See [`gnome-extension/README.md`](gnome-extension/README.md).

## Games

19 games playable directly on the Stream Deck. 11 support 2-player mode with two Stream Decks (auto-detection).

### Arcade

#### Snake

Classic. The snake grows by eating food. Speed increases with score. Wrap-around at edges.

- **Controls**: press any button to turn the snake toward that direction
- **2 players**: two snakes (green/blue) on the same grid. Collision with the other = death

<!-- [fr] -->

### keyboard_talk.py

Script d'automatisation clavier. Utilise `wmctrl` pour cibler une fenêtre terminal, puis envoie une séquence de touches automatisée via la librairie `keyboard`.

### Extension GNOME Shell

Le répertoire `gnome-extension/` fournit un panneau à six indicateurs (controller,
pencil, film, ERPLibre, network, device) ainsi que l'interface D-Bus de tuilage
utilisée par les helpers Python. Voir [`gnome-extension/README.fr.md`](gnome-extension/README.fr.md).

## Jeux

19 jeux jouables directement sur le Stream Deck. 11 supportent le mode 2 joueurs avec deux Stream Decks (auto-détection).

### Arcade

#### Snake

Classique. Le serpent grandit en mangeant la nourriture. Vitesse augmente avec le score. Wrap-around aux bords.

- **Contrôles** : appuie n'importe quel bouton pour tourner le serpent vers cette direction
- **2 joueurs** : deux serpents (vert/bleu) sur la même grille. Collision avec l'autre = mort

<!-- [common] -->

```bash
make streamdeck_snake
```

<!-- [en] -->

#### Breakout

Brick breaker rotated 90 degrees. Bricks on the left, paddle on the right, ball bounces horizontally.

- **Controls**: press the right column to place the paddle, or anywhere to move it

<!-- [fr] -->

#### Breakout

Casse-briques pivoté 90°. Briques à gauche, paddle à droite, balle rebondit horizontalement.

- **Contrôles** : appuie sur la colonne de droite pour placer le paddle, ou n'importe où pour le déplacer

<!-- [common] -->

```bash
make streamdeck_breakout
```

<!-- [en] -->

#### Flappy Bird

The bird moves left to right, obstacles (pipes) scroll. Gravity pulls the bird downward.

- **Controls**: press any button to rise one cell

<!-- [fr] -->

#### Flappy Bird

L'oiseau avance de gauche à droite, les obstacles (tuyaux) défilent. Gravité tire l'oiseau vers le bas.

- **Contrôles** : appuie n'importe quel bouton pour monter d'une case

<!-- [common] -->

```bash
make streamdeck_flappy
```

<!-- [en] -->

#### Pong

Classic Pong rotated 90 degrees. Left paddle vs right paddle. First to 5 points wins.

- **1 player**: left column = you, right = AI
- **2 players**: each deck controls a paddle, press to place it at that line

<!-- [fr] -->

#### Pong

Pong classique pivoté 90°. Paddle gauche vs paddle droite. Premier à 5 points gagne.

- **1 joueur** : colonne gauche = toi, droite = IA
- **2 joueurs** : chaque deck contrôle un paddle, appuie pour placer à cette ligne

<!-- [common] -->

```bash
make streamdeck_pong
```

<!-- [en] -->

#### Bomberman

Move your character, drop bombs, destroy walls. Don't blow yourself up!

- **Controls**: press adjacent to move, press your position to drop a bomb (3s delay)
- **2 players**: P1 (blue) and P2 (orange) on the same grid. Last alive wins

<!-- [fr] -->

#### Bomberman

Déplace ton personnage, pose des bombes, détruis les murs. Ne te fais pas exploser!

- **Contrôles** : appuie adjacent pour bouger, appuie sur ta position pour poser une bombe (3s de délai)
- **2 joueurs** : P1 (bleu) et P2 (orange) sur la même grille. Dernier vivant gagne

<!-- [common] -->

```bash
make streamdeck_bomberman
```

<!-- [en] -->

### Reflex

#### Whack-a-Mole

Moles appear randomly for 30 seconds. Whack them! Speed increases with score. 3 second cooldown at end of game to view score.

- **2 players**: same moles on both decks, separate scores. Highest wins

<!-- [fr] -->

### Réflexe

#### Whack-a-Mole

Des taupes apparaissent aléatoirement pendant 30 secondes. Tape-les! La vitesse augmente avec le score. 3 secondes de cooldown en fin de partie pour voir le score.

- **2 joueurs** : mêmes taupes sur les deux decks, scores séparés. Le plus haut gagne

<!-- [common] -->

```bash
make streamdeck_whackamole
```

<!-- [en] -->

#### Reaction Time

A green button lights up after a random delay. Tap it as fast as possible! 5 rounds, time in milliseconds.

- **2 players**: same target, the fastest wins each round. Average compared at the end

<!-- [fr] -->

#### Reaction Time

Un bouton vert s'allume après un délai aléatoire. Tape-le le plus vite possible! 5 rounds, temps en millisecondes.

- **2 joueurs** : même cible, le plus rapide gagne chaque round. Moyenne comparée à la fin

<!-- [common] -->

```bash
make streamdeck_reaction
```

<!-- [en] -->

### Memory

#### Simon Says

The deck plays a light sequence. Reproduce it in order. The sequence grows with each turn.

- **2 players**: same sequence on both decks. First one to make a mistake loses

<!-- [fr] -->

### Mémoire

#### Simon Says

Le deck joue une séquence lumineuse. Reproduis-la dans l'ordre. La séquence s'allonge à chaque tour.

- **2 joueurs** : même séquence sur les deux decks. Le premier à se tromper perd

<!-- [common] -->

```bash
make streamdeck_simon
```

<!-- [en] -->

#### Color Match

Memory pair game. Flip two cards: if they are the same color, they stay revealed. Find all pairs.

- **2 players**: same board, each flips on their deck. Player with most pairs wins

<!-- [fr] -->

#### Color Match

Jeu de mémoire de paires. Retourne deux cartes : si elles sont de la même couleur, elles restent révélées. Trouve toutes les paires.

- **2 joueurs** : même plateau, chacun retourne sur son deck. Le joueur avec le plus de paires gagne

<!-- [common] -->

```bash
make streamdeck_colormatch
```

<!-- [en] -->

### Puzzle

#### Minesweeper

Classic Minesweeper with flag animation (yellow progressive bar on long-press).

- **Controls**: short press = reveal, long press (0.6s) = place/remove flag, press a number = chord (reveal neighbors if flags are correct)
- **2 players (VS Mine Hunter)**: rules reversed! Find mines to score. Mine = +1 + keep your turn. Safe cell = opponent's turn. Flood-fill on empty cells. Player with most mines found wins
- **Parameters**: `-m N` to change mine count, `-v` to display parameters

<!-- [fr] -->

### Puzzle

#### Minesweeper

Démineur classique avec animation de flag (barre jaune progressive en appui long).

- **Contrôles** : appui court = révéler, appui long (0.6s) = poser/retirer drapeau, appui sur chiffre = chord (révéler voisins si drapeaux corrects)
- **2 joueurs (VS Mine Hunter)** : règles inversées! Trouve les mines pour marquer. Mine = +1 + garde ton tour. Case safe = tour de l'adversaire. Flood-fill sur les cases vides. Le joueur avec le plus de mines trouvées gagne
- **Paramètres** : `-m N` pour changer le nombre de mines, `-v` pour afficher les paramètres

<!-- [common] -->

```bash
make streamdeck_minesweeper           # auto (25% solo, 35% VS)
./script/stream_deck/game_minesweeper.py -m 6      # 6 mines
./script/stream_deck/game_minesweeper.py -v         # show params / afficher paramètres
```

<!-- [en] -->

#### Lights Out

Press a button to toggle it and its 4 neighbors. Turn off all lights to win.

- **2 players (coop)**: shared grid! Both players act on the same board

<!-- [fr] -->

#### Lights Out

Appuie un bouton pour le toggle ainsi que ses 4 voisins. Éteins toutes les lumières pour gagner.

- **2 joueurs (coop)** : grille partagée! Les deux joueurs agissent sur le même plateau

<!-- [common] -->

```bash
make streamdeck_lightsout
```

<!-- [en] -->

#### 2048

Merge tiles of equal value to reach 2048. Distinct colors per value.

- **Controls**: corners = directions (top-left=up, top-right=right, bottom-left=left, bottom-right=down). Or press the left/right half to go in that direction

<!-- [fr] -->

#### 2048

Fusionne les tuiles de même valeur pour atteindre 2048. Couleurs distinctes par valeur.

- **Contrôles** : coins = directions (haut-gauche=haut, haut-droite=droite, bas-gauche=gauche, bas-droite=bas). Ou appuie la moitié gauche/droite pour aller dans cette direction

<!-- [common] -->

```bash
make streamdeck_2048
```

<!-- [en] -->

#### Taquin (Sliding Puzzle)

Numbered tiles to put back in order (1->N) by sliding them toward the empty cell. N = number of buttons - 1.

- **Controls**: press a tile adjacent to the empty cell to move it

<!-- [fr] -->

#### Taquin (Sliding Puzzle)

Tuiles numérotées à remettre en ordre (1→N) en les glissant vers la case vide. N = nombre de boutons - 1.

- **Contrôles** : appuie une tuile adjacente à la case vide pour la déplacer

<!-- [common] -->

```bash
make streamdeck_taquin
```

<!-- [en] -->

#### Sokoban

Push boxes (B) onto targets (X). All boxes on targets = victory.

- **Controls**: press adjacent to move. If a box is in front, it gets pushed

<!-- [fr] -->

#### Sokoban

Pousse les boîtes (B) sur les cibles (X). Toutes les boîtes sur les cibles = victoire.

- **Contrôles** : appuie adjacent pour bouger. Si une boîte est devant, elle est poussée

<!-- [common] -->

```bash
make streamdeck_sokoban
```

<!-- [en] -->

#### Flood Fill

The grid has random colors. Pick a color in the bottom row to flood-fill from the top-left corner. Fill the whole grid in a limited number of moves.

- **2 players**: same starting grid, each plays independently. First to fill wins

<!-- [fr] -->

#### Flood Fill

La grille a des couleurs aléatoires. Choisis une couleur dans la rangée du bas pour flood-fill depuis le coin haut-gauche. Remplis toute la grille en un nombre limité de coups.

- **2 joueurs** : même grille de départ, chacun joue indépendamment. Premier à remplir gagne

<!-- [common] -->

```bash
make streamdeck_floodfill
```

<!-- [en] -->

### Strategy / Deduction

#### Battleship

Naval battle. Ships are hidden. Shoot to find them.

- **1 player**: solo grid, find all ships
- **2 players**: each deck = private attack grid. Hit = keep your turn. Miss = opponent's turn. Sunken ships in dark red. Ships revealed at end of game

<!-- [fr] -->

### Stratégie / Déduction

#### Battleship

Bataille navale. Les bateaux sont cachés. Tire pour les trouver.

- **1 joueur** : grille solo, trouve tous les bateaux
- **2 joueurs** : chaque deck = grille d'attaque privée. Touché = garde ton tour. Manqué = tour de l'adversaire. Bateaux coulés en rouge foncé. Bateaux révélés en fin de partie

<!-- [common] -->

```bash
make streamdeck_battleship
```

<!-- [en] -->

#### Mastermind

Guess the secret color code. Bottom row = your guess (press to cycle colors). Top-right = submit. Feedback after each guess: E = exact (right color, right place), P = partial (right color, wrong place).

<!-- [fr] -->

#### Mastermind

Devine le code secret de couleurs. Rangée du bas = ton essai (appuie pour cycler les couleurs). Haut-droite = soumettre. Feedback après chaque essai : E = exact (bonne couleur, bonne place), P = partiel (bonne couleur, mauvaise place).

<!-- [common] -->

```bash
make streamdeck_mastermind
```

<!-- [en] -->

#### Tic-Tac-Toe

Classic noughts and crosses on a 3x3 grid centered on the deck.

- **1 player**: hot seat, players alternate on the same deck
- **2 players**: each deck = one player (X or O). Only the active player's deck accepts input. The other displays "WAIT"

<!-- [fr] -->

#### Tic-Tac-Toe

Morpion classique sur une grille 3x3 centrée sur le deck.

- **1 joueur** : hot seat, les joueurs alternent sur le même deck
- **2 joueurs** : chaque deck = un joueur (X ou O). Seul le deck du joueur actif accepte les inputs. L'autre affiche "WAIT"

<!-- [common] -->

```bash
make streamdeck_tictactoe
```

<!-- [en] -->

#### Wordle

Guess a 5-letter word. Bottom row = letters (press to cycle A-Z). Last button = submit. Green = right letter right place, yellow = right letter wrong place, gray = absent. 6 attempts.

<!-- [fr] -->

#### Wordle

Devine un mot de 5 lettres. Rangée du bas = lettres (appuie pour cycler A-Z). Dernier bouton = soumettre. Vert = bonne lettre bonne place, jaune = bonne lettre mauvaise place, gris = absent. 6 essais.

<!-- [common] -->

```bash
make streamdeck_wordle
```

<!-- [en] -->

#### Checkers

Simplified checkers. Select a piece then press the destination. Diagonal moves. Jump to capture.

- **2 players**: red vs blue, each on their own deck

<!-- [fr] -->

#### Checkers

Dames simplifiées. Sélectionne une pièce puis appuie la destination. Déplacements diagonaux. Saute pour capturer.

- **2 joueurs** : rouge vs bleu, chacun son deck

<!-- [common] -->

```bash
make streamdeck_checkers
```

<!-- [en] -->

#### Reversi / Othello

Place pieces to flip the opponent's. Most pieces at the end wins.

- **1 player**: vs AI (simple strategy)
- **2 players**: black vs white

<!-- [fr] -->

#### Reversi / Othello

Place des pièces pour retourner celles de l'adversaire. Le plus de pièces à la fin gagne.

- **1 joueur** : vs IA (stratégie simple)
- **2 joueurs** : noir vs blanc

<!-- [common] -->

```bash
make streamdeck_reversi
```

<!-- [en] -->

### Arcade (continued)

#### Pac-Man

Eat all the dots. Avoid the ghost! Press to change direction. The ghost chases you.

<!-- [fr] -->

### Arcade (suite)

#### Pac-Man

Mange tous les points. Évite le fantôme! Appuie pour changer de direction. Le fantôme te chasse.

<!-- [common] -->

```bash
make streamdeck_pacman
```

<!-- [en] -->

#### Space Invaders

The aliens descend. You are on the bottom row. Press your position to shoot, press adjacent to move.

<!-- [fr] -->

#### Space Invaders

Les aliens descendent. Tu es sur la rangée du bas. Appuie ta position pour tirer, appuie adjacent pour bouger.

<!-- [common] -->

```bash
make streamdeck_spaceinvaders
```

<!-- [en] -->

#### Frogger

Cross the road. Cars scroll by. Hop from cell to cell to reach the top!

<!-- [fr] -->

#### Frogger

Traverse la route. Les voitures défilent. Saute de case en case pour atteindre le haut!

<!-- [common] -->

```bash
make streamdeck_frogger
```

<!-- [en] -->

#### Tetris

Pieces fall right to left (rotated 90 degrees). Top row = rotate, bottom = drop, middle = move.

<!-- [fr] -->

#### Tetris

Pièces tombent de droite à gauche (pivoté 90°). Rangée du haut = rotation, bas = drop, milieu = déplacer.

<!-- [common] -->

```bash
make streamdeck_tetris
```

<!-- [en] -->

#### Tower Defense

Enemies cross the middle row. Place towers above/below to take them out. Survive 5 waves!

<!-- [fr] -->

#### Tower Defense

Les ennemis traversent la rangée du milieu. Place des tours au-dessus/en-dessous pour les éliminer. Survie 5 vagues!

<!-- [common] -->

```bash
make streamdeck_towerdefense
```

<!-- [en] -->

### Word / Guess

#### Hangman

Each button = a letter. Press to guess. 6 mistakes = game over.

<!-- [fr] -->

### Mot / Devinette

#### Hangman

Chaque bouton = une lettre. Appuie pour deviner. 6 erreurs = game over.

<!-- [common] -->

```bash
make streamdeck_hangman
```

<!-- [en] -->

#### Number Guess

Guess a number 1-100. Buttons display values. Colors = hot/cold. Fewer attempts = better score.

<!-- [fr] -->

#### Number Guess

Devine un nombre 1-100. Les boutons affichent des valeurs. Couleurs = chaud/froid. Moins d'essais = meilleur score.

<!-- [common] -->

```bash
make streamdeck_numberguess
```

<!-- [en] -->

#### Rock Paper Scissors

3 buttons: rock, paper, scissors. Best of 5.

- **2 players**: simultaneous choice, reveal!

<!-- [fr] -->

#### Rock Paper Scissors

3 boutons : pierre, papier, ciseaux. Best of 5.

- **2 joueurs** : choix simultané, révélation!

<!-- [common] -->

```bash
make streamdeck_rps
```

<!-- [en] -->

### Puzzle (continued)

#### Sudoku 3x3

Simplified 3x3 grid centered on the deck. Press to cycle digits. No repetitions in rows/columns.

<!-- [fr] -->

### Puzzle (suite)

#### Sudoku 3x3

Grille 3x3 simplifiée centrée sur le deck. Appuie pour cycler les chiffres. Pas de répétitions en lignes/colonnes.

<!-- [common] -->

```bash
make streamdeck_sudoku
```

<!-- [en] -->

#### Maze Runner

Randomly generated maze. Navigate from top-left corner to bottom-right. Press adjacent cells to move.

<!-- [fr] -->

#### Maze Runner

Labyrinthe généré aléatoirement. Navigue du coin haut-gauche au bas-droite. Appuie les cases adjacentes pour bouger.

<!-- [common] -->

```bash
make streamdeck_maze
```

<!-- [en] -->

### Simulation

#### Game of Life

Conway's cellular automaton. Cells live or die based on their neighbors. Wrap-around at edges.

- **Controls**: press to toggle a cell. Top-left = play/pause. Top-right = randomize. Bottom-right = clear

<!-- [fr] -->

### Simulation

#### Game of Life

Automate cellulaire de Conway. Les cellules vivent ou meurent selon leurs voisins. Wrap-around aux bords.

- **Contrôles** : appuie pour toggle une cellule. Haut-gauche = play/pause. Haut-droite = randomize. Bas-droite = clear

<!-- [common] -->

```bash
make streamdeck_life
```

<!-- [en] -->

#### Langton's Ant

Cellular automaton: an ant moves on the grid. On white -> turn right + black. On black -> turn left + white. Emerging patterns!

<!-- [fr] -->

#### Langton's Ant

Automate cellulaire : une fourmi se déplace sur la grille. Sur blanc → tourne à droite + noir. Sur noir → tourne à gauche + blanc. Motifs émergents!

<!-- [common] -->

```bash
make streamdeck_langton
```

<!-- [en] -->

### Stream Deck + (dials + touchscreen)

#### Safe Cracker

Turn the 4 dials to guess a 4-digit combination. Hot/cold bars on the touchscreen. Click = lock.

<!-- [fr] -->

### Stream Deck + (dials + touchscreen)

#### Safe Cracker

Tourne les 4 dials pour deviner une combinaison 4 chiffres. Barres chaud/froid sur le touchscreen. Click = lock.

<!-- [common] -->

```bash
make streamdeck_safecracker
```

<!-- [en] -->

#### Slot Machine

Click a dial to spin all reels. Click each dial to stop its reel. 3 identical = jackpot!

<!-- [fr] -->

#### Slot Machine

Click un dial pour spinner toutes les roues. Click chaque dial pour stopper sa roue. 3 identiques = jackpot!

<!-- [common] -->

```bash
make streamdeck_slots
```

<!-- [en] -->

#### Color Mixer

3 dials = Red, Green, Blue. Mix to match the target color displayed on the touchscreen. Dial 4 = submit.

<!-- [fr] -->

#### Color Mixer

3 dials = Rouge, Vert, Bleu. Mixe pour matcher la couleur cible affichée sur le touchscreen. Dial 4 = soumettre.

<!-- [common] -->

```bash
make streamdeck_colormixer
```

<!-- [en] -->

#### Pong+

Pong on the 800x100px touchscreen! Dial = paddle. Ball bounces. 2 Stream Deck+ = 2 players!

<!-- [fr] -->

#### Pong+

Pong sur le touchscreen 800x100px! Dial = paddle. Balle rebondit. 2 Stream Deck+ = 2 joueurs!

<!-- [common] -->

```bash
make streamdeck_pong
```

<!-- [en] -->

#### DJ Scratch

Turn the dials to scratch vinyl. Animated waveforms on the touchscreen. Click = change style (sine/square/saw/noise).

<!-- [fr] -->

#### DJ Scratch

Tourne les dials pour scratcher du vinyl. Waveforms animées sur le touchscreen. Click = changer de style (sine/square/saw/noise).

<!-- [common] -->

```bash
make streamdeck_djscratch
```

<!-- [en] -->

#### Fishing

Click dial = cast. When the fish bites (touchscreen flash), turn to reel in! Too fast = the line breaks.

<!-- [fr] -->

#### Fishing

Click dial = lancer. Quand le poisson mord (touchscreen flash), tourne pour mouliner! Trop vite = la ligne casse.

<!-- [common] -->

```bash
make streamdeck_fishing
```

<!-- [en] -->

#### Piano

Bottom row = piano keys (C D E F G A B). Dial 1 = change octave. Colors per note on the touchscreen.

<!-- [fr] -->

#### Piano

Rangée du bas = touches de piano (C D E F G A B). Dial 1 = changer d'octave. Couleurs par note sur le touchscreen.

<!-- [common] -->

```bash
make streamdeck_piano
```

<!-- [en] -->

#### Thermometer

Turn the dial to guess the secret temperature. Thermometer bar on the touchscreen with hot/cold gradient.

<!-- [fr] -->

#### Thermometer

Tourne le dial pour deviner la température secrète. Barre thermomètre sur le touchscreen avec gradient chaud/froid.

<!-- [common] -->

```bash
make streamdeck_thermometer
```

<!-- [en] -->

## Game roundup (42 titles)

| Game | Command | Type | Multi |
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
| Whack-a-Mole | `make streamdeck_whackamole` | Reflex | 2P VS |
| Reaction Time | `make streamdeck_reaction` | Reflex | 2P VS |
| Simon Says | `make streamdeck_simon` | Memory | 2P VS |
| Color Match | `make streamdeck_colormatch` | Memory | 2P VS |
| Minesweeper | `make streamdeck_minesweeper` | Puzzle | 2P VS |
| Lights Out | `make streamdeck_lightsout` | Puzzle | 2P Coop |
| 2048 | `make streamdeck_2048` | Puzzle | - |
| Taquin | `make streamdeck_taquin` | Puzzle | - |
| Sokoban | `make streamdeck_sokoban` | Puzzle | - |
| Flood Fill | `make streamdeck_floodfill` | Puzzle | 2P VS |
| Sudoku 3x3 | `make streamdeck_sudoku` | Puzzle | - |
| Maze Runner | `make streamdeck_maze` | Puzzle | - |
| Battleship | `make streamdeck_battleship` | Strategy | 2P VS |
| Mastermind | `make streamdeck_mastermind` | Deduction | - |
| Tic-Tac-Toe | `make streamdeck_tictactoe` | Strategy | 2P VS |
| Connect 4 | `make streamdeck_connect4` | Strategy | 2P VS |
| Checkers | `make streamdeck_checkers` | Strategy | 2P VS |
| Reversi | `make streamdeck_reversi` | Strategy | 2P VS |
| Wordle | `make streamdeck_wordle` | Word | - |
| Hangman | `make streamdeck_hangman` | Word | - |
| Number Guess | `make streamdeck_numberguess` | Guess | - |
| Rock Paper Scissors | `make streamdeck_rps` | Quick | 2P VS |
| Game of Life | `make streamdeck_life` | Simulation | - |
| Langton's Ant | `make streamdeck_langton` | Simulation | - |
| Safe Cracker | `make streamdeck_safecracker` | SD+ Puzzle | - |
| Slot Machine | `make streamdeck_slots` | SD+ Arcade | - |
| Color Mixer | `make streamdeck_colormixer` | SD+ Puzzle | - |
| DJ Scratch | `make streamdeck_djscratch` | SD+ Music | - |
| Fishing | `make streamdeck_fishing` | SD+ Arcade | - |
| Piano | `make streamdeck_piano` | SD+ Music | - |
| Thermometer | `make streamdeck_thermometer` | SD+ Guess | - |

## Files

<!-- [fr] -->

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

<!-- [common] -->

```
script/stream_deck/
├── README.md                  # English / Anglais
├── README.fr.md               # French / Français
├── INSTALL.md                 # Dependency install guide / Guide d'installation
├── plan.md                    # StreamController integration plan / Plan d'intégration
├── requirements.txt           # Python dependencies / Dépendances Python
├── Assets/                    # Controller images and fonts / Images et polices
├── gnome-extension/           # GNOME Shell extension / Extension GNOME Shell
├── erplibre_controller.py     # Main ERPLibre controller / Contrôleur principal
├── keyboard_talk.py           # Keyboard automation / Automatisation clavier
└── game_*.py                  # 42 games / 42 jeux
```

<!-- [en] -->

## License

AGPL-3.0 — [TechnoLibre](http://www.technolibre.ca)

<!-- [fr] -->

## Licence

AGPL-3.0 — [TechnoLibre](http://www.technolibre.ca)
