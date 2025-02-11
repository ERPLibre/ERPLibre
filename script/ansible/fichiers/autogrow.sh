#!/bin/bash

LOG_FILE="/var/log/autogrow.log"

# Fonction pour écrire dans le fichier log avec timestamp
log_message() {
    local timestamp
    timestamp=$(date "+%Y-%m-%d %H:%M:%S")
    echo "${timestamp} - $1" >> "${LOG_FILE}"
}

# Fonction pour exécuter une commande et gérer les erreurs
run_command() {
    log_message "Exécution de la commande : $1"
    local output
    output=$($1 2>&1)
    local status=$?

    if [ $status -eq 0 ]; then
        log_message "✅ Commande exécutée avec succès."
    elif echo "$output" | grep -q "NOCHANGE"; then
        log_message "ℹ️ Aucun espace supplémentaire à allouer. Commande terminée sans modification."
    else
        log_message "❌ Erreur lors de l'exécution : $output"
        exit 1
    fi
}

# Script principal
log_message "🔍 Début de l'exécution du script autogrow..."

# Redimensionner la partition sda1 avec growpart
run_command "sudo growpart /dev/sda 1"

# Étendre le système de fichiers ext4 sur sda1
run_command "sudo resize2fs /dev/sda1"

log_message "🎉 Opération terminée avec succès."

