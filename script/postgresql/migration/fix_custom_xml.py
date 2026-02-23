#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script à exécuter avec Odoo shell pour détecter les vues XML modifiées
manuellement en base de données et les archiver.

Usage:
    odoo shell -d MA_BASE < detect_modified_views.py
    # ou
    odoo shell -d MA_BASE --shell-interface=python < detect_modified_views.py

Le script compare l'arch stocké en DB avec l'arch original du fichier XML
source du module. Si les deux diffèrent, la vue est considérée comme
modifiée manuellement.

Par défaut, le script tourne en mode DRY RUN (rapport uniquement).
Passer DRY_RUN = False pour archiver réellement les vues détectées.
"""

import logging
import os
import re
from lxml import etree

_logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================
DRY_RUN = True  # True = rapport uniquement, False = archive les vues détectées
MODULES_FILTER = []  # Liste de modules à scanner. Vide = tous les modules.
# Exemple: MODULES_FILTER = ['event', 'sale', 'purchase']


def normalize_arch(arch_str):
    """Normalise un arch XML pour comparaison fiable.

    Supprime les espaces blancs superflus, les commentaires,
    et normalise les attributs pour une comparaison cohérente.
    """
    if not arch_str:
        return ""
    try:
        if isinstance(arch_str, bytes):
            arch_str = arch_str.decode("utf-8")
        # Nettoyer les espaces et commentaires
        parser = etree.XMLParser(remove_blank_text=True, remove_comments=True)
        tree = etree.fromstring(arch_str.strip().encode("utf-8"), parser=parser)
        # Sérialiser de manière canonique
        return etree.tostring(tree, pretty_print=False, encoding="unicode")
    except etree.XMLSyntaxError:
        # Fallback: nettoyage basique par regex
        cleaned = re.sub(r"\s+", " ", arch_str).strip()
        return cleaned


def get_arch_from_xml_file(filepath, xmlid_name):
    """Extrait l'arch d'une vue depuis le fichier XML source du module.

    Args:
        filepath: Chemin absolu vers le fichier XML
        xmlid_name: Nom court du xmlid (sans le préfixe module)

    Returns:
        str ou None: L'arch XML trouvé, ou None si introuvable
    """
    if not os.path.isfile(filepath):
        return None
    try:
        tree = etree.parse(filepath)
        root = tree.getroot()

        # Chercher le record avec l'id correspondant
        for record in root.iter("record"):
            rec_id = record.get("id", "")
            if rec_id == xmlid_name:
                # Trouver le field arch
                for field in record.findall("field"):
                    if field.get("name") == "arch" and field.get("type") == "xml":
                        # Extraire le contenu XML du field
                        children = list(field)
                        if children:
                            return etree.tostring(
                                children[0], pretty_print=False, encoding="unicode"
                            )
        return None
    except Exception as e:
        _logger.debug("Erreur lecture %s: %s", filepath, e)
        return None


def find_xml_files_for_module(module_name):
    """Trouve tous les fichiers XML data d'un module installé.

    Returns:
        list: Liste des chemins absolus vers les fichiers XML
    """
    module = env["ir.module.module"].search(
        [("name", "=", module_name), ("state", "=", "installed")], limit=1
    )
    if not module:
        return []

    # Trouver le chemin du module
    mod_path = module._path if hasattr(module, "_path") else None
    if not mod_path:
        import odoo.modules.module as mod_module

        mod_path = mod_module.get_module_path(module_name, display_warning=False)

    if not mod_path or not os.path.isdir(mod_path):
        return []

    xml_files = []
    # Scanner les répertoires classiques contenant des vues
    for subdir in ["views", "data", "security", "wizard", "report", ""]:
        search_dir = os.path.join(mod_path, subdir) if subdir else mod_path
        if not os.path.isdir(search_dir):
            continue
        for fname in os.listdir(search_dir):
            if fname.endswith(".xml"):
                xml_files.append(os.path.join(search_dir, fname))

    return xml_files


def detect_modified_views():
    """Détecte toutes les vues dont l'arch en DB diffère du fichier source.

    Returns:
        list: Liste de dicts avec les infos des vues modifiées
    """
    modified_views = []

    # Récupérer toutes les vues ayant un xmlid (donc définies dans un module)
    domain = [("model", "=", "ir.ui.view")]
    if MODULES_FILTER:
        domain.append(("module", "in", MODULES_FILTER))

    imd_records = env["ir.model.data"].search(domain)
    total = len(imd_records)
    print(f"\n{'='*70}")
    print(f"Analyse de {total} vues avec xmlid...")
    print(f"{'='*70}\n")

    # Cache des fichiers XML parsés par module
    module_xml_cache = {}

    for idx, imd in enumerate(imd_records):
        if idx % 100 == 0 and idx > 0:
            print(f"  Progression: {idx}/{total} vues analysées...")

        module_name = imd.module
        xmlid_name = imd.name
        full_xmlid = f"{module_name}.{xmlid_name}"

        # Récupérer la vue en DB
        try:
            view = env["ir.ui.view"].browse(imd.res_id)
            if not view.exists():
                continue
        except Exception:
            continue

        # Récupérer l'arch depuis la DB
        arch_db = view.arch_db or ""
        if not arch_db:
            continue

        # Charger les fichiers XML du module (avec cache)
        if module_name not in module_xml_cache:
            module_xml_cache[module_name] = find_xml_files_for_module(module_name)

        xml_files = module_xml_cache[module_name]

        # Chercher l'arch original dans les fichiers source
        arch_file = None
        source_file = None
        for xml_file in xml_files:
            arch_file = get_arch_from_xml_file(xml_file, xmlid_name)
            if arch_file is not None:
                source_file = xml_file
                break

        if arch_file is None:
            # Pas trouvé dans les fichiers source — possiblement une vue
            # créée uniquement en DB ou dans un fichier non standard
            continue

        # Comparer les arch normalisés
        norm_db = normalize_arch(arch_db)
        norm_file = normalize_arch(arch_file)

        if norm_db != norm_file:
            # Vérifier aussi le type de vue vs ce qui est attendu
            view_type_mismatch = False
            try:
                db_root = etree.fromstring(arch_db.encode("utf-8"))
                file_root = etree.fromstring(arch_file.encode("utf-8"))
                if db_root.tag != file_root.tag:
                    view_type_mismatch = True
            except Exception:
                pass

            modified_views.append(
                {
                    "view_id": view.id,
                    "xmlid": full_xmlid,
                    "name": view.name,
                    "model": view.model,
                    "type": view.type,
                    "module": module_name,
                    "source_file": source_file,
                    "inherit_id": view.inherit_id.name if view.inherit_id else False,
                    "type_mismatch": view_type_mismatch,
                    "active": view.active,
                }
            )

    return modified_views


def print_report(modified_views):
    """Affiche un rapport détaillé des vues modifiées."""
    print(f"\n{'='*70}")
    print(f" RAPPORT DES VUES MODIFIÉES MANUELLEMENT")
    print(f"{'='*70}")
    print(f" Total détecté: {len(modified_views)} vue(s)\n")

    if not modified_views:
        print(" Aucune vue modifiée détectée. Tout est conforme !")
        return

    # Grouper par module pour lisibilité
    by_module = {}
    for v in modified_views:
        by_module.setdefault(v["module"], []).append(v)

    for module_name in sorted(by_module.keys()):
        views = by_module[module_name]
        print(f"\n  Module: {module_name} ({len(views)} vue(s))")
        print(f"  {'-'*60}")
        for v in views:
            flags = []
            if v["type_mismatch"]:
                flags.append("TYPE MISMATCH")
            if not v["active"]:
                flags.append("DÉJÀ ARCHIVÉE")
            if v["inherit_id"]:
                flags.append(f"hérite de: {v['inherit_id']}")

            flag_str = f" [{', '.join(flags)}]" if flags else ""
            print(f"    ID: {v['view_id']:>6} | {v['xmlid']}")
            print(f"           Nom: {v['name']}")
            print(f"           Modèle: {v['model']} | Type: {v['type']}{flag_str}")
            print(f"           Fichier: {v['source_file']}")
            print()


def archive_views(modified_views):
    """Archive les vues modifiées (les désactive).

    Ne touche pas aux vues déjà archivées.
    """
    to_archive = [v for v in modified_views if v["active"]]

    if not to_archive:
        print("\n Aucune vue active à archiver.")
        return

    print(f"\n{'='*70}")
    if DRY_RUN:
        print(f" MODE DRY RUN — {len(to_archive)} vue(s) SERAIENT archivées:")
    else:
        print(f" ARCHIVAGE de {len(to_archive)} vue(s):")
    print(f"{'='*70}\n")

    view_ids = [v["view_id"] for v in to_archive]

    for v in to_archive:
        status = "[DRY RUN]" if DRY_RUN else "[ARCHIVÉ]"
        print(f"  {status} {v['xmlid']} (ID: {v['view_id']}) — {v['name']}")

    if not DRY_RUN:
        views_to_archive = env["ir.ui.view"].browse(view_ids)
        views_to_archive.write({"active": False})
        env.cr.commit()
        print(f"\n {len(to_archive)} vue(s) archivée(s) avec succès.")
    else:
        print(f"\n Pour archiver réellement, modifiez DRY_RUN = False dans le script.")


def generate_sql_restore():
    """Génère les requêtes SQL pour restaurer les vues archivées si besoin."""
    print(f"\n{'='*70}")
    print(f" REQUÊTES SQL DE RESTAURATION (au cas où)")
    print(f"{'='*70}\n")
    print("-- Exécuter ces requêtes pour restaurer les vues si nécessaire:")
    for v in modified_views:
        if v["active"]:
            print(
                f"UPDATE ir_ui_view SET active = true WHERE id = {v['view_id']}; "
                f"-- {v['xmlid']}"
            )
    print()


# ============================================================================
# EXÉCUTION PRINCIPALE
# ============================================================================
print("\n" + "=" * 70)
print(" DÉTECTION DES VUES ODOO MODIFIÉES MANUELLEMENT")
print(f" Mode: {'DRY RUN (rapport uniquement)' if DRY_RUN else 'ARCHIVAGE ACTIF'}")
if MODULES_FILTER:
    print(f" Modules: {', '.join(MODULES_FILTER)}")
else:
    print(f" Modules: TOUS")
print("=" * 70)

modified_views = detect_modified_views()
print_report(modified_views)
archive_views(modified_views)
generate_sql_restore()

print("\nTerminé.\n")
