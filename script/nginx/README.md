# Deployment from Odoo

Because Odoo hasn't root password, you can exempt with command

```bash
visudo
```

Add this content

```text
odoo ALL=(root) NOPASSWD: /usr/sbin/nginx -t
odoo ALL=(root) NOPASSWD: /usr/bin/systemctl reload nginx
odoo ALL=(root) NOPASSWD: /bin/ln -s * /etc/nginx/sites-enabled/*
odoo ALL=(root) NOPASSWD: /home/odoo/erplibre/script/nginx/deploy_nginx_and_cerbot.py
```

Run script

```bash
sudo ./script/nginx/deploy_nginx_and_cerbot.py --generate_nginx --run_certbot --domain DOMAINS;DOMAINS
```
