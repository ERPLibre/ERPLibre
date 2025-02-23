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

## 6. Contenu du Script Complet

```bash
#!/bin/bash
#
# Script de gestion d'une PKI avec Easy-RSA
#
# Usage général :
#   ./easypki.sh <nompki> [--utilisateur [<nomcert>]|--machine [<nomcert>]|--renouv <nomcert>|--revoque <nomcert>]
#
# Comportement :
#   - Avec un seul paramètre (<nompki>) :
#       • Si la PKI n'existe pas, elle est créée :
#           - Initialisation du dossier pki et création de la CA principale.
#           - Création des certificats de CA subordonnées : "CA_utilisateur" et "CA_machine".
#       • Sinon, on affiche les propriétés de la PKI : on affiche d'abord le certificat de la CA principale,
#         puis ceux des CA subordonnées, et enfin on liste tous les certificats (utilisateur et machine).
#
#   - Avec deux paramètres ou plus :
#       --utilisateur
#           • Sans argument supplémentaire : affiche le certificat de la CA subordonnée "CA_utilisateur"
#             puis la liste de tous les certificats utilisateur.
#           • Avec un argument : crée (ou remplace) le certificat utilisateur du nom fourni.
#
#       --machine
#           • Sans argument supplémentaire : affiche le certificat de la CA subordonnée "CA_machine"
#             puis la liste de tous les certificats machine.
#           • Avec un argument : crée (ou remplace) le certificat machine du nom fourni.
#
#       --renouv <nomcert>
#           Renouvelle le certificat du nom indiqué en utilisant la même requête (uniquement si le certificat n'est pas révoqué).
#
#       --revoque <nomcert>
#           Révoque le certificat du nom indiqué.
#

set -e

# Forcer le mode non interactif d'Easy-RSA
export EASYRSA_BATCH=1

# Chemin vers l'exécutable Easy-RSA
EASYRSA="/usr/share/easy-rsa/easyrsa"

# Vérification du premier argument (nom de la PKI)
if [ $# -lt 1 ]; then
  echo "Usage: $0 <nompki> [--utilisateur [<nomcert>]|--machine [<nomcert>]|--renouv <nomcert>|--revoque <nomcert>]"
  exit 1
fi

PKI_NAME="$1"
shift

# Dossier de gestion de la PKI
PKI_DIR="./${PKI_NAME}"

# Noms des CA subordonnées
SUB_CA_UTIL="CA_utilisateur"
SUB_CA_MACH="CA_machine"

# --- Fonction de nettoyage des certificats révoqués expirés ---
cleanup_revoked() {
  local index_file="${PKI_DIR}/pki/index.txt"
  if [ -f "$index_file" ]; then
    while IFS= read -r line; do
      if [[ "$line" =~ ^R ]]; then
        exp_date=$(echo "$line" | awk '{print $2}')
        exp_date_clean=${exp_date%Z}
        exp_epoch=$(date -d "${exp_date_clean}" +%s 2>/dev/null || true)
        now_epoch=$(date +%s)
        if [ -n "$exp_epoch" ] && [ "$now_epoch" -gt "$exp_epoch" ]; then
          cn=$(echo "$line" | grep -o '/CN=[^/]*' | cut -d '=' -f2)
          if [ -n "$cn" ]; then
            cert_file="${PKI_DIR}/pki/issued/${cn}.crt"
            if [ -f "$cert_file" ]; then
              rm -f "$cert_file"
              echo "Nettoyage : Certificat révoqué '$cn' supprimé (expiration dépassée)."
            fi
          fi
        fi
      fi
    done < "$index_file"
  fi
}

# --- Fonction d'affichage d'un certificat CA subordonné ---
show_sub_ca_info() {
  local subca_name="$1"
  local subca_path="${PKI_DIR}/pki/issued/${subca_name}.crt"
  if [ -f "$subca_path" ]; then
    echo "CA subordonné ${subca_name#CA_} :"
    openssl x509 -in "$subca_path" -noout -subject -issuer -enddate
    echo "------------------------------"
  fi
}

# --- Fonction d'affichage des propriétés de la PKI (CA principale + CA subordonnées) ---
show_pki_info() {
  if [ -f "${PKI_DIR}/pki/ca.crt" ]; then
    echo "CA principale :"
    openssl x509 -in "${PKI_DIR}/pki/ca.crt" -noout -subject -issuer -enddate
    echo "------------------------------"
  else
    echo "Aucune CA principale trouvée dans la PKI."
  fi

  # Affichage des CA subordonnées
  show_sub_ca_info "$SUB_CA_UTIL"
  show_sub_ca_info "$SUB_CA_MACH"
}

# --- Fonction de liste de tous les certificats (hors CA principales/subordonnées) groupés par type ---
list_all_certificates() {
  local index_file="${PKI_DIR}/pki/index.txt"
  if [ ! -f "$index_file" ]; then
      echo "Aucun index trouvé."
      return
  fi

  echo "Certificats Utilisateur :"
  grep -E '/CN=' "$index_file" | while read -r line; do
    cn=$(echo "$line" | grep -o '/CN=[^/]*' | cut -d '=' -f2)
    # Exclure les CA subordonnées
    if [[ "$cn" != "$SUB_CA_UTIL" && "$cn" != "$SUB_CA_MACH" && "$cn" != *.* ]]; then
      cert_file="${PKI_DIR}/pki/issued/${cn}.crt"
      if [ -f "$cert_file" ]; then
        exp=$(openssl x509 -enddate -noout -in "$cert_file" 2>/dev/null | cut -d= -f2)
        echo "  $cn - Expiration : $exp"
      fi
    fi
  done

  echo "Certificats Machine :"
  grep -E '/CN=' "$index_file" | while read -r line; do
    cn=$(echo "$line" | grep -o '/CN=[^/]*' | cut -d '=' -f2)
    if [[ "$cn" != "$SUB_CA_UTIL" && "$cn" != "$SUB_CA_MACH" && "$cn" == *.* ]]; then
      cert_file="${PKI_DIR}/pki/issued/${cn}.crt"
      if [ -f "$cert_file" ]; then
        exp=$(openssl x509 -enddate -noout -in "$cert_file" 2>/dev/null | cut -d= -f2)
        echo "  $cn - Expiration : $exp"
      fi
    fi
  done
}

# --- Fonctions de liste par type avec affichage du CA subordonné ---
list_utilisateur_certificates() {
  local index_file="${PKI_DIR}/pki/index.txt"
  if [ ! -f "$index_file" ]; then
      echo "Aucun index trouvé."
      return
  fi
  echo "Certificat du CA subordonné Utilisateur :"
  show_sub_ca_info "$SUB_CA_UTIL"
  echo "Certificats Utilisateur :"
  grep -E '/CN=' "$index_file" | while read -r line; do
    cn=$(echo "$line" | grep -o '/CN=[^/]*' | cut -d '=' -f2)
    # Exclure le CA subordonné
    if [[ "$cn" != "$SUB_CA_UTIL" && "$cn" != "$SUB_CA_MACH" && "$cn" != *.* ]]; then
      cert_file="${PKI_DIR}/pki/issued/${cn}.crt"
      if [ -f "$cert_file" ]; then
        exp=$(openssl x509 -enddate -noout -in "$cert_file" 2>/dev/null | cut -d= -f2)
        echo "  $cn - Expiration : $exp"
      fi
    fi
  done
}

list_machine_certificates() {
  local index_file="${PKI_DIR}/pki/index.txt"
  if [ ! -f "$index_file" ];then
      echo "Aucun index trouvé."
      return
  fi
  echo "Certificat du CA subordonné Machine :"
  show_sub_ca_info "$SUB_CA_MACH"
  echo "Certificats Machine :"
  grep -E '/CN=' "$index_file" | while read -r line; do
    cn=$(echo "$line" | grep -o '/CN=[^/]*' | cut -d '=' -f2)
    if [[ "$cn" != "$SUB_CA_UTIL" && "$cn" != "$SUB_CA_MACH" && "$cn" == *.* ]]; then
      cert_file="pki/issued/${cn}.crt"
      if [ -f "$cert_file" ]; then
        exp=$(openssl x509 -enddate -noout -in "$cert_file" 2>/dev/null | cut -d= -f2)
        echo "  $cn - Expiration : $exp"
      fi
    fi
  done
}

# --- Création de la PKI ou affichage de ses propriétés ---
if [ $# -eq 0 ]; then
  if [ ! -d "${PKI_DIR}" ]; then
    echo "Création de la PKI '${PKI_NAME}'..."
    mkdir -p "${PKI_DIR}"
    pushd "${PKI_DIR}" > /dev/null

    # Initialisation du dossier pki et création de la CA principale
    $EASYRSA init-pki
    $EASYRSA build-ca nopass

    # Création des CA subordonnées pour utilisateur et machine
    echo "Création du CA subordonné '${SUB_CA_UTIL}'..."
    $EASYRSA gen-req "$SUB_CA_UTIL" nopass
    $EASYRSA sign-req ca "$SUB_CA_UTIL"

    echo "Création du CA subordonné '${SUB_CA_MACH}'..."
    $EASYRSA gen-req "$SUB_CA_MACH" nopass
    $EASYRSA sign-req ca "$SUB_CA_MACH"

    popd > /dev/null
    echo "PKI '${PKI_NAME}' créée avec la CA principale et les CA subordonnées."
  else
    echo "PKI '${PKI_NAME}' existante."
    show_pki_info
    echo ""
    list_all_certificates
  fi
  exit 0
fi

# Exécution du nettoyage à chaque lancement (si la PKI existe)
if [ -d "${PKI_DIR}" ]; then
  cleanup_revoked
fi

# --- Traitement des actions ---
action="$1"
shift

case "$action" in
  --utilisateur)
    if [ $# -eq 0 ]; then
      echo "Liste des certificats utilisateur de la PKI '${PKI_NAME}':"
      list_utilisateur_certificates
    else
      CERT_NAME="$1"
      shift
      echo "Création/remplacement du certificat utilisateur pour '$CERT_NAME'..."
      pushd "${PKI_DIR}" > /dev/null
      # Création du certificat utilisateur (signature via build-client-full)
      $EASYRSA build-client-full "$CERT_NAME" nopass
      popd > /dev/null
      echo "Certificat utilisateur '$CERT_NAME' créé/remplacé."
    fi
    ;;
  --machine)
    if [ $# -eq 0 ]; then
      echo "Liste des certificats machine de la PKI '${PKI_NAME}':"
      list_machine_certificates
    else
      CERT_NAME="$1"
      shift
      echo "Création/remplacement du certificat machine pour '$CERT_NAME'..."
      pushd "${PKI_DIR}" > /dev/null
      $EASYRSA build-server-full "$CERT_NAME" nopass
      popd > /dev/null
      echo "Certificat machine '$CERT_NAME' créé/remplacé."
    fi
    ;;
  --renouv)
    if [ $# -gt 0 ]; then
      CERT_NAME="$1"
      shift
      echo "Renouvellement du certificat '$CERT_NAME'..."
      pushd "${PKI_DIR}" > /dev/null
      if [ ! -f "pki/issued/${CERT_NAME}.crt" ]; then
        echo "Erreur : Le certificat '$CERT_NAME' n'existe pas."
        popd > /dev/null
        exit 1
      fi
      if grep -q "^R.*\/CN=${CERT_NAME}\b" pki/index.txt; then
        echo "Erreur : Le certificat '$CERT_NAME' est révoqué et ne peut être renouvelé."
        popd > /dev/null
        exit 1
      fi
      # Détermine le type du certificat (machine si le nom contient un point, sinon utilisateur)
      if [[ "$CERT_NAME" == *.* ]]; then
          TYPE="machine"
      else
          TYPE="utilisateur"
      fi
      if [ ! -f "pki/private/${CERT_NAME}.key" ]; then
        echo "Erreur : La clé privée pour '$CERT_NAME' est introuvable, impossible de renouveler."
        popd > /dev/null
        exit 1
      fi
      mkdir -p pki/reqs
      openssl req -new -key "pki/private/${CERT_NAME}.key" -out "pki/reqs/${CERT_NAME}.csr" -subj "/CN=${CERT_NAME}" >/dev/null 2>&1
      if [ "$TYPE" == "machine" ]; then
          $EASYRSA sign-req server "$CERT_NAME"
      else
          $EASYRSA sign-req client "$CERT_NAME"
      fi
      popd > /dev/null
      echo "Certificat '$CERT_NAME' renouvelé."
    else
      echo "Erreur : Veuillez préciser le nom du certificat à renouveler après --renouv."
      exit 1
    fi
    ;;
  --revoque)
    if [ $# -gt 0 ]; then
      CERT_NAME="$1"
      shift
      echo "Révocation du certificat '$CERT_NAME'..."
      pushd "${PKI_DIR}" > /dev/null
      $EASYRSA revoke "$CERT_NAME"
      $EASYRSA gen-crl
      popd > /dev/null
      echo "Certificat '$CERT_NAME' révoqué."
    else
      echo "Erreur : Veuillez préciser le nom du certificat à révoquer après --revoque."
      exit 1
    fi
    ;;
  *)
    echo "Option inconnue : $action"
    exit 1
    ;;
esac
```

---

## 7. Conclusion

Ce script propose une approche complète pour **initialiser** une PKI avec une **CA principale**, deux **CA subordonnées** (pour utilisateurs et machines), et gère le **cycle de vie** des certificats finaux : création, listing, renouvellement et révocation.  

- **À retenir** :  
  - L’action la plus basique (appeler le script avec juste `<nompki>`) permet soit de créer l’entièreté de la PKI, soit d’afficher son état complet.  
  - Les autres options gèrent les différents cas d’utilisation (certificats utilisateur/machine, renouvellement, révocation).  
  - La sécurité de l’infrastructure dépendra beaucoup de la **protection des clés privées** et de la **mise à disposition des CRL** pour informer de la révocation des certificats.

Vous avez désormais tous les éléments pour manipuler votre PKI via ce script !
