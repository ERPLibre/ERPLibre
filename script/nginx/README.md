
# Deployment from Odoo

## Database backups larger than 1 GiB

The Odoo 18 templates give `/web/database/backup` its own location. With
nginx's default `proxy_max_temp_file_size` of 1024m, a larger backup arrives
cut short: nginx stops reading Odoo past that size, the Odoo worker gives up
after its 2 s socket timeout, and the zip stops at about 1 GiB. That location
spools the whole backup to nginx's temporary directory (`/var/lib/nginx/proxy`
on Debian and Ubuntu), which therefore needs as much free disk as the largest
backup; raise `20480m` past that size. nginx takes `k` or `m` for this
directive, not `g`.

## Support Wildcard

You can support Wildcard domain, like *.mysite.com

Generate manually the certificate :

```bash
sudo certbot certonly --manual --preferred-challenges=dns --server https://acme-v02.api.letsencrypt.org/directory -d "*.mysite.com" -d "*.mysecondsite.com"
```

Follow instruction. Manually update it each 90 days.

## Single domain per website

This solution will create nginx file and run certbot.

Because Odoo hasn't root password, you can exempt with command

```bash
visudo
```

Add this content

```text
odoo ALL=(root) NOPASSWD: /usr/sbin/nginx -t
odoo ALL=(root) NOPASSWD: /usr/bin/systemctl reload nginx
odoo ALL=(root) NOPASSWD: /bin/ln -s * /etc/nginx/sites-enabled/*
odoo ALL=(root) NOPASSWD: /home/odoo/erplibre/script/nginx/deploy_nginx_and_certbot.py
```

Run script

```bash
sudo ./script/nginx/deploy_nginx_and_certbot.py --generate_nginx --run_certbot --domain DOMAINS;DOMAINS
```