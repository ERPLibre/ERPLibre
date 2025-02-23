
Spécifications de l'infra de clés privée :

---

## **1. Certificat de la CA racine (Root CA)**
- **Algorithme de clé** : **ED25519** (plus sûr et performant que RSA)
- **Format** : X.509 v3
- **Validité** : **10 ans** (modifiable)
- **Nom commun (CN)** : `<nom_pki> Root CA`
- **Extensions** :
  - `Basic Constraints: CA:TRUE`
  - `Key Usage: Certificate Sign, CRL Sign`
  - `Subject Key Identifier (SKI)`

---

## **2. Certificat de la CA intermédiaire pour les machines**
- **Algorithme de clé** : **ED25519**
- **Format** : X.509 v3
- **Validité** : **5 ans** (modifiable)
- **Nom commun (CN)** : `<nom_pki> Machine CA`
- **Extensions** :
  - `Basic Constraints: CA:TRUE`
  - `Key Usage: Certificate Sign, CRL Sign`
  - `Authority Key Identifier (AKI) pointant vers la CA racine`
  - `Subject Key Identifier (SKI)`

---

## **3. Certificat de la CA intermédiaire pour les utilisateurs OpenVPN**
- **Algorithme de clé** : **ED25519**
- **Format** : X.509 v3
- **Validité** : **5 ans** (modifiable)
- **Nom commun (CN)** : `<nom_pki> User CA`
- **Extensions** :
  - `Basic Constraints: CA:TRUE`
  - `Key Usage: Certificate Sign, CRL Sign`
  - `Authority Key Identifier (AKI) pointant vers la CA racine`
  - `Subject Key Identifier (SKI)`

---

## **4. Certificats finaux (Machines et Clients VPN)**
### 🔹 **Certificats pour les machines (ex : serveurs, services)**
- **Algorithme de clé** : **ED25519**
- **Format** : X.509 v3
- **Validité** : **3 ans** (modifiable)
- **Nom commun (CN)** : `nom_du_serveur`
- **Key Usage** :
  - `Digital Signature`
  - `Key Encipherment`
  - `TLS Web Server Authentication`
- **SAN (Subject Alternative Names)** :
  - Nom DNS et/ou adresse IP du serveur

### 🔹 **Certificats pour les utilisateurs OpenVPN**
- **Algorithme de clé** : **ED25519**
- **Format** : X.509 v3
- **Validité** : **1 an** (modifiable)
- **Nom commun (CN)** : `nom_utilisateur`
- **Key Usage** :
  - `Digital Signature`
  - `Key Encipherment`
  - `TLS Web Client Authentication`
- **Extensions** :
  - `Extended Key Usage: TLS Web Client Authentication`
  - `Authority Key Identifier (AKI) pointant vers la CA intermédiaire utilisateur`
  - `Subject Key Identifier (SKI)`

---

## **Pourquoi ED25519 au lieu de RSA ?**
- **Sécurité accrue** : ED25519 offre une résistance aux attaques quantiques bien meilleure que **RSA 2048**.
- **Performance optimisée** : Plus rapide que RSA pour les signatures et la vérification.
- **Taille de clé plus petite** : 256 bits pour ED25519 vs 2048 bits pour RSA, tout en offrant une **meilleure sécurité**.

---

## **5. Autorité de révocation des certificats (CRL)**
- **Liste de révocation générée** pour chaque CA intermédiaire.
- **Fichier CRL** mis à jour pour invalider les certificats compromis.
- **Intégration facile avec OpenVPN et serveurs web**.

---

### **Personnalisation**
Ces paramètres peuvent être modifiés dans **Easy-RSA** en ajustant les fichiers de configuration (`vars`).

---
