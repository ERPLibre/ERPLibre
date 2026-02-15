
# Windows 10 version 2004 et plus ou 11 - publication et developpement

Un guide pour configurer un espace de travail et executer ERPLibre sur Windows 10 version 2004 et plus ou Windows 11. Il existe deux methodes d'installation, une automatique et l'autre manuelle.

**"WSL2 Ubuntu 22.04" sera designe par "WSL2"**

**"PyCharm Professional" sera designe par "PyCharm"**

## Installer WSL2

Executez Powershell avec les droits administrateur et lancez la commande suivante :

```bash
wsl --install -d Ubuntu-22.04
```

Si vous avez des difficultes a ouvrir Powershell avec les droits administrateur, appuyez sur `Windows + R`, entrez la ligne suivante et appuyez sur `OK`. Les droits administrateur vous seront automatiquement demandes.

```bash
powershell.exe
```

### Depannage - Optionnel
Si vous rencontrez des problemes, activez les options de virtualisation dans le BIOS si disponibles (hyper-v, vt-x, etc). Recherchez `Activer ou desactiver des fonctionnalites Windows` dans la barre de recherche Windows et assurez-vous que `Sous-systeme Windows pour Linux` est active avant de redemarrer votre machine.

Vous pouvez aussi essayer ces commandes powershell :

```bash
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
wsl --set-default-version 2
```

Telechargez et installez le dernier package de mise a jour du noyau Linux de Microsoft avec le [lien](https://wslstorestorage.blob.core.windows.net/wslblob/wsl_update_x64.msi) suivant :

```bash
https://wslstorestorage.blob.core.windows.net/wslblob/wsl_update_x64.msi
```

N'executez cette commande qu'en dernier recours car elle peut casser d'autres machines virtuelles :

```bash
bcdedit /set hypervisorlaunchtype auto
```

### Autres methodes d'installation pour WSL2

Executez Powershell avec les droits administrateur et lancez la commande suivante :

```bash
curl.exe -L -o ubuntu-2004.appx https://aka.ms/wslubuntu2004
```

Executez Powershell avec les droits administrateur et lancez les commandes suivantes :

```bash
Invoke-WebRequest -Uri https://aka.ms/wslubuntu2004 -OutFile Ubuntu.appx -UseBasicParsing
Add-AppxPackage .\Ubuntu.appx
```

Installez WSL2 depuis le Microsoft Store avec le [lien](https://apps.microsoft.com/store/detail/ubuntu-22041-lts/9PN20MSR04DW) suivant :

```bash
https://apps.microsoft.com/store/detail/ubuntu-22041-lts/9PN20MSR04DW
```

## Configurer WSL2 pour ERPLibre

Une fois WSL2 installe correctement, redemarrez votre ordinateur.

### Vous pouvez ouvrir votre Ubuntu de plusieurs facons :

* Recherchez "Ubuntu" en cliquant sur la touche Windows
* [Telechargez le Terminal Windows depuis le Microsoft Store](https://apps.microsoft.com/store/detail/windows-terminal/9N0DX20HK701)

Si vous utilisez le Terminal Windows, vous n'avez qu'a cliquer sur la petite fleche a cote du signe + et vous verrez Ubuntu.

![image](https://user-images.githubusercontent.com/59217113/230186101-579d8a5b-0825-404f-bd28-3642adce0948.png)


### Configurer une interface graphique pour votre Ubuntu

1. Mettre a jour votre Ubuntu

```bash
sudo apt-get update -y && sudo apt-get upgrade -y
```

2. Installer le bureau XFCE4

```bash
sudo apt install -y xrdp xfce4 xfce4-goodies
```

3. Configurer le bureau

```bash
sudo cp /etc/xrdp/xrdp.ini /etc/xrdp/xrdp.ini.bak
sudo sed -i 's/3389/3390/g' /etc/xrdp/xrdp.ini
sudo sed -i 's/max_bpp=32/#max_bpp=32\nmax_bpp=128/g' /etc/xrdp/xrdp.ini
sudo sed -i 's/xserverbpp=24/#xserverbpp=24\nxserverbpp=128/g' /etc/xrdp/xrdp.ini
echo xfce4-session > ~/.xsession
```

4. Configurer la connexion Bureau a distance

```bash
sudo nano /etc/xrdp/startwm.sh
```

Commentez ces lignes avec un #

```bash
test -x /etc/X11/Xsession && exec /etc/X11/Xsession
exec /bin/sh /etc/X11/Xsession
```

Ajoutez cette ligne a la fin du fichier

```bash
startxfce4
```

Quittez avec Ctrl+S, Ctrl+X

5. Demarrer l'interface graphique du bureau Ubuntu

Ouvrez le terminal Ubuntu sur votre Windows et entrez cette commande

```bash
sudo /etc/init.d/xrdp start
```

Ensuite ouvrez *Connexion Bureau a distance* en cliquant sur la touche Windows et connectez-vous a *localhost:3390*

### Memoire - Optionnel
Si WSL utilise trop de memoire, vous pouvez la reduire avec une etape simple.
Il suffit d'aller dans *C:\Users\VotreNomUtilisateur\.wslconfig* et de creer un fichier *.wslconfig* et d'ecrire :

```bash
sudo /etc/init.d/xrdp start

[wsl2]
memory=3GB
```

### Installation des outils necessaires et a jour

```bash
sudo apt update
sudo apt install build-essential zlib1g-dev libncurses5-dev libgdbm-dev libnss3-dev libssl-dev libsqlite3-dev libreadline-dev libffi-dev curl libbz2-dev rsync make git
```

## Installation d'ERPLibre sous WSL2

Assurez-vous d'etre dans le repertoire ou vous souhaitez cloner le projet.

```bash
git clone https://github.com/ERPLibre/ERPLibre.git
cd ERPLibre
make install
```

Ajoutez un role a PostgreSQL, changez le champ `USERNAME` dans la commande avec votre nom d'utilisateur UNIX de votre environnement WSL2.

```bash
sudo service postgresql start
sudo su - postgres -c "createuser -s USERNAME" 2>/dev/null || true
```

## Problemes courants lors de l'installation

### Erreur lors de `make install`
Assurez-vous que toutes les dependances sont installees correctement. Relancez la commande suivante pour corriger les dependances cassees :

```bash
sudo apt-get install -f
```

### PostgreSQL ne demarre pas
Verifiez le statut du service PostgreSQL avec la commande suivante :

```bash
sudo service postgresql status
```

Si PostgreSQL ne fonctionne pas, essayez de le redemarrer avec :

```bash
sudo service postgresql restart
```


## Executer ERPLibre

A chaque redemarrage de votre machine, la commande suivante doit etre executee pour demarrer le service PostgreSQL s'il n'est pas deja en cours d'execution :

```bash
sudo service postgresql start
```

Ensuite lancez cette commande a la racine du projet :

```bash
./run.sh
```

## Verification d'ERPLibre
Pendant qu'ERPLibre est en cours d'execution, assurez-vous que vous pouvez vous connecter a l'URL suivante `http://localhost:8069` et que vous avez la possibilite de creer, modifier et supprimer des bases de donnees.

## Configurer l'environnement de developpement - PyCharm

### Installer PyCharm

Installez PyCharm depuis le [lien](https://www.jetbrains.com/pycharm/download/#section=windows) suivant :

```bash
https://www.jetbrains.com/pycharm/download/#section=windows
```

### Configurer Pycharm

Selectionnez `Connect to WSL` sous `Remote Development`. Ensuite selectionnez votre instance Ubuntu ("Ubuntu-22.04"). Pointez `Project directory` vers la racine du projet. Une fois que tout a ete selectionne et rempli correctement, cliquez sur `Start IDE and Connect`.

![Welcome to PyCharm Wizard](image/remote_development.png)

Appuyez sur `CTRL+ALT+S`, recherchez `interpreter` et dans la page `Python Interpreter`, cliquez sur `Add Interpreter` et selectionnez `Add Local Interpreter...`.

![Interpreter Settings](image/add_local_interpreter.png)

Assurez-vous de selectionner `Virtualenv Environment` a gauche et le bouton radio `Existing`. Une fois les deux correctement selectionnes, pointez votre interpreteur vers le repertoire `../ERPLibre/.venv/bin/python` du projet et cliquez sur `OK`.

![Environment Settings](image/existing_venv.png)

Si ces dernieres etapes pour configurer votre environnement de developpement n'ont pas fonctionne, suivez les etapes "Manuelles" suivantes pour configurer votre environnement.

## Installation manuelle

### Installer Python 3.10.14
Vous pouvez supprimer les fichiers restants dans votre repertoire personnel concernant l'installation de Python une fois les etapes completees avec succes.

```bash
cd ~
wget https://www.python.org/ftp/python/3.10.14/Python-3.10.14.tgz
tar -xzf Python-3.10.14.tgz
cd Python-3.10.14
./configure --enable-optimizations
make -j $(nproc)
sudo make install
```

### Verifier l'installation

```bash
python3.10
```

### Definir Python 3.10.14 par defaut

```bash
alias python='/usr/local/bin/python3.10'
source ~/.bashrc
```

### Configurer Pycharm

Ouvrez le repertoire du projet dans PyCharm.

Appuyez sur `CTRL+ALT+S`, recherchez `interpreter` et dans la page `Python Interpreter`, cliquez sur `Add Interpreter` et selectionnez `On WSL...`.

![Interpreter Settings](image/on_wsl.png)

Attendez que PyCharm detecte votre instance WSL2 et appuyez sur `NEXT`. Cliquez sur `System Interpreter` a gauche, selectionnez le bon interpreteur s'il ne l'a pas fait automatiquement et cliquez sur `Create`.

![System Interpreter](image/system_python.png)

Fermez les parametres du projet. Lorsque PyCharm vous propose d'importer des modules, autorisez-le.

## Problemes courants avec le developpement Windows

### Terminal casse

Recherchez `terminal` dans les parametres, et sous `Application Settings` dans le champ `Shell path:` entrez la ligne suivante :

```bash
wsl.exe
```

![Shell Path - Terminal](image/shell_path.png)

### Avertissements d'utilisation elevee de la memoire
Si vous constatez une utilisation elevee de la memoire, cliquez sur `Help` dans la barre d'outils et choisissez `Change Memory Settings` pour augmenter la memoire allouee a l'IDE.

### Modules importes manquants ou incorrects
PyCharm peut ne pas reconnaitre completement certains details de `requirements.txt` et `pyproject.toml` (par exemple, des versions specifiques de modules). Si vous rencontrez des problemes a l'execution ou lors du debogage, recherchez la bonne version du module et reinstallez-le avec le gestionnaire de paquets de PyCharm.

### Impossible d'executer ERPLibre depuis PyCharm

Si ERPLibre ne se lance pas depuis PyCharm, executez la commande suivante dans le repertoire racine du projet depuis le terminal de PyCharm ou WSL2 :

```bash
./script/ide/pycharm_configuration.py
```

### Impossible de redemarrer ERPLibre
Lancez `htop` depuis le terminal de PyCharm ou WSL2 et fermez les processus Python lies a ERPLibre pour liberer le socket.

## References
[Installation de WSL](https://learn.microsoft.com/en-us/windows/wsl/install)
Guide complet sur l'installation du Sous-systeme Windows pour Linux (WSL) sur Windows.

[Documentation officielle de PostgreSQL](https://www.postgresql.org/docs/)
Documentation officielle de PostgreSQL pour le depannage des problemes courants et pour en apprendre davantage sur les commandes et la configuration de PostgreSQL.

[Installation et configuration de PyCharm](https://www.jetbrains.com/pycharm/quickstart/)
Guide de demarrage rapide pour la configuration de PyCharm, incluant la gestion des modules Python et la configuration de l'environnement.

[Depannage de WSL](https://learn.microsoft.com/en-us/windows/wsl/troubleshoot)
Guide de depannage pour les problemes courants rencontres avec WSL, fournissant des solutions pour divers problemes qui peuvent survenir.

[Interface graphique Linux](https://hub.tcno.co/windows/wsl/desktop-gui/)
Instructions pour configurer une interface graphique (GUI) dans WSL, ce qui peut etre utile pour une meilleure integration des applications Linux.

[Probleme de memoire](https://www.aleksandrhovhannisyan.com/blog/limiting-memory-usage-in-wsl-2/)
Guide sur la gestion et la limitation de l'utilisation de la memoire dans WSL 2 pour eviter les problemes de consommation elevee de memoire.