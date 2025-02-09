# Guide Debian

Installer Ansible sur le noeud de contrôle

```bash
sudo apt update
sudo apt install ansible
```

Initialiser le compte pour Ansible sur le noeud de contrôle

```bash
sudo useradd ansible
sudo usermod -aG sudo ansible
sudo mkdir /home/ansible
sudo chown -R ansible:ansible /home/ansible
sudo su - ansible
ssh-keygen -t ed25519
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
exit
# NOTE : On peut lancer ansible-playbook -i <fichier d'inventaire>
# au lieu des 3 commandes qui suivent
sudo mkdir /etc/ansible
sudo chmod 755 /etc/ansible
sudo touch /etc/ansible/hosts.conf
```

ÉTAPE OPTIONNELLE SI LE NOEUD EST CRÉÉ AVEC LE SCRIPT ADDVM

Initialiser le compte pour Ansible sur un noeud géré

```bash
sudo useradd ansible
sudo usermod -aG sudo ansible
sudo mkdir /home/ansible
sudo chown -R ansible:ansible /home/ansible
sudo su - ansible
touch .ssh
chmod 700 .ssh
touch .ssh/authorized_keys
chmod 600 .ssh/authorized_keys
# Aller chercher la clé SSH publique de ansible
# Idéalement, on la rend accessible de tous les noeuds gérés d'un endroit central.
scp <fqdn_du_noeud_de_controle>:~/.ssh/id_ed25519.pub .ssh/id_ed25519.pub
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
exit
```

********** INTÉGRATION DANS MON ÉCOSYSTÈME PROXMOX **************
*********** QUI REND L'ÉTAPE PRÉCÉDENTE OBSOLÈTE ****************

Concept de "royaume" pour segmenter et sécuriser les environnements gérés par Ansible:

Un "royaume" correspond à un environnement spécifique, tel que "kbr-dev", pour lequel une paire de clés SSH unique est générée et utilisée. Cette approche permet d'isoler les différents environnements et de renforcer la sécurité en limitant l'accès aux ressources selon le royaume associé.

Concrètement, pour chaque royaume, une paire de clés SSH est créée sur le noeud de contrôle. Ensuite, la clé publique est copiée dans le répertoire /etc/pve/priv/ des hyperviseurs Proxmox.

Lors de la création des machines virtuelles (VM), la clé publique correspondante est injectée via Cloud-Init, en fonction du royaume spécifié.

De plus, un fichier de configuration nommé /etc/pve/priv/royaumes.ini contient les associations entre chaque royaume et le mot de passe à utiliser pour le compte Ansible sur les VM.

Cette organisation vise à assurer une séparation claire entre les environnements, facilitant ainsi une gestion plus sécurisée et structurée des déploiements automatisés avec Ansible.

Arbitrairement, ca sera toujours le compte "ansible" qu'on utilisera

L'identifiant du royaume est une courte chaîne de caractères.  Elle sert aussi à 
pour renseigner la nomenclature des fichiers de clés, d'un pool dans PROXMOX
ainsi que les noms des vm.

PRÉMISSES POUR QUE TOU CECI FONCTIONNE :


PREMIÈMENT LE FICHIER /etc/pve/royaumes.ini
  On peu dire qu'il s'agit là du joyau de la couronne
  car ce fichier contient le mot de passe du compte ansible 
  pour CHAQUE "royaume ansible" !!

-rw------- 1 root www-data   76 Feb  7 17:31 royaumes.ini

Voici à quoi ça ressemble :

royaumeA:riuvn0s4wt
royaumeB:lkj&&?%n0iuy
...


ENSUITE, IL Y A LES FICHIERS DES CLÉS PUBLIQUES DE ansible POUR CHAQUE ROYAUME
  Remarquer la nomenclature : id_ed25519_ansible_<nom_du_royaume>.pub

-rw------- 1 root www-data  117 Feb  7 16:44 id_ed25519_ansible_kbr-dev.pub
-rw------- 1 root www-data  118 Feb  7 16:44 id_ed25519_ansible_kbr-prod.pub
-rw------- 1 root www-data  118 Feb  7 16:44 id_ed25519_ansible_kbr-test.pub

Ces fichiers sont obtenus À partir de la commande ajoutRoyaumeAnsible <nom_royaume>
qui doit être exécutée sur la machine de contrôle. (voir dans ./script/ansible)

Exemple :
Création d'un royaume nommé "dev-projetX"

ÉTAPE 1 -> SET DE CLÉS DU ROYAUME ANSIBLE
Se fait sur la machine d'ou se lancent les playbook ansible (le noeud de contrôle).

```bash
su ansible
ajoutRoyaumeAnsible dev-projetX"
```

ÉTAPE 2 -> RENDRE LA CLÉ ACCESSIBLE DANS TOUT L'ÉCOSYSTÈME
COPIER LE FICHIER .pub dans le répertoire /etc/pve/priv d'un hyperviseur. (peu importe lequel)
scp ~/.ssh/id_ed25519_<royaume>.pub root@<hyperviseur>:/etc/pve/priv

ÉTAPE 3 -> INJECTION DE LA CLÉ AU MOMENT DE LA CRÉATION DE LA VM
Se fait sur un hyperviseur

C'est avec la commande addvm (voir dans script/proxmox) que sera injectée la bonne clé.
NOTE : L'identifiant du royaume ansible est aussi utilisé pour créer un pool proxmox.
Une colone du fichier des intrants de addvm est renseignée du nom du royaume.

Exemple de fichier intrants.txt :
vm_id,vm_royaume,vm_name,vm_disk_size,ip_address,gateway,dns_servers,vm_memory,vm_cores,vm_vlan
10101,kbr-dev,sys-01,32,10.10.1.101/24,10.10.1.254,10.10.0.10 10.10.0.20,2048,4,1001
10102,kbr-dev,sys-02,32,10.10.1.102/24,10.10.1.254,10.10.0.10 10.10.0.20,2048,4,1001
10103,kbr-dev,sys-03,32,10.10.1.103/24,10.10.1.254,10.10.0.10 10.10.0.20,2048,4,1001
10104,kbr-dev,sys-04,32,10.10.1.104/24,10.10.1.254,10.10.0.10 10.10.0.20,2048,4,1001


********************************************************************************************************************
MÉTHODE SIMLPLIFIÉE PERMETTANT D'EXÉCUTER N'IMPORTE QUEL PLAYBOOK
SUR N'IMPORTEQUL HÔTE SANS AVOIR À SE SOUCIER DU FICHIER D'INVENTAIRE 

```bash
./playbook-adhoc <PLAYBOOK> <IP1> [<IP2> ...]
```
Ce script va créer un fichier d'inventaire nommé <PLAYBOOK>.hosts et s'en servir.

Exemple : playbook-adhoc integrations 192.168.0.100 10.10.4.56

cette commande va créer le fichier integrations.hosts : 

```
[leChoixDuSysadmin]
192.168.0.100
10.10.4.56

et puis lancer le playbook comme suit :


********************************************************************************************************************
MÉTHODE PERMETTANT D'EXÉCUTER UN PLAYBOOK SUR UN GRAND NOMBRE DE MACHINES 

MOTE:  Cette mesure est facultative car on peut tout aussi bien
spécifier le fichier d'inventaire en lancant le playbook avec -i

Créer et renseigner le fichier `/etc/ansible/hosts.conf`

```bash
IP=$(ip a | grep -oP '(?<=inet )(.*)(?=/)' | head -n 2 | awk 'NR==2')
echo "[leChoixDuSysadmin]" | sudo tee -a /etc/ansible/hosts.conf
echo "$IP" | sudo tee -a /etc/ansible/hosts.conf
```

Le résultat devrait ressembler à ceci :

```
[leChoixDuSysadmin]
192.168.1.100
```
****** NOTE IMPORTANTE *********
dans les playbook, il doit être mentionné "hosts : leChoixDuSysadmin"
c'est une contrainte que j'ai induite avec le script "playbook-adhoc".


Exécuter un playbook :

```bash
sudo -u ansible ansible-playbook ./script/ansible/durcissement_se.yml --ask-become-pass [-i <fichier d'inventaire>]
```
