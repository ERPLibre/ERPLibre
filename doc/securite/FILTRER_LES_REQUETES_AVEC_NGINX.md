Pour filtrer les accès à Odoo via **Nginx**, en fonction des paramètres `action` et `model` présents dans l'URL, voici une approche structurée :

---

## 📌 **1. Comprendre les paramètres `action` et `model` dans Odoo**
Odoo utilise ces paramètres dans l'URL pour identifier :
- **`model`** : La table ou l'entité dans la base de données (ex. `res.users`, `sale.order`, `account.invoice`, etc.).
- **`action`** : L'action associée à ce modèle (ex. `tree`, `form`, `kanban`, `report`, etc.).

Exemple d'URL dans Odoo :
```
https://odoo.example.com/web?#action=101&model=res.partner&view_type=form
```
- `action=101` → Identifiant d'une action spécifique (définie dans `ir.actions`).
- `model=res.partner` → Modèle correspondant aux partenaires (clients et fournisseurs).
- `view_type=form` → Type de vue (`tree`, `form`, `kanban`, etc.).

---

## 📌 **2. Obtenir la liste des actions et leur correspondance**
Odoo stocke ces actions dans la table `ir.actions.actions`. Pour récupérer toutes les actions définies, exécutez cette requête SQL :

```sql
SELECT id, name, type, res_model FROM ir_actions;
```
Cela retournera les actions disponibles et les modèles auxquels elles sont associées.

### 🔹 **Principaux types d'actions :**
| Type d'action              | Description |
|----------------------------|------------|
| `ir.actions.act_window`    | Ouvre une vue sur un modèle spécifique |
| `ir.actions.report`        | Génère un rapport (PDF, QWeb, etc.) |
| `ir.actions.server`        | Exécute du code côté serveur |
| `ir.actions.client`        | Exécute du code client (ex. rafraîchissement de l'interface) |

---

## 📌 **3. Filtrage via Nginx**
Une fois la liste des actions identifiées, vous pouvez filtrer les accès avec une configuration **Nginx** qui restreint certaines actions. Exemple :

```nginx
server {
    listen 443 ssl;
    server_name odoo.example.com;

    location /web {
        # Filtrage basé sur les paramètres de l'URL
        if ($arg_model ~* "(ir.module.module|ir.model.access|res.users)") {
            return 403;
        }

        if ($arg_action ~* "(admin_dashboard|some_sensitive_action)") {
            return 403;
        }

        proxy_pass http://localhost:8069;
    }
}
```

### 🛑 **Explication de cette configuration :**
- Bloque l'accès à des modèles sensibles (`ir.module.module`, `ir.model.access`, `res.users`).
- Bloque certaines actions spécifiques (ex. `admin_dashboard`).
- Redirige les autres requêtes vers Odoo normalement.

---

## 📌 **4. Méthode alternative : Définir des règles dans Odoo directement**
Plutôt que d'utiliser **Nginx**, vous pouvez aussi restreindre les actions en **modifiant les règles d'accès (`ir.model.access`)** et en personnalisant les contrôleurs Odoo.

Par exemple, pour empêcher certains utilisateurs d'accéder aux actions :
1. **Allez dans** : **Paramètres > Utilisateurs & Entreprises > Groupes**.
2. **Ajoutez une règle d'accès** pour interdire certains modèles à des groupes d'utilisateurs spécifiques.

---

## 📌 **5. Automatiser le filtrage avec un script Python**
Si vous voulez extraire dynamiquement la liste des actions et modèles, utilisez cette commande dans l'environnement Odoo :

```python
# Script à exécuter dans Odoo shell
models = env['ir.actions.actions'].search([])
for action in models:
    print(f"ID: {action.id}, Name: {action.name}, Type: {action.type}, Model: {action.res_model}")
```

Cela vous donnera la liste complète des actions disponibles et les modèles associés.

---

### **Conclusion**
👉 **Solution recommandée :** Un mix entre filtrage **Nginx** et gestion des accès dans Odoo.  
- Utiliser **Nginx** pour **bloquer les accès directs** à certains modèles/actions sensibles.
- Configurer les **permissions utilisateur** dans Odoo pour un contrôle plus précis.

Si tu veux un script Ansible ou un fichier de config Nginx plus avancé, dis-moi ! 🚀
