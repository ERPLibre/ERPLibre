#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import sys
import zipfile


def process_zip(
    path_backup_zip, path_output_zip, word_to_delete, file_to_modify
):
    # Ouvrir le zip d'entrée en lecture
    try:
        with zipfile.ZipFile(path_backup_zip, "r") as zin, zipfile.ZipFile(
            path_output_zip, "w"
        ) as zout:

            # Parcourir tous les fichiers du zip
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == file_to_modify:

                    try:
                        # On suppose un fichier texte en UTF-8
                        text = data.decode("utf-8")
                    except UnicodeDecodeError:
                        print(
                            f"Erreur : impossible de décoder {file_to_modify} en UTF-8",
                            file=sys.stderr,
                        )
                        sys.exit(1)

                    # Filtrer les lignes qui NE contiennent PAS le mot à supprimer
                    lines = text.splitlines(
                        keepends=True
                    )  # garder les fins de lignes
                    filtered_lines = [
                        line for line in lines if word_to_delete not in line
                    ]
                    new_text = "".join(filtered_lines)
                    new_data = new_text.encode("utf-8")

                    # Écrire la version modifiée dans le nouveau zip
                    zout.writestr(item, new_data)
                else:
                    # Pour les autres fichiers, on recopie tel quel
                    zout.writestr(item, data)

    except FileNotFoundError:
        print(
            f"Erreur : fichier zip source introuvable : {path_backup_zip}",
            file=sys.stderr,
        )
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Modifier un fichier dans un zip en supprimant les lignes contenant un mot donné."
    )
    parser.add_argument(
        "--path_backup_zip", help="Chemin vers le zip original"
    )
    parser.add_argument(
        "--path_output_zip", help="Chemin vers le nouveau zip à créer"
    )
    parser.add_argument(
        "--word_to_delete",
        help="Mot clé à supprimer (lignes contenant ce mot seront retirées)",
    )
    parser.add_argument(
        "--file_to_modify",
        default="dump.sql",
        help="Nom du fichier à modifier à l'intérieur du zip (chemin interne)",
    )

    args = parser.parse_args()

    process_zip(
        args.path_backup_zip,
        args.path_output_zip,
        args.word_to_delete,
        args.file_to_modify,
    )


if __name__ == "__main__":
    main()
