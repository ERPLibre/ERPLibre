# Documentation du script de gestion d'une PKI avec Easy-RSA

Ce document décrit l’utilisation et le fonctionnement du script Bash permettant de gérer une **PKI** (Public Key Infrastructure) via **Easy-RSA**.  
Le script crée une CA principale (Certificate Authority), ainsi que deux CA subordonnées :  
- **CA_utilisateur** (pour signer les certificats utilisateurs, dont le CN ne contient pas de point),  
- **CA_machine** (pour signer les certificats machines, dont le CN contient un point).

Le script permet également de lister, renouveler et révoquer les certificats.

---

## 1. Principe de fonctionnement

1. **Easy-RSA** est un ensemble d’utilitaires qui facilite la création et la gestion d’une PKI.  
2. **Le script** s’appuie sur Easy-RSA pour :  
   - Initialiser la PKI (création d’un répertoire local contenant les clés, certificats et métadonnées nécessaires).  
   - Générer automatiquement :  
     - Une **CA principale** (racine).  
     - Deux **CA subordonnées** : l’une pour les certificats *utilisateur* (appelée `CA_utilisateur`), l’autre pour les certificats *machine* (appelée `CA_machine`).  
   - Gérer les certificats finaux (création, liste, renouvellement, révocation).

3. **Structure du répertoire PKI** :  
   Le dossier de la PKI contient tous les fichiers générés par Easy-RSA (clés privées, certificats, fichier d’index, CRL, etc.).

---

## 2. Utilisation générale

```bash
./easypki.sh <nompki> [--utilisateur [<nomcert>]|--machine [<nomcert>]|--renouv <nomcert>|--revoque <nomcert>]
```

- **`<nompki>`** (obligatoire) : Le nom (et donc le dossier) de la PKI que vous souhaitez gérer.  
- **Actions** (paramètre suivant) :  
  - `--utilisateur [<nomcert>]`  
  - `--machine [<nomcert>]`  
  - `--renouv <nomcert>`  
  - `--revoque <nomcert>`  

### 2.1. Cas sans action supplémentaire

Si la commande est lancée **avec un seul paramètre** :

```bash
./easypki.sh <nompki>
```

- **Si le répertoire `<nompki>` n’existe pas**, le script :  
  1. Crée ce répertoire et l’initialise (`init-pki`).  
  2. Génère une **CA principale** (root CA).  
  3. Crée deux **CA subordonnées** : `CA_utilisateur` et `CA_machine`.  

- **Si le répertoire `<nompki>` existe déjà**, le script :  
  1. Affiche les propriétés (sujets, émetteurs, dates d’expiration) de la **CA principale** et des **CA subordonnées**.  
  2. Liste **tous les certificats finaux**, en distinguant ceux de type **utilisateur** et **machine**.

### 2.2. Actions disponibles

#### 2.2.1. `--utilisateur [<nomcert>]`

- **Sans `<nomcert>`** :  
  Affiche la **propriété du CA subordonné** correspondant (CA_utilisateur), puis liste **tous les certificats utilisateur** (filtrés sur le fait que le CN ne contient pas de point).

  ```bash
  ./easypki.sh <nompki> --utilisateur
  ```
  
- **Avec `<nomcert>`** :  
  Crée (ou remplace) un certificat utilisateur nommé `<nomcert>`.

  ```bash
  ./easypki.sh <nompki> --utilisateur monuser
  ```
  
  Cela génère un certificat final pour `monuser`, signé par `CA_utilisateur`.

#### 2.2.2. `--machine [<nomcert>]`

- **Sans `<nomcert>`** :  
  Affiche la **propriété du CA subordonné** correspondant (CA_machine), puis liste **tous les certificats machine** (filtrés sur le fait que le CN contient un point).

  ```bash
  ./easypki.sh <nompki> --machine
  ```
  
- **Avec `<nomcert>`** :  
  Crée (ou remplace) un certificat machine nommé `<nomcert>`.

  ```bash
  ./easypki.sh <nompki> --machine monserveur.example.com
  ```
  
  Cela génère un certificat final pour `monserveur.example.com`, signé par `CA_machine`.

#### 2.2.3. `--renouv <nomcert>`

Renouvelle le certificat `<nomcert>`, en utilisant la même clé privée et donc la même requête (CSR).  
Le certificat précédent doit exister et ne pas avoir été révoqué.  

```bash
./easypki.sh <nompki> --renouv monuser
```

> **Note :**  
> Le script vérifie que :  
> - Le certificat `<nomcert>` existe dans `pki/issued/`.  
> - Il n’est pas marqué comme **révoqué** dans `pki/index.txt`.  
> - La clé privée `pki/private/<nomcert>.key` est disponible.  
> Ensuite, il génère une nouvelle CSR avec la même clé et la signe pour créer un **nouveau certificat** valide (nouvelle date d’expiration).

#### 2.2.4. `--revoque <nomcert>`

Révoque le certificat `<nomcert>` et régénère la **CRL** (Certificate Revocation List).  

```bash
./easypki.sh <nompki> --revoque monuser
```

> **Attention :**  
> Un certificat révoqué **ne peut plus être renouvelé**. Le script le signale et refuse la commande de `--renouv`.

---

## 3. Exemples pratiques

### 3.1. Créer la PKI « demoPKI » et ses CA

```bash
./easypki.sh demoPKI
```

- Si le dossier `./demoPKI` n’existe pas, le script va :
  1. Créer `./demoPKI`.
  2. Initialiser la PKI (`init-pki`).
  3. Générer la CA principale (`build-ca nopass`).
  4. Générer et signer deux CA subordonnées :  
     - `CA_utilisateur` (pour signer des certificats utilisateur),  
     - `CA_machine` (pour signer des certificats machine).

### 3.2. Lister les propriétés et certificats d’une PKI existante

```bash
./easypki.sh demoPKI
```

- Si le dossier `./demoPKI` existe déjà, on verra :  
  - Les infos de la **CA principale** (sujet, émetteur, date de fin).  
  - Les infos des **CA subordonnées** : `CA_utilisateur` et `CA_machine`.  
  - La liste des **certificats finaux** (utilisateurs et machines).

### 3.3. Créer ou remplacer un certificat utilisateur

```bash
./easypki.sh demoPKI --utilisateur alice
```

- Génère un certificat pour `alice` si celui-ci n’existe pas, ou le remplace s’il existe déjà.

### 3.4. Lister uniquement les certificats utilisateur

```bash
./easypki.sh demoPKI --utilisateur
```

- Affiche d’abord le **certificat CA_utilisateur**, puis la liste des certificats utilisateurs (CN sans point, hors CA subordonnés).

### 3.5. Créer ou remplacer un certificat machine

```bash
./easypki.sh demoPKI --machine srv.example.com
```

- Génère un certificat pour `srv.example.com` (signé par **CA_machine**).

### 3.6. Lister uniquement les certificats machine

```bash
./easypki.sh demoPKI --machine
```

- Affiche d’abord le **certificat CA_machine**, puis la liste des certificats machines (CN contenant un point).

### 3.7. Renouveler un certificat existant

```bash
./easypki.sh demoPKI --renouv srv.example.com
```

- Utilise la même clé privée que précédemment pour `srv.example.com`.  
- Génère une nouvelle CSR **avec cette même clé**, puis la signe afin d’actualiser la date de validité du certificat.  
- Échoue si le certificat est révoqué ou si la clé privée n’est pas trouvée.

### 3.8. Révoquer un certificat

```bash
./easypki.sh demoPKI --revoque alice
```

- Marque le certificat `alice` comme révoqué dans `pki/index.txt`.  
- Supprime le fichier .crt correspondant (lorsque sa date d’expiration est dépassée) via la fonction de nettoyage.  
- Régénère la CRL (Certificate Revocation List).

---

## 4. Nettoyage des certificats révoqués et expirés

À **chaque exécution** du script, si le répertoire PKI existe déjà, une fonction `cleanup_revoked` lit le fichier `pki/index.txt` pour identifier les certificats marqués comme **révoqués** (« R ») et compare les dates d’expiration. Ceux qui sont **déjà expirés** sont physiquement supprimés du dossier `pki/issued/`.

Cela permet de **nettoyer** les certificats obsolètes et d’éviter l’encombrement de la PKI.

---

## 5. Points d’attention

1. **Export / distribution des CA**  
   - Pour qu’un client ou un serveur fasse confiance aux certificats signés par la CA principale ou ses CA subordonnées, il faut leur **fournir** ces certificats (au moins la chaîne de certification).  
   - Les clés **privées** de la CA racine et des sub-CA **doivent rester secrètes**.

2. **Sauvegardes**  
   - Si vous supprimez le répertoire `./<nompki>`, vous perdez **toute** la PKI. Les certificats (crts) et clés (keys) ne seront plus disponibles.  
   - Pensez à faire des **sauvegardes** régulières.

3. **Révocation vs. expiration**  
   - Un certificat **révoqué** est censé ne plus être valide **immédiatement** et doit être inclus dans la CRL distribuée.  
   - Un certificat simplement **expiré** devient invalide automatiquement mais n’est pas listé dans la CRL.  
   - Par sécurité, si vous souhaitez **retirer la confiance** à un certificat **avant** sa date d’expiration (compromis, départ utilisateur, etc.), vous **devez** le révoquer.

---

## 6. Conclusion

Ce script propose une approche complète pour **initialiser** une PKI avec une **CA principale**, deux **CA subordonnées** (pour utilisateurs et machines), et gère le **cycle de vie** des certificats finaux : création, listing, renouvellement et révocation.  

- **À retenir** :  
  - L’action la plus basique (appeler le script avec juste `<nompki>`) permet soit de créer l’entièreté de la PKI, soit d’afficher son état complet.  
  - Les autres options gèrent les différents cas d’utilisation (certificats utilisateur/machine, renouvellement, révocation).  
  - La sécurité de l’infrastructure dépendra beaucoup de la **protection des clés privées** et de la **mise à disposition des CRL** pour informer de la révocation des certificats.

Vous avez désormais tous les éléments pour manipuler votre PKI via ce script !
