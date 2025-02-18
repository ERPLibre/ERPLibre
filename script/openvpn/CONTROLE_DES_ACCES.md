
---

### **1. Architecture**
- Un **serveur OpenVPN** avec **Easy-RSA** pour gérer PKI.
- Deux **CAs intermédiaires** :
  - Une **CA machines** pour certifier le serveur et les équipements.
  - Une **CA utilisateurs** pour certifier les clients OpenVPN.
- Des **certificats utilisateurs** pour chaque appareil ou utilisateur mobile.

---

### **2. Déploiement**
#### **1. Installer Easy-RSA et OpenVPN**
Sur le serveur :
```bash
sudo apt update && sudo apt install -y openvpn easy-rsa
```

#### **2. Créer la PKI et les CAs intermédiaires**
Créer une CA principale et deux CAs intermédiaires :

```bash
# Initialiser Easy-RSA
mkdir -p /etc/openvpn/easy-rsa
cd /etc/openvpn/easy-rsa
cp -r /usr/share/easy-rsa/* .

# Initialiser la CA principale
./easyrsa init-pki
./easyrsa build-ca nopass
```
Ensuite, créer les **CAs intermédiaires** :
```bash
# CA pour les machines
./easyrsa build-ca nopass sub-ca-machines

# CA pour les utilisateurs
./easyrsa build-ca nopass sub-ca-utilisateurs
```
Les **CAs intermédiaires** sont signées par la **CA principale**.

#### **3. Générer le certificat du serveur**
```bash
./easyrsa build-server-full serveur-openvpn nopass
```
Puis copier les fichiers sur `/etc/openvpn/` :
```bash
cp pki/issued/serveur-openvpn.crt /etc/openvpn/
cp pki/private/serveur-openvpn.key /etc/openvpn/
cp pki/ca.crt /etc/openvpn/
```

#### **4. Générer des certificats clients (utilisateurs mobiles)**
Chaque utilisateur aura son propre certificat :
```bash
./easyrsa build-client-full utilisateur1 nopass
./easyrsa build-client-full utilisateur2 nopass
```
Tu peux forcer la révocation en cas de besoin.

---

### **3. Configuration OpenVPN**
Dans `/etc/openvpn/server.conf` :
```ini
port 1194
proto udp
dev tun
ca /etc/openvpn/ca.crt
cert /etc/openvpn/serveur-openvpn.crt
key /etc/openvpn/serveur-openvpn.key
dh none
tls-auth /etc/openvpn/ta.key 0
cipher AES-256-GCM
auth SHA256
server 10.8.0.0 255.255.255.0
ifconfig-pool-persist ipp.txt
keepalive 10 120
persist-key
persist-tun
status openvpn-status.log
verb 3
```
Active la **revocation list** :
```bash
./easyrsa gen-crl
cp pki/crl.pem /etc/openvpn/
```
Ajoute à `server.conf` :
```ini
crl-verify /etc/openvpn/crl.pem
```

---

### **4. Gestion des Accès**
- Un certificat = **un accès**
- Pour **révoquer un utilisateur**, exécuter :
  ```bash
  ./easyrsa revoke utilisateur1
  ./easyrsa gen-crl
  cp pki/crl.pem /etc/openvpn/
  ```
- **Mise en place d’une expiration automatique** (optionnel) :
  ```bash
  ./easyrsa build-client-full utilisateur1 nopass valid-days=365
  ```

---

### **5. Distribution des Certificats**
Chaque utilisateur doit recevoir ces fichiers :
- `utilisateur1.crt`
- `utilisateur1.key`
- `ca.crt`
- `ta.key`
- `client.ovpn`

Exemple de fichier `client.ovpn` :
```ini
client
dev tun
proto udp
remote MON_SERVEUR 1194
resolv-retry infinite
nobind
persist-key
persist-tun
ca ca.crt
cert utilisateur1.crt
key utilisateur1.key
tls-auth ta.key 1
cipher AES-256-GCM
auth SHA256
verb 3
```

---

### **6. Automatisation**
Un **script Ansible** peut :
- Gérer la création et distribution des certificats
- Révoquer un utilisateur automatiquement
- Mettre à jour `crl.pem`

Si besoin, on peut l'automatiser avec **un portail web** utilisant **EASY-RSA API** pour la gestion des certificats.

---

### **7. Sécurisation Supplémentaire**
- **Utiliser OpenVPN 2.5+** avec `tls-crypt`
- **Forcer l’authentification double facteur** (ex: FreeOTP + plugin PAM)
- **Bloquer le pays d'origine des connexions** avec **iptables**

---

### **Résumé**
✅ PKI avec **deux CAs intermédiaires**  
✅ Gestion **certificat par utilisateur**  
✅ Révocation et CRL automatique  
✅ Configuration **sécurisée**  
✅ Option d’automatisation avec **Ansible / portail web**

---

