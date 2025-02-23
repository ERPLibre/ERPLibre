# 🔐 Interface de Gestion des Accès

## 📌 Introduction

La gestion des accès aux systèmes critiques est une nécessité en cybersécurité. Pour permettre au client de **contrôler lui-même** les accès des utilisateurs, nous proposons une **Interface de Gestion des Accès** qui offre un moyen rapide et centralisé de **désactiver, suspendre ou révoquer les accès** en cas de nécessité (départ d’un employé, compromission de compte, etc.).

Cette interface permet :
- ✅ **Révocation immédiate** des accès d’un utilisateur en un clic.
- ✅ **Contrôle centralisé** des accès aux différents services.
- ✅ **Réduction des risques** en limitant la fenêtre d’attaque d’un compte compromis.
- ✅ **Traçabilité et journalisation** des actions de gestion des accès.

---

## **🔹 Fonctionnalités de l’Interface de Gestion des Accès**

### 📌 **Désactivation instantanée via Keycloak**
L’interface permet de **désactiver immédiatement un utilisateur** dans Keycloak :

```bash
curl -X PUT "https://keycloak.chezlepro.ca/auth/admin/realms/mon_realm/users/{user_id}" \
     -H "Authorization: Bearer {access_token}" \
     -H "Content-Type: application/json" \
     -d '{"enabled": false}'
```
✅ Empêche toute nouvelle connexion de l’utilisateur.
✅ Révocation automatique des sessions actives.

### 📌 **Révocation de l’accès VPN (OpenVPN ou WireGuard)**

➡ **OpenVPN** :
```bash
sudo ./easyrsa revoke {username}
sudo systemctl restart openvpn
```
➡ **WireGuard** : Suppression de la clé publique de l’utilisateur de la configuration VPN.

✅ Coupe immédiatement la connexion de l’utilisateur au réseau interne.

### 📌 **Désactivation de l’accès à ERPLibre**

Si ERPLibre est intégré avec Keycloak, **la désactivation de Keycloak suffit**.
Si ERPLibre gère les comptes localement, un script SQL peut être utilisé pour désactiver l’utilisateur.

```sql
UPDATE users SET active = 0 WHERE username = '{username}';
```
✅ Garantit que l’utilisateur ne peut plus accéder aux ressources ERP.

### 📌 **Journalisation et notification**
L’interface logge chaque action de révocation et peut envoyer des **notifications aux administrateurs** :

➡ **Stockage dans un fichier log sécurisé.**
➡ **Envoi d’une alerte par e-mail ou webhook à l’équipe IT.**

---

## **🔹 Interface Utilisateur**

Nous proposons une **interface web simplifiée** permettant de :
- **Sélectionner un utilisateur** via une liste déroulante.
- **Désactiver ses accès** en un seul clic.
- **Consulter l’historique des désactivations**.

L’interface pourrait être intégrée à **Nextcloud, Keycloak, ou un tableau de bord dédié**, et sécurisée avec :
- **Authentification forte (MFA) pour les administrateurs.**
- **Restrictions d’accès aux personnes autorisées.**
- **Journalisation des actions pour assurer une traçabilité complète.**

---

## **🔹 Avantages de cette Interface pour le Client**

✅ **Contrôle total** : Le client peut gérer lui-même les accès, sans dépendre d’un tiers.  
✅ **Réactivité accrue** : Réaction immédiate en cas de besoin, réduisant les risques.  
✅ **Simplicité d’usage** : Interface intuitive, utilisable sans connaissances techniques avancées.  
✅ **Sécurité renforcée** : Désactivation en cascade pour éviter les points de faiblesse.

---

## **🚀 Conclusion**

L’**Interface de Gestion des Accès** est une solution efficace et sécurisée qui permet au client de **garder un contrôle total sur la gestion des comptes utilisateurs**. Elle assure **une réaction rapide** en cas de menace et garantit **une traçabilité complète** des actions prises.

Cette interface représente **un élément clé** dans une stratégie de cybersécurité proactive, assurant la **protection des données et des systèmes critiques** tout en offrant au client **autonomie et flexibilité**.


