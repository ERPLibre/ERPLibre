# Manuel d'utilisation - Gestion des clients OpenVPN

## Introduction
Ce manuel décrit l'utilisation du script `openvpn_manager.py` pour gérer les clients OpenVPN. 
Il permet d'ajouter, révoquer, supprimer et lister les clients ainsi que de vérifier l'état du serveur OpenVPN.

## Prérequis
Avant d'utiliser ce script, assurez-vous que :
- OpenVPN et Easy-RSA sont installés et configurés sur votre serveur.
- Le script `openvpn_manager.py` est placé sur le serveur OpenVPN.
- Vous avez les permissions nécessaires pour exécuter les commandes requises.

## Utilisation
Le script doit être exécuté en ligne de commande avec une commande spécifique :

```sh
python openvpn_manager.py <commande> [arguments]
```

### Commandes disponibles

#### 1. Ajouter un client
Crée un certificat et une clé pour un nouveau client OpenVPN.

```sh
python openvpn_manager.py add <nom_client>
```

Exemple :
```sh
python openvpn_manager.py add client1
```

#### 2. Révoquer un client
Révoque un client et met à jour la liste de révocation des certificats (CRL).

```sh
python openvpn_manager.py revoke <nom_client>
```

Exemple :
```sh
python openvpn_manager.py revoke client1
```

#### 3. Supprimer un client
Supprime les fichiers de certificat et de clé d'un client OpenVPN.

```sh
python openvpn_manager.py delete <nom_client>
```

Exemple :
```sh
python openvpn_manager.py delete client1
```

#### 4. Lister les clients connectés
Affiche la liste des clients actuellement connectés au serveur OpenVPN.

```sh
python openvpn_manager.py list
```

#### 5. Vérifier l'état du serveur OpenVPN
Affiche l'état actuel du service OpenVPN.

```sh
python openvpn_manager.py status
```

## Exemple d'utilisation
Voici un exemple de workflow typique :
1. Ajouter un nouveau client :
   ```sh
   python openvpn_manager.py add utilisateur1
   ```
2. Vérifier la connexion des clients :
   ```sh
   python openvpn_manager.py list
   ```
3. Révoquer un client :
   ```sh
   python openvpn_manager.py revoke utilisateur1
   ```
4. Vérifier l'état du serveur OpenVPN :
   ```sh
   python openvpn_manager.py status
   ```

## Notes supplémentaires
- Le script utilise `Easy-RSA` pour la gestion des certificats.
- La révocation d'un client met à jour la CRL, mais vous devez redémarrer OpenVPN pour que les changements prennent effet.
- L'état du serveur OpenVPN est vérifié à l'aide de `systemctl`.

## Support
Si vous avez des questions ou des problèmes, contactez l'administrateur du serveur OpenVPN.

