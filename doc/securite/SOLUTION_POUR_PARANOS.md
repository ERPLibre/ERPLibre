# 📌 Sécurisation d'ERPLibre : Analyse et Solution

## 🔹 Contexte

Un client exprime des préoccupations quant à la sécurité de son système. Son raisonnement est basé sur l'idée qu'un site web pourrait être compromis par des attaquants ou découvert par des compétiteurs. Il envisage une application mobile comme solution pour éviter ces risques.

Nous avons analysé cette crainte et conclu que l'option d'une application mobile n'apporte pas une sécurité supplémentaire significative. Nous proposons plutôt une architecture robuste garantissant **sécurité, confidentialité et contrôle d'accès**.

---

## 🔹 Solution Proposée

Nous mettons en place une architecture qui protège ERPLibre en **limitant et sécurisant strictement l'accès aux utilisateurs autorisés**.

### **🔐 Composants Sécurisés**

1️⃣ **NGINX** *(Reverse Proxy sécurisé)*

- Agit comme un **bouclier** entre Internet et ERPLibre.
- Protège contre les attaques courantes (DDoS, injections, etc.).
- Applique des règles de filtrage et de sécurité strictes.

2️⃣ **Keycloak** *(Gestion centralisée de l'authentification et du MFA)*

- **Fédération des identités** : unifie les connexions à plusieurs services.
- **Gestion du MFA (OTP)** : renforce la sécurité avec une authentification à deux facteurs.
- **Compatible avec OIDC/SAML** : permet une extension vers d'autres services futurs.

3️⃣ **ERPLibre** *(Accessible uniquement aux utilisateurs authentifiés)*

- Derrière NGINX, il n'est **jamais exposé directement à Internet**.
- Ne gère pas l’authentification directement, tout passe par Keycloak.

4️⃣ **OpenVPN** *(Accès restreint aux clients légitimes)*

- Seuls les utilisateurs connectés via **VPN sécurisé** peuvent accéder à ERPLibre.
- Protège contre l’exposition directe sur Internet.

5️⃣ **OTP (MFA) obligatoire**

- Keycloak impose une **authentification forte** pour garantir que seuls les utilisateurs autorisés accèdent à la plateforme.

---

## 🔹 Pourquoi cette solution ?

### **❌ Pourquoi une application mobile ne résout pas le problème ?**

- Une application mobile communique avec un serveur, tout comme un site web.
- Si ce serveur n’est pas sécurisé, l’application **peut être compromise**.
- Une application **peut être analysée** (reverse engineering) et exposer des vulnérabilités.

### **✅ Pourquoi notre solution est plus robuste ?**

- **ERPLibre est caché derrière un Reverse Proxy sécurisé**.
- **Aucune connexion directe possible sans passer par le VPN**.
- **Keycloak assure une authentification centralisée avec MFA**.
- **Même en cas de vol de mot de passe, l’OTP protège l’accès**.
- **L’attaquant devrait voler et hacker l’appareil d’un utilisateur légitime pour réussir.**
- **La solution est évolutive** et compatible avec d’autres services.

---

## 🔹 Schéma de l’architecture sécurisée

```plaintext
[Utilisateur] --(VPN)-- [NGINX Reverse Proxy] --(OIDC)-- [Keycloak (MFA)] --(Validation)-- [ERPLibre]
```

- L’utilisateur doit **obligatoirement** passer par OpenVPN.
- Ensuite, il doit **s’authentifier avec Keycloak** (MFA obligatoire).
- Une fois authentifié, il reçoit un **token sécurisé** permettant d’accéder à ERPLibre.
- **Aucun accès direct à ERPLibre depuis Internet n’est possible.**

---

## 🔹 Conclusion

La sécurité ne réside **pas** dans le choix entre une application mobile et un site web, mais dans **la gestion des accès et de l’authentification**. Notre architecture offre **une solution robuste, cloisonnée et évolutive** qui protège contre les intrusions et les compétiteurs.

Nous sommes convaincus que cette approche garantit **une tranquillité d’esprit totale** pour notre client, tout en lui permettant d’utiliser ERPLibre en toute sécurité. 🚀


