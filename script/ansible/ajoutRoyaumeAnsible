#!/usr/bin/env python3

import os
import subprocess

def generer_cles_ssh(royaume):
    # Définir le chemin du répertoire .ssh
    repertoire_ssh = os.path.expanduser("~/.ssh")
    if not os.path.exists(repertoire_ssh):
        os.makedirs(repertoire_ssh)
        print(f"📁 Répertoire {repertoire_ssh} créé.")

    # Chemins des fichiers de clés
    cle_privee = os.path.join(repertoire_ssh, f"id_ed25519_ansible_{royaume}")
    cle_publique = f"{cle_privee}.pub"

    # Générer la paire de clés SSH
    try:
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-f", cle_privee, "-C", f"Cle ansible pour le royaume {royaume}", "-N", ""],
            check=True
        )
        print(f"✅ Paires de clés SSH générées :\n- Clé privée : {cle_privee}\n- Clé publique : {cle_publique}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Erreur lors de la génération des clés SSH : {e}")

if __name__ == "__main__":
    royaume = input("Entrez le nom du royaume (par exemple, 'mon_royaume') : ")
    generer_cles_ssh(royaume)

