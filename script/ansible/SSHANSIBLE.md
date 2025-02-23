# Guide d'utilisation de la commande `sshansible`

## Description

La commande `sshansible` permet d'établir une connexion SSH avec un hôte en utilisant la clé SSH spécifique à un "royaume" donné. La connexion est effectuée avec l'utilisateur `ansible`.

## Usage

```bash
sshansible <royaume> <hôte>
```

### Paramètres
- `<royaume>` : Identifiant du royaume permettant de sélectionner la bonne clé SSH.
- `<hôte>` : Adresse IP ou nom DNS de l'hôte cible.

## Fonctionnement
1. Le script récupère le nom du royaume fourni en premier argument.
2. Il construit le chemin de la clé SSH en utilisant la convention suivante :
   ```bash
   ~/.ssh/id_ed25519_ansible_<royaume>
   ```
3. Il vérifie que la clé SSH existe.
4. Il établit la connexion SSH à l'hôte en utilisant l'utilisateur `ansible` et la clé appropriée.

## Prérequis
- Une clé SSH spécifique pour chaque royaume, nommée selon le format `id_ed25519_ansible_<royaume>` et placée dans `~/.ssh/`.
- L'utilisateur `ansible` doit être autorisé à se connecter à l'hôte cible avec cette clé.
- Le script `sshansible` doit être exécutable :
  ```bash
  chmod +x sshansible
  ```

## Exemple d'utilisation

Connexion à l'hôte `server1.example.com` dans le royaume `prod` :

```bash
sshansible prod server1.example.com
```

## Installation
Si vous souhaitez utiliser cette commande globalement, placez le script dans `/usr/local/bin/` :

```bash
sudo mv sshansible /usr/local/bin/
```

Vous pourrez ensuite l'utiliser depuis n'importe quel répertoire.

## Dépannage
- **Erreur : La clé SSH n'existe pas**  
  Vérifiez que la clé SSH correspondant au royaume est bien présente dans `~/.ssh/`.
  
- **Connexion refusée**  
  Assurez-vous que l'utilisateur `ansible` est autorisé à se connecter à l'hôte cible avec la clé spécifiée.

---
