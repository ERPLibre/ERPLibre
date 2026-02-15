
# Déploiement depuis Odoo

## Support Wildcard

Vous pouvez supporter les domaines Wildcard, comme *.mysite.com

Générez manuellement le certificat :

```bash
sudo certbot certonly --manual --preferred-challenges=dns --server https://acme-v02.api.letsencrypt.org/directory -d "*.mysite.com" -d "*.mysecondsite.com"
```

Suivez les instructions. Mettez-le à jour manuellement tous les 90 jours.

## Un seul domaine par site web

Cette solution va créer un fichier nginx et exécuter certbot.

Comme Odoo n'a pas de mot de passe root, vous pouvez l'exempter avec la commande

```bash
visudo
```

Ajoutez ce contenu

```text
odoo ALL=(root) NOPASSWD: /usr/sbin/nginx -t
odoo ALL=(root) NOPASSWD: /usr/bin/systemctl reload nginx
odoo ALL=(root) NOPASSWD: /bin/ln -s * /etc/nginx/sites-enabled/*
odoo ALL=(root) NOPASSWD: /home/odoo/erplibre/script/nginx/deploy_nginx_and_certbot.py
```

Exécutez le script

```bash
sudo ./script/nginx/deploy_nginx_and_certbot.py --generate_nginx --run_certbot --domain DOMAINS;DOMAINS
```