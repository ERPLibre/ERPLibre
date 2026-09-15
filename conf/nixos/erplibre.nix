# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Dépendances système d'ERPLibre, pour NixOS.
#
# Le pendant DÉCLARATIF des quatre install_<distro>_dependency.sh. Ceux-là
# posent des paquets par apt, dnf, pacman ou zypper ; ici rien ne s'installe
# par une commande — ce qui doit rester se déclare, et ce fichier est cette
# déclaration. Un « nixos-rebuild switch » l'applique ; ce qui aurait été posé
# à la main disparaîtrait à la reconstruction suivante.
#
# Déposé en /etc/nixos/erplibre.nix par script/install/install_nixos_dependency.sh,
# qui l'ajoute aussi aux « imports » de la configuration de la machine.
#
# DEUX options portent tout le reste, et sans elles rien de ce dépôt ne
# fonctionne sur NixOS :
#
#   services.envfs.enable — NixOS ne peuple pas /bin ni /usr/bin. Or le
#   Makefile force « SHELL := /bin/bash » (toute cible make échouerait avant
#   sa première ligne) et lib_python_provider.sh ne cherche l'interpréteur du
#   système qu'en /usr/bin/pythonX.Y, jamais dans le PATH. envfs fabrique ces
#   deux répertoires à la volée depuis le PATH : les scripts du dépôt marchent
#   alors sans être réécrits.
#
#   programs.nix-ld.enable — les binaires téléchargés (roues manylinux de pip,
#   CPython précompilé de mise, archives amont) sont liés à
#   /lib64/ld-linux-x86-64.so.2, qui n'existe pas ici. nix-ld le fournit et
#   leur donne les bibliothèques listées plus bas.
{ config, lib, pkgs, ... }:

{
  # ── Ce que /bin, /usr/bin et l'éditeur de liens doivent porter ──────────
  services.envfs.enable = true;

  programs.nix-ld.enable = true;
  # Les bibliothèques que réclament les roues manylinux d'Odoo : psycopg2 veut
  # libpq, lxml veut libxml2/libxslt, cryptography veut openssl, pillow veut
  # zlib et freetype. Une roue qui n'en trouve pas une échoue à l'IMPORT, pas
  # à l'installation — donc bien après, et sans rapport apparent.
  programs.nix-ld.libraries = with pkgs; [
    stdenv.cc.cc.lib
    zlib
    openssl
    libxml2
    libxslt
    libffi
    libpq
    freetype
    fontconfig
    libjpeg
    glib
    expat
    bzip2
    xz
    ncurses
    readline
    sqlite
    util-linux
    openldap
    cyrus_sasl
    cups
    libmysqlclient
  ];

  # ── La base de données ───────────────────────────────────────────────────
  # Le compte de service est SUPERUSER comme sur les autres distributions :
  # ERPLibre crée et détruit des bases (migrations, copies neutralisées), ce
  # qu'un rôle ordinaire ne peut pas faire.
  services.postgresql = {
    enable = true;
    # PostGIS comme les quatre autres scripts de distribution le posent. Ici
    # c'est une extension DU SERVEUR, pas un paquet du système : déclarée
    # ailleurs, elle ne serait pas chargeable par « CREATE EXTENSION ».
    extensions = ps: with ps; [ postgis ];
    ensureUsers = [
      {
        name = "@EL_USER@";
        ensureClauses.superuser = true;
        ensureClauses.createdb = true;
        ensureClauses.login = true;
      }
    ];
  };

  # ── Les outils ───────────────────────────────────────────────────────────
  # python3.12 : la version qu'attend ERPLibre (.python-odoo-version). envfs
  # la rend visible en /usr/bin/python3.12, où lib_python_provider.sh la
  # cherche — ni mise ni pyenv n'ont alors à télécharger quoi que ce soit.
  #
  # Les sorties « .dev » portent les en-têtes : sans elles, une roue absente
  # du dépôt amont devrait se compiler et ne trouverait ni libpq-fe.h ni
  # openssl/ssl.h. Elles ne servent qu'à ce cas, et ne coûtent que du disque.
  environment.systemPackages = with pkgs; [
    python312
    python312Packages.pip
    python312Packages.virtualenv
    uv
    nodejs_22
    postgresql
    postgresql.dev
    git
    gnumake
    gcc
    pkg-config
    openssl
    openssl.dev
    zlib
    zlib.dev
    libxml2
    libxml2.dev
    libxslt
    libxslt.dev
    libffi
    libffi.dev
    # python-ldap n'a PAS de roue amont : il compile, et réclame lber.h
    # (openldap) plus sasl.h. Sans ces sorties « .dev », « poetry install »
    # s'arrête sur « fatal error: lber.h: No such file or directory ».
    openldap
    openldap.dev
    cyrus_sasl
    cyrus_sasl.dev
    # « pg_config » est une dérivation à PART dans nixpkgs : il n'est ni dans
    # postgresql ni dans sa sortie « .dev », et psycopg2 s'arrête sur
    # « Error: pg_config executable not found ».
    postgresql.pg_config
    # pycups veut cups/http.h, mysqlclient veut mysql.h. Les quatre autres
    # scripts posent les mêmes (libcups2-dev, cups-devel,
    # mariadb-connector-c-devel, mariadb-libs).
    cups
    # « cups.lib » porte libcups.so, que « out » n'a pas : sans elle la
    # compilation de pycups PASSE et l'édition de liens échoue sur « -lcups ».
    cups.lib
    cups.dev
    libmysqlclient
    libmysqlclient.dev
    # « less » est le PAGINATEUR ; « nodePackages.less » est lessc, le
    # compilateur LESS des assets Odoo. Les quatre autres scripts les posent
    # tous deux, l'un par le gestionnaire du système et l'autre par « npm
    # install -g » — geste impossible ici, le préfixe npm étant le store, en
    # lecture seule. nixpkgs les porte : ils se déclarent comme le reste.
    less
    nodePackages.less
    nodePackages.rtlcss
    sshpass
    curl
    wget
    unzip
    wkhtmltopdf
  ];

  # Le profil du système ne porte PAS « /include » : la liste par défaut de
  # ce qui y est lié ne contient ni les en-têtes ni les fichiers pkg-config.
  # Sans cette ligne, déclarer une sortie « .dev » ne met rien nulle part, et
  # « fatal error: lber.h: No such file or directory » reste entier.
  environment.pathsToLink = [ "/include" "/lib/pkgconfig" ];

  # Les manuels HTML, et EUX SEULS, sont écartés.
  #
  # NixOS installe la sortie « doc » de CHAQUE paquet du système
  # (environment.extraOutputsToInstall vaut « man info doc »). Celle de
  # CPython n'est pas dans le cache binaire : le premier « nixos-rebuild »
  # la BÂTIT — un Sphinx qui lit puis écrit 3 000 pages. Sur une VM de 4 Go
  # et 4 cœurs, cela domine le temps d'installation ; sur une de 2 Go, la
  # machine cesse de répondre pendant la construction.
  #
  # « documentation.doc » et non « documentation » : les pages de manuel et
  # info restent, elles se lisent depuis un terminal et ne coûtent rien.
  documentation.doc.enable = false;

  # « sessionVariables » et NON « variables » : la seconde n'écrit que dans
  # /etc/set-environment, que seul un shell de CONNEXION lit. Or le
  # déploiement installe par « ssh hôte 'commande' », qui n'en est pas un —
  # la variable y serait vide. sessionVariables passe par pam_env, que toute
  # session traverse, y compris celle-là.
  environment.sessionVariables = {
    CPATH = "/run/current-system/sw/include";
    LIBRARY_PATH = "/run/current-system/sw/lib";
    PKG_CONFIG_PATH = "/run/current-system/sw/lib/pkgconfig";
  };

  # Le port d'Odoo, OUVERT.
  #
  # NixOS active un pare-feu par défaut ; aucune des images cloud des quatre
  # autres distributions n'en active un. Le service écoute bien sur
  # 0.0.0.0:8069 et répond en local, mais l'extérieur ne reçoit RIEN — pas un
  # refus, un silence, donc une attente jusqu'au délai. Ce qui sonde depuis
  # l'hôte conclut « Odoo absent » sur une machine où il tourne, et le journal
  # de l'installation ne porte aucune trace de la cause : elle est dans le
  # pare-feu, pas dans l'application.
  #
  # 8069 SEUL. Le port websocket est configuré à 8072, mais Odoo ne le lie
  # qu'en mode multi-processus, que cette configuration n'emploie pas : rien
  # n'y écoute, et l'ouvrir donnerait un port béant sans service derrière.
  # PostgreSQL n'écoute déjà que sur la boucle locale et n'a rien à ouvrir.
  networking.firewall.allowedTCPPorts = [ 8069 ];

  # Le service ERPLibre, DÉCLARÉ et non écrit.
  #
  # Sur toute autre distribution l'installation dépose l'unité par
  # « tee /etc/systemd/system/erplibre.service ». Ici /etc est généré depuis
  # le store et monté en lecture seule : le tee échoue sur « Read-only file
  # system », et l'installation entière rend 1 à sa dernière étape, après que
  # tout le reste a réussi.
  #
  # « wantedBy » est l'équivalent déclaratif de « systemctl enable » :
  # l'activation par lien symbolique écrirait elle aussi dans /etc.
  #
  # L'interpréteur vient du STORE et non de /bin. /bin et /usr/bin sont ici
  # un montage FUSE d'envfs, et systemd résout l'exécutable d'ExecStart
  # lui-même, hors de portée de ce montage : « /bin/bash » y rend
  # « 203/EXEC, Unable to locate executable ». Avec Restart=always, l'unité
  # boucle alors indéfiniment. La même raison vaut pour /usr/bin/env, donc
  # le shebang de run.sh ne suffirait pas davantage.
  #
  # La première reconstruction déclare le service AVANT qu'ERPLibre ne soit
  # installé, et son démarrage échoue alors — c'est attendu, et c'est
  # exactement le cas que « nixos-rebuild rend 4 » recouvre. L'installation
  # le relance une fois le dépôt en place.
  systemd.services.erplibre = {
    description = "ERPLibre";
    requires = [ "postgresql.service" ];
    after = [ "network.target" "network-online.target" "postgresql.service" ];
    wantedBy = [ "multi-user.target" ];
    # Une unité systemd ne reçoit PAS le PATH d'une session : le sien ne
    # porte que coreutils, findutils, grep, sed et systemd.
    #
    # bash — run.sh lance odoo_bin.sh et lib_db_select.sh, dont le shebang est
    # « #!/usr/bin/env bash ». env est là, bash non : « env: 'bash': No such
    # file or directory », et run.sh s'arrête avant Odoo.
    #
    # python3 — la sonde de réveil tourne AVANT que odoo_bin.sh n'active le
    # venv, donc avec le python du système. Son échec est silencieux
    # (« 2>/dev/null ») : sans elle, la première page ouverte attendrait le
    # chargement du registre sans que rien ne le dise.
    path = with pkgs; [ bash python312 ];
    serviceConfig = {
      Type = "simple";
      User = "@EL_USER@";
      WorkingDirectory = "@EL_DIR@";
      ExecStart = "${pkgs.bash}/bin/bash @EL_DIR@/run.sh";
      Restart = "always";
      RestartSec = 5;
      StandardOutput = "journal+console";
    };
  };
}
