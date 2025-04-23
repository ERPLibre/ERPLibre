#!/usr/bin/env python3

import argparse
import os
import subprocess
import tempfile


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Exécute un playbook Ansible ad hoc sur un ou plusieurs hôtes."
        ),
    )
    parser.add_argument(
        "--playbook",
        required=True,
        help="Le nom du playbook Ansible à exécuter.",
    )
    parser.add_argument(
        "--royaume",
        required=True,
        help="Le nom du royaume ou de l'environnement cible.",
    )
    parser.add_argument(
        "--user",
        help=(
            "L'utilisateur distant. Par défaut, le nom de l'utilisateur sera"
            " le même que celui qui exécute la commande."
        ),
    )
    parser.add_argument(
        "--ips",
        nargs="+",
        required=True,
        help="Une ou plusieurs adresses IP des hôtes cibles.",
    )

    args = parser.parse_args()
    return args


def execute_playbook(config):
    # Générer le contenu du fichier d'inventaire
    choix_du_sysadmin = "\n".join(config.ips)

    inventory_content = f"""[leChoixDuSysadmin]
{choix_du_sysadmin}
"""

    # Écrire l'inventaire dans un fichier temporaire

    with tempfile.NamedTemporaryFile(mode="w", delete=False) as file_host:
        file_host.write(inventory_content)
        tmp_file_name = file_host.name

    print(f"✅ Fichier d'inventaire généré temporaire : {tmp_file_name}")

    # Construire le chemin de la clé privée en fonction du royaume
    private_key = f"~/.ssh/id_ed25519_ansible_{config.royaume}"

    # Exécuter le playbook Ansible
    optional_command = ""
    if config.user:
        optional_command += f" -u {config.user}"
    command = (
        f"ansible-playbook {config.playbook}.yml -K{optional_command} -i"
        f" {tmp_file_name} --private-key {private_key}"
    )
    print(f"🚀 Exécution de : {command}")

    try:
        subprocess.run(command, shell=True, check=True)
        print("✅ Playbook exécuté avec succès !")
    except subprocess.CalledProcessError:
        print("❌ Erreur lors de l'exécution du playbook.")
    finally:
        os.remove(tmp_file_name)


if __name__ == "__main__":
    config = get_config()
    execute_playbook(config)
