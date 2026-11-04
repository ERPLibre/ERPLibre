
# Installation de Selenium

Les scripts tournent dans le venv d'outillage, `.venv.erplibre`, qui contient
déjà `selenium`. L'enregistreur vidéo a besoin de PyGObject, compilé contre
les bibliothèques système ci-dessous ;
`script/install/install_debian_dependency.sh` les installe sur Debian et
Ubuntu.

```bash
sudo apt install libcairo2-dev python3-dev pkg-config libxt-dev libgirepository-2.0-dev ffmpeg

.venv.erplibre/bin/pip install -r script/selenium/requirements.txt
```

`requirements.txt` épingle PyGObject, qui tire pycairo. PyGObject 3.50 et
plus se compile contre girepository-2.0 et exige GLib 2.80 : Debian 13 et
Ubuntu 24.04 l'ont, Debian 12 non. L'enregistrement vidéo n'y est pas
disponible ; n'installez que `webdriver_manager`, dont se sert le pilote
Chrome. `ffmpeg` convertit les enregistrements en MP4.

geckodriver ne demande aucune installation : Selenium Manager, livré avec
`selenium`, le télécharge dans `~/.cache/selenium` au premier usage.

Enregistreur vidéo : https://github.com/szemate/pyselenium-video-recorder