<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Deployment from Odoo

## Support Wildcard

You can support Wildcard domain, like *.mysite.com

Generate manually the certificate :

<!-- [fr] -->
# Déploiement depuis Odoo

## Support Wildcard

Vous pouvez supporter les domaines Wildcard, comme *.mysite.com

Générez manuellement le certificat :

<!-- [common] -->
```bash
sudo certbot certonly --manual --preferred-challenges=dns --server https://acme-v02.api.letsencrypt.org/directory -d "*.mysite.com" -d "*.mysecondsite.com"
```

<!-- [en] -->
Follow instruction. Manually update it each 90 days.

## Single domain per website

This solution will create nginx file and run certbot.

Because Odoo hasn't root password, you can exempt with command

<!-- [fr] -->
Suivez les instructions. Mettez-le à jour manuellement tous les 90 jours.

## Un seul domaine par site web

Cette solution va créer un fichier nginx et exécuter certbot.

Comme Odoo n'a pas de mot de passe root, vous pouvez l'exempter avec la commande

<!-- [common] -->
```bash
visudo
```

<!-- [en] -->
Add this content

<!-- [fr] -->
Ajoutez ce contenu

<!-- [common] -->
```text
odoo ALL=(root) NOPASSWD: /usr/sbin/nginx -t
odoo ALL=(root) NOPASSWD: /usr/bin/systemctl reload nginx
odoo ALL=(root) NOPASSWD: /bin/ln -s * /etc/nginx/sites-enabled/*
odoo ALL=(root) NOPASSWD: /home/odoo/erplibre/script/nginx/deploy_nginx_and_certbot.py
```

<!-- [en] -->
Run script

<!-- [fr] -->
Exécutez le script

<!-- [common] -->
```bash
sudo ./script/nginx/deploy_nginx_and_certbot.py --generate_nginx --run_certbot --domain DOMAINS;DOMAINS
```
