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
  ];

  # ── La base de données ───────────────────────────────────────────────────
  # Le compte de service est SUPERUSER comme sur les autres distributions :
  # ERPLibre crée et détruit des bases (migrations, copies neutralisées), ce
  # qu'un rôle ordinaire ne peut pas faire.
  services.postgresql = {
    enable = true;
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
    less
    curl
    wget
    unzip
    wkhtmltopdf
  ];

  # Un compilateur lancé hors d'un nix-shell ne cherche les en-têtes ni les
  # bibliothèques dans le profil du système : ces trois variables les lui
  # donnent, et c'est ce qui permet à « poetry install » de bâtir ce qui n'a
  # pas de roue.
  environment.variables = {
    CPATH = "/run/current-system/sw/include";
    LIBRARY_PATH = "/run/current-system/sw/lib";
    PKG_CONFIG_PATH = "/run/current-system/sw/lib/pkgconfig";
  };
}
