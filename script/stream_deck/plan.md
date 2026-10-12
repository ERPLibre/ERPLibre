# Stream Deck Integration Plan — ERPLibre

## Analyse du code existant (`develop_stream_deck`)

### Fonctionnalités implémentées (25 commits, 1073 lignes)

| Feature | Status |
|---------|--------|
| Détection auto USB (pyudev) | OK |
| Support Stream Deck + (touchscreen, dials) | OK |
| Animations GIF sur boutons | OK |
| Big image sur tout le deck | OK |
| Webcam (locale + IP) en thread séparé | OK |
| Smyleys dynamiques avec collision | WIP |
| Debug overlay (x/y/w/h) | OK |
| Bouton 0 → lance todo.py | OK |
| Bouton 3 → keyboard automation | OK |
| Brightness +/- (boutons 1/2) | OK |
| Makefile target `make streamdeck` | OK |

### Dettes techniques identifiées

- Monolithe — toute la logique dans une seule classe
- Hardcoded — `BIG_IMAGE_TYPE`, `WEBCAM_TYPE`, `is_feature` en constantes globales commentées/décommentées
- Pas de config — pas de fichier YAML/JSON pour configurer boutons/actions
- Thread webcam — `threading.Thread(target=self.webcam_thread())` appelle la fonction au lieu de la passer comme target
- Algorithme de collision complexe, difficile à maintenir

---

## Alternatives Open-Source

### Tier 1 — Meilleurs candidats pour intégration ERP (Python)

#### StreamController

- **GitHub** : https://github.com/StreamController/StreamController
- **Langage** : Python (GTK4)
- **Licence** : GPL-3.0
- **Stars** : ~993
- **Stream Deck Plus** : Oui (touchscreen + dials)
- **Dernière activité** : Avril 2026 (très actif)
- **Architecture plugin** : Oui (store intégré, publication de plugins)
- **Features** : App Linux élégante, plugin store, wallpapers, screen saver, auto page switching (GNOME/KDE/Hyprland/Sway/X11), auto-lock. Distribution Flatpak. Supporte Original v2, Mini, XL, Pedal, Plus, Neo, Modules.
- **Pertinence ERP** : Meilleur candidat — Python + plugin architecture + GPL-3.0 compatible AGPL-3.0 d'ERPLibre. Créer un plugin StreamController connecté à Odoo XML-RPC/JSON-RPC.

#### DevDeck

- **GitHub** : https://github.com/jamesridgway/devdeck
- **Langage** : Python
- **Licence** : BSD-3-Clause
- **Stars** : ~131
- **Stream Deck Plus** : Non
- **Dernière activité** : Février 2026 (faible activité)
- **Architecture plugin** : Oui (plugins installables via pip)
- **Features** : Orienté développeur. Inclut : clock, command execution, mic mute, timer, volume control. Plugins existants : devdeck-slack, devdeck-home-assistant, devdeck-key-light. API DeckControl/DeckController pour écrire des plugins.
- **Pertinence ERP** : Plugin architecture avec Slack + Home Assistant comme templates. Créer `devdeck-erplibre` suivrait le même pattern. Licence BSD très permissive.

#### home-assistant-streamdeck-yaml

- **GitHub** : https://github.com/basnijholt/home-assistant-streamdeck-yaml
- **Langage** : Python
- **Licence** : Apache-2.0
- **Stars** : ~358
- **Stream Deck Plus** : Oui (support dials)
- **Dernière activité** : Avril 2026 (actif)
- **Architecture plugin** : Non (configuration YAML avec templates Jinja2)
- **Features** : Config YAML pour Home Assistant. Cross-platform. Templates dynamiques pour boutons. Add-on Home Assistant. Événements touchscreen et dials.
- **Pertinence ERP** : Démontre le pattern connexion Stream Deck → système web via API REST. L'approche YAML/Jinja2 adaptable pour workflows Odoo/ERP.

#### streamdeck-ui

- **GitHub** : https://github.com/timothycrosley/streamdeck-ui
- **Langage** : Python (Qt)
- **Licence** : MIT
- **Stars** : ~1268
- **Stream Deck Plus** : Non (pas de support touchscreen/dials)
- **Dernière activité** : Avril 2026 (maintenu)
- **Architecture plugin** : Non (basé sur commandes)
- **Features** : GUI Linux-first. Boutons configurables avec commandes, hotkeys, texte. Multi-page, brightness. Config YAML. Utilise python-elgato-streamdeck.
- **Pertinence ERP** : Simple et MIT. Bon point de départ pour outil léger mais manque plugin system et support Plus.

#### pydeck+ (streamdeck-plus-software)

- **GitHub** : https://github.com/goglesquirmintontheiii/streamdeck-plus-software
- **Langage** : Python (Tkinter)
- **Licence** : GPL-3.0
- **Stars** : ~105
- **Stream Deck Plus** : Oui (cible principale — touchscreen + dials)
- **Dernière activité** : Mars 2026 (beta)
- **Architecture plugin** : Oui
- **Features** : Spécifiquement pour Stream Deck Plus. GUI click-to-configure pour boutons, écran et dials. Système d'installateur.

#### streamdeckfs

- **GitHub** : https://github.com/twidi/streamdeckfs
- **Langage** : Python
- **Licence** : MIT
- **Stars** : ~23
- **Dernière activité** : Mars 2026 (maintenu)
- **Architecture plugin** : Non (configuration par filesystem)
- **Features** : Approche unique par filesystem — configurer le Stream Deck en créant fichiers/répertoires. Layers, texte, formes, images, animations.

#### snakedeck

- **GitHub** : https://github.com/jpetazzo/snakedeck
- **Langage** : Python
- **Licence** : Non spécifiée
- **Stars** : ~24
- **Dernière activité** : Décembre 2025 (faible activité)
- **Architecture plugin** : Partiel
- **Features** : Alternative légère. Contrôle lumières, caméras, workflows Docker/Kubernetes. Alpha.

### Tier 2 — Écosystème plus large (autres langages)

#### OpenDeck (Rust)

- **GitHub** : https://github.com/nekename/OpenDeck
- **Langage** : Rust + TypeScript (Tauri)
- **Licence** : GPL-3.0
- **Stars** : ~1531
- **Stream Deck Plus** : Oui (via rust-elgato-streamdeck)
- **Dernière activité** : Avril 2026 (très actif)
- **Architecture plugin** : Oui (supporte plugins Elgato SDK natifs + OpenAction API)
- **Features** : Cross-platform. Exécute plugins Elgato originaux via Wine sur Linux/macOS. Multi-actions, toggle actions, auto profile switching. Marketplace à marketplace.rivul.us.
- **Pertinence ERP** : Supporte l'écosystème de plugins Elgato directement. Écrire un plugin Elgato-compatible pour Odoo fonctionnerait dans OpenDeck ET le logiciel officiel.

#### Bitfocus Companion (TypeScript)

- **GitHub** : https://github.com/bitfocus/companion
- **Langage** : TypeScript (Node.js)
- **Licence** : MIT
- **Stars** : ~2135
- **Stream Deck Plus** : Oui
- **Dernière activité** : Avril 2026 (très actif, projet professionnel)
- **Architecture plugin** : Oui (300+ modules d'intégration)
- **Features** : Outil professionnel broadcast/AV. Supporte Stream Deck, X-Keys, Loupedeck, surfaces custom. Modules : ATEM, OBS, vMix, OSC, ArtNet, DMX, HTTP/REST, TCP/UDP, MQTT. UI web de configuration. Mode satellite pour opération à distance.
- **Pertinence ERP** : Le plus mature. Les modules HTTP/REST et MQTT pourraient déjà connecter à Odoo sans code custom. Le SDK modules permet créer des intégrations custom.

#### deckmaster (Go)

- **GitHub** : https://github.com/muesli/deckmaster
- **Langage** : Go
- **Licence** : MIT
- **Stars** : ~291
- **Stream Deck Plus** : Non
- **Dernière activité** : Mars 2026 (maintenu)
- **Architecture plugin** : Non (config fichiers widget/action)
- **Features** : Linux, léger. Widgets : boutons, horloge, CPU/mem, météo, output commande, fenêtres récentes. Actions : commandes, émulation clavier, clipboard, dbus. Support short/long press. Auto-start systemd via udev.

#### WebDeck (Python/Flask)

- **GitHub** : https://github.com/Lenochxd/WebDeck
- **Langage** : Python (Flask/Jinja2)
- **Licence** : GPL-3.0
- **Stars** : ~874
- **Stream Deck Plus** : N/A (utilise phone/tablette comme Stream Deck virtuel)
- **Dernière activité** : Avril 2026 (actif)
- **Architecture plugin** : Oui
- **Features** : Pas de hardware nécessaire — transforme tout phone/tablette en Stream Deck via navigateur web. App Flask. Layouts custom, intégration OBS, contrôles media, commandes système.
- **Pertinence ERP** : L'approche web signifie que tout appareil avec un navigateur devient une surface de contrôle. Adaptable pour afficher dashboards/actions Odoo sur un phone.

#### ODeck (TypeScript)

- **GitHub** : https://github.com/willianrod/ODeck
- **Langage** : TypeScript
- **Licence** : MIT
- **Stars** : ~434
- **Stream Deck Plus** : Non
- **Dernière activité** : Mars 2026 (maintenu)
- **Architecture plugin** : Oui
- **Features** : Solution phone-as-StreamDeck. Serveur cross-platform + app mobile.

#### DeckSurf (C#/.NET)

- **GitHub** : https://github.com/dend/DeckSurf
- **Langage** : C#
- **Licence** : MIT
- **Stars** : ~159
- **Dernière activité** : Avril 2026 (actif)
- **Architecture plugin** : Oui (SDK orienté extensibilité)
- **Features** : Outil .NET léger avec approche CLI + SDK.

### Tier 3 — Librairies bas-niveau (pour solutions custom)

#### Python

| Nom | GitHub | Stars | Licence | SD+ |
|-----|--------|-------|---------|-----|
| python-elgato-streamdeck | https://github.com/abcminiuser/python-elgato-streamdeck | ~1103 | MIT | Oui |

#### Rust

| Nom | GitHub | Stars | Licence | SD+ |
|-----|--------|-------|---------|-----|
| rust-elgato-streamdeck | https://github.com/OpenActionAPI/rust-elgato-streamdeck | ~77 | MPL-2.0 | Oui |
| rust-streamdeck | https://github.com/ryankurte/rust-streamdeck | ~77 | MPL-2.0 | Partiel |

#### Go

| Nom | GitHub | Stars | Licence | SD+ |
|-----|--------|-------|---------|-----|
| dh1tw/streamdeck | https://github.com/dh1tw/streamdeck | ~86 | MIT | Inconnu |
| go-streamdeck | https://github.com/magicmonkey/go-streamdeck | ~79 | MIT | Inconnu |
| Luzifer/streamdeck | https://github.com/Luzifer/streamdeck | ~36 | Apache-2.0 | Non |

#### Node.js / TypeScript

| Nom | GitHub | Stars | Licence | SD+ |
|-----|--------|-------|---------|-----|
| node-elgato-stream-deck | https://github.com/Julusian/node-elgato-stream-deck | ~194 | MIT | Oui (WebHID browser) |

#### C# / .NET

| Nom | GitHub | Stars | Licence | SD+ |
|-----|--------|-------|---------|-----|
| StreamDeckSharp | https://github.com/OpenMacroBoard/StreamDeckSharp | ~393 | MIT | Partiel |
| streamdeck-tools | https://github.com/BarRaider/streamdeck-tools | ~539 | MIT | Oui (wraps SDK officiel) |

### Référence — Plugin Home Assistant pour Elgato

- **GitHub** : https://github.com/cgiesche/streamdeck-homeassistant
- **Langage** : Vue/JavaScript
- **Licence** : MIT
- **Stars** : ~1014
- **Pertinence** : Modèle architectural exact pour ERP — démontre comment bâtir un plugin Elgato SDK-compatible connecté à un système web via websocket/REST API. Substituer l'API Home Assistant par XML-RPC/JSON-RPC Odoo donnerait un plugin Stream Deck pour Odoo.

---

## Recommandation : StreamController + plugin ERPLibre

### Pourquoi StreamController

1. **Python** — même stack qu'ERPLibre/Odoo
2. **Plugin store** — distribution communautaire immédiate
3. **GPL-3.0** — compatible AGPL-3.0 d'ERPLibre
4. **Support SD+** — touchscreen + dials
5. **Actif** — commits avril 2026
6. **Flatpak** — installation simple pour utilisateurs

### Architecture proposée

```
StreamController (app existante)
  └── plugin-erplibre/
       ├── __init__.py          # Plugin registration
       ├── actions/
       │   ├── odoo_action.py   # Bouton: exécuter action Odoo
       │   ├── todo_action.py   # Bouton: naviguer todo.py
       │   ├── db_status.py     # Bouton: statut DB (vert/rouge)
       │   └── module_action.py # Bouton: install/update module
       ├── api/
       │   ├── odoo_rpc.py      # Client XML-RPC/JSON-RPC Odoo
       │   └── erplibre_api.py  # Wrapper scripts ERPLibre
       └── assets/
           └── icons/           # Icônes ERPLibre pour boutons
```

### Plan de travail

#### Phase 1 — Fondation (1-2 semaines)

- [ ] Fork/clone StreamController, comprendre architecture plugin
- [ ] Créer plugin squelette `streamcontroller-plugin-erplibre`
- [ ] Implémenter connexion Odoo XML-RPC (host/port/db/user/pass)
- [ ] Premier bouton : afficher statut serveur Odoo (vert/rouge)

#### Phase 2 — Actions core (2-3 semaines)

- [ ] Bouton todo.py — lance/navigue CLI interactif
- [ ] Bouton DB — clone/restore/switch base
- [ ] Bouton module — install/update addons
- [ ] Bouton make — targets Makefile fréquentes
- [ ] Config touchscreen SD+ pour navigation

#### Phase 3 — Fonctionnel Odoo (2-3 semaines)

- [ ] Boutons dynamiques : afficher compteurs (commandes, factures, tickets)
- [ ] Actions workflow : valider devis, confirmer commande
- [ ] Notifications push sur touchscreen (nouveaux messages, alertes)
- [ ] Pages multiples (dev, production, monitoring)

#### Phase 4 — Migration code existant (1 semaine)

- [ ] Porter features webcam, animations, smyleys comme actions plugin
- [ ] Garder `keyboard_talk.py` comme action externe
- [ ] Tests + documentation

#### Phase 5 — Contribution upstream (continu)

- [ ] Publier plugin sur StreamController store
- [ ] PR features génériques upstream
- [ ] Documentation bilingue (mmg)

### Alternative : garder code custom

Si préférence pour garder le contrôleur actuel sans dépendre de StreamController :

- Refactorer `erplibre_controller.py` en modules séparés
- Ajouter config YAML (inspiré de home-assistant-streamdeck-yaml)
- Le code actuel reste, mais structuré en plugin system maison
