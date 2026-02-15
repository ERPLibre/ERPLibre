<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Restful

REST (representational state transfer) service in ERPLibre, create a token and get data.

## Installation

In your instance, install module `restful`.

## Example

The example works with application Helpdesk, install module `helpdesk_mgmt`.

You need to run with specified database, and you can run the example script.

<!-- [fr] -->
# Restful

Service REST (representational state transfer) dans ERPLibre, créez un jeton et obtenez des données.

## Installation

Dans votre instance, installez le module `restful`.

## Exemple

L'exemple fonctionne avec l'application Helpdesk, installez le module `helpdesk_mgmt`.

Vous devez exécuter avec une base de données spécifiée, et vous pouvez lancer le script d'exemple.

<!-- [common] -->
```bash
./script/database/db_restore.py --database test
./script/addons/install_addons.sh test restful,helpdesk_mgmt
./run.sh -d test
```

<!-- [en] -->
Test with the example while the server is running. You can add data manually.

<!-- [fr] -->
Testez avec l'exemple pendant que le serveur est en cours d'exécution. Vous pouvez ajouter des données manuellement.

<!-- [common] -->
```bash
./script/restful/restful_example.py
```
