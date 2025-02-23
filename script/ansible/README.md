## Guide Debian

Config de base Ansible & comment je l'ai intégré dans mon écosystème numérique Proxmox.

## Installation d'Ansible sur le nœud de contrôle

Mettez à jour les paquets et installez Ansible sur le noeud de contrôle :

```bash
sudo apt update
sudo apt install ansible
```

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

*Remarque : Par défaut, ansible cherche l'inventaire des machines à traiter dans /etc/ansible/hosts
Alternativement, il est possible de lancer la commande ansible-playbook -i <fichier d'inventaire>*

```bash
sudo mkdir /etc/ansible
sudo chmod 755 /etc/ansible
sudo touch /etc/ansible/hosts
```

## Initialisation du compte Ansible sur un nœud géré

*NOTE : Optionnel si le nœud est créé avec le script `ADDVM` (voir ./script/proxmox).*

**D'abord, sur le nœud géré, créez et configurez le compte `ansible` :**

```bash
sudo useradd -m -s /bin/bash ansible
sudo usermod -aG sudo ansible
sudo su - ansible
mkdir ~/.ssh
chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

**Ensuite, récupérez la clé publique SSH du compte `ansible` du nœud de contrôle :**

```bash
scp <fqdn_du_nœud_de_contrôle>:~/.ssh/id_ed25519.pub ~/.ssh/id_ed25519.pub
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
exit
```

## Intégration dans l'écosystème Proxmox

Pour segmenter et sécuriser les environnements gérés par Ansible, j'ai introduit le concept de "royaume".

Un "royaume" correspond à un environnement spécifique, tel que "dev-projetX", pour lequel une paire de clés SSH unique est générée et utilisée.

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

Sur un hyperviseur, utilisez la commande `addvm` (qui utilise un csv) pour injecter la clé appropriée.

*Exemple : `nouvelles_vm.csv` :*

```
vm_id,vm_royaume,vm_name,vm_disk_size,vm_vlan,ip_address,gateway,dns_servers,vm_memory,vm_cores
10101,dev-projetX,dev-sys-01,32,1001,10.10.1.101/24,10.10.1.254,10.10.0.10 10.10.0.20,2048,4
```

## Méthode simplifiée pour exécuter des playbooks

Pour exécuter un playbook sur des hôtes spécifiques sans se soucier d'un fichier d'inventaire
j'ai créé le script `playbook-adhoc`. Voici comment l'utiliser :

```bash
./playbook-adhoc <ROYAUME> <PLAYBOOK> <IP1> [<IP2> ...]
```

*Exemple :*

```bash
./playbook-adhoc dev-projetX integrations 192.168.0.100 10.10.4.56
```

Ce script crée un fichier d'inventaire nommé `integrations.hosts` et l'utiliser pour exécuter le playbook integrations.yml.
Fichier integrations.hosts:

```
[leChoixDuSysadmin]
192.168.0.100
10.10.4.56
```

*** NOTE IMPORTANTE ***
Pour que ca fonctionne, il fait que l'entête du playbook ait ceci :

```
  hosts: leChoixDuSysadmin 
```

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
