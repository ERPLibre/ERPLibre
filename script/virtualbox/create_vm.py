import subprocess

def create_ubuntu_vm(vm_name, iso_path, preseed_path, memory=2048, cpus=2, disk_size=20000):
    # Créer une nouvelle machine virtuelle
    subprocess.run(["VBoxManage", "createvm", "--name", vm_name, "--ostype", "Ubuntu_64", "--register"])

    # Configurer la mémoire
    subprocess.run(["VBoxManage", "modifyvm", vm_name, "--memory", str(memory), "--cpus", str(cpus)])

    # Créer un disque dur virtuel
    subprocess.run(["VBoxManage", "createhd", "--filename", f"{vm_name}.vdi", "--size", str(disk_size)])

    # Attacher le disque dur à la machine virtuelle
    subprocess.run(["VBoxManage", "storagectl", vm_name, "--name", "SATA Controller", "--add", "sata"])
    subprocess.run(["VBoxManage", "storageattach", vm_name, "--storagectl", "SATA Controller", "--port", "0", "--device", "0", "--type", "hdd", "--medium", f"{vm_name}.vdi"])

    # Attacher l'ISO d'Ubuntu
    subprocess.run(["VBoxManage", "storagectl", vm_name, "--name", "IDE Controller", "--add", "ide"])
    subprocess.run(["VBoxManage", "storageattach", vm_name, "--storagectl", "IDE Controller", "--port", "1", "--device", "0", "--type", "dvddrive", "--medium", iso_path])

    # Configurer le réseau
    subprocess.run(["VBoxManage", "modifyvm", vm_name, "--nic1", "nat"])

    # Ajouter le fichier de préconfiguration
    subprocess.run(["VBoxManage", "modifyvm", vm_name, "--preseed", f"file:{preseed_path}"])

    # Démarrer la machine virtuelle
    subprocess.run(["VBoxManage", "startvm", vm_name])

# Exemple d'utilisation
create_ubuntu_vm(
    vm_name="UbuntuVM",
    iso_path="~/Documents/setup/ubuntu-24.04.1-desktop-amd64.iso",
    preseed_path="./script/virtualbox/preseed.cfg",
    memory=2048,
    cpus=2,
    disk_size=20000  # Taille en Mo
)
