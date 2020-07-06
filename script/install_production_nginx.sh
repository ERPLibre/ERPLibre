#!/usr/bin/env bash

. ./env_var.sh

#--------------------------------------------------
# Install Nginx if needed
#--------------------------------------------------
if [ ${EL_INSTALL_NGINX} = "True" ]; then
  echo -e "\n---- Installing and setting up Nginx ----"
  cat <<EOF > /tmp/nginx${EL_USER}
upstream erplibre${EL_USER} {
  server 127.0.0.1:${EL_PORT};
}
upstream erplibre${EL_USER}chat {
  server 127.0.0.1:${EL_LONGPOLLING_PORT};
}

server {
    listen 80;

    server_name ${EL_WEBSITE_NAME};

    # Add Headers for erplibre proxy mode
    proxy_set_header X-Forwarded-Host \$host;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header X-Real-IP \$remote_addr;
    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-XSS-Protection "1; mode=block";

    # erplibre request log files
    access_log /var/log/nginx/${EL_USER}-access.log;
    error_log /var/log/nginx/${EL_USER}-error.log;

    # Increase proxy buffer size
    proxy_buffers 16 64k;
    proxy_buffer_size 128k;

    proxy_read_timeout 720s;
    proxy_connect_timeout 720s;
    proxy_send_timeout 720s;

    # Force timeouts if the backend dies
    proxy_next_upstream error timeout invalid_header http_500 http_502
    http_503;

    types {
       text/less less;
       text/scss scss;
    }

    # Enable data compression
    gzip on;
    gzip_min_length 1100;
    gzip_buffers 4 32k;
    gzip_types text/css text/less text/plain text/xml application/xml application/json application/javascript application/pdf image/jpeg image/png;
    gzip_vary on;
    client_header_buffer_size 4k;
    large_client_header_buffers 4 64k;
    client_max_body_size 1024M;

    location / {
       proxy_pass http://erplibre${EL_USER};
       # by default, do not forward anything
       proxy_redirect off;
    }

    location /longpolling {
       proxy_pass http://erplibre${EL_USER}chat;
    }

    # cache some static data in memory for 60mins.
    location ~ /[a-zA-Z0-9_-]*/static/ {
       proxy_cache_valid 200 302 60m;
       proxy_cache_valid 404 1m;
       proxy_buffering on;
       expires 864000;
       proxy_pass http://erplibre${EL_USER};
    }
}
EOF

  sudo mv -f /tmp/nginx${EL_USER} /etc/nginx/sites-available/${EL_WEBSITE_NAME}
  sudo ln -fs /etc/nginx/sites-available/${EL_WEBSITE_NAME} /etc/nginx/sites-enabled/${EL_WEBSITE_NAME}
  sudo rm -f /etc/nginx/sites-enabled/default /etc/nginx/sites-available/default
  sudo systemctl restart nginx
  echo "Done! The Nginx server is up and running. Configuration can be found at /etc/nginx/sites-enabled/${EL_WEBSITE_NAME}"
  echo "Run manually certbot : sudo certbot --nginx"
else
  echo "Nginx isn't installed due to choice of the user!"
fi
