# Guide Debian

Installer Ansible sur le noeud de coltrôle

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

# MOTE:  Cette mesure est facultative car on peut tout aussi bien
# spécifier le fichier d'inventaire en lancant le playbook avec -i

Créer et renseigner le fichier `/etc/ansible/hosts.conf`L

```bash
IP=$(ip a | grep -oP '(?<=inet )(.*)(?=/)' | head -n 2 | awk 'NR==2')
echo "[webservers]" | sudo tee -a /etc/ansible/hosts.conf
echo "$IP" | sudo tee -a /etc/ansible/hosts.conf
```

Le résultat devrait ressembler à ceci :

```
[webservers]
192.168.1.100
```

Exécuter les playbooks :

```bash
sudo -u ansible ansible-playbook ./script/ansible/durcissement_se.yml --ask-become-pass [-i <fichier d'inventaire>]
```
