### **📌 Mutual TLS (mTLS) avec Nginx pour sécuriser l'accès à l'ERP**
L'idée du **mutual TLS (mTLS)** est d'imposer une **authentification par certificat client** au niveau du proxy **Nginx** pour **filtrer les accès à ton ERP**.

---

## **🔒 Comment ça fonctionne ?**
1. **Chaque machine autorisée reçoit un certificat machine signé par ta PKI**.
2. **Le client OpenVPN utilise ce certificat pour s'authentifier auprès du VPN**.
3. **Nginx est configuré pour n'accepter que les connexions HTTPS provenant de clients ayant un certificat machine valide**.
4. **Si un client n'a pas de certificat valide, il ne peut pas accéder à la page de login de l'ERP**.

---

## **📌 Étape 1 : Générer les certificats pour mTLS**
Tu peux réutiliser les certificats générés par Easy-RSA :

- **CA Root** : `/etc/openvpn/pki/ca.crt`
- **Certificat machine** : `/etc/openvpn/pki/issued/client_machine.crt`
- **Clé privée de la machine** : `/etc/openvpn/pki/private/client_machine.key`

Chaque machine qui se connecte via VPN aura **son propre certificat machine**, ce qui garantit que **seules les machines autorisées peuvent voir la page de login de l'ERP**.

---

## **📌 Étape 2 : Configurer Nginx pour activer le mutual TLS**
### **1️⃣ Ajouter la configuration du proxy avec mTLS**
Ajoute cette configuration dans `/etc/nginx/sites-available/erp.conf` :
```nginx
server {
    listen 443 ssl;
    server_name erp.example.com;

    # Certificat du serveur (SSL)
    ssl_certificate /etc/ssl/certs/nginx-erp.crt;
    ssl_certificate_key /etc/ssl/private/nginx-erp.key;

    # Activer le Mutual TLS
    ssl_client_certificate /etc/openvpn/pki/ca.crt;
    ssl_verify_client on;

    location / {
        proxy_pass http://localhost:8000; # URL interne de l'ERP
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Host $host;
    }

    error_page 403 = @forbidden;
}

server {
    listen 80;
    server_name erp.example.com;
    return 301 https://$host$request_uri;
}

location @forbidden {
    return 403;
}
```

### **2️⃣ Redémarrer Nginx**
```sh
systemctl restart nginx
```

---

## **📌 Étape 3 : Tester l'accès**
### **🚀 Un client autorisé :**
✅ Si la machine a un certificat valide (`client_machine.crt` signé par ta CA), Nginx l'acceptera et elle pourra accéder à **l'ERP**.

### **🚫 Un client non autorisé :**
❌ Si la machine **n'a pas de certificat valide**, Nginx rejettera la connexion avec une **erreur 403 (Forbidden)**.

---

## **📌 Résumé**
✅ **Seules les machines ayant un certificat machine valide pourront accéder à l’ERP**.  
✅ **Nginx filtre les connexions grâce au Mutual TLS (mTLS)**.  
✅ **Tu contrôles totalement qui peut se connecter** à l'ERP via OpenVPN et mTLS.  

---

💡 **Tu veux que j’ajoute cette configuration Nginx dans ton playbook Ansible pour tout automatiser ?** 🚀
