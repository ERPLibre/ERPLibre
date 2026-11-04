<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Selenium Installation

The scripts run in the tooling venv, `.venv.erplibre`, which already holds
`selenium`. The video recorder needs PyGObject, built against the system
libraries below; `script/install/install_debian_dependency.sh` installs them
on Debian and Ubuntu.

<!-- [fr] -->
# Installation de Selenium

Les scripts tournent dans le venv d'outillage, `.venv.erplibre`, qui contient
déjà `selenium`. L'enregistreur vidéo a besoin de PyGObject, compilé contre
les bibliothèques système ci-dessous ;
`script/install/install_debian_dependency.sh` les installe sur Debian et
Ubuntu.

<!-- [common] -->
```bash
sudo apt install libcairo2-dev python3-dev pkg-config libxt-dev libgirepository-2.0-dev ffmpeg

.venv.erplibre/bin/pip install -r script/selenium/requirements.txt
```

<!-- [en] -->
`requirements.txt` pins PyGObject, which pulls pycairo. PyGObject 3.50 and
later builds against girepository-2.0 and requires GLib 2.80: Debian 13 and
Ubuntu 24.04 have it, Debian 12 does not. There, video recording is not
available; install only `webdriver_manager`, which the Chrome driver uses.
`ffmpeg` converts the recordings to MP4.

geckodriver needs no installation: Selenium Manager, shipped with `selenium`,
downloads it into `~/.cache/selenium` on first use.

Video recorder: https://github.com/szemate/pyselenium-video-recorder

<!-- [fr] -->
`requirements.txt` épingle PyGObject, qui tire pycairo. PyGObject 3.50 et
plus se compile contre girepository-2.0 et exige GLib 2.80 : Debian 13 et
Ubuntu 24.04 l'ont, Debian 12 non. L'enregistrement vidéo n'y est pas
disponible ; n'installez que `webdriver_manager`, dont se sert le pilote
Chrome. `ffmpeg` convertit les enregistrements en MP4.

geckodriver ne demande aucune installation : Selenium Manager, livré avec
`selenium`, le télécharge dans `~/.cache/selenium` au premier usage.

Enregistreur vidéo : https://github.com/szemate/pyselenium-video-recorder
