```markdown
# Guide Debian

## Sommaire

1. [Introduction](#introduction)
2. [Installation d'Ansible sur le nœud de contrôle](#installation-dansible-sur-le-nœud-de-contrôle)
3. [Initialisation du compte Ansible sur le nœud de contrôle](#initialisation-du-compte-ansible-sur-le-nœud-de-contrôle)
4. [Initialisation du compte Ansible sur un nœud géré (Optionnel)](#initialisation-du-compte-ansible-sur-un-nœud-géré-optionnel)
5. [Intégration dans l'écosystème Proxmox](#intégration-dans-lécosystème-proxmox)
6. [Méthode simplifiée pour exécuter des playbooks](#méthode-simplifiée-pour-exécuter-des-playbooks)
7. [Exécution d'un playbook sur plusieurs machines](#exécution-dun-playbook-sur-plusieurs-machines)

## Introduction

Ce guide fournit des instructions détaillées pour installer et configurer Ansible sur Debian, ainsi que son intégration dans un environnement Proxmox.

## Installation d'Ansible sur le nœud de contrôle

Mettez à jour les paquets et installez Ansible :

```bash
sudo apt update
sudo apt install ansible
```

**Exemple supplémentaire :** Si vous préférez utiliser `pip` pour installer Ansible, vous pouvez exécuter :

```bash
sudo apt install python3-pip
pip3 install ansible --user
```

Cette méthode est particulièrement utile si vous souhaitez installer une version spécifique d'Ansible ou si vous rencontrez des problèmes avec les dépôts APT. citeturn0search7

## Initialisation du compte Ansible sur le nœud de contrôle

Créez et configurez le compte `ansible` :

```bash
sudo useradd -m -s /bin/bash ansible
sudo usermod -aG sudo ansible
sudo su - ansible
ssh-keygen -t ed25519
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
exit
```

*Remarque :* Vous pouvez exécuter `ansible-playbook -i <fichier d'inventaire>` au lieu des trois commandes suivantes :

```bash
sudo mkdir /etc/ansible
sudo chmod 755 /etc/ansible
sudo touch /etc/ansible/hosts.conf
```

## Initialisation du compte Ansible sur un nœud géré (Optionnel)

Cette étape est optionnelle si le nœud est créé avec le script `ADDVM`.

Sur le nœud géré, créez et configurez le compte `ansible` :

```bash
sudo useradd -m -s /bin/bash ansible
sudo usermod -aG sudo ansible
sudo su - ansible
mkdir ~/.ssh
chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Récupérez la clé publique SSH du compte `ansible` du nœud de contrôle :

```bash
scp <fqdn_du_nœud_de_contrôle>:~/.ssh/id_ed25519.pub ~/.ssh/id_ed25519.pub
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
exit
```

## Intégration dans l'écosystème Proxmox

Pour segmenter et sécuriser les environnements gérés par Ansible, nous utilisons le concept de "royaume". Un "royaume" correspond à un environnement spécifique, tel que "kbr-dev", pour lequel une paire de clés SSH unique est générée et utilisée.

**Étape 1 : Génération de la paire de clés du royaume Ansible**

Sur le nœud de contrôle, exécutez :

```bash
su ansible
ajoutRoyaumeAnsible dev-projetX
```

**Étape 2 : Distribution de la clé publique**

Copiez le fichier `.pub` dans le répertoire `/etc/pve/priv` d'un hyperviseur Proxmox :

```bash
scp ~/.ssh/id_ed25519_dev-projetX.pub root@<hyperviseur>:/etc/pve/priv
```

**Étape 3 : Injection de la clé lors de la création de la VM**

Sur un hyperviseur, utilisez la commande `addvm` pour injecter la clé appropriée.

*Exemple de fichier `intrants.txt` :*

```
vm_id,vm_royaume,vm_name,vm_disk_size,ip_address,gateway,dns_servers,vm_memory,vm_cores,vm_vlan
10101,kbr-dev,sys-01,32,10.10.1.101/24,10.10.1.254,10.10.0.10 10.10.0.20,2048,4,1001
```

## Méthode simplifiée pour exécuter des playbooks

Pour exécuter un playbook sur des hôtes spécifiques sans modifier le fichier d'inventaire, utilisez le script `playbook-adhoc` :

```bash
./playbook-adhoc <PLAYBOOK> <IP1> [<IP2> ...]
```

*Exemple :*

```bash
./playbook-adhoc integrations 192.168.0.100 10.10.4.56
```

Ce script crée un fichier d'inventaire nommé `<PLAYBOOK>.hosts` et l'utilise pour exécuter le playbook.

## Exécution d'un playbook sur plusieurs machines

Pour exécuter un playbook sur un grand nombre de machines, créez et renseignez le fichier `/etc/ansible/hosts.conf` :

```bash
IP=$(hostname -I | awk '{print $1}')
echo "[leChoixDuSysadmin]" | sudo tee -a /etc/ansible/hosts.conf
echo "$IP" | sudo tee -a /etc/ansible/hosts.conf
```

Le fichier devrait ressembler à ceci :

```
[leChoixDuSysadmin]
192.168.1.100
```

*Remarque importante :* Dans les playbooks, spécifiez `hosts: leChoixDuSysadmin` pour correspondre au groupe défini dans le fichier d'inventaire.

Pour exécuter le playbook :

```bash
sudo -u ansible ansible-playbook ./script/ansible/durcissement_se.yml --ask-become-pass [-i <fichier d'inventaire>]
```
```

Ce document amélioré inclut un sommaire interactif pour une navigation aisée et des exemples supplémentaires pour l'installation d'Ansible sur Debian. N'hésitez pas à me solliciter pour toute assistance supplémentaire ou clarification. 
