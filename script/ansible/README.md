# Guide Debian

Install Ansible

```bash
sudo apt update
sudo apt install ansible
```

Initialization of Ansible

```bash
sudo useradd ansible
sudo usermod -aG sudo ansible
sudo mkdir /home/ansible
sudo su - ansible
ssh-keygen -t ed25519
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
exit
sudo mkdir /etc/ansible
sudo touch /etc/ansible/hosts.conf
sudo chown -R ansible:ansible /etc/ansible
```

Adapt the file `/etc/ansible/hosts.conf` :

```bash
IP=$(ip a | grep -oP '(?<=inet )(.*)(?=/)' | head -n 2 | awk 'NR==2')
echo "[webservers]" | sudo tee -a /etc/ansible/hosts.conf
echo "$IP" | sudo tee -a /etc/ansible/hosts.conf
```

Validate the file `/etc/ansible/hosts.conf` for a similar result of :

```
[webservers]
192.168.1.100
```

Exécuter les playbooks :

```bash
sudo -u ansible ansible-playbook ./script/ansible/durcissement_se.yml --ask-become-pass
```



