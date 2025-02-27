#!/usr/bin/env python3

import os
import sys
import subprocess

# Vérifier les arguments
if len(sys.argv) < 4:
    print("❌ Utilisation: ./playbook-adhoc <PLAYBOOK> <ROYAUME> <IP1> [<IP2> ...]")
    sys.exit(1)

PLAYBOOK = sys.argv[1]
ROYAUME = sys.argv[2]
TARGETS = sys.argv[3:]

# Générer le nom du fichier d'inventaire
inventaireDuSysadmin = f"/tmp/adhoc.hosts"

# Générer le contenu du fichier d'inventaire
choixDuSysadmin = "\n".join([f"{ip}" for ip in TARGETS])

inventory_content = f"""[leChoixDuSysadmin]
{choixDuSysadmin}
"""

# Écrire l'inventaire dans un fichier temporaire
with open(inventaireDuSysadmin, "w") as file:
    file.write(inventory_content)

print(f"✅ Fichier d'inventaire généré : {inventaireDuSysadmin}")

# Construire le chemin de la clé privée en fonction du royaume
private_key = f"~/.ssh/id_ed25519_ansible_{ROYAUME}"

# Exécuter le playbook Ansible
command = f"ansible-playbook {PLAYBOOK}.yml -K -i {inventaireDuSysadmin} --private-key {private_key}"
print(f"🚀 Exécution de : {command}")

try:
    subprocess.run(command, shell=True, check=True)
    print("✅ Playbook exécuté avec succès !")
except subprocess.CalledProcessError:
    print("❌ Erreur lors de l'exécution du playbook.")

# Supprimer le fichier temporaire
os.remove(inventaireDuSysadmin)

