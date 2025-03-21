# Guide d'utilisation de la commande `ajoutRoyaumeAnsible.py`

## Description

Ce script doit être exécuté à partir de l'utilisateur ansible du noeud de contrôle.
La commande `ajoutRoyaumeAnsible.py` est un script Python permettant de générer une
paire
de clés SSH pour un "royaume" spécifique. Ces clés sont stockées dans le répertoire
`~/.ssh` et suivent la nomenclature `id_ed25519_ansible_<royaume>`.

## Usage

```bash
ajoutRoyaumeAnsible.py
```

### Paramètre

- Le script demande à l'utilisateur de saisir un nom de royaume (`<royaume>`), qui sera
  utilisé pour nommer la paire de clés SSH générée.

## Fonctionnement

1. Vérifie si le répertoire `~/.ssh` existe, et le crée si nécessaire.
2. Génère une paire de clés SSH avec la commande `ssh-keygen` et les stocke dans
   `~/.ssh/`.
3. Affiche les chemins des fichiers de clé privée et publique générés.

## Prérequis

- Avoir Python 3 installé.
- Avoir l'outil `ssh-keygen` installé et accessible dans le PATH.
- Le script doit être exécutable :

```bash
chmod +x ajoutRoyaumeAnsible.py
```

## Exemple d'utilisation

1. Lancer le script :

```bash
ajoutRoyaumeAnsible.py
```

2. Saisir le nom du royaume lorsqu'il est demandé, par exemple :

```
Entrez le nom du royaume (par exemple, 'mon_royaume') : prod
```

3. Résultat attendu :

```
✅ Paires de clés SSH générées :
- Clé privée : ~/.ssh/id_ed25519_ansible_prod
- Clé publique : ~/.ssh/id_ed25519_ansible_prod.pub
```

## Installation

Si vous souhaitez utiliser ce script globalement, placez-le dans `/usr/local/bin/` et
assurez-vous qu'il est exécutable :

```bash
sudo mv ajoutRoyaumeAnsible.py /usr/local/bin/
chmod +x /usr/local/bin/ajoutRoyaumeAnsible
```

Vous pourrez ensuite l'exécuter depuis n'importe quel répertoire en tapant :

```bash
ajoutRoyaumeAnsible
```

## Dépannage

- **Erreur : Commande introuvable `ssh-keygen`**
  Assurez-vous que `ssh-keygen` est installé. Sur les systèmes basés sur Debian/Ubuntu,
  installez-le avec :
  ```bash
  sudo apt install openssh-client
  ```

- **Permission refusée lors de la création du répertoire `~/.ssh`**
  Vérifiez que vous avez les permissions nécessaires pour écrire dans votre répertoire
  utilisateur.

---
