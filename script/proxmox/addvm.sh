#!/bin/bash

# Fichier de configuration
CONFIG_FILE="vm_dev.csv"

# Vérification du fichier de configuration
if [ ! -f "$CONFIG_FILE" ]; then
  echo "Fichier de configuration introuvable : $CONFIG_FILE"
  exit 1
fi

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
  if [ -z "$vm_id" ] || [ -z "$vm_name" ] || [ -z "$ip_address" ] || [ -z "$vm_disk_size" ]; then
    echo "Erreur : vm_id, vm_name, ip_address ou vm_disk_size manquant pour une ligne. Ignorée."
    continue
  fi

  # Création de la VM
  qm create "$vm_id" --name "$vm_name" --cpu host --memory "$vm_memory" --cores "$vm_cores" --agent enabled=1 --net0 virtio,bridge=vmbr1,tag="$vm_vlan"
  qm set "$vm_id" --ide2 CephNVMe:cloudinit
  qm set "$vm_id" --boot c --bootdisk scsi0
  qm set "$vm_id" --scsihw virtio-scsi-single

  # Associer une image cloud-init
  qm importdisk "$vm_id" /var/lib/vz/template/qcow/debian-12-genericcloud-amd64.qcow2 CephNVMe
  qm set "$vm_id" --scsi0 CephNVMe:vm-${vm_id}-disk-0

  # Redimensionner le disque principal
  #echo "Redimensionnement du disque principal à ${vm_disk_size}G pour la VM $vm_name"
  #qm resize "$vm_id" scsi0 ${vm_disk_size}G

  # Configurer Cloud-init
  qm set "$vm_id" --ciuser ansible
  qm set "$vm_id" --cipassword T0rp1n0uch3.
  qm set "$vm_id" --sshkey "$ssh_key"
  qm set "$vm_id" --ipconfig0 ip="$ip_address",gw="$gateway"
  qm set "$vm_id" --nameserver "$(echo $dns_servers | tr '|' ',')"

  # Vérifier si le pool existe, sinon le créer
  #if ! pvesh get /pools | grep -q "\"$vm_pool\""; then
  #    pvesh create /pools -poolid "$vm_pool"
  #fi

  # Démarrer la VM (optionnel)
   qm start "$vm_id"

  # Redimensionner le disque principal
  # echo "Redimensionnement du disque principal à ${vm_disk_size}G pour la VM $vm_name"
  # qm resize "$vm_id" scsi0 ${vm_disk_size}G

  echo "VM $vm_name (ID: $vm_id) configurée avec succès."
done

