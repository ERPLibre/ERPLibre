
# Restful

Service REST (representational state transfer) dans ERPLibre, créez un jeton et obtenez des données.

## Installation

Dans votre instance, installez le module `restful`.

## Exemple

L'exemple fonctionne avec l'application Helpdesk, installez le module `helpdesk_mgmt`.

Vous devez exécuter avec une base de données spécifiée, et vous pouvez lancer le script d'exemple.

```bash
./script/database/db_restore.py --database test
./script/addons/install_addons.sh test restful,helpdesk_mgmt
./run.sh -d test
```

Testez avec l'exemple pendant que le serveur est en cours d'exécution. Vous pouvez ajouter des données manuellement.

```bash
./script/restful/restful_example.py
```