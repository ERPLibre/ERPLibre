#!/bin/bash

# Vérification des arguments
if [ -z "$1" ]; then
    echo "Usage: $0 <VMID> [-d <délai en secondes>]"
    exit 1
fi

VMID=$1
STORAGE="CephNVMe"  # Modifie selon ton stockage (ex: CephNVMe, local, local-lvm)
DELAY=0  # Valeur par défaut pour le délai

# Analyse des arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--delay)
            if [[ -n $2 && $2 =~ ^[0-9]+$ ]]; then
                DELAY=$2
                shift 2
            else
                echo "Erreur : l'option -d nécessite un argument numérique (ex: -d 5)."
                exit 1
            fi
            ;;
        *)
            shift
            ;;
    esac
done

# Appliquer le délai, si spécifié
if [ "$DELAY" -gt 0 ]; then
    echo "⏳ Attente de $DELAY secondes..."
    sleep $DELAY
fi

# Étape 1 : Éteindre la VM
echo "📌 Arrêt de la VM $VMID..."
qm stop $VMID

# Étape 2 : Changer la machine en q35 et le BIOS en OVMF
echo "🔧 Changement du BIOS en OVMF et de la machine en q35..."
qm set $VMID --machine q35 --bios ovmf

# Étape 3 : Ajouter un disque EFI si non existant
echo "💾 Vérification du disque EFI..."
EFI_DISK_EXIST=$(qm config $VMID | grep efidisk0)

if [ -z "$EFI_DISK_EXIST" ]; then
    echo "➕ Ajout d'un disque EFI..."
    rbd create $STORAGE/vm-$VMID-disk-efi --size 4M
    qm set $VMID --efidisk0 $STORAGE:vm-$VMID-disk-efi
else
    echo "✅ Le disque EFI existe déjà."
fi

# Étape 4 : Redémarrer la VM
echo "🚀 Redémarrage de la VM $VMID..."
qm start $VMID

echo "✅ Conversion terminée ! La VM est maintenant en mode q35 + OVMF avec un disque EFI."

