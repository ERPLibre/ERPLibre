#!/bin/bash

# Vérifier si un argument a été fourni
if [ -z "$1" ]; then
    echo "Erreur : aucun nom de fichier spécifié."
    echo "Usage : $0 nom_de_base_du_fichier"
    exit 1
fi

# Nom de base du fichier fourni en argument
nom_base="$1"

# Ajouter l'extension .vm.cfg
CONFIG_FILE="${nom_base}.vm.cfg"

# Vérifier si le fichier avec l'extension existe
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Erreur : le fichier '$CONFIG_FILE' n'existe pas."
    exit 1
fi

# Fichier des royaumes
ROYAUMES_FILE="/etc/pve/priv/royaumes.ini"

# Vérification des fichiers de configuration
if [ ! -f "$ROYAUMES_FILE" ]; then
  echo "Fichier des royaumes introuvable : $ROYAUMES_FILE"
  exit 1
fi

# Lire le fichier des royaumes et stocker les informations dans un tableau associatif
declare -A ROYAUMES
while IFS=':' read -r royaume motdepasse; do
  ROYAUMES["$royaume"]="$motdepasse"
done < "$ROYAUMES_FILE"

# Lire la première ligne pour obtenir les noms des colonnes
IFS=',' read -r -a COLUMNS < "$CONFIG_FILE"

# Lecture des lignes de configuration, à partir de la 2e ligne
tail -n +2 "$CONFIG_FILE" | while IFS=',' read -r ${COLUMNS[@]}; do

  # Afficher les variables dynamiquement pour validation
  echo "=== Configuration pour VM ==="
  for column in "${COLUMNS[@]}"; do
    eval value=\$$column
    echo "$column: $value"
  done

  # Vérification des paramètres essentiels
  if [ -z "$vm_id" ] || [ -z "$vm_name" ] || [ -z "$ip_address" ] || [ -z "$vm_disk_size" ] || [ -z "$vm_royaume" ]; then
    echo "Erreur : vm_id, vm_name, ip_address, vm_disk_size ou vm_royaume manquant pour une ligne. Ignorée."
    continue
  fi

  # Récupérer le mot de passe associé au royaume
  vm_password="${ROYAUMES[$vm_royaume]}"
  if [ -z "$vm_password" ]; then
    echo "Erreur : Aucun mot de passe trouvé pour le royaume '$vm_royaume'. Ignorée."
    continue
  fi
  echo "Mot de passe : ${vm_password}"

  # Déterminer le chemin de la clé SSH publique en fonction du royaume
  ssh_key_path="/etc/pve/priv/id_ed25519_ansible_${vm_royaume}.pub"
  if [ ! -f "$ssh_key_path" ]; then
    echo "Erreur : Clé SSH publique introuvable pour le royaume '$vm_royaume' : $ssh_key_path"
    continue
  fi

  # Création de la VM
  qm create "$vm_id" --name "$vm_name" --cpu host --memory "$vm_memory" --cores "$vm_cores" --agent enabled=1 --net0 virtio,bridge=vmbr1,tag="$vm_vlan"
  qm set "$vm_id" --ide2 CephNVMe:cloudinit
  qm set "$vm_id" --boot c --bootdisk scsi0
  qm set "$vm_id" --scsihw virtio-scsi-single
  qm importdisk "$vm_id" /var/lib/vz/template/qcow/debian-12-genericcloud-amd64.qcow2 CephNVMe
  qm set "$vm_id" --scsi0 CephNVMe:vm-${vm_id}-disk-0
  qm set "$vm_id" --ciuser ansible --cipassword "$vm_password" --sshkey "$ssh_key_path"
  qm set "$vm_id" --ipconfig0 ip="$ip_address",gw="$gateway"
  qm set "$vm_id" --nameserver "$dns_servers"

  # créer le pool
  pool_name="$vm_royaume"
  #if ! pvesh get /pools | grep -q "\"${pool_name}\""; then
    echo "Création du pool : $pool_name"
    pvesh create /pools -poolid "$pool_name"
  #fi

  # Ajouter la VM au pool
  echo "Ajout de la VM $vm_name (ID: $vm_id) au pool $pool_name"
  pvesh set /pools/"$pool_name" --vms "$vm_id"
  #pvesh create /pools/"$pool_name"/vms -vmid "$vm_id"

  # Démarrer la VM
  qm start "$vm_id"
  nohup ./goQ35.sh "$vm_id" -d 120 >> ./goQ35."$vm_id".log 2>&1 &

  echo "VM $vm_name (ID: $vm_id) configurée avec succès et ajoutée au pool $pool_name."
done

