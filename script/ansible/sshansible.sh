#!/bin/bash

# Vérifier que deux arguments sont fournis
if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <royaume> <hôte>"
    exit 1
fi

# Récupérer les arguments
ROYAUME="$1"
HOTE="$2"

# Construire le chemin vers la clé SSH
CLE_SSH="$HOME/.ssh/id_ed25519_ansible_$ROYAUME"

# Vérifier si la clé SSH existe
if [ ! -f "$CLE_SSH" ]; then
    echo "Erreur: La clé SSH '$CLE_SSH' n'existe pas."
    exit 2
fi

# Lancer la connexion SSH avec la bonne clé et le compte ansible
ssh -i "$CLE_SSH" ansible@"$HOTE"
