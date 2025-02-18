# Guide d'utilisation du script de gestion PKI avec Easy-RSA

## Introduction
Ce script permet d'automatiser la création et la gestion d'une **Infrastructure à Clé Publique (PKI)** en utilisant **Easy-RSA**. Il prend en charge la création :

- D'une **CA racine** (Root CA)
- De **deux CA intermédiaires** (une pour les machines et une pour les utilisateurs OpenVPN)
- De certificats pour **les serveurs et les clients VPN**

## Prérequis
Avant d'exécuter le script, assurez-vous que **Easy-RSA** est installé sur votre système. Il est généralement disponible dans :

```
/usr/share/easy-rsa/
```

Si ce n'est pas le cas, installez-le sur Debian/Ubuntu avec :
```bash
sudo apt install easy-rsa
```

## Utilisation
### 1️⃣ Lancer le script
Le script s'exécute avec un seul paramètre : le **nom de la PKI**.

```bash
./script_pki.sh <nom_pki>
```

🔹 **Exemple** :
```bash
./script_pki.sh monPKI
```
Cela créera une structure PKI dans `/etc/easy-rsa/monPKI/`.

---

### 2️⃣ Structure des fichiers générés
Après exécution, la structure des fichiers sera la suivante :
```
/etc/easy-rsa/monPKI/
├── root/  (CA racine)
│   ├── pki/
│   ├── issued/
│   ├── private/
│   ├── reqs/
├── machine/ (CA intermédiaire pour machines)
│   ├── pki/
│   ├── certs/
│   ├── reqs/
├── user/ (CA intermédiaire pour utilisateurs OpenVPN)
│   ├── pki/
│   ├── certs/
│   ├── reqs/
```

Chaque répertoire **contient les clés privées, les demandes de certificat et les certificats signés**.

---

### 3️⃣ Générer un certificat pour un serveur ou un utilisateur VPN
Une fois la PKI créée, vous pouvez générer un certificat supplémentaire avec :

```bash
./script_pki.sh <nom_pki> <type> <nom_certificat>
```

- `<type>` : **machine** ou **user**
- `<nom_certificat>` : le nom du certificat

🔹 **Exemple** (Générer un certificat pour un serveur) :
```bash
./script_pki.sh monPKI machine server01
```

🔹 **Exemple** (Générer un certificat pour un utilisateur OpenVPN) :
```bash
./script_pki.sh monPKI user vpnclient01
```

Le certificat généré se trouvera dans :
```
/etc/easy-rsa/monPKI/machine/pki/certs/server01.crt
/etc/easy-rsa/monPKI/user/pki/certs/vpnclient01.crt
```

---

## Fonctionnement du script
Le script suit les étapes suivantes :
1. **Création de la structure PKI** dans `/etc/easy-rsa/<nom_pki>/`
2. **Initialisation de la CA racine**
3. **Création des CA intermédiaires** (machines et utilisateurs VPN)
4. **Génération des clés et certificats**
5. **Signature des certificats intermédiaires** par la Root CA
6. **Stockage des certificats et clés** dans les bons répertoires

Chaque commande Easy-RSA est appelée directement sans changement de répertoire grâce à `--pki-dir`.

---

## Sécurité et bonnes pratiques
✔️ **Ne jamais partager les clés privées !**
✔️ **Stocker la clé de la CA racine hors ligne**
✔️ **Utiliser une durée de vie adaptée pour les certificats (ex: 1 an pour les utilisateurs, 3 ans pour les machines)**
✔️ **Mettre en place un processus de révocation des certificats compromis**

---

## Dépannage
- **Permission refusée ?** Essayez d’exécuter le script avec `sudo`.
- **Easy-RSA introuvable ?** Vérifiez son installation avec :
  ```bash
  ls /usr/share/easy-rsa/
  ```
- **Le certificat n’est pas signé ?** Vérifiez que la CA intermédiaire est bien reconnue par la Root CA.

---

📌 **En suivant ce guide, vous disposez maintenant d'une PKI fonctionnelle pour sécuriser vos services et VPN. 🚀**


