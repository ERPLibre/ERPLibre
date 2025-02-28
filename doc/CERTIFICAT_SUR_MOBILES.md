# **📌 Étapes pour configurer les certificats sur iPhone et Android**
### **🔹 Objectif :**
- **Importer le certificat client OpenVPN** dans l’appareil.
- **S’assurer qu’il est utilisé automatiquement pour les connexions HTTPS** vers NGINX.
- **Éviter que l’utilisateur doive le sélectionner manuellement à chaque connexion**.

---

## **1️⃣ Exporter et préparer le certificat client OpenVPN**
Sur ton **serveur OpenVPN**, localise le certificat et la clé privée du client (chaque employé a un certificat unique) :
```bash
cd /etc/openvpn/easy-rsa/pki
ls -l issued/ private/
```

Pour un employé nommé `user1`, tu auras ces fichiers :
- Certificat client : `issued/user1.crt`
- Clé privée client : `private/user1.key`
- CA OpenVPN : `ca.crt`

Maintenant, crée un **fichier PKCS#12 (.p12)** qui contient le certificat client, la clé privée et la CA :
```bash
openssl pkcs12 -export -out user1.p12 -inkey private/user1.key -in issued/user1.crt -certfile ca.crt -name "VPN Auth" -passout pass:mypass
```
📌 **Note :** Remplace `mypass` par un mot de passe sécurisé (ou demande à l’employé de le taper lors de l’importation sur son appareil).

---

## **2️⃣ Installer le certificat sur un iPhone (iOS)**
### **📌 Étapes manuelles**
1. **Envoyer le fichier .p12** à l’utilisateur :
   - Par e-mail sécurisé
   - Via AirDrop (Mac → iPhone)
   - Téléchargement via un lien HTTPS sécurisé
2. **Sur l’iPhone :**
   - Ouvrir le fichier `.p12`
   - Saisir le mot de passe `mypass`
   - Installer le certificat dans **Réglages → Général → Profils**
3. **Activer l’utilisation du certificat dans Safari**
   - Aller dans **Réglages → VPN et Réseau → Wi-Fi**  
   - Sélectionner le Wi-Fi de l’entreprise  
   - Cliquer sur **Configurer un proxy** → Automatique (ajouter l’URL du proxy NGINX si nécessaire)  
   - Activer **Authentification par certificat** et choisir **VPN Auth**  

✅ **Maintenant, l’iPhone présentera automatiquement le bon certificat à NGINX** lors de la connexion.

---

## **3️⃣ Installer le certificat sur un Android**
### **📌 Étapes manuelles**
1. **Envoyer le fichier `.p12` à l’utilisateur** (via e-mail sécurisé ou USB).
2. **Sur l’Android :**
   - Aller dans **Paramètres → Sécurité → Certificats → Installer un certificat**  
   - Sélectionner **Certificat utilisateur** et choisir le fichier `.p12`  
   - Entrer le mot de passe `mypass`  
   - Renommer le certificat si besoin (**VPN Auth**)
3. **Associer le certificat aux connexions Wi-Fi et HTTPs**
   - Aller dans **Paramètres → Réseau & Internet → Wi-Fi**
   - Sélectionner le Wi-Fi de l’entreprise
   - Modifier les paramètres avancés et choisir **Authentification avec certificat**
   - Sélectionner **VPN Auth**

✅ **Désormais, l’Android utilisera automatiquement le bon certificat pour les connexions à NGINX.**

---

## **4️⃣ Automatisation avec un MDM (JAMF, Mosyle, Intune)**
Si tu as un **MDM** en place, tu peux **automatiser l’installation du certificat sur tous les iPhones et Androids** :
- Déployer le **profil de configuration** avec le certificat `.p12`
- Assigner automatiquement le certificat aux connexions Wi-Fi et VPN
- Forcer l’utilisation du proxy d’entreprise

💡 **Avec JAMF Pro (iOS) ou Intune (Android), le certificat est installé et utilisé automatiquement.** L’utilisateur n’a rien à faire.

---

# **🚀 Conclusion**
✅ **Exporter les certificats OpenVPN en format `.p12`**  
✅ **Importer le certificat sur iOS et Android**  
✅ **Associer le certificat aux connexions Wi-Fi et HTTPS**  
✅ **Option MDM pour une installation automatique**  

👉 **Tu veux que je t’écrive un script Ansible ou Bash pour automatiser la création et l’envoi des certificats `.p12` ?** 😊
