# Restful

REST (representational state transfer) service in ERPLibre, create a token and get data.

## Installation

In your instance, install module `restful`.

## Example

The example works with application Helpdesk, install module `helpdesk_mgmt`.

You need to run with specified database, and you can run the example script.

```bash
./script/database/db_restore.py --database test
./script/addons/install_addons.sh test restful,helpdesk_mgmt
./run.sh -d test
```

Test with the example while the server is running. You can add data manually.

```bash
./script/restful/restful_example.py
```
