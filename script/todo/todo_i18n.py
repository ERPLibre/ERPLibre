#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os
import re

ENV_VAR_FILE = "./env_var.sh"

_current_lang = None

TRANSLATIONS = {
    # Main menu
    "Importation success!": {
        "fr": "L'importation est un succès!",
        "en": "Importation success!",
    },
    "Opening TODO ...": {
        "fr": "Ouverture de TODO en cours ...",
        "en": "Opening TODO ...",
    },
    "=> Enter your choice by number and press Enter!": {
        "fr": "=> Entre tes directives par son chiffre et fait Entrée!",
        "en": "=> Enter your choice by number and press Enter!",
    },
    "Command:": {
        "fr": "Commande :",
        "en": "Command:",
    },
    "Execute": {
        "fr": "🧰 Exécution",
        "en": "🧰 Execute",
    },
    "Install": {
        "fr": "📦 Installation",
        "en": "📦 Install",
    },
    "Assistant": {
        "fr": "🤖 Assistant",
        "en": "🤖 Assistant",
    },
    "Fork - Open TODO in a new tab": {
        "fr": "🔀 Fork - Ouvre TODO dans une nouvelle tabulation",
        "en": "🔀 Fork - Open TODO in a new tab",
    },
    "Quit": {
        "fr": "Quitter",
        "en": "Quit",
    },
    "Command not found !": {
        "fr": "Commande non trouvée !",
        "en": "Command not found !",
    },
    "Back": {
        "fr": "🔙 Retour",
        "en": "🔙 Back",
    },
    # Execute submenu
    "Run - Execute and install an instance": {
        "fr": "🏃 Run - Exécuter et installer une instance",
        "en": "🏃 Run - Execute and install an instance",
    },
    "Automation - Demonstration of developed features": {
        "fr": "🦾 Automatisation - Demonstration des fonctions développées",
        "en": "🦾 Automation - Demonstration of developed features",
    },
    "Update - Update all developed staging source code": {
        "fr": "🔃 Mise à jour - Update all developed staging source code",
        "en": "🔃 Update - Update all developed staging source code",
    },
    "Code - Developer tools": {
        "fr": "💻 Code - Outil pour développeur",
        "en": "💻 Code - Developer tools",
    },
    "Doc - Documentation search": {
        "fr": "📖 Doc - Recherche de documentation",
        "en": "📖 Doc - Documentation search",
    },
    "Database - Database tools": {
        "fr": "💾 Database - Outils sur les bases de données",
        "en": "💾 Database - Database tools",
    },
    "Process - Execution tools": {
        "fr": "📟 Process - Outils sur les executions",
        "en": "📟 Process - Execution tools",
    },
    "Config - Configuration file management": {
        "fr": "🔧 Config - Traitement du fichier de configuration",
        "en": "🔧 Config - Configuration file management",
    },
    "Network - Network tools": {
        "fr": "📡 Réseau - Outil réseautique",
        "en": "📡 Network - Network tools",
    },
    "Security - Dependency security audit": {
        "fr": "🔒 Sécurité - Audit de sécurité des dépendances",
        "en": "🔒 Security - Dependency security audit",
    },
    "RTK - CLI proxy to reduce LLM token consumption": {
        "fr": "RTK - Proxy CLI pour réduire la consommation de tokens LLM",
        "en": "RTK - CLI proxy to reduce LLM token consumption",
    },
    "Language - Change language / Changer la langue": {
        "fr": "🌍 Langue - Changer la langue / Change language",
        "en": "🌍 Language - Change language / Changer la langue",
    },
    # Deploy section
    "Deploy - Deploy ERPLibre locally": {
        "fr": "🚀 Déploiement - Déployer ERPLibre localement",
        "en": "🚀 Deploy - Deploy ERPLibre locally",
    },
    "Deploy ERPLibre to a local directory!": {
        "fr": "Déployer ERPLibre dans un répertoire local!",
        "en": "Deploy ERPLibre to a local directory!",
    },
    "Clone ERPLibre locally (git clone)": {
        "fr": "📥 Cloner ERPLibre localement (git clone)",
        "en": "📥 Clone ERPLibre locally (git clone)",
    },
    "Target directory path (default: ~/erplibre): ": {
        "fr": "Chemin du répertoire cible (défaut: ~/erplibre) : ",
        "en": "Target directory path (default: ~/erplibre): ",
    },
    "Directory already exists: ": {
        "fr": "Le répertoire existe déjà : ",
        "en": "Directory already exists: ",
    },
    "Cloning ERPLibre...": {
        "fr": "Clonage d'ERPLibre en cours...",
        "en": "Cloning ERPLibre...",
    },
    "ERPLibre cloned successfully to: ": {
        "fr": "ERPLibre cloné avec succès dans : ",
        "en": "ERPLibre cloned successfully to: ",
    },
    "Error cloning ERPLibre: ": {
        "fr": "Erreur lors du clonage d'ERPLibre : ",
        "en": "Error cloning ERPLibre: ",
    },
    "Configure sshfs": {
        "fr": "📁 Configurer sshfs",
        "en": "📁 Configure sshfs",
    },
    "Local": {
        "fr": "💻 Local",
        "en": "💻 Local",
    },
    "SSH (remote host)": {
        "fr": "SSH (hôte distant)",
        "en": "SSH (remote host)",
    },
    "Remote & services": {
        "fr": "🌐 Distant & services",
        "en": "🌐 Remote & services",
    },
    "SSH (remote host)...": {
        "fr": "🔐 SSH (hôte distant)…",
        "en": "🔐 SSH (remote host)...",
    },
    "Deploy ERPLibre to a remote host over SSH!": {
        "fr": "Déployer ERPLibre sur un hôte distant via SSH !",
        "en": "Deploy ERPLibre to a remote host over SSH!",
    },
    "Virtualization & notifications": {
        "fr": "Virtualisation & notifications",
        "en": "Virtualization & notifications",
    },
    "Development": {
        "fr": "🧰 Développement",
        "en": "🧰 Development",
    },
    "Data": {
        "fr": "📊 Données",
        "en": "📊 Data",
    },
    "Sources & documentation": {
        "fr": "📚 Sources & documentation",
        "en": "📚 Sources & documentation",
    },
    "AI & automation": {
        "fr": "🧠 IA & automatisation",
        "en": "🧠 AI & automation",
    },
    "Deployment, network & security": {
        "fr": "🌐 Déploiement, réseau & sécurité",
        "en": "🌐 Deployment, network & security",
    },
    "Preferences": {
        "fr": "🎨 Préférences",
        "en": "🎨 Preferences",
    },
    "Deployment": {
        "fr": "🚀 Déploiement",
        "en": "🚀 Deployment",
    },
    "Manage": {
        "fr": "🛠  Gérer",
        "en": "🛠  Manage",
    },
    "Catalog": {
        "fr": "📚 Catalogue",
        "en": "📚 Catalog",
    },
    "Open the console on a VM": {
        "fr": "🖥  Ouvrir la console d'une VM",
        "en": "🖥  Open the console on a VM",
    },
    "Backup": {
        "fr": "Sauvegarde",
        "en": "Backup",
    },
    "Restore": {
        "fr": "Restauration",
        "en": "Restore",
    },
    "Danger zone": {
        "fr": "Zone dangereuse",
        "en": "Danger zone",
    },
    "Setup": {
        "fr": "Installation",
        "en": "Setup",
    },
    "Status": {
        "fr": "Statut",
        "en": "Status",
    },
    "Optimize": {
        "fr": "Optimisation",
        "en": "Optimize",
    },
    "Generate": {
        "fr": "Génération",
        "en": "Generate",
    },
    "Advanced": {
        "fr": "Avancé",
        "en": "Advanced",
    },
    "To leave the console, press Ctrl+] (then Enter).": {
        "fr": "Pour quitter la console, appuyez sur Ctrl+] (puis Entrée).",
        "en": "To leave the console, press Ctrl+] (then Enter).",
    },
    "Default login (if set at deploy): erplibre / erplibre": {
        "fr": "Login par défaut (si défini au déploiement) : "
        "erplibre / erplibre",
        "en": "Default login (if set at deploy): erplibre / erplibre",
    },
    "Console password for 'erplibre' (default: erplibre): ": {
        "fr": "Mot de passe console pour « erplibre » (défaut : erplibre) : ",
        "en": "Console password for 'erplibre' (default: erplibre): ",
    },
    "Console/SSH login:": {
        "fr": "Connexion console/SSH :",
        "en": "Console/SSH login:",
    },
    "Default login:": {
        "fr": "Login par défaut :",
        "en": "Default login:",
    },
    "Add this VM to ~/.ssh/config? (y/N): ": {
        "fr": "Ajouter cette VM à ~/.ssh/config ? (o/N, défaut : non) : ",
        "en": "Add this VM to ~/.ssh/config? (y/N, default: no): ",
    },
    "Add each VM to ~/.ssh/config? (Y/n): ": {
        "fr": "Ajouter chaque VM à ~/.ssh/config ? (O/n, défaut : oui) : ",
        "en": "Add each VM to ~/.ssh/config? (Y/n, default: yes): ",
    },
    "Waiting for the VM IP (DHCP lease)...": {
        "fr": "Attente de l'IP de la VM (bail DHCP)...",
        "en": "Waiting for the VM IP (DHCP lease)...",
    },
    "No IP yet; add it later once the VM has booted.": {
        "fr": "Pas encore d'IP ; à ajouter plus tard une fois la VM démarrée.",
        "en": "No IP yet; add it later once the VM has booted.",
    },
    "Added to ~/.ssh/config:": {
        "fr": "Ajouté à ~/.ssh/config :",
        "en": "Added to ~/.ssh/config:",
    },
    "SSH address input method": {
        "fr": "Méthode de saisie de l'adresse SSH",
        "en": "SSH address input method",
    },
    "Manual entry": {
        "fr": "Saisie manuelle",
        "en": "Manual entry",
    },
    "From ~/.ssh/config": {
        "fr": "Depuis ~/.ssh/config",
        "en": "From ~/.ssh/config",
    },
    "Your choice (1/2): ": {
        "fr": "Votre choix (1/2) : ",
        "en": "Your choice (1/2): ",
    },
    "No SSH hosts found in ~/.ssh/config": {
        "fr": "Aucun hôte SSH trouvé dans ~/.ssh/config",
        "en": "No SSH hosts found in ~/.ssh/config",
    },
    "Select SSH host number: ": {
        "fr": "Numéro de l'hôte SSH à sélectionner : ",
        "en": "Select SSH host number: ",
    },
    "Invalid selection!": {
        "fr": "Sélection invalide!",
        "en": "Invalid selection!",
    },
    "SSH host (e.g.: user@192.168.1.100): ": {
        "fr": "Hôte SSH (ex: user@192.168.1.100) : ",
        "en": "SSH host (e.g.: user@192.168.1.100): ",
    },
    "Mounting sshfs on: ": {
        "fr": "Montage sshfs sur : ",
        "en": "Mounting sshfs on: ",
    },
    "Mounted on: ": {
        "fr": "Monté sur : ",
        "en": "Mounted on: ",
    },
    "To unmount: ": {
        "fr": "Pour démonter : ",
        "en": "To unmount: ",
    },
    "Error mounting sshfs: ": {
        "fr": "Erreur lors du montage sshfs : ",
        "en": "Error mounting sshfs: ",
    },
    # RTK (Rust Token Killer)
    "Manage RTK (Rust Token Killer) for token optimization!": {
        "fr": "Gérer RTK (Rust Token Killer) pour optimiser les tokens!",
        "en": "Manage RTK (Rust Token Killer) for token optimization!",
    },
    "Install RTK": {
        "fr": "Installer RTK",
        "en": "Install RTK",
    },
    "Check RTK version": {
        "fr": "Vérifier la version de RTK",
        "en": "Check RTK version",
    },
    "Show cumulative token savings": {
        "fr": "Afficher les économies de tokens cumulées",
        "en": "Show cumulative token savings",
    },
    "Discover optimization opportunities": {
        "fr": "Identifier les opportunités d'optimisation",
        "en": "Discover optimization opportunities",
    },
    "Initialize global auto-rewrite hook": {
        "fr": "Initialiser le hook auto-rewrite global",
        "en": "Initialize global auto-rewrite hook",
    },
    "Check RTK status": {
        "fr": "Vérifier le statut de RTK",
        "en": "Check RTK status",
    },
    "RTK is not installed. Use option 1 to install it.": {
        "fr": "RTK n'est pas installé. Utilisez l'option 1 pour l'installer.",
        "en": "RTK is not installed. Use option 1 to install it.",
    },
    "RTK is installed, version: ": {
        "fr": "RTK est installé, version : ",
        "en": "RTK is installed, version: ",
    },
    "Global auto-rewrite hook: active": {
        "fr": "Hook auto-rewrite global : actif",
        "en": "Global auto-rewrite hook: active",
    },
    "Global auto-rewrite hook: inactive": {
        "fr": "Hook auto-rewrite global : inactif",
        "en": "Global auto-rewrite hook: inactive",
    },
    "Installation method:": {
        "fr": "Méthode d'installation :",
        "en": "Installation method:",
    },
    "curl - Automatic install script": {
        "fr": "curl - Script d'installation automatique",
        "en": "curl - Automatic install script",
    },
    "brew - Homebrew (macOS/Linux)": {
        "fr": "brew - Homebrew (macOS/Linux)",
        "en": "brew - Homebrew (macOS/Linux)",
    },
    "cargo - Build from source (Rust required)": {
        "fr": "cargo - Compilation depuis les sources (Rust requis)",
        "en": "cargo - Build from source (Rust required)",
    },
    # Prompts and messages
    "Enter your password: ": {
        "fr": "Entrez votre mot de passe : ",
        "en": "Enter your password: ",
    },
    "Write your question ": {
        "fr": "Écrit moi ta question ",
        "en": "Write your question ",
    },
    "Do you want a new instance?": {
        "fr": "Voulez-vous une nouvelle instance?",
        "en": "Do you want a new instance?",
    },
    "SSH port-forwarding": {
        "fr": "SSH port-forwarding",
        "en": "SSH port-forwarding",
    },
    "Network performance request per second": {
        "fr": "Performance réseau en requêtes par seconde",
        "en": "Network performance request per second",
    },
    "Setup queue job for parallelism": {
        "fr": "Configurer la file d'attente pour l'exécution parallèle",
        "en": "Setup queue job for parallelism",
    },
    "Choose your database": {
        "fr": "Choisir sa base de données",
        "en": "Choose your database",
    },
    "Development update": {
        "fr": "Mise à jour du développement",
        "en": "Development update",
    },
    "What do you need for development?": {
        "fr": "Qu'avez-vous de besoin pour développer?",
        "en": "What do you need for development?",
    },
    "Looking for documentation?": {
        "fr": "Vous cherchez de la documentation?",
        "en": "Looking for documentation?",
    },
    "Make changes to databases!": {
        "fr": "Faites des modifications sur les bases de données!",
        "en": "Make changes to databases!",
    },
    # Database drop / erase
    "Erase a database": {
        "fr": "Effacer une base de données",
        "en": "Erase a database",
    },
    "Erase a database — irreversible operation!": {
        "fr": "Effacer une base de données — opération irréversible !",
        "en": "Erase a database — irreversible operation!",
    },
    "Erase ALL databases (make db_drop_all)": {
        "fr": "Effacer TOUTES les bases de données (make db_drop_all)",
        "en": "Erase ALL databases (make db_drop_all)",
    },
    "Erase a single database": {
        "fr": "Effacer une seule base de données",
        "en": "Erase a single database",
    },
    "You are about to erase ALL databases. This cannot be undone.": {
        "fr": (
            "Tu es sur le point d'effacer TOUTES les bases de données."
            " C'est irréversible."
        ),
        "en": "You are about to erase ALL databases. This cannot be undone.",
    },
    "You are about to erase the database '{database}'. This cannot be undone.": {
        "fr": (
            "Tu es sur le point d'effacer la base de données « {database} »."
            " C'est irréversible."
        ),
        "en": (
            "You are about to erase the database '{database}'."
            " This cannot be undone."
        ),
    },
    "Type 'oui' to confirm (default: no): ": {
        "fr": "Tape « oui » pour confirmer (défaut : non) : ",
        "en": "Type 'oui'/'yes' to confirm (default: no): ",
    },
    "Database deletion cancelled.": {
        "fr": "Effacement de la base de données annulé.",
        "en": "Database deletion cancelled.",
    },
    "No database selected.": {
        "fr": "Aucune base de données sélectionnée.",
        "en": "No database selected.",
    },
    "Cannot list the databases (exit code): ": {
        "fr": "Impossible de lister les bases (code de retour) : ",
        "en": "Cannot list the databases (exit code): ",
    },
    "Is PostgreSQL running?": {
        "fr": "PostgreSQL est-il démarré ?",
        "en": "Is PostgreSQL running?",
    },
    "No database on this PostgreSQL server.": {
        "fr": "Aucune base sur ce serveur PostgreSQL.",
        "en": "No database on this PostgreSQL server.",
    },
    "Manage execution processes!": {
        "fr": "Manipuler les processus d'exécution!",
        "en": "Manage execution processes!",
    },
    "Manage ERPLibre and Odoo configuration!": {
        "fr": "Manipuler la configuration ERPLibre et Odoo!",
        "en": "Manage ERPLibre and Odoo configuration!",
    },
    "Network tools!": {
        "fr": "Outil réseautique!",
        "en": "Network tools!",
    },
    "Dependency security audit!": {
        "fr": "Audit de securite des dépendances!",
        "en": "Dependency security audit!",
    },
    "The Bash script failed with return code": {
        "fr": "Le script Bash a échoué avec le code de retour",
        "en": "The Bash script failed with return code",
    },
    "No installed environment found. Install an Odoo version first.": {
        "fr": "Aucun environnement installe trouve. Installez d'abord une version d'Odoo.",
        "en": "No installed environment found. Install an Odoo version first.",
    },
    "Choose an environment for the audit:": {
        "fr": "Choisir un environnement pour l'audit :",
        "en": "Choose an environment for the audit:",
    },
    "Select: ": {
        "fr": "Sélection : ",
        "en": "Select: ",
    },
    "Error, cannot understand value": {
        "fr": "Erreur, impossible de comprendre la valeur",
        "en": "Error, cannot understand value",
    },
    "Dependencies file not found: ": {
        "fr": "Fichier de dépendances introuvable : ",
        "en": "Dependencies file not found: ",
    },
    "Execution: ": {
        "fr": "Execution : ",
        "en": "Execution: ",
    },
    "Current": {
        "fr": "Actuel",
        "en": "Current",
    },
    "Default": {
        "fr": "Défaut",
        "en": "Default",
    },
    "Reboot TODO ...": {
        "fr": "Reboot TODO ...",
        "en": "Reboot TODO ...",
    },
    "pip-audit - Check vulnerabilities on Python environments": {
        "fr": "pip-audit - Verifier les vulnérabilités sur les environnements Python",
        "en": "pip-audit - Check vulnerabilities on Python environments",
    },
    "Will execute:": {
        "fr": "Va exécuter :",
        "en": "Will execute:",
    },
    "Choose a version:": {
        "fr": "Choisir une version :",
        "en": "Choose a version:",
    },
    "Install type:": {
        "fr": "Type d'installation :",
        "en": "Install type:",
    },
    "Standard install (without extra modules)": {
        "fr": "Installation standard (sans modules extra)",
        "en": "Standard install (without extra modules)",
    },
    "Install with extra modules (CybroOdoo - large, slow)": {
        "fr": "Installation avec modules extra (CybroOdoo - gros, lent)",
        "en": "Install with extra modules (CybroOdoo - large, slow)",
    },
    # todo.json translatable prompt_descriptions
    "Test - Minimal base instance": {
        "fr": "Test - Instance de base minimale",
        "en": "Test - Minimal base instance",
    },
    "Open RobotLibre 🤖 minimal": {
        "fr": "Ouvrir RobotLibre 🤖 minimal",
        "en": "Open RobotLibre 🤖 minimal",
    },
    "Open RobotLibre 🤖 with search enabled": {
        "fr": "Ouvrir RobotLibre 🤖 en activant la recherche",
        "en": "Open RobotLibre 🤖 with search enabled",
    },
    "Open ERPLibre with TODO 🤖": {
        "fr": "Ouvrir ERPLibre avec TODO 🤖",
        "en": "Open ERPLibre with TODO 🤖",
    },
    "Update all erplibre_base on database test": {
        "fr": "🔄 Mise à jour de tous les erplibre_base sur la base de données test",
        "en": "🔄 Update all erplibre_base on database test",
    },
    "Show code status": {
        "fr": "🔍 Afficher le statut du code",
        "en": "🔍 Show code status",
    },
    "Stash all code": {
        "fr": "📦 Remiser tout le code",
        "en": "📦 Stash all code",
    },
    "Format modified code": {
        "fr": "🎨 Formater le code modifié",
        "en": "🎨 Format modified code",
    },
    # todo.py hardcoded prompt_descriptions
    "Mobile - Compile and run software": {
        "fr": "Mobile - Compiler et exécuter le logiciel",
        "en": "Mobile - Compile and run software",
    },
    "Upgrade Odoo - Migration Database": {
        "fr": "🚚 Mise à jour Odoo - Migration de base de données",
        "en": "🚚 Upgrade Odoo - Migration Database",
    },
    "Upgrade Poetry - Dependency of Odoo": {
        "fr": "📦 Mise à jour Poetry - Dépendances d'Odoo",
        "en": "📦 Upgrade Poetry - Dependency of Odoo",
    },
    "Open SHELL": {
        "fr": "🐚 Ouvrir le SHELL",
        "en": "🐚 Open SHELL",
    },
    "Upgrade Module": {
        "fr": "🧩 Mise à jour de module",
        "en": "🧩 Upgrade Module",
    },
    "Debug": {
        "fr": "🐛 Débogage",
        "en": "🐛 Debug",
    },
    "Migration module coverage": {
        "fr": "Couverture de migration des modules",
        "en": "Migration module coverage",
    },
    "What change between version": {
        "fr": "Quels changements entre les versions",
        "en": "What change between version",
    },
    "OCA guidelines": {
        "fr": "Directives OCA",
        "en": "OCA guidelines",
    },
    "OCA migration Odoo 19 milestone": {
        "fr": "Migration OCA Odoo 19 - Jalons",
        "en": "OCA migration Odoo 19 milestone",
    },
    "Download database to create backup (.zip)": {
        "fr": "Télécharger une base de données pour créer une sauvegarde (.zip)",
        "en": "Download database to create backup (.zip)",
    },
    "Restore from backup (.zip)": {
        "fr": "Restaurer a partir d'une sauvegarde (.zip)",
        "en": "Restore from backup (.zip)",
    },
    "Create backup (.zip)": {
        "fr": "Créer une sauvegarde (.zip)",
        "en": "Create backup (.zip)",
    },
    "Kill Odoo process from actual port": {
        "fr": "Terminer le processus Odoo du port actuel",
        "en": "Kill Odoo process from actual port",
    },
    "Kill git daemon server process": {
        "fr": "Terminer le processus du serveur git daemon",
        "en": "Kill git daemon server process",
    },
    "Git daemon process killed.": {
        "fr": "Processus git daemon terminé.",
        "en": "Git daemon process killed.",
    },
    "Generate all configuration": {
        "fr": "Générer toute la configuration",
        "en": "Generate all configuration",
    },
    "Generate from pre-configuration": {
        "fr": "Générer a partir de la pre-configuration",
        "en": "Generate from pre-configuration",
    },
    "Generate from backup file": {
        "fr": "Générer a partir d'un fichier de sauvegarde",
        "en": "Generate from backup file",
    },
    "Generate from database": {
        "fr": "Générer a partir de la base de données",
        "en": "Generate from database",
    },
    "base": {
        "fr": "base",
        "en": "base",
    },
    "base + code_generator": {
        "fr": "base + code_generator",
        "en": "base + code_generator",
    },
    "base + image_db": {
        "fr": "base + image_db",
        "en": "base + image_db",
    },
    "all": {
        "fr": "tout",
        "en": "all",
    },
    "Debug todo.py": {
        "fr": "Débogage todo.py",
        "en": "Debug todo.py",
    },
    # Test section
    "Test - Test an Odoo module": {
        "fr": "🧪 Test - Tester un module Odoo",
        "en": "🧪 Test - Test an Odoo module",
    },
    "Test an Odoo module on a temporary database!": {
        "fr": "Tester un module Odoo sur une base de données temporaire!",
        "en": "Test an Odoo module on a temporary database!",
    },
    "Test a module": {
        "fr": "Tester un module",
        "en": "Test a module",
    },
    "Test a module with code coverage": {
        "fr": "Tester un module avec couverture de code",
        "en": "Test a module with code coverage",
    },
    "ERPLibre unit tests": {
        "fr": "Tests unitaires ERPLibre",
        "en": "ERPLibre unit tests",
    },
    "Mail unit tests": {
        "fr": "Tests unitaires courriel",
        "en": "Mail unit tests",
    },
    "Analyse unit tests": {
        "fr": "Tests unitaires analyse",
        "en": "Analyse unit tests",
    },
    "Running unit tests": {
        "fr": "Exécution des tests unitaires",
        "en": "Running unit tests",
    },
    "All unit tests passed": {
        "fr": "Tous les tests unitaires ont réussi",
        "en": "All unit tests passed",
    },
    "Some unit tests failed, exit code": {
        "fr": "Des tests unitaires ont échoué, code de sortie",
        "en": "Some unit tests failed, exit code",
    },
    "Module name to test: ": {
        "fr": "Nom du module à tester : ",
        "en": "Module name to test: ",
    },
    "Temporary database name (default: test_todo_tmp): ": {
        "fr": "Nom de la base de données temporaire (défaut: test_todo_tmp) : ",
        "en": "Temporary database name (default: test_todo_tmp): ",
    },
    "Extra modules to install (comma-separated, empty for none): ": {
        "fr": "Modules supplémentaires à installer (séparés par des virgules, vide pour aucun) : ",
        "en": "Extra modules to install (comma-separated, empty for none): ",
    },
    "Log level (default: test): ": {
        "fr": "Niveau de log (défaut: test) : ",
        "en": "Log level (default: test): ",
    },
    "Creating temporary database": {
        "fr": "Création de la base de données temporaire",
        "en": "Creating temporary database",
    },
    "Installing modules": {
        "fr": "Installation des modules",
        "en": "Installing modules",
    },
    "Running tests": {
        "fr": "Exécution des tests",
        "en": "Running tests",
    },
    "Cleaning up temporary database": {
        "fr": "Suppression de la base de données temporaire",
        "en": "Cleaning up temporary database",
    },
    "Keep the temporary database? (y/N): ": {
        "fr": "Conserver la base de données temporaire? (o/N, défaut : non) : ",
        "en": "Keep the temporary database? (y/N, default: no): ",
    },
    "Database kept": {
        "fr": "Base de données conservée",
        "en": "Database kept",
    },
    "Tests completed successfully!": {
        "fr": "Tests terminés avec succès!",
        "en": "Tests completed successfully!",
    },
    "Tests failed with return code": {
        "fr": "Les tests ont échoué avec le code de retour",
        "en": "Tests failed with return code",
    },
    "Module name is required!": {
        "fr": "Le nom du module est requis!",
        "en": "Module name is required!",
    },
    # Git section
    "Git - Git tools": {
        "fr": "🌿 Git - Outils Git",
        "en": "🌿 Git - Git tools",
    },
    "Git management tools!": {
        "fr": "Outils de gestion Git!",
        "en": "Git management tools!",
    },
    "Local git server": {
        "fr": "Serveur git local",
        "en": "Local git server",
    },
    "Manage local git repository server!": {
        "fr": "Gérer le serveur de dépôts git local!",
        "en": "Manage local git repository server!",
    },
    "Deploy a local git server (~/.git-server)": {
        "fr": "Déployer un serveur git local (~/.git-server)",
        "en": "Deploy a local git server (~/.git-server)",
    },
    "Deploy a production git server (/srv/git, root required)": {
        "fr": "Déployer un serveur git production (/srv/git, root requis)",
        "en": "Deploy a production git server (/srv/git, root required)",
    },
    "Starting git server deployment...": {
        "fr": "Démarrage du déploiement du serveur git...",
        "en": "Starting git server deployment...",
    },
    "Local mode (~/.git-server)": {
        "fr": "Mode local (~/.git-server)",
        "en": "Local mode (~/.git-server)",
    },
    "Production mode (/srv/git, root required)": {
        "fr": "Mode production (/srv/git, root requis)",
        "en": "Production mode (/srv/git, root required)",
    },
    "Run all (init + remote + push + serve)": {
        "fr": "Tout exécuter (init + remote + push + serve)",
        "en": "Run all (init + remote + push + serve)",
    },
    "Init - Create bare repos": {
        "fr": "Init - Créer les bare repos",
        "en": "Init - Create bare repos",
    },
    "Remote - Add local remotes": {
        "fr": "Remote - Ajouter les remotes locaux",
        "en": "Remote - Add local remotes",
    },
    "Push - Push to local server": {
        "fr": "Push - Pousser vers le serveur local",
        "en": "Push - Push to local server",
    },
    "Serve - Start git daemon": {
        "fr": "Serve - Démarrer le daemon git",
        "en": "Serve - Start git daemon",
    },
    # Git remote add
    "Add a remote to a local repository": {
        "fr": "Ajouter un remote vers un dépôt local",
        "en": "Add a remote to a local repository",
    },
    "Remote name (default: localhost): ": {
        "fr": "Nom du remote (défaut: localhost) : ",
        "en": "Remote name (default: localhost): ",
    },
    "Repository address (e.g.: git://192.168.1.100/my-repo.git): ": {
        "fr": "Adresse du dépôt (ex: git://192.168.1.100/mon-repo.git) : ",
        "en": "Repository address (e.g.: git://192.168.1.100/my-repo.git): ",
    },
    "Repository address is required!": {
        "fr": "L'adresse du dépôt est requise!",
        "en": "Repository address is required!",
    },
    "Remote added successfully!": {
        "fr": "Remote ajouté avec succès!",
        "en": "Remote added successfully!",
    },
    "Error adding remote: ": {
        "fr": "Erreur lors de l'ajout du remote : ",
        "en": "Error adding remote: ",
    },
    # Git config vim
    "Configure git local editor to vim": {
        "fr": "Configuration git local par vim",
        "en": "Configure git local editor to vim",
    },
    "Generate git patch to /tmp": {
        "fr": "Générer une patch git dans /tmp",
        "en": "Generate git patch to /tmp",
    },
    "Git editor configured to vim successfully!": {
        "fr": "Éditeur git configuré sur vim avec succès!",
        "en": "Git editor configured to vim successfully!",
    },
    "Error during configuration: ": {
        "fr": "Erreur lors de la configuration : ",
        "en": "Error during configuration: ",
    },
    # GPT code - Claude automation
    "Add an automation with Claude in todo.py": {
        "fr": "Ajouter une automatisation avec Claude dans todo.py",
        "en": "Add an automation with Claude in todo.py",
    },
    "Description of the command to add: ": {
        "fr": "Description de la commande à ajouter : ",
        "en": "Description of the command to add: ",
    },
    "Bash command to execute: ": {
        "fr": "Commande bash à exécuter : ",
        "en": "Bash command to execute: ",
    },
    "Menu section (git/code/config/network/process): ": {
        "fr": "Section du menu (git/code/config/network/process) : ",
        "en": "Menu section (git/code/config/network/process): ",
    },
    "Automation added successfully in todo.json!": {
        "fr": "Automatisation ajoutée avec succès dans todo.json!",
        "en": "Automation added successfully in todo.json!",
    },
    "Error adding automation: ": {
        "fr": "Erreur lors de l'ajout de l'automatisation : ",
        "en": "Error adding automation: ",
    },
    # SSH Deploy section
    "Deploy - Deploy ERPLibre via SSH": {
        "fr": "Déploiement - Déployer ERPLibre via SSH",
        "en": "Deploy - Deploy ERPLibre via SSH",
    },
    "SSH deployment tools!": {
        "fr": "Outils de déploiement SSH!",
        "en": "SSH deployment tools!",
    },
    "SSH - Check connection": {
        "fr": "🔌 SSH - Vérifier la connexion",
        "en": "🔌 SSH - Check connection",
    },
    "SSH - Sync files (rsync)": {
        "fr": "🔄 SSH - Synchroniser les fichiers (rsync)",
        "en": "🔄 SSH - Sync files (rsync)",
    },
    "SSH - Install ERPLibre": {
        "fr": "📦 SSH - Installer ERPLibre",
        "en": "📦 SSH - Install ERPLibre",
    },
    "SSH - Start Odoo": {
        "fr": "🟢 SSH - Démarrer Odoo",
        "en": "🟢 SSH - Start Odoo",
    },
    "SSH - Stop Odoo": {
        "fr": "🔴 SSH - Arrêter Odoo",
        "en": "🔴 SSH - Stop Odoo",
    },
    "SSH - Restart Odoo": {
        "fr": "🔁 SSH - Redémarrer Odoo",
        "en": "🔁 SSH - Restart Odoo",
    },
    "SSH - Service status": {
        "fr": "📊 SSH - Statut du service",
        "en": "📊 SSH - Service status",
    },
    "SSH - View logs": {
        "fr": "📜 SSH - Voir les logs",
        "en": "📜 SSH - View logs",
    },
    "SSH - Run make target": {
        "fr": "🧰 SSH - Exécuter une cible make",
        "en": "🧰 SSH - Run make target",
    },
    "SSH - Install systemd service": {
        "fr": "🧩 SSH - Installer le service systemd",
        "en": "🧩 SSH - Install systemd service",
    },
    "SSH - Configure nginx + SSL": {
        "fr": "🔒 SSH - Configurer nginx + SSL",
        "en": "🔒 SSH - Configure nginx + SSL",
    },
    "Remote host (user@hostname or hostname): ": {
        "fr": "Hôte distant (user@hostname ou hostname) : ",
        "en": "Remote host (user@hostname or hostname): ",
    },
    "SSH user (default: erplibre): ": {
        "fr": "Utilisateur SSH (défaut: erplibre) : ",
        "en": "SSH user (default: erplibre): ",
    },
    "SSH port (default: 22): ": {
        "fr": "Port SSH (défaut: 22) : ",
        "en": "SSH port (default: 22): ",
    },
    "SSH key path (default: ~/.ssh/id_rsa, empty for none): ": {
        "fr": "Chemin de la clé SSH (défaut: ~/.ssh/id_rsa, vide pour aucune) : ",
        "en": "SSH key path (default: ~/.ssh/id_rsa, empty for none): ",
    },
    "Remote path (default: ~/erplibre_deploy_2): ": {
        "fr": "Chemin distant (défaut: ~/erplibre_deploy_2) : ",
        "en": "Remote path (default: ~/erplibre_deploy_2): ",
    },
    "Make target to run remotely: ": {
        "fr": "Cible make à exécuter à distance : ",
        "en": "Make target to run remotely: ",
    },
    "Domain name (e.g.: example.com): ": {
        "fr": "Nom de domaine (ex: example.com) : ",
        "en": "Domain name (e.g.: example.com): ",
    },
    "Admin email for SSL certificate: ": {
        "fr": "Email administrateur pour le certificat SSL : ",
        "en": "Admin email for SSL certificate: ",
    },
    "SSH host is required!": {
        "fr": "L'hôte SSH est requis!",
        "en": "SSH host is required!",
    },
    # Language selection
    "Choose language / Choisir la langue": {
        "fr": "Choisir la langue / Choose language",
        "en": "Choose language / Choisir la langue",
    },
    "French": {
        "fr": "Francais",
        "en": "French",
    },
    "English": {
        "fr": "Anglais",
        "en": "English",
    },
    "Language changed to: English": {
        "fr": "Langue changée pour : Francais",
        "en": "Language changed to: English",
    },
    "TODO execution time": {
        "fr": "Temps d'exécution TODO",
        "en": "TODO execution time",
    },
    "Keyboard interrupt": {
        "fr": "Interruption clavier",
        "en": "Keyboard interrupt",
    },
    # GPT code section
    "GPT code - AI assistant tools": {
        "fr": "🤖 GPT code - Outils d'assistant IA",
        "en": "🤖 GPT code - AI assistant tools",
    },
    "AI assistant tools for development!": {
        "fr": "Outils d'assistant IA pour le développement!",
        "en": "AI assistant tools for development!",
    },
    "Configure Claude Code configurations": {
        "fr": "Configurer les configurations Claude Code",
        "en": "Configure Claude Code configurations",
    },
    "Commit - OCA/Odoo commit command": {
        "fr": "Commit - Commande de commit OCA/Odoo",
        "en": "Commit - OCA/Odoo commit command",
    },
    "Todo Add Command - Add a command to todo.py menu": {
        "fr": "Todo Add Command - Ajouter une commande au menu todo.py",
        "en": "Todo Add Command - Add a command to todo.py menu",
    },
    "Enter your full name: ": {
        "fr": "Entrez votre nom complet : ",
        "en": "Enter your full name: ",
    },
    "Enter your email: ": {
        "fr": "Entrez votre courriel : ",
        "en": "Enter your email: ",
    },
    "Deploy Claude Code commands!": {
        "fr": "Déployer les commandes Claude Code!",
        "en": "Deploy Claude Code commands!",
    },
    "Show installed custom commands": {
        "fr": "Afficher les commandes personnalisées installées",
        "en": "Show installed custom commands",
    },
    "No custom commands found in ~/.claude/commands/": {
        "fr": "Aucune commande personnalisée trouvée dans ~/.claude/commands/",
        "en": "No custom commands found in ~/.claude/commands/",
    },
    "Claude Code custom commands:": {
        "fr": "Commandes personnalisées Claude Code :",
        "en": "Claude Code custom commands:",
    },
    "File already exists: ": {
        "fr": "Le fichier existe déjà : ",
        "en": "File already exists: ",
    },
    "Do you want to overwrite the file? (y/Y): ": {
        "fr": "Voulez-vous écraser le fichier? (y/Y) : ",
        "en": "Do you want to overwrite the file? (y/Y): ",
    },
    "Nothing to do.": {
        "fr": "Rien à faire.",
        "en": "Nothing to do.",
    },
    "File created successfully: ": {
        "fr": "Fichier créé avec succès : ",
        "en": "File created successfully: ",
    },
    "Error creating file: ": {
        "fr": "Erreur lors de la création du fichier : ",
        "en": "Error creating file: ",
    },
    # NTFY section
    "Deploy - Install NTFY notification server": {
        "fr": "🔔 Déployer - Installer le serveur de notifications NTFY",
        "en": "🔔 Deploy - Install NTFY notification server",
    },
    "Deploy a local NTFY push notification server (Ubuntu/Arch)": {
        "fr": "Déployer un serveur local de notifications NTFY (Ubuntu/Arch)",
        "en": "Deploy a local NTFY push notification server (Ubuntu/Arch)",
    },
    "NTFY server port (default: 8080): ": {
        "fr": "Port du serveur NTFY (défaut : 8080) : ",
        "en": "NTFY server port (default: 8080): ",
    },
    "NTFY base URL": {
        "fr": "URL de base NTFY",
        "en": "NTFY base URL",
    },
    "Installing NTFY server (requires sudo)...": {
        "fr": "Installation du serveur NTFY (sudo requis)...",
        "en": "Installing NTFY server (requires sudo)...",
    },
    "NTFY server installed and started successfully!": {
        "fr": "Serveur NTFY installé et démarré avec succès!",
        "en": "NTFY server installed and started successfully!",
    },
    "Error installing NTFY server: ": {
        "fr": "Erreur lors de l'installation du serveur NTFY : ",
        "en": "Error installing NTFY server: ",
    },
    "NTFY install script not found: ": {
        "fr": "Script d'installation NTFY introuvable : ",
        "en": "NTFY install script not found: ",
    },
    # QEMU / KVM (libvirt) VM deployment
    "QEMU/KVM - Deploy an Ubuntu VM (libvirt)": {
        "fr": "💻 QEMU/KVM - Déployer une VM Ubuntu (libvirt)",
        "en": "💻 QEMU/KVM - Deploy an Ubuntu VM (libvirt)",
    },
    "Deploy a QEMU/KVM virtual machine (libvirt)!": {
        "fr": "Déployer une machine virtuelle QEMU/KVM (libvirt) !",
        "en": "Deploy a QEMU/KVM virtual machine (libvirt)!",
    },
    "QEMU deploy script not found: ": {
        "fr": "Script de déploiement QEMU introuvable : ",
        "en": "QEMU deploy script not found: ",
    },
    "Deploy a new VM": {
        "fr": "Déployer une nouvelle VM",
        "en": "Deploy a new VM",
    },
    "Preview a deployment (dry-run, no sudo)": {
        "fr": "🔍 Prévisualiser un déploiement (dry-run, sans sudo)",
        "en": "🔍 Preview a deployment (dry-run, no sudo)",
    },
    "Download a cloud image only": {
        "fr": "⬇  Télécharger seulement une image cloud",
        "en": "⬇  Download a cloud image only",
    },
    "List VMs (virsh list --all)": {
        "fr": "📋 Lister les VM (virsh list --all)",
        "en": "📋 List VMs (virsh list --all)",
    },
    "Show a VM IP address": {
        "fr": "🌐 Afficher l'adresse IP d'une VM",
        "en": "🌐 Show a VM IP address",
    },
    "List available images and specs": {
        "fr": "🗂  Lister les images disponibles et leurs specs",
        "en": "🗂  List available images and specs",
    },
    "Distribution:": {
        "fr": "Distribution :",
        "en": "Distribution:",
    },
    "Choice (number or name, default: ubuntu): ": {
        "fr": "Choix (numéro ou nom, défaut : ubuntu) : ",
        "en": "Choice (number or name, default: ubuntu): ",
    },
    "Invalid selection, using ubuntu": {
        "fr": "Sélection invalide, utilisation d'ubuntu",
        "en": "Invalid selection, using ubuntu",
    },
    "Version for": {
        "fr": "Version des",
        "en": "Version for",
    },
    "Versions for": {
        "fr": "Versions des",
        "en": "Versions of",
    },
    "Architecture:": {
        "fr": "Architecture :",
        "en": "Architecture:",
    },
    "native": {
        "fr": "native",
        "en": "native",
    },
    "IBM Z — emulated, slow on x86; Ubuntu only": {
        "fr": "IBM Z — émulé, lent sur x86 ; Ubuntu uniquement",
        "en": "IBM Z — emulated, slow on x86; Ubuntu only",
    },
    "IBM Z — emulated, slow; Ubuntu only": {
        "fr": "IBM Z — émulé, lent ; Ubuntu uniquement",
        "en": "IBM Z — emulated, slow; Ubuntu only",
    },
    "ARM 64-bit — emulated, slow": {
        "fr": "ARM 64 bits — émulé, lent",
        "en": "ARM 64-bit — emulated, slow",
    },
    "emulated, slow": {
        "fr": "émulé, lent",
        "en": "emulated, slow",
    },
    "This architecture is emulated (TCG): boot and install are"
    " much slower than the native one.": {
        "fr": "Cette architecture est émulée (TCG) : le boot et l'installation"
        " sont bien plus lents que l'architecture native.",
        "en": "This architecture is emulated (TCG): boot and install are"
        " much slower than the native one.",
    },
    "images for this arch only exist for:": {
        "fr": "images pour cette architecture disponibles seulement pour :",
        "en": "images for this arch only exist for:",
    },
    "All supported architectures": {
        "fr": "Toutes les architectures supportées",
        "en": "All supported architectures",
    },
    "installation": {
        "fr": "installation",
        "en": "installation",
    },
    "Resources per VM (x1 = catalog minimum):": {
        "fr": "Ressources par VM (x1 = minimum catalogue) :",
        "en": "Resources per VM (x1 = catalog minimum):",
    },
    "Host:": {
        "fr": "Hôte :",
        "en": "Host:",
    },
    "free": {
        "fr": "libres",
        "en": "free",
    },
    "free RAM unknown": {
        "fr": "RAM libre inconnue",
        "en": "free RAM unknown",
    },
    "> host free RAM": {
        "fr": "> RAM libre de l'hôte",
        "en": "> host free RAM",
    },
    "total RAM": {
        "fr": "RAM totale",
        "en": "total RAM",
    },
    "Choice (1-4, default 1):": {
        "fr": "Choix (1-4, défaut 1) :",
        "en": "Choice (1-4, default 1):",
    },
    "Choice (1-5, default 1):": {
        "fr": "Choix (1-5, défaut 1) :",
        "en": "Choice (1-5, default 1):",
    },
    "Custom - set vCPU, RAM and disk": {
        "fr": "Personnalisé — choisir vCPU, RAM et disque",
        "en": "Custom — set vCPU, RAM and disk",
    },
    "custom": {
        "fr": "personnalisé",
        "en": "custom",
    },
    "varies": {
        "fr": "varié",
        "en": "varies",
    },
    "vCPU per VM, blank = keep": {
        "fr": "vCPU par VM, vide = garder",
        "en": "vCPU per VM, blank = keep",
    },
    "New vCPU count, blank = keep": {
        "fr": "Nouveau nombre de vCPU, vide = garder",
        "en": "New vCPU count, blank = keep",
    },
    "Invalid vCPU count.": {
        "fr": "Nombre de vCPU invalide.",
        "en": "Invalid vCPU count.",
    },
    "More vCPU than host cores": {
        "fr": "Plus de vCPU que de cœurs sur l'hôte",
        "en": "More vCPU than host cores",
    },
    "> host cores": {
        "fr": "> cœurs de l'hôte",
        "en": "> host cores",
    },
    "Total vCPU (all running):": {
        "fr": "vCPU total (toutes démarrées) :",
        "en": "Total vCPU (all running):",
    },
    "Deploy VM(s) (one or many)": {
        "fr": "🚀 Déployer une ou plusieurs VM",
        "en": "🚀 Deploy VM(s) (one or many)",
    },
    "Deploy ERPLibre VM(s)!": {
        "fr": "Déployer une ou plusieurs VM ERPLibre !",
        "en": "Deploy ERPLibre VM(s)!",
    },
    "VM names (default = auto):": {
        "fr": "Noms des VM (défaut = auto) :",
        "en": "VM names (default = auto):",
    },
    "Rename which VMs? (numbers, comma-separated; blank = none): ": {
        "fr": "Renommer quelles VM ? (numéros séparés par des virgules ; "
        "vide = aucune) : ",
        "en": "Rename which VMs? (numbers, comma-separated; blank = none): ",
    },
    "->": {
        "fr": "->",
        "en": "->",
    },
    "VMs (default = no change):": {
        "fr": "VM (défaut = aucune modification) :",
        "en": "VMs (default = no change):",
    },
    "Modify which VMs? (numbers, comma-separated; blank = none): ": {
        "fr": "Modifier quelles VM ? (numéros séparés par des virgules ; "
        "vide = aucune) : ",
        "en": "Modify which VMs? (numbers, comma-separated; blank = none): ",
    },
    "new name (blank = keep):": {
        "fr": "nouveau nom (vide = garder) :",
        "en": "new name (blank = keep):",
    },
    "New disk size in G, blank = keep": {
        "fr": "Nouvelle taille disque en G, vide = garder",
        "en": "New disk size in G, blank = keep",
    },
    "New RAM in MB, blank = keep": {
        "fr": "Nouvelle RAM en Mo, vide = garder",
        "en": "New RAM in MB, blank = keep",
    },
    "Duplicate names detected; keeping as entered.": {
        "fr": "Noms en double détectés ; conservés tels quels.",
        "en": "Duplicate names detected; keeping as entered.",
    },
    "Preview (dry-run):": {
        "fr": "Aperçu (dry-run) :",
        "en": "Preview (dry-run):",
    },
    "(includes emulated architectures — some VMs are slow)": {
        "fr": "(inclut des architectures émulées — certaines VM sont lentes)",
        "en": "(includes emulated architectures — some VMs are slow)",
    },
    "install monitoring": {
        "fr": "suivi d'installation",
        "en": "install monitoring",
    },
    "Navigation telemetry (TUI)": {
        "fr": "📊 Télémétrie de navigation (TUI)",
        "en": "📊 Navigation telemetry (TUI)",
    },
    "Configuration": {
        "fr": "⚙  Configuration",
        "en": "⚙  Configuration",
    },
    "Interface": {
        "fr": "Interface",
        "en": "Interface",
    },
    "Maintenance": {
        "fr": "Maintenance",
        "en": "Maintenance",
    },
    "Language / Langue": {
        "fr": "🌐 Langue / Language",
        "en": "🌐 Language / Langue",
    },
    "QEMU deployment interface": {
        "fr": "🖥  Interface de déploiement QEMU",
        "en": "🖥  QEMU deployment interface",
    },
    "Display while deploying": {
        "fr": "📜 Affichage pendant le déploiement",
        "en": "📜 Display while deploying",
    },
    "Ask every time": {
        "fr": "Demander à chaque fois",
        "en": "Ask every time",
    },
    "TUI form": {
        "fr": "Formulaire TUI",
        "en": "TUI form",
    },
    "Classic questions (line by line)": {
        "fr": "Questions classiques (ligne par ligne)",
        "en": "Classic questions (line by line)",
    },
    "CLI output (easy to copy)": {
        "fr": "Sortie CLI (facile à copier)",
        "en": "CLI output (easy to copy)",
    },
    "TUI, collapsible blocks per VM": {
        "fr": "TUI, blocs repliables par VM",
        "en": "TUI, collapsible blocks per VM",
    },
    "Choice (number, blank = keep):": {
        "fr": "Choix (numéro, vide = garder) :",
        "en": "Choice (number, blank = keep):",
    },
    "SSH port forwarding (open Odoo in the browser)": {
        "fr": "🔌 Redirection de port SSH (ouvrir Odoo dans le navigateur)",
        "en": "🔌 SSH port forwarding (open Odoo in the browser)",
    },
    "SSH port forwarding": {
        "fr": "Redirection de port SSH",
        "en": "SSH port forwarding",
    },
    "Host (number or name):": {
        "fr": "Hôte (numéro ou nom) :",
        "en": "Host (number or name):",
    },
    "Remote port (default:": {
        "fr": "Port distant (défaut :",
        "en": "Remote port (default:",
    },
    "Local port (default:": {
        "fr": "Port local (défaut :",
        "en": "Local port (default:",
    },
    "virsh is missing: libvirt is not installed here.": {
        "fr": "virsh est absent : libvirt n'est pas installé ici.",
        "en": "virsh is missing: libvirt is not installed here.",
    },
    "Every VM command will fail until it is.": {
        "fr": "Toutes les commandes VM échoueront tant que ce sera le cas.",
        "en": "Every VM command will fail until it is.",
    },
    "Install the QEMU/libvirt tools now? (Y/n): ": {
        "fr": "Installer les outils QEMU/libvirt maintenant ? "
        "(O/n, défaut : oui) : ",
        "en": "Install the QEMU/libvirt tools now? (Y/n, default: yes): ",
    },
    "libvirt is available.": {
        "fr": "libvirt est disponible.",
        "en": "libvirt is available.",
    },
    "virsh still missing; a reboot may be required.": {
        "fr": "virsh toujours absent ; un redémarrage est peut-être requis.",
        "en": "virsh still missing; a reboot may be required.",
    },
    "No SSH public key found in ~/.ssh.": {
        "fr": "Aucune clé publique SSH trouvée dans ~/.ssh.",
        "en": "No SSH public key found in ~/.ssh.",
    },
    "Without one the VMs start with no SSH access.": {
        "fr": "Sans elle, les VM démarrent sans accès SSH.",
        "en": "Without one the VMs start with no SSH access.",
    },
    "Generate one now? (Y/n): ": {
        "fr": "En générer une maintenant ? (O/n, défaut : oui) : ",
        "en": "Generate one now? (Y/n, default: yes): ",
    },
    "Checking the remote port...": {
        "fr": "Vérification du port distant...",
        "en": "Checking the remote port...",
    },
    "Nothing is listening on port": {
        "fr": "Rien n'écoute sur le port",
        "en": "Nothing is listening on port",
    },
    "of": {
        "fr": "de",
        "en": "of",
    },
    "Start the service there, or continue anyway.": {
        "fr": "Démarrer le service là-bas, ou continuer quand même.",
        "en": "Start the service there, or continue anyway.",
    },
    "Continue anyway? (y/N): ": {
        "fr": "Continuer quand même ? (o/N, défaut : non) : ",
        "en": "Continue anyway? (y/N, default: no): ",
    },
    "Could not probe the remote port; going on.": {
        "fr": "Impossible de sonder le port distant ; on continue.",
        "en": "Could not probe the remote port; going on.",
    },
    "Local port already in use:": {
        "fr": "Port local déjà occupé :",
        "en": "Local port already in use:",
    },
    "Try anyway? (y/N): ": {
        "fr": "Essayer quand même ? (o/N, défaut : non) : ",
        "en": "Try anyway? (y/N, default: no): ",
    },
    "Local port differs from the remote one.": {
        "fr": "Le port local diffère du port distant.",
        "en": "Local port differs from the remote one.",
    },
    "Odoo redirects using web.base.url; check it": {
        "fr": "Odoo redirige d'après web.base.url ; vérifier qu'il",
        "en": "Odoo redirects using web.base.url; check it",
    },
    "matches http://localhost:": {
        "fr": "vaut bien http://localhost:",
        "en": "matches http://localhost:",
    },
    "Ctrl+C closes the tunnel.": {
        "fr": "Ctrl+C referme le tunnel.",
        "en": "Ctrl+C closes the tunnel.",
    },
    "Tunnel closed.": {
        "fr": "Tunnel refermé.",
        "en": "Tunnel closed.",
    },
    "SSH configuration (~/.ssh/config, ProxyJump)": {
        "fr": "🔑 Configuration SSH (~/.ssh/config, ProxyJump)",
        "en": "🔑 SSH configuration (~/.ssh/config, ProxyJump)",
    },
    "SSH configuration for QEMU VMs": {
        "fr": "Configuration SSH des VM QEMU",
        "en": "SSH configuration for QEMU VMs",
    },
    "Where should the machines come from?": {
        "fr": "D'où viennent les machines à configurer ?",
        "en": "Where should the machines come from?",
    },
    "Local QEMU VMs (virsh)": {
        "fr": "VM QEMU locales (virsh)",
        "en": "Local QEMU VMs (virsh)",
    },
    "Hosts from ~/.ssh/config": {
        "fr": "Hôtes de ~/.ssh/config",
        "en": "Hosts from ~/.ssh/config",
    },
    "Type a host or an IP": {
        "fr": "Saisir un hôte ou une IP",
        "en": "Type a host or an IP",
    },
    "~/.ssh/config holds no host.": {
        "fr": "~/.ssh/config ne contient aucun hôte.",
        "en": "~/.ssh/config holds no host.",
    },
    "Which hosts? (numbers, comma-separated; blank = all): ": {
        "fr": "Quels hôtes ? (numéros séparés par des virgules ; "
        "vide = tous) : ",
        "en": "Which hosts? (numbers, comma-separated; blank = all): ",
    },
    "Host or IP:": {
        "fr": "Hôte ou IP :",
        "en": "Host or IP:",
    },
    "User": {
        "fr": "Utilisateur",
        "en": "User",
    },
    "Name for ~/.ssh/config": {
        "fr": "Nom pour ~/.ssh/config",
        "en": "Name for ~/.ssh/config",
    },
    "Depth (1 = these machines only, default:": {
        "fr": "Profondeur (1 = ces machines seulement, défaut :",
        "en": "Depth (1 = these machines only, default:",
    },
    "Which VMs? (numbers, comma-separated; blank = all): ": {
        "fr": "Quelles VM ? (numéros séparés par des virgules ; "
        "vide = toutes) : ",
        "en": "Which VMs? (numbers, comma-separated; blank = all): ",
    },
    "Depth (default:": {
        "fr": "Profondeur (défaut :",
        "en": "Depth (default:",
    },
    "entry": {
        "fr": "entrée",
        "en": "entry",
    },
    "written": {
        "fr": "écrite(s)",
        "en": "written",
    },
    "skipped": {
        "fr": "ignorée(s)",
        "en": "skipped",
    },
    "Level": {
        "fr": "Niveau",
        "en": "Level",
    },
    "machines to probe": {
        "fr": "machines à sonder",
        "en": "machines to probe",
    },
    "SSH refused the identity.": {
        "fr": "SSH a refusé l'identité.",
        "en": "SSH refused the identity.",
    },
    "Existing key:": {
        "fr": "Clé existante :",
        "en": "Existing key:",
    },
    "Deploy it on this host (ssh-copy-id)? (Y/n): ": {
        "fr": "La déployer sur cet hôte (ssh-copy-id) ? "
        "(O/n, défaut : oui) : ",
        "en": "Deploy it on this host (ssh-copy-id)? (Y/n, default: yes): ",
    },
    "No SSH key in ~/.ssh.": {
        "fr": "Aucune clé SSH dans ~/.ssh.",
        "en": "No SSH key in ~/.ssh.",
    },
    "Create one and deploy it? (Y/n): ": {
        "fr": "En créer une et la déployer ? (O/n, défaut : oui) : ",
        "en": "Create one and deploy it? (Y/n, default: yes): ",
    },
    "access refused": {
        "fr": "accès refusé",
        "en": "access refused",
    },
    "timed out": {
        "fr": "délai dépassé",
        "en": "timed out",
    },
    "unreachable": {
        "fr": "injoignable",
        "en": "unreachable",
    },
    "no QEMU/libvirt here": {
        "fr": "pas de QEMU/libvirt ici",
        "en": "no QEMU/libvirt here",
    },
    "virsh present but not accessible": {
        "fr": "virsh présent mais inaccessible (droits)",
        "en": "virsh present but not accessible (permissions)",
    },
    "Add the user to the libvirt group there:": {
        "fr": "Ajoutez l'utilisateur au groupe libvirt là-bas :",
        "en": "Add the user to the libvirt group there:",
    },
    "QEMU present, no VM": {
        "fr": "QEMU présent, aucune VM",
        "en": "QEMU present, no VM",
    },
    "Create the SSH key if missing and deploy it? (Y/n): ": {
        "fr": "Créer la clé SSH si absente et la déployer ? "
        "(O/n, défaut : oui) : ",
        "en": "Create the SSH key if missing and deploy it? "
        "(Y/n, default: yes): ",
    },
    "Generating an ed25519 SSH key": {
        "fr": "Génération d'une clé SSH ed25519",
        "en": "Generating an ed25519 SSH key",
    },
    "Cannot generate the key": {
        "fr": "Impossible de générer la clé",
        "en": "Cannot generate the key",
    },
    "Deploying the key on": {
        "fr": "Déploiement de la clé sur",
        "en": "Deploying the key on",
    },
    "host": {
        "fr": "hôte",
        "en": "host",
    },
    "key already accepted": {
        "fr": "clé déjà acceptée",
        "en": "key already accepted",
    },
    "deployed": {
        "fr": "déployée(s)",
        "en": "deployed",
    },
    "already there": {
        "fr": "déjà en place",
        "en": "already there",
    },
    "virt-manager detected": {
        "fr": "virt-manager détecté",
        "en": "virt-manager detected",
    },
    "virt-manager: every connection already there": {
        "fr": "virt-manager : toutes les connexions sont déjà là",
        "en": "virt-manager: every connection already there",
    },
    "Add the missing connections to virt-manager? (Y/n): ": {
        "fr": "Ajouter les connexions manquantes à virt-manager ? "
        "(O/n, défaut : oui) : ",
        "en": "Add the missing connections to virt-manager? "
        "(Y/n, default: yes): ",
    },
    "Restart virt-manager to see the new connections": {
        "fr": "Redémarrer virt-manager pour voir les nouvelles connexions",
        "en": "Restart virt-manager to see the new connections",
    },
    "the names apply live": {
        "fr": "les noms s'appliquent à chaud",
        "en": "the names apply live",
    },
    "SSH hosts written": {
        "fr": "Hôtes SSH écrits",
        "en": "SSH hosts written",
    },
    "via": {
        "fr": "via",
        "en": "via",
    },
    "Odoo migration interface": {
        "fr": "🚚 Interface de la migration Odoo",
        "en": "🚚 Odoo migration interface",
    },
    "modules of the list have no code in the active Odoo:": {
        "fr": "modules de la liste n'ont plus de code dans l'Odoo actif :",
        "en": "modules of the list have no code in the active Odoo:",
    },
    "Odoo cannot uninstall a module whose code is gone;": {
        "fr": "Odoo ne peut pas désinstaller un module dont le code a"
        " disparu ;",
        "en": "Odoo cannot uninstall a module whose code is gone;",
    },
    "one of them fails the whole uninstall command.": {
        "fr": "un seul d'entre eux fait échouer toute la désinstallation.",
        "en": "one of them fails the whole uninstall command.",
    },
    "are present and can be uninstalled:": {
        "fr": "sont présents et peuvent être désinstallés :",
        "en": "are present and can be uninstalled:",
    },
    "No module of the list is present.": {
        "fr": "Aucun module de la liste n'est présent.",
        "en": "No module of the list is present.",
    },
    "Uninstall the present ones, skip the missing": {
        "fr": "Désinstaller les présents, ignorer les manquants",
        "en": "Uninstall the present ones, skip the missing",
    },
    "Try the whole list anyway (it will fail)": {
        "fr": "Tout tenter quand même (ça échouera)",
        "en": "Try the whole list anyway (it will fail)",
    },
    "Uninstall nothing, continue": {
        "fr": "Ne rien désinstaller, continuer",
        "en": "Uninstall nothing, continue",
    },
    "Nothing uninstalled.": {
        "fr": "Rien de désinstallé.",
        "en": "Nothing uninstalled.",
    },
    "Check the COW views that drifted": {
        "fr": "Vérifier les vues COW en retard sur leur vue module",
        "en": "Check the COW views that drifted",
    },
    "Tool not found": {
        "fr": "Outil introuvable",
        "en": "Tool not found",
    },
    "To reset one of them onto its module view:": {
        "fr": "Pour réinitialiser l'une d'elles sur sa vue module :",
        "en": "To reset one of them onto its module view:",
    },
    "Read the diff first: a copy can hold a customisation.": {
        "fr": "Lire le diff d'abord : une copie peut porter une"
        " personnalisation.",
        "en": "Read the diff first: a copy can hold a customisation.",
    },
    "Migration statistics (read-only)": {
        "fr": "📊 Statistiques de la migration (lecture seule)",
        "en": "📊 Migration statistics (read-only)",
    },
    "Choice (0-3, default 1): ": {
        "fr": "Choix (0-3, défaut 1) : ",
        "en": "Choice (0-3, default 1): ",
    },
    "Migration statistics": {
        "fr": "Statistiques de la migration",
        "en": "Migration statistics",
    },
    "elapsed": {
        "fr": "écoulé",
        "en": "elapsed",
    },
    "Level reached": {
        "fr": "Niveau atteint",
        "en": "Level reached",
    },
    "Modules": {
        "fr": "Modules",
        "en": "Modules",
    },
    "modules": {
        "fr": "modules",
        "en": "modules",
    },
    "At the start": {
        "fr": "Au départ",
        "en": "At the start",
    },
    "Removed in total": {
        "fr": "Supprimés au total",
        "en": "Removed in total",
    },
    "Reported missing": {
        "fr": "Signalés manquants",
        "en": "Reported missing",
    },
    "Duplicated": {
        "fr": "En double",
        "en": "Duplicated",
    },
    "Migration fixes": {
        "fr": "Correctifs de migration",
        "en": "Migration fixes",
    },
    "COW views": {
        "fr": "Vues COW",
        "en": "COW views",
    },
    "views": {
        "fr": "vues",
        "en": "views",
    },
    "no snapshot": {
        "fr": "aucun instantané",
        "en": "no snapshot",
    },
    "Journal": {
        "fr": "Journal",
        "en": "Journal",
    },
    "commands": {
        "fr": "commandes",
        "en": "commands",
    },
    "recorded decisions": {
        "fr": "décisions annotées",
        "en": "recorded decisions",
    },
    "Removed modules, with their reason": {
        "fr": "Modules supprimés, avec leur justification",
        "en": "Removed modules, with their reason",
    },
    "Removed modules, comma-separated (copy)": {
        "fr": "Modules supprimés, séparés par des virgules (à copier)",
        "en": "Removed modules, comma-separated (copy)",
    },
    "COW views: snapshots and differences": {
        "fr": "Vues COW : instantanés et différences",
        "en": "COW views: snapshots and differences",
    },
    "Recorded decisions (journal)": {
        "fr": "Décisions annotées (journal)",
        "en": "Recorded decisions (journal)",
    },
    "Executed commands (last 30)": {
        "fr": "Commandes exécutées (30 dernières)",
        "en": "Executed commands (last 30)",
    },
    "nothing recorded": {
        "fr": "rien d'annoté",
        "en": "nothing recorded",
    },
    "Need two snapshots to diff.": {
        "fr": "Il faut deux instantanés pour comparer.",
        "en": "Need two snapshots to diff.",
    },
    "Diff which two? (e.g. 1,2 — blank to skip)": {
        "fr": "Comparer lesquels ? (ex. 1,2 — vide pour passer)",
        "en": "Diff which two? (e.g. 1,2 — blank to skip)",
    },
    "No migration in progress to resume.": {
        "fr": "Aucune migration en cours à reprendre.",
        "en": "No migration in progress to resume.",
    },
    "Quit without doing anything": {
        "fr": "Quitter sans rien faire",
        "en": "Quit without doing anything",
    },
    "Version bumps": {
        "fr": "Montées de version",
        "en": "Version bumps",
    },
    "Step": {
        "fr": "Étape",
        "en": "Step",
    },
    "Detail": {
        "fr": "Détail",
        "en": "Detail",
    },
    "Enter on a step or a version = replay from there": {
        "fr": "Entrée sur une étape ou une version = rejouer depuis là",
        "en": "Enter on a step or a version = replay from there",
    },
    "New migration": {
        "fr": "Nouvelle migration",
        "en": "New migration",
    },
    "Keep the zip only": {
        "fr": "Garder seulement le zip",
        "en": "Keep the zip only",
    },
    "Reset all preferences": {
        "fr": "🧹 Réinitialiser toutes les préférences",
        "en": "🧹 Reset all preferences",
    },
    "Preferences reset": {
        "fr": "Préférences réinitialisées",
        "en": "Preferences reset",
    },
    "Interface:": {
        "fr": "Interface :",
        "en": "Interface:",
    },
    "(change the default in TODO > Configuration)": {
        "fr": "(changer le défaut dans TODO > Configuration)",
        "en": "(change the default in TODO > Configuration)",
    },
    "Loading (VM list, branches)...": {
        "fr": "Chargement (liste des VM, branches)...",
        "en": "Loading (VM list, branches)...",
    },
    "Architecture": {
        "fr": "Architecture",
        "en": "Architecture",
    },
    "Resources per VM": {
        "fr": "Ressources par VM",
        "en": "Resources per VM",
    },
    "Install ERPLibre": {
        "fr": "Installer ERPLibre",
        "en": "Install ERPLibre",
    },
    "Production (/opt, confined)": {
        "fr": "Production (/opt, confiné)",
        "en": "Production (/opt, confined)",
    },
    "Monitoring dashboard": {
        "fr": "Tableau de bord de suivi",
        "en": "Monitoring dashboard",
    },
    "Add each VM to ~/.ssh/config": {
        "fr": "Ajouter chaque VM à ~/.ssh/config",
        "en": "Add each VM to ~/.ssh/config",
    },
    "Parallelism": {
        "fr": "Parallélisme",
        "en": "Parallelism",
    },
    "Name": {
        "fr": "Nom",
        "en": "Name",
    },
    "Distro": {
        "fr": "Distro",
        "en": "Distro",
    },
    "Version": {
        "fr": "Version",
        "en": "Version",
    },
    "Arch": {
        "fr": "Archi",
        "en": "Arch",
    },
    "vCPU": {
        "fr": "vCPU",
        "en": "vCPU",
    },
    "RAM (MB)": {
        "fr": "RAM (Mo)",
        "en": "RAM (MB)",
    },
    "cloud-init still running after 20 min - install starts anyway"
    " (it waits for cloud-init first)": {
        "fr": "cloud-init tourne encore apres 20 min - l'installation demarre"
        " quand meme (elle attend d'abord cloud-init)",
        "en": "cloud-init still running after 20 min - install starts anyway"
        " (it waits for cloud-init first)",
    },
    "Waiting for cloud-init to finish (up to 15 min)": {
        "fr": "Attente de la fin de cloud-init (jusqu'a 15 min)",
        "en": "Waiting for cloud-init to finish (up to 15 min)",
    },
    "cloud-init:": {
        "fr": "cloud-init :",
        "en": "cloud-init:",
    },
    "WARNING libvirt unreachable: the IP will not be refreshed"
    " (libvirt group? re-login required)": {
        "fr": "ATTENTION libvirt injoignable : l'IP ne sera pas rafraichie"
        " (groupe libvirt ? reconnexion necessaire)",
        "en": "WARNING libvirt unreachable: the IP will not be refreshed"
        " (libvirt group? re-login required)",
    },
    "DHCP lease moved:": {
        "fr": "bail DHCP deplace :",
        "en": "DHCP lease moved:",
    },
    "An install is still running:": {
        "fr": "Une installation est encore en cours :",
        "en": "An install is still running:",
    },
    "VM(s) in progress": {
        "fr": "VM en cours",
        "en": "VM(s) in progress",
    },
    "Last activity:": {
        "fr": "Dernière activité il y a :",
        "en": "Last activity:",
    },
    "Reopen that monitoring": {
        "fr": "Rouvrir ce suivi",
        "en": "Reopen that monitoring",
    },
    "Deploy anyway (new run)": {
        "fr": "Déployer quand même (nouveau run)",
        "en": "Deploy anyway (new run)",
    },
    "Choice (number, blank = reopen): ": {
        "fr": "Choix (numéro, vide = rouvrir) : ",
        "en": "Choice (number, blank = reopen): ",
    },
    "Python interpreter:": {
        "fr": "Interpreteur Python :",
        "en": "Python interpreter:",
    },
    "mise (precompiled, faster)": {
        "fr": "mise (precompile, plus rapide)",
        "en": "mise (precompiled, faster)",
    },
    "pyenv (compiles from source)": {
        "fr": "pyenv (compile depuis les sources)",
        "en": "pyenv (compiles from source)",
    },
    "Choice (number, blank = mise): ": {
        "fr": "Choix (numero, vide = mise) : ",
        "en": "Choice (number, blank = mise): ",
    },
    "mise has no binary for:": {
        "fr": "mise ne publie pas de binaire pour :",
        "en": "mise has no binary for:",
    },
    "those VMs use pyenv": {
        "fr": "ces VM utiliseront pyenv",
        "en": "those VMs use pyenv",
    },
    "Installing mise (precompiled Python)": {
        "fr": "Installation de mise (Python precompile)",
        "en": "Installing mise (precompiled Python)",
    },
    "VM type:": {
        "fr": "Type de VM :",
        "en": "VM type:",
    },
    "Server (no graphical interface)": {
        "fr": "Serveur (sans interface graphique)",
        "en": "Server (no graphical interface)",
    },
    "Graphical (server + GNOME desktop)": {
        "fr": "Graphique (serveur + bureau GNOME)",
        "en": "Graphical (server + GNOME desktop)",
    },
    "server": {
        "fr": "serveur",
        "en": "server",
    },
    "Graphical (server + desktop):": {
        "fr": "Graphique (serveur + bureau) :",
        "en": "Graphical (server + desktop):",
    },
    "Installing the desktop (long):": {
        "fr": "Installation du bureau (long) :",
        "en": "Installing the desktop (long):",
    },
    "Choice (number, blank = server): ": {
        "fr": "Choix (numero, vide = serveur) : ",
        "en": "Choice (number, blank = server): ",
    },
    "Installing the GNOME desktop (long)": {
        "fr": "Installation du bureau GNOME (long)",
        "en": "Installing the GNOME desktop (long)",
    },
    "openSUSE mirror:": {
        "fr": "miroir openSUSE :",
        "en": "openSUSE mirror:",
    },
    "Remote desktop:": {
        "fr": "Bureau distant :",
        "en": "Remote desktop:",
    },
    "One run per install": {
        "fr": "une execution par installation",
        "en": "One run per install",
    },
    "limit to host cores": {
        "fr": "limiter au nombre de coeurs de l'hote",
        "en": "limit to host cores",
    },
    "free value…": {
        "fr": "valeur libre…",
        "en": "free value…",
    },
    "Disk (e.g. 250G, 1.5T)": {
        "fr": "Disque (ex. 250G, 1,5T)",
        "en": "Disk (e.g. 250G, 1.5T)",
    },
    "all archs": {
        "fr": "toutes",
        "en": "all",
    },
    "Tick what to deploy": {
        "fr": "Cocher ce qu'on veut déployer",
        "en": "Tick what to deploy",
    },
    "F7 main versions · F6 all": {
        "fr": "F7 versions principales · F6 tout",
        "en": "F7 main versions · F6 all",
    },
    "exists - skipped": {
        "fr": "existe — ignorée",
        "en": "exists - skipped",
    },
    "orphan disk - will FAIL": {
        "fr": "disque orphelin — ÉCHOUERA",
        "en": "orphan disk - will FAIL",
    },
    "press F5 again to confirm": {
        "fr": "F5 à nouveau pour confirmer",
        "en": "press F5 again to confirm",
    },
    "Deploy": {
        "fr": "Déployer",
        "en": "Deploy",
    },
    "Edit VM": {
        "fr": "Éditer la VM",
        "en": "Edit VM",
    },
    "Server": {
        "fr": "Serveur",
        "en": "Server",
    },
    "VM type (default):": {
        "fr": "Type de VM (défaut) :",
        "en": "VM type (default):",
    },
    "These values are the default for every VM;": {
        "fr": "Ces valeurs sont le défaut de chaque VM ;",
        "en": "These values are the default for every VM;",
    },
    "adjust any of them per VM on the right.": {
        "fr": "ajustez-les VM par VM dans la vue de droite.",
        "en": "adjust any of them per VM on the right.",
    },
    "Application store:": {
        "fr": "Magasin d'applications :",
        "en": "Application store:",
    },
    "Application store (graphical Ubuntu VMs):": {
        "fr": "Magasin d'applications (VM Ubuntu graphiques) :",
        "en": "Application store (graphical Ubuntu VMs):",
    },
    "deb only (epiphany-browser)": {
        "fr": "deb uniquement (epiphany-browser)",
        "en": "deb only (epiphany-browser)",
    },
    "Flatpak tooling, no Flathub": {
        "fr": "outillage Flatpak, sans Flathub",
        "en": "Flatpak tooling, no Flathub",
    },
    "snap (Ubuntu default, Firefox)": {
        "fr": "snap (défaut Ubuntu, Firefox)",
        "en": "snap (Ubuntu default, Firefox)",
    },
    "snap needs the store; slow under emulation.": {
        "fr": "snap exige le store ; lent sous émulation.",
        "en": "snap needs the store; slow under emulation.",
    },
    "No graphical VM on a snap-based distro.": {
        "fr": "Aucune VM graphique sur une distribution à snap.",
        "en": "No graphical VM on a snap-based distro.",
    },
    "Resources — applied to ALL VMs": {
        "fr": "Ressources — appliquées à TOUTES les VM",
        "en": "Resources — applied to ALL VMs",
    },
    "The profile and these fields change EVERY VM.": {
        "fr": "Le profil et ces champs changent TOUTES les VM.",
        "en": "The profile and these fields change EVERY VM.",
    },
    "A VM edited on the right (marked) keeps its own.": {
        "fr": "Une VM modifiée à droite (marquée ✎) garde les siennes.",
        "en": "A VM edited on the right (marked) keeps its own.",
    },
    "Rename the VM": {
        "fr": "Renommer la VM",
        "en": "Rename the VM",
    },
    "Rename": {
        "fr": "Renommer",
        "en": "Rename",
    },
    "Empty = back to the automatic name:": {
        "fr": "Vide = revenir au nom automatique :",
        "en": "Empty = back to the automatic name:",
    },
    "Invalid name: letters, digits, hyphens.": {
        "fr": "Nom invalide : lettres, chiffres et traits d'union.",
        "en": "Invalid name: letters, digits, hyphens.",
    },
    "default; a VM may differ, see its line": {
        "fr": "défaut ; une VM peut s'en écarter, voir sa ligne",
        "en": "default; a VM may differ, see its line",
    },
    "varies, see each line": {
        "fr": "varie, voir chaque ligne",
        "en": "varies, see each line",
    },
    "From your workstation:": {
        "fr": "Depuis votre poste :",
        "en": "From your workstation:",
    },
    "then point your client at": {
        "fr": "puis pointez votre client sur",
        "en": "then point your client at",
    },
    "Remote desktop tunnel (VNC/RDP through SSH)": {
        "fr": "🖥  Tunnel bureau distant (VNC/RDP par SSH)",
        "en": "🖥  Remote desktop tunnel (VNC/RDP through SSH)",
    },
    "Remote desktop tunnel": {
        "fr": "Tunnel vers le bureau distant",
        "en": "Remote desktop tunnel",
    },
    "Which VM?": {"fr": "Quelle VM ?", "en": "Which VM?"},
    "No IP for this VM; is it running?": {
        "fr": "Pas d'IP pour cette VM ; tourne-t-elle ?",
        "en": "No IP for this VM; is it running?",
    },
    "Run this on YOUR workstation:": {
        "fr": "À lancer sur VOTRE poste :",
        "en": "Run this on YOUR workstation:",
    },
    "(through the ProxyJump already in ~/.ssh/config)": {
        "fr": "(par le ProxyJump déjà dans ~/.ssh/config)",
        "en": "(through the ProxyJump already in ~/.ssh/config)",
    },
    "No ~/.ssh/config entry; see SSH configuration.": {
        "fr": "Aucune entrée ~/.ssh/config ; voir Configuration SSH.",
        "en": "No ~/.ssh/config entry; see SSH configuration.",
    },
    "Not in an SSH session: check the host address.": {
        "fr": "Hors session SSH : vérifiez l'adresse de l'hôte.",
        "en": "Not in an SSH session: check the host address.",
    },
    "The tunnel stays open as long as that ssh runs.": {
        "fr": "Le tunnel reste ouvert tant que ce ssh tourne.",
        "en": "The tunnel stays open as long as that ssh runs.",
    },
    "No VM defined.": {"fr": "Aucune VM définie.", "en": "No VM defined."},
    "No host in ~/.ssh/config and no local VM.": {
        "fr": "Aucun hôte dans ~/.ssh/config et aucune VM locale.",
        "en": "No host in ~/.ssh/config and no local VM.",
    },
    "local VM": {"fr": "VM locale", "en": "local VM"},
    "Remote desktop kind:": {
        "fr": "Type de bureau distant :",
        "en": "Remote desktop kind:",
    },
    "already defined, not counted": {
        "fr": "déjà définie(s), non comptée(s)",
        "en": "already defined, not counted",
    },
    "RAM: 2048 or 8G": {"fr": "RAM : 2048 ou 8G", "en": "RAM: 2048 or 8G"},
    "Diagnostic dump": {"fr": "Diagnostic", "en": "Diagnostic dump"},
    "State written to": {"fr": "État écrit dans", "en": "State written to"},
    "Reset VM": {
        "fr": "Réinit. VM",
        "en": "Reset VM",
    },
    "Preview": {
        "fr": "Aperçu",
        "en": "Preview",
    },
    "All": {
        "fr": "Tout",
        "en": "All",
    },
    "Main versions": {
        "fr": "Versions principales",
        "en": "Main versions",
    },
    "None": {
        "fr": "Rien",
        "en": "None",
    },
    "Cancel": {
        "fr": "Annuler",
        "en": "Cancel",
    },
    "Apply": {
        "fr": "Appliquer",
        "en": "Apply",
    },
    "Close": {
        "fr": "Fermer",
        "en": "Close",
    },
    "Copy log": {
        "fr": "Copier le log",
        "en": "Copy log",
    },
    "Copy all logs": {
        "fr": "Copier tous les logs",
        "en": "Copy all logs",
    },
    "all logs": {
        "fr": "tous les logs",
        "en": "all logs",
    },
    "c copy log · C copy all · q quit": {
        "fr": "c copier le log · C copier tout · q quitter",
        "en": "c copy log · C copy all · q quit",
    },
    "Clipboard": {
        "fr": "Presse-papiers",
        "en": "Clipboard",
    },
    "chars": {
        "fr": "car.",
        "en": "chars",
    },
    "tail only, log was truncated": {
        "fr": "fin seulement, log tronqué",
        "en": "tail only, log was truncated",
    },
    "Needs an OSC 52 capable terminal.": {
        "fr": "Nécessite un terminal compatible OSC 52.",
        "en": "Needs an OSC 52 capable terminal.",
    },
    "Nothing to copy.": {
        "fr": "Rien à copier.",
        "en": "Nothing to copy.",
    },
    "TODO navigation telemetry": {
        "fr": "TODO — télémétrie de navigation",
        "en": "TODO navigation telemetry",
    },
    "navigations": {
        "fr": "navigations",
        "en": "navigations",
    },
    "menus": {
        "fr": "menus",
        "en": "menus",
    },
    "Telemetry reset.": {
        "fr": "Télémétrie réinitialisée.",
        "en": "Telemetry reset.",
    },
    "tree from code": {
        "fr": "arbre issu du code",
        "en": "tree from code",
    },
    "visited paths only": {
        "fr": "chemins visités seulement",
        "en": "visited paths only",
    },
    "Enter = run, F3 = view": {
        "fr": "Entrée = exécuter, F3 = vue",
        "en": "Enter = run, F3 = view",
    },
    "Enter = run, F3/F4 = views": {
        "fr": "Entrée = exécuter, F3/F4 = vues",
        "en": "Enter = run, F3/F4 = views",
    },
    "view": {
        "fr": "vue",
        "en": "view",
    },
    "avg": {
        "fr": "moy",
        "en": "avg",
    },
    "Last install:": {
        "fr": "Dernière install :",
        "en": "Last install:",
    },
    "No command found.": {
        "fr": "Aucune commande trouvée.",
        "en": "No command found.",
    },
    "Back to telemetry (r) or quit (Enter)? ": {
        "fr": "Revenir à la télémétrie (r) ou quitter (Entrée) ? ",
        "en": "Back to telemetry (r) or quit (Enter)? ",
    },
    "F2 system · F3/F4 views · Enter run": {
        "fr": "F2 système · F3/F4 vues · Entrée exécute",
        "en": "F2 system · F3/F4 views · Enter run",
    },
    "State": {"fr": "État", "en": "State"},
    "uptime": {"fr": "actif depuis", "en": "uptime"},
    "load": {"fr": "charge", "en": "load"},
    "cores": {"fr": "cœurs", "en": "cores"},
    "Memory": {"fr": "Mémoire", "en": "Memory"},
    "Disk": {"fr": "Disque", "en": "Disk"},
    "Network": {"fr": "Réseau", "en": "Network"},
    "Battery": {"fr": "Batterie", "en": "Battery"},
    "Temperature": {"fr": "Température", "en": "Temperature"},
    "lm-sensors absent — press i to install": {
        "fr": "lm-sensors absent — appuyez sur i pour installer",
        "en": "lm-sensors absent — press i to install",
    },
    "Sensors already available.": {
        "fr": "Capteurs déjà disponibles.",
        "en": "Sensors already available.",
    },
    "Sensors now available.": {
        "fr": "Capteurs désormais disponibles.",
        "en": "Sensors now available.",
    },
    "Still no temperature (reboot/modprobe may be needed).": {
        "fr": "Toujours pas de température (redémarrage/modprobe requis ?).",
        "en": "Still no temperature (reboot/modprobe may be needed).",
    },
    "Unknown package manager for lm-sensors.": {
        "fr": "Gestionnaire de paquets inconnu pour lm-sensors.",
        "en": "Unknown package manager for lm-sensors.",
    },
    "Proposed install command:": {
        "fr": "Commande d'installation proposée :",
        "en": "Proposed install command:",
    },
    "Install lm-sensors now? (y/N): ": {
        "fr": "Installer lm-sensors maintenant ? (o/N) : ",
        "en": "Install lm-sensors now? (y/N): ",
    },
    "Command failed: ": {
        "fr": "Échec de la commande : ",
        "en": "Command failed: ",
    },
    "Textual is required for this screen.": {
        "fr": "Textual est nécessaire pour cet écran.",
        "en": "Textual is required for this screen.",
    },
    "Install it now? (Y/n): ": {
        "fr": "L'installer maintenant ? (O/n, défaut : oui) : ",
        "en": "Install it now? (Y/n, default: yes): ",
    },
    "Textual is installed.": {
        "fr": "Textual est installé.",
        "en": "Textual is installed.",
    },
    "Installation finished but textual is still missing.": {
        "fr": "Installation terminée mais textual reste introuvable.",
        "en": "Installation finished but textual is still missing.",
    },
    "pip exited with": {
        "fr": "pip a retourné",
        "en": "pip exited with",
    },
    "Your distribution may package it as python3-textual.": {
        "fr": "Votre distribution le fournit peut-être en python3-textual.",
        "en": "Your distribution may package it as python3-textual.",
    },
    "Resize a VM disk": {
        "fr": "📐 Redimensionner le disque d'une VM",
        "en": "📐 Resize a VM disk",
    },
    "VM name to resize: ": {
        "fr": "Nom de la VM à redimensionner : ",
        "en": "VM name to resize: ",
    },
    "VM not found.": {
        "fr": "VM introuvable.",
        "en": "VM not found.",
    },
    "Main disk not found for this VM.": {
        "fr": "Disque principal introuvable pour cette VM.",
        "en": "Main disk not found for this VM.",
    },
    "Current disk:": {
        "fr": "Disque actuel :",
        "en": "Current disk:",
    },
    "Current virtual size:": {
        "fr": "Taille virtuelle actuelle :",
        "en": "Current virtual size:",
    },
    "VM state:": {
        "fr": "État de la VM :",
        "en": "VM state:",
    },
    "Could not read current disk size; aborting.": {
        "fr": "Impossible de lire la taille actuelle du disque ; abandon.",
        "en": "Could not read current disk size; aborting.",
    },
    "Host free space:": {
        "fr": "Espace libre hôte :",
        "en": "Host free space:",
    },
    "max sustainable total (before host full):": {
        "fr": "max soutenable au total (avant hôte plein) :",
        "en": "max sustainable total (before host full):",
    },
    "Beyond host capacity by ~%.1f G — overcommit.": {
        "fr": "Dépasse la capacité de l'hôte de ~%.1f G — surallocation.",
        "en": "Beyond host capacity by ~%.1f G — overcommit.",
    },
    "The qcow2 is thin: fine until the VM fills it, then the "
    "host disk runs out. Max sustainable: ~%.1f G.": {
        "fr": "Le qcow2 est creux : OK tant que la VM ne remplit pas, sinon "
        "l'hôte tombe à court. Max soutenable : ~%.1f G.",
        "en": "The qcow2 is thin: fine until the VM fills it, then the "
        "host disk runs out. Max sustainable: ~%.1f G.",
    },
    "Safe shrink needs libguestfs (virt-resize).": {
        "fr": "La réduction sûre nécessite libguestfs (virt-resize).",
        "en": "Safe shrink needs libguestfs (virt-resize).",
    },
    "Install libguestfs-tools now? (y/N): ": {
        "fr": "Installer libguestfs-tools maintenant ? (o/N) : ",
        "en": "Install libguestfs-tools now? (y/N): ",
    },
    "Shrink aborted; disk left intact.": {
        "fr": "Réduction annulée ; disque laissé intact.",
        "en": "Shrink aborted; disk left intact.",
    },
    "Could not detect the partition to shrink; aborting.": {
        "fr": "Partition à réduire introuvable ; abandon.",
        "en": "Could not detect the partition to shrink; aborting.",
    },
    "Missing tools for safe shrink:": {
        "fr": "Outils manquants pour la réduction sûre :",
        "en": "Missing tools for safe shrink:",
    },
    "Backing up the disk before shrinking…": {
        "fr": "Sauvegarde du disque avant réduction…",
        "en": "Backing up the disk before shrinking…",
    },
    "Back up the disk before shrinking? (Y/n): ": {
        "fr": "Sauvegarder le disque avant réduction ? (O/n, défaut : oui) : ",
        "en": "Back up the disk before shrinking? (Y/n, default: yes): ",
    },
    "No backup: a failure could leave the disk broken.": {
        "fr": "Sans sauvegarde : un échec pourrait rendre le disque inutilisable.",
        "en": "No backup: a failure could leave the disk broken.",
    },
    "Disk safely shrunk.": {
        "fr": "Disque réduit en toute sécurité.",
        "en": "Disk safely shrunk.",
    },
    "No backup to restore; run fsck on the disk before use.": {
        "fr": "Pas de sauvegarde à restaurer ; lancez fsck avant utilisation.",
        "en": "No backup to restore; run fsck on the disk before use.",
    },
    "A disk backup was kept:": {
        "fr": "Une sauvegarde du disque a été conservée :",
        "en": "A disk backup was kept:",
    },
    "Delete this backup now? (y/N): ": {
        "fr": "Effacer cette sauvegarde maintenant ? (o/N) : ",
        "en": "Delete this backup now? (y/N): ",
    },
    "Backup deleted.": {
        "fr": "Sauvegarde effacée.",
        "en": "Backup deleted.",
    },
    "Backup kept (delete later via Clean up QEMU).": {
        "fr": "Sauvegarde conservée (à effacer plus tard via Nettoyer QEMU).",
        "en": "Backup kept (delete later via Clean up QEMU).",
    },
    "disk backup (resize)": {
        "fr": "sauvegarde de disque (redim.)",
        "en": "disk backup (resize)",
    },
    "Backup failed; aborting.": {
        "fr": "Échec de la sauvegarde ; abandon.",
        "en": "Backup failed; aborting.",
    },
    "Could not attach the disk (nbd); aborting.": {
        "fr": "Impossible d'attacher le disque (nbd) ; abandon.",
        "en": "Could not attach the disk (nbd); aborting.",
    },
    "Only ext2/3/4 can be shrunk safely; aborting.": {
        "fr": "Seul ext2/3/4 peut être réduit en sécurité ; abandon.",
        "en": "Only ext2/3/4 can be shrunk safely; aborting.",
    },
    "Target size too small for this layout; aborting.": {
        "fr": "Taille cible trop petite pour cette disposition ; abandon.",
        "en": "Target size too small for this layout; aborting.",
    },
    "Not enough used-space margin to shrink; aborting.": {
        "fr": "Espace utilisé trop proche de la cible ; abandon.",
        "en": "Not enough used-space margin to shrink; aborting.",
    },
    "Shrinking guest ext filesystem": {
        "fr": "Réduction du système de fichiers ext invité",
        "en": "Shrinking guest ext filesystem",
    },
    "resize2fs failed; reverting.": {
        "fr": "resize2fs a échoué ; restauration.",
        "en": "resize2fs failed; reverting.",
    },
    "Internal size check failed; reverting.": {
        "fr": "Contrôle de taille interne échoué ; restauration.",
        "en": "Internal size check failed; reverting.",
    },
    "Shrinking the partition…": {
        "fr": "Réduction de la partition…",
        "en": "Shrinking the partition…",
    },
    "Partition rewrite failed; reverting.": {
        "fr": "Réécriture de la partition échouée ; restauration.",
        "en": "Partition rewrite failed; reverting.",
    },
    "Shrinking the qcow2 container…": {
        "fr": "Réduction du conteneur qcow2…",
        "en": "Shrinking the qcow2 container…",
    },
    "Container shrink failed; reverting.": {
        "fr": "Réduction du conteneur échouée ; restauration.",
        "en": "Container shrink failed; reverting.",
    },
    "Restoring the original disk from backup…": {
        "fr": "Restauration du disque d'origine depuis la sauvegarde…",
        "en": "Restoring the original disk from backup…",
    },
    "Shrinking guest FS + partition via virt-resize": {
        "fr": "Réduction du FS invité + partition via virt-resize",
        "en": "Shrinking guest FS + partition via virt-resize",
    },
    "virt-resize failed; original disk left intact.": {
        "fr": "virt-resize a échoué ; disque d'origine laissé intact.",
        "en": "virt-resize failed; original disk left intact.",
    },
    "Disk safely shrunk. Backup kept at:": {
        "fr": "Disque réduit en toute sécurité. Sauvegarde conservée :",
        "en": "Disk safely shrunk. Backup kept at:",
    },
    "click to expand": {
        "fr": "cliquer pour déplier",
        "en": "click to expand",
    },
    "No error detected.": {
        "fr": "Aucune erreur détectée.",
        "en": "No error detected.",
    },
    "Test a VM (open Odoo in a CLI browser)": {
        "fr": "🧪 Tester une VM (ouvrir Odoo dans un navigateur CLI)",
        "en": "🧪 Test a VM (open Odoo in a CLI browser)",
    },
    "Reopen install monitoring (last run / history)": {
        "fr": "📈 Rouvrir le suivi d'installation (dernier run / historique)",
        "en": "📈 Reopen install monitoring (last run / history)",
    },
    "No install run found in history.": {
        "fr": "Aucun run d'installation dans l'historique.",
        "en": "No install run found in history.",
    },
    "Install runs (most recent first):": {
        "fr": "Runs d'installation (du plus récent) :",
        "en": "Install runs (most recent first):",
    },
    "Choice (number, blank = last): ": {
        "fr": "Choix (numéro, vide = le dernier) : ",
        "en": "Choice (number, blank = last): ",
    },
    "Invalid selection.": {
        "fr": "Sélection invalide.",
        "en": "Invalid selection.",
    },
    "Resolving VM IP...": {
        "fr": "Résolution de l'IP de la VM…",
        "en": "Resolving VM IP...",
    },
    "No IP found for this VM.": {
        "fr": "Aucune IP trouvée pour cette VM.",
        "en": "No IP found for this VM.",
    },
    "No CLI browser installed. Which to install?": {
        "fr": "Aucun navigateur CLI installé. Lequel installer ?",
        "en": "No CLI browser installed. Which to install?",
    },
    "Which browser to install?": {
        "fr": "Quel navigateur installer ?",
        "en": "Which browser to install?",
    },
    "Install another browser": {
        "fr": "Installer un autre navigateur",
        "en": "Install another browser",
    },
    "Choice (number, blank = w3m): ": {
        "fr": "Choix (numéro, vide = w3m) : ",
        "en": "Choice (number, blank = w3m): ",
    },
    "Unknown package manager; install it manually.": {
        "fr": "Gestionnaire de paquets inconnu ; installez-le manuellement.",
        "en": "Unknown package manager; install it manually.",
    },
    "Install now? (y/N): ": {
        "fr": "Installer maintenant ? (o/N) : ",
        "en": "Install now? (y/N): ",
    },
    "Which browser to view the page?": {
        "fr": "Quel navigateur pour voir la page ?",
        "en": "Which browser to view the page?",
    },
    "Choice (number, blank = first): ": {
        "fr": "Choix (numéro, vide = le premier) : ",
        "en": "Choice (number, blank = first): ",
    },
    "Page may not have loaded: Odoo not started on :8069, "
    "or network/firewall.": {
        "fr": "La page ne s'est peut-être pas affichée : Odoo n'est pas "
        "démarré sur :8069, ou réseau/pare-feu.",
        "en": "Page may not have loaded: Odoo not started on :8069, "
        "or network/firewall.",
    },
    "errors": {
        "fr": "erreurs",
        "en": "errors",
    },
    "warnings": {
        "fr": "avertissements",
        "en": "warnings",
    },
    "Esc to close": {
        "fr": "Échap pour fermer",
        "en": "Esc to close",
    },
    "No running VM to pause.": {
        "fr": "Aucune VM en cours à mettre en pause.",
        "en": "No running VM to pause.",
    },
    "No paused VM to resume.": {
        "fr": "Aucune VM en pause à reprendre.",
        "en": "No paused VM to resume.",
    },
    "resumed": {
        "fr": "reprise(s)",
        "en": "resumed",
    },
    "SSH grow failed; trying the guest agent.": {
        "fr": "Échec SSH ; tentative via l'agent invité.",
        "en": "SSH grow failed; trying the guest agent.",
    },
    "No IP; trying the guest agent (no network).": {
        "fr": "Pas d'IP ; tentative via l'agent invité (sans réseau).",
        "en": "No IP; trying the guest agent (no network).",
    },
    "Guest filesystem grown via guest agent.": {
        "fr": "FS invité étendu via l'agent invité.",
        "en": "Guest filesystem grown via guest agent.",
    },
    "Guest agent grow failed; falling back to console.": {
        "fr": "Échec de l'agent invité ; repli sur la console.",
        "en": "Guest agent grow failed; falling back to console.",
    },
    "Guest agent unavailable; falling back to serial console.": {
        "fr": "Agent invité indisponible ; repli sur la console série.",
        "en": "Guest agent unavailable; falling back to serial console.",
    },
    "Running via guest agent (no network)…": {
        "fr": "Exécution via l'agent invité (sans réseau)…",
        "en": "Running via guest agent (no network)…",
    },
    "SSH grow failed; falling back to serial console.": {
        "fr": "Échec de l'extension via SSH ; repli sur la console série.",
        "en": "SSH grow failed; falling back to serial console.",
    },
    "No IP; falling back to serial console.": {
        "fr": "Pas d'IP ; repli sur la console série.",
        "en": "No IP; falling back to serial console.",
    },
    "Serial console fallback. Log in, then paste:": {
        "fr": "Repli console série. Connectez-vous, puis collez :",
        "en": "Serial console fallback. Log in, then paste:",
    },
    "Open the serial console now? (y/N): ": {
        "fr": "Ouvrir la console série maintenant ? (o/N) : ",
        "en": "Open the serial console now? (y/N): ",
    },
    "The VM must be off. Shut it down and retry? (y/N): ": {
        "fr": "La VM doit être éteinte. L'éteindre et réessayer ? (o/N) : ",
        "en": "The VM must be off. Shut it down and retry? (y/N): ",
    },
    "VM is still not off; aborting.": {
        "fr": "La VM n'est toujours pas éteinte ; abandon.",
        "en": "VM is still not off; aborting.",
    },
    "Waiting for the VM to shut down...": {
        "fr": "Attente de l'arrêt de la VM…",
        "en": "Waiting for the VM to shut down...",
    },
    "timeout": {
        "fr": "délai max",
        "en": "timeout",
    },
    "shutting down": {
        "fr": "arrêt en cours",
        "en": "shutting down",
    },
    "remaining": {
        "fr": "restantes",
        "en": "remaining",
    },
    "VM is off.": {
        "fr": "VM éteinte.",
        "en": "VM is off.",
    },
    "The VM was shut down for the resize.": {
        "fr": "La VM a été éteinte pour le redimensionnement.",
        "en": "The VM was shut down for the resize.",
    },
    "Start the VM now? (y/N): ": {
        "fr": "Démarrer la VM maintenant ? (o/N) : ",
        "en": "Start the VM now? (y/N): ",
    },
    "Graceful shutdown timed out. Force off (destroy)? (y/N): ": {
        "fr": "Arrêt gracieux trop long. Forcer l'arrêt (destroy) ? (o/N) : ",
        "en": "Graceful shutdown timed out. Force off (destroy)? (y/N): ",
    },
    "Show advanced info (vCPU, RAM, disk)? (y/N): ": {
        "fr": "Afficher les infos avancées (vCPU, RAM, disque) ? (o/N) : ",
        "en": "Show advanced info (vCPU, RAM, disk)? (y/N): ",
    },
    "What do you want to do?": {
        "fr": "Que voulez-vous faire ?",
        "en": "What do you want to do?",
    },
    "Advanced info (vCPU, RAM, disk)": {
        "fr": "Infos avancées (vCPU, RAM, disque)",
        "en": "Advanced info (vCPU, RAM, disk)",
    },
    "Change the state of one or more VMs": {
        "fr": "Changer l'état d'une ou plusieurs VM",
        "en": "Change the state of one or more VMs",
    },
    "Enter": {
        "fr": "Entrée",
        "en": "Enter",
    },
    "Nothing": {
        "fr": "Rien",
        "en": "Nothing",
    },
    "Choice: ": {
        "fr": "Choix : ",
        "en": "Choice: ",
    },
    "Available VMs:": {
        "fr": "VM disponibles :",
        "en": "Available VMs:",
    },
    "VMs to change (comma-separated): ": {
        "fr": "VM à modifier (séparées par des virgules) : ",
        "en": "VMs to change (comma-separated): ",
    },
    "Unknown VM(s):": {
        "fr": "VM inconnue(s) :",
        "en": "Unknown VM(s):",
    },
    "Target state:": {
        "fr": "État cible :",
        "en": "Target state:",
    },
    "Target environment?": {
        "fr": "Environnement cible ?",
        "en": "Target environment?",
    },
    "Development (~/git/erplibre, SELinux relaxed)": {
        "fr": "Développement (~/git/erplibre, SELinux relâché)",
        "en": "Development (~/git/erplibre, SELinux relaxed)",
    },
    "Production (/opt/erplibre, SELinux enforced)": {
        "fr": "Production (/opt/erplibre, SELinux confiné)",
        "en": "Production (/opt/erplibre, SELinux enforced)",
    },
    "Choice (1-2, default 1): ": {
        "fr": "Choix (1-2, défaut 1) : ",
        "en": "Choice (1-2, default 1): ",
    },
    "Open (start)": {
        "fr": "Ouvrir (démarrer)",
        "en": "Open (start)",
    },
    "Close (shut down)": {
        "fr": "Fermer (éteindre)",
        "en": "Close (shut down)",
    },
    "start": {
        "fr": "démarrer",
        "en": "start",
    },
    "shut down": {
        "fr": "éteindre",
        "en": "shut down",
    },
    "Apply:": {
        "fr": "Appliquer :",
        "en": "Apply:",
    },
    "Confirm for real? (y/N): ": {
        "fr": "Confirmer pour de vrai ? (o/N) : ",
        "en": "Confirm for real? (y/N): ",
    },
    "Storage": {
        "fr": "Stockage",
        "en": "Storage",
    },
    "total": {
        "fr": "au total",
        "en": "total",
    },
    "used": {
        "fr": "utilisés",
        "en": "used",
    },
    "Enter +NG to grow, -NG to shrink, or NG for a target size "
    "(e.g. +20G, -10G, 60G).": {
        "fr": "Entrez +NG pour agrandir, -NG pour réduire, ou NG pour une "
        "taille cible (ex. +20G, -10G, 60G).",
        "en": "Enter +NG to grow, -NG to shrink, or NG for a target size "
        "(e.g. +20G, -10G, 60G).",
    },
    "Resize: ": {
        "fr": "Redimensionner : ",
        "en": "Resize: ",
    },
    "Invalid size.": {
        "fr": "Taille invalide.",
        "en": "Invalid size.",
    },
    "No change.": {
        "fr": "Aucun changement.",
        "en": "No change.",
    },
    "New virtual size:": {
        "fr": "Nouvelle taille virtuelle :",
        "en": "New virtual size:",
    },
    "SHRINKING is DANGEROUS: the guest filesystem is NOT shrunk. "
    "Data beyond the new size is LOST. Shrink the guest FS FIRST, "
    "and only then shrink here.": {
        "fr": "RÉDUIRE est DANGEREUX : le système de fichiers invité n'est "
        "PAS réduit. Les données au-delà de la nouvelle taille sont PERDUES. "
        "Réduisez d'ABORD le FS invité, puis seulement ici.",
        "en": "SHRINKING is DANGEROUS: the guest filesystem is NOT shrunk. "
        "Data beyond the new size is LOST. Shrink the guest FS FIRST, "
        "and only then shrink here.",
    },
    "Shut the VM off before shrinking (virsh shutdown).": {
        "fr": "Éteignez la VM avant de réduire (virsh shutdown).",
        "en": "Shut the VM off before shrinking (virsh shutdown).",
    },
    "Type y to confirm you understand the risk (y/N): ": {
        "fr": "Tapez o pour confirmer que vous comprenez le risque "
        "(o/N, défaut : non) : ",
        "en": "Type y to confirm you understand the risk (y/N): ",
    },
    "Resize failed (see error above).": {
        "fr": "Échec du redimensionnement (voir l'erreur ci-dessus).",
        "en": "Resize failed (see error above).",
    },
    "Virtual disk resized.": {
        "fr": "Disque virtuel redimensionné.",
        "en": "Virtual disk resized.",
    },
    "Grow the guest filesystem now (over SSH)? (y/N): ": {
        "fr": "Étendre le système de fichiers invité maintenant (via SSH) ? "
        "(o/N, défaut : non) : ",
        "en": "Grow the guest filesystem now (over SSH)? (y/N): ",
    },
    "No IP; grow the guest FS manually once booted.": {
        "fr": "Pas d'IP ; étendez le FS invité manuellement après le boot.",
        "en": "No IP; grow the guest FS manually once booted.",
    },
    "completed": {
        "fr": "terminées",
        "en": "completed",
    },
    "deleted": {
        "fr": "effacée",
        "en": "deleted",
    },
    "paused": {
        "fr": "pause",
        "en": "paused",
    },
    "Waiting for the VM to start (boot + cloud-init)": {
        "fr": "En attente du démarrage de la VM (boot + cloud-init)",
        "en": "Waiting for the VM to start (boot + cloud-init)",
    },
    "(an emulated architecture can be slow; this is normal)": {
        "fr": "(une architecture émulée peut être lente ; c'est normal)",
        "en": "(an emulated architecture can be slow; this is normal)",
    },
    "VM ready - starting the ERPLibre install": {
        "fr": "VM prête — installation ERPLibre en cours",
        "en": "VM ready - starting the ERPLibre install",
    },
    "Choice (number or name, blank = native):": {
        "fr": "Choix (numéro ou nom, vide = native) :",
        "en": "Choice (number or name, blank = native):",
    },
    "Pick exact versions (comma-separated list)": {
        "fr": "Choisir des versions précises (liste séparée par des virgules)",
        "en": "Pick exact versions (comma-separated list)",
    },
    "Selection (numbers, 'all', 'principal' or 'granulaire',"
    " default: all): ": {
        "fr": "Sélection (numéros, « all », « principal » ou « granulaire »,"
        " défaut : all) : ",
        "en": "Selection (numbers, 'all', 'principal' or 'granulaire',"
        " default: all): ",
    },
    "All versions:": {
        "fr": "Toutes les versions :",
        "en": "All versions:",
    },
    "Selection (comma-separated numbers): ": {
        "fr": "Sélection (numéros séparés par des virgules) : ",
        "en": "Selection (comma-separated numbers): ",
    },
    "s390x images only exist for:": {
        "fr": "images s390x disponibles seulement pour :",
        "en": "s390x images only exist for:",
    },
    "ignored:": {
        "fr": "ignoré :",
        "en": "ignored:",
    },
    "IBM Z — emulated, slow on x86": {
        "fr": "IBM Z — émulé, lent sur x86",
        "en": "IBM Z — emulated, slow on x86",
    },
    "Choice (number or name, blank = amd64):": {
        "fr": "Choix (numéro ou nom, vide = amd64) :",
        "en": "Choice (number or name, blank = amd64):",
    },
    "s390x is emulated (TCG): boot and install are much "
    "slower than x86.": {
        "fr": "s390x est émulé (TCG) : le boot et l'installation sont bien "
        "plus lents que x86.",
        "en": "s390x is emulated (TCG): boot and install are much "
        "slower than x86.",
    },
    "Choice (number or version, blank = default):": {
        "fr": "Choix (numéro ou version, vide = défaut) :",
        "en": "Choice (number or version, blank = default):",
    },
    "Invalid selection, using": {
        "fr": "Sélection invalide, utilisation de",
        "en": "Invalid selection, using",
    },
    "select all": {
        "fr": "tout sélectionner",
        "en": "select all",
    },
    "Delete VM(s)": {
        "fr": "🗑  Effacer une ou plusieurs VM",
        "en": "🗑  Delete VM(s)",
    },
    "No VM found.": {
        "fr": "Aucune VM trouvée.",
        "en": "No VM found.",
    },
    "Select VMs to delete:": {
        "fr": "Sélectionner les VM à effacer :",
        "en": "Select VMs to delete:",
    },
    "Selection (numbers, or 'all'): ": {
        "fr": "Sélection (numéros, ou « all ») : ",
        "en": "Selection (numbers, or 'all'): ",
    },
    "Also delete disk images (qcow2 + seed ISO)? (y/N): ": {
        "fr": "Effacer aussi les disques (qcow2 + seed ISO) ? (o/N, défaut : non) : ",
        "en": "Also delete disk images (qcow2 + seed ISO)? (y/N, default: no): ",
    },
    "Will delete:": {
        "fr": "Sera effacé :",
        "en": "Will delete:",
    },
    "disk images and seed ISOs": {
        "fr": "les disques et les seed ISO",
        "en": "disk images and seed ISOs",
    },
    "disks kept": {
        "fr": "disques conservés",
        "en": "disks kept",
    },
    "Confirm deletion? (y/N): ": {
        "fr": "Confirmer l'effacement ? (o/N, défaut : non) : ",
        "en": "Confirm deletion? (y/N, default: no): ",
    },
    "Deletion done.": {
        "fr": "Effacement terminé.",
        "en": "Deletion done.",
    },
    "Clean up QEMU (orphan files)": {
        "fr": "🧹 Nettoyer QEMU (fichiers orphelins)",
        "en": "🧹 Clean up QEMU (orphan files)",
    },
    "Scanning for orphan QEMU files...": {
        "fr": "Recherche des fichiers QEMU orphelins...",
        "en": "Scanning for orphan QEMU files...",
    },
    "orphan disk": {
        "fr": "disque orphelin",
        "en": "orphan disk",
    },
    "orphan seed": {
        "fr": "seed orphelin",
        "en": "orphan seed",
    },
    "partial download": {
        "fr": "téléchargement interrompu",
        "en": "partial download",
    },
    "orphan UEFI nvram": {
        "fr": "nvram UEFI orpheline",
        "en": "orphan UEFI nvram",
    },
    "No orphan files found.": {
        "fr": "Aucun fichier orphelin trouvé.",
        "en": "No orphan files found.",
    },
    "Orphan files:": {
        "fr": "Fichiers orphelins :",
        "en": "Orphan files:",
    },
    "Total:": {
        "fr": "Total :",
        "en": "Total:",
    },
    "files": {
        "fr": "fichiers",
        "en": "files",
    },
    "Delete these orphan files? (y/N): ": {
        "fr": "Effacer ces fichiers orphelins ? (o/N, défaut : non) : ",
        "en": "Delete these orphan files? (y/N, default: no): ",
    },
    "Cleanup done.": {
        "fr": "Nettoyage terminé.",
        "en": "Cleanup done.",
    },
    "Cached base images (reusable):": {
        "fr": "Images de base en cache (réutilisables) :",
        "en": "Cached base images (reusable):",
    },
    "Also delete the cached base images? (y/N): ": {
        "fr": "Effacer aussi les images de base en cache ? (o/N, défaut : non) : ",
        "en": "Also delete the cached base images? (y/N, default: no): ",
    },
    "All cached base images (reusable):": {
        "fr": "Toutes les images de base en cache (réutilisables) :",
        "en": "All cached base images (reusable):",
    },
    "Delete ALL cached base images? (y/N): ": {
        "fr": "Effacer TOUTES les images de base en cache ? (o/N, défaut : non) : ",
        "en": "Delete ALL cached base images? (y/N, default: no): ",
    },
    "Ghost domains (defined but disk missing):": {
        "fr": "Domaines fantômes (définis, disque manquant) :",
        "en": "Ghost domains (defined but disk missing):",
    },
    "Undefine these ghost domains? (y/N): ": {
        "fr": "Supprimer la définition de ces domaines ? (o/N, défaut : non) : ",
        "en": "Undefine these ghost domains? (y/N, default: no): ",
    },
    "Stale codename-named Ubuntu images (duplicates):": {
        "fr": "Images Ubuntu nommées par codename (doublons) :",
        "en": "Stale codename-named Ubuntu images (duplicates):",
    },
    "Delete these duplicate images? (y/N): ": {
        "fr": "Effacer ces images en double ? (o/N, défaut : non) : ",
        "en": "Delete these duplicate images? (y/N, default: no): ",
    },
    "Orphan ~/.ssh/config entries:": {
        "fr": "Entrées ~/.ssh/config orphelines :",
        "en": "Orphan ~/.ssh/config entries:",
    },
    "Remove these ~/.ssh/config entries? (y/N): ": {
        "fr": "Retirer ces entrées de ~/.ssh/config ? (o/N, défaut : non) : ",
        "en": "Remove these ~/.ssh/config entries? (y/N, default: no): ",
    },
    "Stale DHCP leases (no matching VM):": {
        "fr": "Baux DHCP périmés (aucune VM correspondante) :",
        "en": "Stale DHCP leases (no matching VM):",
    },
    "Clear these stale leases? (y/N): ": {
        "fr": "Effacer ces baux périmés ? (o/N, défaut : non) : ",
        "en": "Clear these stale leases? (y/N, default: no): ",
    },
    "Deploy ERPLibre infra (one minimal VM per image)": {
        "fr": "Déployer l'infra ERPLibre (une VM minimale par image)",
        "en": "Deploy ERPLibre infra (one minimal VM per image)",
    },
    "Deploy ERPLibre infra: one minimal VM per image": {
        "fr": "Déployer l'infra ERPLibre : une VM minimale par image",
        "en": "Deploy ERPLibre infra: one minimal VM per image",
    },
    "Cannot load QEMU catalog: ": {
        "fr": "Impossible de charger le catalogue QEMU : ",
        "en": "Cannot load QEMU catalog: ",
    },
    "Distributions:": {
        "fr": "Distributions :",
        "en": "Distributions:",
    },
    "Whole catalog (every version)": {
        "fr": "Tout le catalogue (chaque version)",
        "en": "Whole catalog (every version)",
    },
    "The main version of each distro (marked *)": {
        "fr": "La version principale de chaque distro (marquée *)",
        "en": "The main version of each distro (marked *)",
    },
    "Selection (numbers, 'all' or 'principal', default: all): ": {
        "fr": "Sélection (numéros, « all » ou « principal », défaut : all) : ",
        "en": "Selection (numbers, 'all' or 'principal', default: all): ",
    },
    "Selection (numbers, or 'all', default: all): ": {
        "fr": "Sélection (numéros, ou « all », défaut : all) : ",
        "en": "Selection (numbers, or 'all', default: all): ",
    },
    "Nothing selected.": {
        "fr": "Rien de sélectionné.",
        "en": "Nothing selected.",
    },
    "Deployment plan": {
        "fr": "Plan de déploiement",
        "en": "Deployment plan",
    },
    "disk": {
        "fr": "disque",
        "en": "disk",
    },
    "Total RAM (all running):": {
        "fr": "RAM totale (toutes actives) :",
        "en": "Total RAM (all running):",
    },
    "Total virtual disk (thin qcow2):": {
        "fr": "Disque virtuel total (qcow2 thin) :",
        "en": "Total virtual disk (thin qcow2):",
    },
    "Host RAM available:": {
        "fr": "RAM disponible de l'hôte :",
        "en": "Host RAM available:",
    },
    "Total RAM exceeds host free RAM: not all VMs will run at once.": {
        "fr": "La RAM totale dépasse la RAM libre de l'hôte : les VM ne "
        "tourneront pas toutes en même temps.",
        "en": "Total RAM exceeds host free RAM: not all VMs will run at once.",
    },
    "Install ERPLibre into ~/git/erplibre on each VM? (Y/n): ": {
        "fr": "Installer ERPLibre dans ~/git/erplibre sur chaque VM ? "
        "(O/n, défaut : oui) : ",
        "en": "Install ERPLibre into ~/git/erplibre on each VM? "
        "(Y/n, default: yes): ",
    },
    "Deploy these VMs now? (Y/n): ": {
        "fr": "Déployer ces VM maintenant ? (O/n, défaut : oui) : ",
        "en": "Deploy these VMs now? (Y/n, default: yes): ",
    },
    "Discard everything and start over? (y/N): ": {
        "fr": "Tout abandonner et recommencer ? (o/N, défaut : non) : ",
        "en": "Discard everything and start over? (y/N, default: no): ",
    },
    "Final review before deployment": {
        "fr": "Récapitulatif final avant déploiement",
        "en": "Final review before deployment",
    },
    "VMs to create:": {
        "fr": "VM à créer :",
        "en": "VMs to create:",
    },
    "Existing, left untouched:": {
        "fr": "Existantes, laissées intactes :",
        "en": "Existing, left untouched:",
    },
    "ERPLibre install:": {
        "fr": "Installation ERPLibre :",
        "en": "ERPLibre install:",
    },
    "profile": {
        "fr": "profil",
        "en": "profile",
    },
    "branch": {
        "fr": "branche",
        "en": "branch",
    },
    "production (/opt, confined)": {
        "fr": "production (/opt, confiné)",
        "en": "production (/opt, confined)",
    },
    "development (~/git)": {
        "fr": "développement (~/git)",
        "en": "development (~/git)",
    },
    "no": {
        "fr": "non",
        "en": "no",
    },
    "SSH key:": {
        "fr": "Clé SSH :",
        "en": "SSH key:",
    },
    "~/.ssh/config:": {
        "fr": "~/.ssh/config :",
        "en": "~/.ssh/config:",
    },
    "one entry per VM": {
        "fr": "une entrée par VM",
        "en": "one entry per VM",
    },
    "untouched": {
        "fr": "inchangé",
        "en": "untouched",
    },
    "Parallelism:": {
        "fr": "Parallélisme :",
        "en": "Parallelism:",
    },
    "at a time": {
        "fr": "à la fois",
        "en": "at a time",
    },
    "Nothing to create - every VM already exists.": {
        "fr": "Rien à créer — toutes les VM existent déjà.",
        "en": "Nothing to create — every VM already exists.",
    },
    "Name collisions detected": {
        "fr": "Collisions de noms détectées",
        "en": "Name collisions detected",
    },
    "VM already defined - SKIPPED, nothing overwritten": {
        "fr": "VM déjà définie — IGNORÉE, rien ne sera écrasé",
        "en": "VM already defined — SKIPPED, nothing overwritten",
    },
    "disk present without VM - deployment will FAIL": {
        "fr": "disque présent sans VM — le déploiement ÉCHOUERA",
        "en": "disk present without VM - deployment will FAIL",
    },
    "Remove it by hand, or rename the VM.": {
        "fr": "L'effacer à la main, ou renommer la VM.",
        "en": "Remove it by hand, or rename the VM.",
    },
    "Continue despite these collisions? (y/N): ": {
        "fr": "Continuer malgré ces collisions ? (o/N, défaut : non) : ",
        "en": "Continue despite these collisions? (y/N, default: no): ",
    },
    "Resolving VM IPs (parallel, emulated boot is slow)...": {
        "fr": "Résolution des IP des VM (en parallèle, le démarrage émulé "
        "est lent)...",
        "en": "Resolving VM IPs (parallel, emulated boot is slow)...",
    },
    "no IP": {
        "fr": "pas d'IP",
        "en": "no IP",
    },
    "Cloning ERPLibre on each VM": {
        "fr": "Clonage d'ERPLibre sur chaque VM",
        "en": "Cloning ERPLibre on each VM",
    },
    "Installing ERPLibre on each VM": {
        "fr": "Installation d'ERPLibre sur chaque VM",
        "en": "Installing ERPLibre on each VM",
    },
    "Install ERPLibre into ~/git/erplibre on this VM? (y/N): ": {
        "fr": "Installer ERPLibre dans ~/git/erplibre sur cette VM ? (o/N, défaut : non) : ",
        "en": "Install ERPLibre into ~/git/erplibre on this VM? (y/N, default: no): ",
    },
    "installing ERPLibre": {
        "fr": "installation d'ERPLibre",
        "en": "installing ERPLibre",
    },
    "no IP obtained, ERPLibre install skipped.": {
        "fr": "aucune IP obtenue, installation ERPLibre ignorée.",
        "en": "no IP obtained, ERPLibre install skipped.",
    },
    "waiting for SSH...": {
        "fr": "attente du SSH...",
        "en": "waiting for SSH...",
    },
    "SSH not reachable, ERPLibre install skipped.": {
        "fr": "SSH injoignable, installation ERPLibre ignorée.",
        "en": "SSH not reachable, ERPLibre install skipped.",
    },
    "What to install on the VM(s)?": {
        "fr": "Que veut-on installer sur la/les VM ?",
        "en": "What to install on the VM(s)?",
    },
    "Choice (number, blank = Odoo 18): ": {
        "fr": "Choix (numéro, vide = Odoo 18) : ",
        "en": "Choice (number, blank = Odoo 18): ",
    },
    "ERPLibre + all Odoo versions": {
        "fr": "ERPLibre + toutes les versions Odoo",
        "en": "ERPLibre + all Odoo versions",
    },
    "ERPLibre only (no Odoo)": {
        "fr": "ERPLibre seulement (sans Odoo)",
        "en": "ERPLibre only (no Odoo)",
    },
    "ERPLibre mobile (home)": {
        "fr": "ERPLibre mobile (home)",
        "en": "ERPLibre mobile (home)",
    },
    "ERPLibre Deployment (+ QEMU + dev)": {
        "fr": "ERPLibre Déploiement (+ QEMU + dev)",
        "en": "ERPLibre Deployment (+ QEMU + dev)",
    },
    "Interactive monitoring dashboard? (y/N): ": {
        "fr": "Suivi interactif (dashboard) ? (O/n, défaut : oui) : ",
        "en": "Interactive monitoring dashboard? (Y/n, default: yes): ",
    },
    "resolving IP...": {
        "fr": "résolution de l'IP...",
        "en": "resolving IP...",
    },
    "no IP, skipped.": {
        "fr": "pas d'IP, ignorée.",
        "en": "no IP, skipped.",
    },
    "No VM to install.": {
        "fr": "Aucune VM à installer.",
        "en": "No VM to install.",
    },
    "Opening the interactive monitor...": {
        "fr": "Ouverture du suivi interactif...",
        "en": "Opening the interactive monitor...",
    },
    "Monitor closed. Installs keep running in the background.": {
        "fr": "Suivi fermé. Les installations continuent en arrière-plan.",
        "en": "Monitor closed. Installs keep running in the background.",
    },
    "Logs:": {
        "fr": "Logs :",
        "en": "Logs:",
    },
    "Read the logs:": {
        "fr": "Lire les logs :",
        "en": "Read the logs:",
    },
    "Log files:": {
        "fr": "Fichiers de log :",
        "en": "Log files:",
    },
    "Parallel deployments (default:": {
        "fr": "Déploiements en parallèle (défaut :",
        "en": "Parallel deployments (default:",
    },
    "VMs": {
        "fr": "VM",
        "en": "VMs",
    },
    "Deploy summary:": {
        "fr": "Bilan déploiement :",
        "en": "Deploy summary:",
    },
    "IPs resolved:": {
        "fr": "IP résolues :",
        "en": "IPs resolved:",
    },
    "still waiting for": {
        "fr": "encore en attente de",
        "en": "still waiting for",
    },
    "TOTAL summary": {
        "fr": "Sommaire TOTAL",
        "en": "TOTAL summary",
    },
    "VMs deployed:": {
        "fr": "VM déployées :",
        "en": "VMs deployed:",
    },
    "total incl. existing:": {
        "fr": "total avec existantes :",
        "en": "total incl. existing:",
    },
    "Total time:": {
        "fr": "Temps total :",
        "en": "Total time:",
    },
    "Deploying": {
        "fr": "Déploiement de",
        "en": "Deploying",
    },
    "parallel jobs:": {
        "fr": "tâches parallèles :",
        "en": "parallel jobs:",
    },
    "ERPLibre infra deployment done.": {
        "fr": "Déploiement de l'infra ERPLibre terminé.",
        "en": "ERPLibre infra deployment done.",
    },
    "Manage with:": {
        "fr": "Gérer avec :",
        "en": "Manage with:",
    },
    "Fetching ERPLibre branch list...": {
        "fr": "Récupération de la liste des branches ERPLibre...",
        "en": "Fetching ERPLibre branch list...",
    },
    "Branch (default:": {
        "fr": "Branche (défaut :",
        "en": "Branch (default:",
    },
    "Branches:": {
        "fr": "Branches :",
        "en": "Branches:",
    },
    "Choice (number or name, default:": {
        "fr": "Choix (numéro ou nom, défaut :",
        "en": "Choice (number or name, default:",
    },
    "no IP obtained, ERPLibre clone skipped.": {
        "fr": "aucune IP obtenue, clonage ERPLibre ignoré.",
        "en": "no IP obtained, ERPLibre clone skipped.",
    },
    "cloning ERPLibre": {
        "fr": "clonage d'ERPLibre",
        "en": "cloning ERPLibre",
    },
    "VM name (required): ": {
        "fr": "Nom de la VM (requis) : ",
        "en": "VM name (required): ",
    },
    "VM name is required!": {
        "fr": "Le nom de la VM est requis !",
        "en": "VM name is required!",
    },
    "VM name: ": {
        "fr": "Nom de la VM : ",
        "en": "VM name: ",
    },
    "VM name or ID: ": {
        "fr": "Nom ou ID de la VM : ",
        "en": "VM name or ID: ",
    },
    "VM name or ID (or 'all'): ": {
        "fr": "Nom ou ID de la VM (ou « all ») : ",
        "en": "VM name or ID (or 'all'): ",
    },
    "RAM in MB (blank = version minimum): ": {
        "fr": "RAM en Mo (vide = minimum de la version) : ",
        "en": "RAM in MB (blank = version minimum): ",
    },
    "vCPUs (default: 2): ": {
        "fr": "vCPU (défaut : 2) : ",
        "en": "vCPUs (default: 2): ",
    },
    "Disk size (blank = version min; e.g. 30G, 1T): ": {
        "fr": "Taille du disque (vide = min. version ; ex. 30G, 1T) : ",
        "en": "Disk size (blank = version min; e.g. 30G, 1T): ",
    },
    "VM name (default: ": {
        "fr": "Nom de la VM (défaut : ",
        "en": "VM name (default: ",
    },
    "Deployment failed (see the error above).": {
        "fr": "Échec du déploiement (voir l'erreur ci-dessus).",
        "en": "Deployment failed (see the error above).",
    },
    "SSH public key path": {
        "fr": "Chemin de la clé publique SSH",
        "en": "SSH public key path",
    },
    "Timezone": {
        "fr": "Fuseau horaire",
        "en": "Timezone",
    },
    "virsh cannot reach qemu:///system without sudo.": {
        "fr": "virsh ne peut pas joindre qemu:///system sans sudo.",
        "en": "virsh cannot reach qemu:///system without sudo.",
    },
    "The install monitor runs detached and cannot type a": {
        "fr": "Le suivi d'installation tourne détaché et ne peut pas saisir",
        "en": "The install monitor runs detached and cannot type a",
    },
    "password: it would lose the VM when its lease moves.": {
        "fr": "de mot de passe : il perdrait la VM au changement de bail.",
        "en": "password: it would lose the VM when its lease moves.",
    },
    "You are in the libvirt group, but this session": {
        "fr": "Vous êtes dans le groupe libvirt, mais cette session est",
        "en": "You are in the libvirt group, but this session",
    },
    "predates it. Log out and back in, or run:": {
        "fr": "antérieure. Reconnectez-vous, ou lancez :",
        "en": "predates it. Log out and back in, or run:",
    },
    "Group is active, so the cause is elsewhere:": {
        "fr": "Le groupe est actif : la cause est donc ailleurs.",
        "en": "Group is active, so the cause is elsewhere:",
    },
    "Add your user to the libvirt group?": {
        "fr": "Ajouter votre utilisateur au groupe libvirt ?",
        "en": "Add your user to the libvirt group?",
    },
    "Run it now? (Y/n): ": {
        "fr": "L'exécuter maintenant ? (O/n) : ",
        "en": "Run it now? (Y/n): ",
    },
    "Command failed.": {
        "fr": "La commande a échoué.",
        "en": "Command failed.",
    },
    "Added. Log out and back in for it to take effect,": {
        "fr": "Ajouté. Reconnectez-vous pour que ça prenne effet,",
        "en": "Added. Log out and back in for it to take effect,",
    },
    "or start a new shell with: newgrp libvirt": {
        "fr": "ou ouvrez un shell neuf avec : newgrp libvirt",
        "en": "or start a new shell with: newgrp libvirt",
    },
    "Timezone for the VMs": {
        "fr": "Fuseau horaire des VM",
        "en": "Timezone for the VMs",
    },
    "Locale for the VMs": {
        "fr": "Locale des VM",
        "en": "Locale for the VMs",
    },
    "KVM is unavailable: the VMs will be EMULATED.": {
        "fr": "KVM indisponible : les VM seront ÉMULÉES.",
        "en": "KVM is unavailable: the VMs will be EMULATED.",
    },
    "A boot then takes 10-15 min, not under a minute.": {
        "fr": "Un démarrage prend alors 10 à 15 min, pas moins d'une minute.",
        "en": "A boot then takes 10-15 min, not under a minute.",
    },
    "Cause: /dev/kvm is missing. This host is itself a VM": {
        "fr": "Cause : /dev/kvm est absent. Cet hôte est lui-même une VM",
        "en": "Cause: /dev/kvm is missing. This host is itself a VM",
    },
    "whose hypervisor does not expose nested virtualization.": {
        "fr": "dont l'hyperviseur n'expose pas la virtualisation imbriquée.",
        "en": "whose hypervisor does not expose nested virtualization.",
    },
    "To fix it ON THE PARENT HYPERVISOR, not here:": {
        "fr": "Pour corriger, SUR L'HYPERVISEUR PARENT, pas ici :",
        "en": "To fix it ON THE PARENT HYPERVISOR, not here:",
    },
    "then set this VM to the host-passthrough CPU mode and": {
        "fr": "puis donner à cette VM le mode CPU « host-passthrough », et",
        "en": "then set this VM to the host-passthrough CPU mode and",
    },
    "stop it and start it again - a reboot is not enough.": {
        "fr": "l'arrêter puis la redémarrer — un reboot ne suffit pas.",
        "en": "stop it and start it again - a reboot is not enough.",
    },
    "Without access to that hypervisor, nothing to do here.": {
        "fr": "Sans accès à cet hyperviseur, il n'y a rien à régler ici.",
        "en": "Without access to that hypervisor, nothing to do here.",
    },
    "Usual cause: this host is itself a VM without nested": {
        "fr": "Cause habituelle : cet hôte est lui-même une VM sans",
        "en": "Usual cause: this host is itself a VM without nested",
    },
    "virtualization. Check: systemd-detect-virt": {
        "fr": "virtualisation imbriquée. Vérifier : systemd-detect-virt",
        "en": "virtualization. Check: systemd-detect-virt",
    },
    "Unknown timezone, keeping": {
        "fr": "Fuseau inconnu, on garde",
        "en": "Unknown timezone, keeping",
    },
    "none": {
        "fr": "aucune",
        "en": "none",
    },
    "No SSH key found. Set a password instead? (Y/n): ": {
        "fr": "Aucune clé SSH trouvée. Définir un mot de passe ? (O/n) : ",
        "en": "No SSH key found. Set a password instead? (Y/n): ",
    },
    "Overwrite existing VM disk if present? (y/N): ": {
        "fr": "Écraser le disque de la VM s'il existe ? (o/N, défaut : non) : ",
        "en": "Overwrite existing VM disk if present? (y/N, default: no): ",
    },
    "Verify SHA256 after download? (y/N): ": {
        "fr": "Vérifier le SHA256 après téléchargement ? (o/N, défaut : non) : ",
        "en": "Verify SHA256 after download? (y/N, default: no): ",
    },
    "QEMU - Sample dry-run (demo-vm, Ubuntu 24.04)": {
        "fr": "🧰 QEMU - Exemple dry-run (demo-vm, Ubuntu 24.04)",
        "en": "🧰 QEMU - Sample dry-run (demo-vm, Ubuntu 24.04)",
    },
    # QEMU - statistics screen
    "Statistics (installs, durations, VMs)": {
        "fr": "📊 Statistiques (installations, durées, VM)",
        "en": "📊 Statistics (installs, durations, VMs)",
    },
    "QEMU statistics": {"fr": "Statistiques QEMU", "en": "QEMU statistics"},
    "No installation recorded yet.": {
        "fr": "Aucune installation enregistrée pour l'instant.",
        "en": "No installation recorded yet.",
    },
    "Installations": {"fr": "Installations", "en": "Installations"},
    "Total": {"fr": "Total", "en": "Total"},
    "succeeded": {"fr": "réussies", "en": "succeeded"},
    "failed": {"fr": "échouées", "en": "failed"},
    "Period": {"fr": "Période", "en": "Period"},
    "days": {"fr": "jours", "en": "days"},
    "Median duration": {"fr": "Durée médiane", "en": "Median duration"},
    "min": {"fr": "min", "en": "min"},
    "max": {"fr": "max", "en": "max"},
    "Cumulated time": {"fr": "Temps cumulé", "en": "Cumulated time"},
    "By distribution": {"fr": "Par distribution", "en": "By distribution"},
    "By version": {"fr": "Par version", "en": "By version"},
    "By architecture": {"fr": "Par architecture", "en": "By architecture"},
    "Virtual machines": {
        "fr": "Machines virtuelles",
        "en": "Virtual machines",
    },
    "Defined": {"fr": "Définies", "en": "Defined"},
    "running": {"fr": "en cours", "en": "running"},
    "stopped": {"fr": "arrêtées", "en": "stopped"},
    "Disk used": {"fr": "Disque utilisé", "en": "Disk used"},
    "image": {"fr": "image", "en": "image"},
    "failure": {"fr": "échec", "en": "failure"},
    "Reset the statistics": {
        "fr": "Réinitialiser les statistiques",
        "en": "Reset the statistics",
    },
    "Nothing to reset.": {"fr": "Rien à effacer.", "en": "Nothing to reset."},
    "Erase": {"fr": "Effacer", "en": "Erase"},
    "recorded runs": {"fr": "runs enregistrés", "en": "recorded runs"},
    "runs erased": {"fr": "runs effacés", "en": "runs erased"},
    "Cancelled.": {"fr": "Annulé.", "en": "Cancelled."},
    # Database migration - resume menu
    "Migration in progress": {
        "fr": "Migration en cours",
        "en": "Migration in progress",
    },
    "File": {"fr": "Fichier", "en": "File"},
    "Database": {"fr": "Base", "en": "Database"},
    "Target": {"fr": "Cible", "en": "Target"},
    "Started": {"fr": "Démarrée", "en": "Started"},
    "Steps": {"fr": "Étapes", "en": "Steps"},
    "Prepare the environment": {
        "fr": "Préparer l'environnement",
        "en": "Prepare the environment",
    },
    "Restore and neutralize the database": {
        "fr": "Restaurer et neutraliser la base",
        "en": "Restore and neutralize the database",
    },
    "Update all addons": {
        "fr": "Mettre à jour tous les modules",
        "en": "Update all addons",
    },
    "Clean up before data migration": {
        "fr": "Nettoyer avant la migration des données",
        "en": "Clean up before data migration",
    },
    "Upgrade version by version (OpenUpgrade)": {
        "fr": "Monter de version en version (OpenUpgrade)",
        "en": "Upgrade version by version (OpenUpgrade)",
    },
    "not started": {"fr": "non démarrée", "en": "not started"},
    "done": {"fr": "terminée", "en": "done"},
    "partially done": {"fr": "partielle", "en": "partially done"},
    "version bumps migrated": {
        "fr": "montées de version faites",
        "en": "version bumps migrated",
    },
    "Continue where it stopped": {
        "fr": "Continuer là où ça s'est arrêté",
        "en": "Continue where it stopped",
    },
    "Replay from that step": {
        "fr": "Reprendre à partir de cette étape",
        "en": "Replay from that step",
    },
    "erases the progression of that step and the next ones": {
        "fr": "efface la progression de cette étape et des suivantes",
        "en": "erases the progression of that step and the next ones",
    },
    "New migration, erase everything": {
        "fr": "Nouvelle migration, tout effacer",
        "en": "New migration, erase everything",
    },
    "Keep the zip only, ask every question again": {
        "fr": "Garder seulement le zip, reposer toutes les questions",
        "en": "Keep the zip only, ask every question again",
    },
    "Your choice": {"fr": "Votre choix", "en": "Your choice"},
    "Unknown choice, continuing where it stopped": {
        "fr": "Choix inconnu, on continue là où ça s'est arrêté",
        "en": "Unknown choice, continuing where it stopped",
    },
    "Replaying from step": {
        "fr": "Reprise à partir de l'étape",
        "en": "Replaying from step",
    },
    "Replay the upgrade from version N": {
        "fr": "Reprendre la montée à partir de la version N",
        "en": "Replay the upgrade from version N",
    },
    "rebuilds the intermediate database": {
        "fr": "recrée la base intermédiaire",
        "en": "rebuilds the intermediate database",
    },
    "Unknown version": {"fr": "Version inconnue", "en": "Unknown version"},
    "The progression file is invalid, ignoring it": {
        "fr": "Le fichier de progression est invalide, on l'ignore",
        "en": "The progression file is invalid, ignoring it",
    },
    # --- Menu Execute › Analyse ---
    # L'émoji vit dans la valeur, jamais dans la clé. Deux clés distinctes,
    # comme « Data » / « Database » : l'entrée de menu porte l'émoji,
    # l'étiquette du fil d'Ariane est nue — _todo_telemetry_tui traduit le
    # dernier segment du chemin, et un émoji y détonnerait.
    "Analyse - Odoo database analysis": {
        "fr": "🔬 Analyse - Analyse de base de données Odoo",
        "en": "🔬 Analyse - Odoo database analysis",
    },
    "Analyse": {"fr": "Analyse", "en": "Analysis"},
    "Analyse a database, without ever writing to it!": {
        "fr": "Analyser une base, sans jamais y écrire !",
        "en": "Analyse a database, without ever writing to it!",
    },
    # Les icônes du sous-menu Analyse. Elles sont réservées d'avance pour la
    # famille entière — 🧱 index, 🎈 ballonnement, 📎 pièces jointes,
    # 🔗 ir_model_data — pour qu'ajouter un outil ne demande pas d'en
    # rechercher une libre, et que deux outils voisins ne se ressemblent pas.
    "Structure": {"fr": "🗄  Structure", "en": "🗄  Structure"},
    "Tables and database size": {
        "fr": "📏 Tables et poids de la base",
        "en": "📏 Tables and database size",
    },
    "Customisation": {"fr": "🎭 Personnalisation", "en": "🎭 Customisation"},
    "Customised views, website copies included": {
        "fr": "🖼  Vues personnalisées, copies de site web comprises",
        "en": "🖼  Customised views, website copies included",
    },
    "Analysis failed: ": {
        "fr": "L'analyse a échoué : ",
        "en": "Analysis failed: ",
    },
    "Full list and JSON output:": {
        "fr": "Liste complète et sortie JSON :",
        "en": "Full list and JSON output:",
    },
    "A backup holds no registry, so nothing was compared with the module"
    " source. The classification above needs none; only the differences do."
    " Restore it, or run this on the database.": {
        "fr": "Une sauvegarde n'a pas de registre, donc rien n'a été comparé"
        " avec la source du module. Le classement ci-dessus n'en a pas besoin"
        " ; seuls les écarts en ont. Restaurez-la, ou lancez ceci sur la base.",
        "en": "A backup holds no registry, so nothing was compared with the"
        " module source. The classification above needs none; only the"
        " differences do. Restore it, or run this on the database.",
    },
    "Could not archive the previous log": {
        "fr": "Impossible d'archiver le journal précédent",
        "en": "Could not archive the previous log",
    },
    "Previous migration log kept in": {
        "fr": "Journal de la migration précédente conservé dans",
        "en": "Previous migration log kept in",
    },
    "done early, before the neutralization": {
        "fr": "faite plus tôt, avant la neutralisation",
        "en": "done early, before the neutralization",
    },
    "compare each website copy with the module view it shadows": {
        "fr": "comparer chaque copie de site web à la vue de module qu'elle"
        " masque",
        "en": "compare each website copy with the module view it shadows",
    },
    "Compare the website copies with the view they shadow": {
        "fr": "🪞 Comparer les copies de site web à la vue qu'elles masquent",
        "en": "🪞 Compare the website copies with the view they shadow",
    },
    "website copies compared with their module view,": {
        "fr": "copies de site web comparées à leur vue de module,",
        "en": "website copies compared with their module view,",
    },
    "differ.": {"fr": "diffèrent.", "en": "differ."},
    "What do you want to do with these COW copies?": {
        "fr": "Que voulez-vous faire de ces copies COW ?",
        "en": "What do you want to do with these COW copies?",
    },
    "Enter = decide at the version bump": {
        "fr": "Entrée = décider au palier de version",
        "en": "Enter = decide at the version bump",
    },
    "what each copy holds": {
        "fr": "ce que chaque copie porte",
        "en": "what each copy holds",
    },
    "why it breaks": {
        "fr": "pourquoi ça casse",
        "en": "why it breaks",
    },
    "full screen": {
        "fr": "plein écran",
        "en": "full screen",
    },
    "neutralize now, reversible": {
        "fr": "neutraliser maintenant, réversible",
        "en": "neutralize now, reversible",
    },
    "Undo with": {
        "fr": "Annuler avec",
        "en": "Undo with",
    },
    "Nothing decided": {
        "fr": "Rien de décidé",
        "en": "Nothing decided",
    },
    "the migration will ask again at the version bump.": {
        "fr": "la migration reposera la question au palier de version.",
        "en": "the migration will ask again at the version bump.",
    },
    "Target version directory not found": {
        "fr": "Répertoire de la version cible introuvable",
        "en": "Target version directory not found",
    },
    "No website COW view changes shape in": {
        "fr": "Aucune vue COW de site ne change de forme dans",
        "en": "No website COW view changes shape in",
    },
    "website COW view(s) will break when moving to": {
        "fr": "vue(s) COW de site casseront au passage à",
        "en": "website COW view(s) will break when moving to",
    },
    "the copy keeps an arch whose shape no longer matches what": {
        "fr": "la copie garde une arch dont la forme ne correspond plus à ce que",
        "en": "the copy keeps an arch whose shape no longer matches what",
    },
    "the target module view expects.": {
        "fr": "la vue module cible attend.",
        "en": "the target module view expects.",
    },
    "The migration offers to neutralize them, and shows what": {
        "fr": "La migration propose de les neutraliser, et montre ce que",
        "en": "The migration offers to neutralize them, and shows what",
    },
    "each copy holds before you answer. To look now:": {
        "fr": "chaque copie porte avant que vous répondiez. Pour regarder maintenant :",
        "en": "each copy holds before you answer. To look now:",
    },
    "reversible with --restore": {
        "fr": "réversible avec --restore",
        "en": "reversible with --restore",
    },
    "Or by hand. To neutralize a copy, rename its key": {
        "fr": "Ou à la main. Pour neutraliser une copie, renommer sa clé",
        "en": "Or by hand. To neutralize a copy, rename its key",
    },
    "an unmatched key is never paired with the": {
        "fr": "une clé sans correspondance n'est jamais appariée à la",
        "en": "an unmatched key is never paired with the",
    },
    "module view, so the copy never receives the new": {
        "fr": "vue module, la copie ne reçoit donc jamais le nouveau",
        "en": "module view, so the copy never receives the new",
    },
    "Setting active=false alone is NOT enough:": {
        "fr": "Mettre active=false seul ne suffit PAS :",
        "en": "Setting active=false alone is NOT enough:",
    },
    "an inactive copy keeping the same key still shadows it.": {
        "fr": "une copie inactive gardant la même clé la masque toujours.",
        "en": "an inactive copy keeping the same key still shadows it.",
    },
    "COW view(s) belong to a module absent from": {
        "fr": "vue(s) COW appartiennent à un module absent de",
        "en": "COW view(s) belong to a module absent from",
    },
    "COW view(s) are pages or records made in the website": {
        "fr": "vue(s) COW sont des pages ou des enregistrements faits dans",
        "en": "COW view(s) are pages or records made in the website",
    },
    "editor (no module view of that name): not at risk.": {
        "fr": "l'éditeur de site (aucune vue module de ce nom) : hors de danger.",
        "en": "editor (no module view of that name): not at risk.",
    },
    "Use -v to list them.": {
        "fr": "Utiliser -v pour les lister.",
        "en": "Use -v to list them.",
    },
    "No view with this prefix on": {
        "fr": "Aucune vue avec ce préfixe sur",
        "en": "No view with this prefix on",
    },
    "archived COW view(s) on": {
        "fr": "vue(s) COW archivées sur",
        "en": "archived COW view(s) on",
    },
    "Their arch is intact. Restore them all with --restore,": {
        "fr": "Leur arch est intacte. Toutes les restaurer avec --restore,",
        "en": "Their arch is intact. Restore them all with --restore,",
    },
    "once the module view they shadow has the right shape.": {
        "fr": "une fois que la vue module qu'elles masquent a la bonne forme.",
        "en": "once the module view they shadow has the right shape.",
    },
    "COW view(s) restored on": {
        "fr": "vue(s) COW restaurées sur",
        "en": "COW view(s) restored on",
    },
    "No website COW view to neutralize.": {
        "fr": "Aucune vue COW de site à neutraliser.",
        "en": "No website COW view to neutralize.",
    },
    "website COW view(s) would break the bump": {
        "fr": "vue(s) COW de site casseraient le palier",
        "en": "website COW view(s) would break the bump",
    },
    "to": {
        "fr": "vers",
        "en": "to",
    },
    "Dry-run. Add --apply to rename their key to": {
        "fr": "Simulation. Ajouter --apply pour renommer leur clé en",
        "en": "Dry-run. Add --apply to rename their key to",
    },
    "and deactivate them. Reversible": {
        "fr": "et les désactiver. Réversible",
        "en": "and deactivate them. Reversible",
    },
    "with --restore; the arch stays in database.": {
        "fr": "avec --restore ; l'arch reste en base.",
        "en": "with --restore; the arch stays in database.",
    },
    "COW view(s) neutralized (key prefixed with": {
        "fr": "vue(s) COW neutralisées (clé préfixée par",
        "en": "COW view(s) neutralized (key prefixed with",
    },
    "deactivated). The arch is kept as an": {
        "fr": "désactivées). L'arch est conservée comme",
        "en": "deactivated). The arch is kept as an",
    },
    "archive; use --restore to undo.": {
        "fr": "archive ; utiliser --restore pour annuler.",
        "en": "archive; use --restore to undo.",
    },
    "target inherits, copy holds a standalone template": {
        "fr": "la cible hérite, la copie porte un modèle autonome",
        "en": "target inherits, copy holds a standalone template",
    },
    "target is a root view, copy holds inheritance specs": {
        "fr": "la cible est une vue racine, la copie porte des specs d'héritage",
        "en": "target is a root view, copy holds inheritance specs",
    },
    "No module view carries this key, so there is nothing to": {
        "fr": "Aucune vue module ne porte cette clé, il n'y a donc rien à",
        "en": "No module view carries this key, so there is nothing to",
    },
    "compare: this copy is a page made in the website editor.": {
        "fr": "comparer : cette copie est une page faite dans l'éditeur de site.",
        "en": "compare: this copy is a page made in the website editor.",
    },
    "The copy is identical to the module view.": {
        "fr": "La copie est identique à la vue module.",
        "en": "The copy is identical to the module view.",
    },
    "line(s) added": {
        "fr": "ligne(s) ajoutée(s)",
        "en": "line(s) added",
    },
    "removed": {
        "fr": "retirée(s)",
        "en": "removed",
    },
    "this is what neutralizing gives up.": {
        "fr": "c'est ce que la neutralisation abandonne.",
        "en": "this is what neutralizing gives up.",
    },
    "the module no longer declares this template": {
        "fr": "le module ne déclare plus ce modèle",
        "en": "the module no longer declares this template",
    },
    "inheritance specs (needs inherit_id)": {
        "fr": "des specs d'héritage (exige inherit_id)",
        "en": "inheritance specs (needs inherit_id)",
    },
    "a standalone template": {
        "fr": "un modèle autonome",
        "en": "a standalone template",
    },
    "Odoo changing the shape of its own template is NOT the": {
        "fr": "Qu'Odoo change la forme de son propre modèle n'est PAS le",
        "en": "Odoo changing the shape of its own template is NOT the",
    },
    "problem: on a database without a copy, the module upgrade": {
        "fr": "problème : sur une base sans copie, la mise à jour du module",
        "en": "problem: on a database without a copy, the module upgrade",
    },
    "rewrites the view and nothing breaks. It breaks here because": {
        "fr": "réécrit la vue et rien ne casse. Ça casse ici parce qu'une",
        "en": "rewrites the view and nothing breaks. It breaks here because",
    },
    "a COPY exists and froze the old shape — the copy follows the": {
        "fr": "COPIE existe et a figé l'ancienne forme — la copie suit le",
        "en": "a COPY exists and froze the old shape — the copy follows the",
    },
    "module and becomes an extension, while still holding a": {
        "fr": "module et devient une extension, tout en portant encore un",
        "en": "module and becomes an extension, while still holding a",
    },
    "standalone template. Odoo then applies that template as an": {
        "fr": "modèle autonome. Odoo applique alors ce modèle comme une",
        "en": "standalone template. Odoo then applies that template as an",
    },
    "inheritance spec and stops on « cannot be located in parent": {
        "fr": "spec d'héritage et s'arrête sur « cannot be located in parent",
        "en": "inheritance spec and stops on « cannot be located in parent",
    },
    "view ».": {
        "fr": "view ».",
        "en": "view ».",
    },
    "This copy has no module view of that name: it is a page": {
        "fr": "Cette copie n'a aucune vue module de ce nom : c'est une page",
        "en": "This copy has no module view of that name: it is a page",
    },
    "made in the website editor, and nothing holds its content.": {
        "fr": "faite dans l'éditeur de site, et rien d'autre ne porte son contenu.",
        "en": "made in the website editor, and nothing holds its content.",
    },
    "This copy is IDENTICAL to the module view it shadows: it": {
        "fr": "Cette copie est IDENTIQUE à la vue module qu'elle masque : elle",
        "en": "This copy is IDENTICAL to the module view it shadows: it",
    },
    "holds no customization, so neutralizing it loses nothing.": {
        "fr": "ne porte aucune personnalisation, la neutraliser ne perd rien.",
        "en": "holds no customization, so neutralizing it loses nothing.",
    },
    "This copy differs from the module view by": {
        "fr": "Cette copie diffère de la vue module de",
        "en": "This copy differs from the module view by",
    },
    "line(s):": {
        "fr": "ligne(s) :",
        "en": "line(s):",
    },
    "that is the customization, and all neutralizing gives up.": {
        "fr": "c'est la personnalisation, et tout ce que la neutralisation abandonne.",
        "en": "that is the customization, and all neutralizing gives up.",
    },
    "Run without --shape to read it.": {
        "fr": "Lancer sans --shape pour la lire.",
        "en": "Run without --shape to read it.",
    },
    "No website COW view is at risk.": {
        "fr": "Aucune vue COW de site n'est en danger.",
        "en": "No website COW view is at risk.",
    },
    "No COW copy has drifted from its module view.": {
        "fr": "Aucune copie COW n'a dérivé de sa vue module.",
        "en": "No COW copy has drifted from its module view.",
    },
    "COW copy(ies) drifted from their module": {
        "fr": "copie(s) COW ont dérivé de leur vue",
        "en": "COW copy(ies) drifted from their module",
    },
    "view in": {
        "fr": "module dans",
        "en": "view in",
    },
    "Odoo surfaces this when the module view is rewritten (a": {
        "fr": "Odoo le fait apparaître quand la vue module est réécrite (un",
        "en": "Odoo surfaces this when the module view is rewritten (a",
    },
    "version bump) or when the page is rendered.": {
        "fr": "palier de version) ou quand la page est rendue.",
        "en": "version bump) or when the page is rendered.",
    },
    "NO module view with this key": {
        "fr": "AUCUNE vue module avec cette clé",
        "en": "NO module view with this key",
    },
    "child": {
        "fr": "enfant",
        "en": "child",
    },
    "cannot apply": {
        "fr": "ne peut s'appliquer",
        "en": "cannot apply",
    },
    "Nothing changed. Re-run with --reset <key> --apply to": {
        "fr": "Rien n'a changé. Relancer avec --reset <clé> --apply pour",
        "en": "Nothing changed. Re-run with --reset <key> --apply to",
    },
    "reset a copy onto its module view.": {
        "fr": "réinitialiser une copie sur sa vue module.",
        "en": "reset a copy onto its module view.",
    },
    "no module view to reset onto, skipped.": {
        "fr": "aucune vue module sur laquelle réinitialiser, ignorée.",
        "en": "no module view to reset onto, skipped.",
    },
    "dry-run": {
        "fr": "simulation",
        "en": "dry-run",
    },
    "would reset": {
        "fr": "réinitialiserait",
        "en": "would reset",
    },
    "onto": {
        "fr": "sur",
        "en": "onto",
    },
    "reset": {
        "fr": "réinitialisé",
        "en": "reset",
    },
    "previous arch saved to": {
        "fr": "arch précédente sauvegardée dans",
        "en": "previous arch saved to",
    },
    "copy(ies) reset. Re-apply any real customisation": {
        "fr": "copie(s) réinitialisée(s). Réappliquer toute vraie personnalisation",
        "en": "copy(ies) reset. Re-apply any real customisation",
    },
    "as an INHERITING view, not a copy, so it cannot go stale": {
        "fr": "comme une vue HÉRITANTE, pas une copie, pour qu'elle ne périme plus",
        "en": "as an INHERITING view, not a copy, so it cannot go stale",
    },
    "again.": {
        "fr": "à l'avenir.",
        "en": "again.",
    },
    "lxml is required to resolve the xpath expressions.": {
        "fr": "lxml est requis pour résoudre les expressions xpath.",
        "en": "lxml is required to resolve the xpath expressions.",
    },
    "COW view(s) recorded in": {
        "fr": "vue(s) COW enregistrées dans",
        "en": "COW view(s) recorded in",
    },
    "COW view(s) disappeared": {
        "fr": "vue(s) COW ont disparu",
        "en": "COW view(s) disappeared",
    },
    "COW view(s) appeared": {
        "fr": "vue(s) COW sont apparues",
        "en": "COW view(s) appeared",
    },
    "arch rewritten": {
        "fr": "arch réécrite",
        "en": "arch rewritten",
    },
    "COW view(s) changed": {
        "fr": "vue(s) COW ont changé",
        "en": "COW view(s) changed",
    },
    "No change on the website COW views.": {
        "fr": "Aucun changement sur les vues COW de site.",
        "en": "No change on the website COW views.",
    },
    "Welcome to the Odoo database upgrade with ERPLibre": {
        "fr": "Bienvenue dans la mise à niveau de base de données Odoo avec ERPLibre",
        "en": "Welcome to the Odoo database upgrade with ERPLibre",
    },
    "Select the zip file of your database backup.": {
        "fr": "Sélectionnez le fichier zip de votre sauvegarde de base de données.",
        "en": "Select the zip file of your database backup.",
    },
    "Give the path of the file, or empty to use a file": {
        "fr": "Donnez le chemin du fichier, ou rien pour utiliser un",
        "en": "Give the path of the file, or empty to use a file",
    },
    "browser, or type": {
        "fr": "navigateur de fichiers, ou tapez",
        "en": "browser, or type",
    },
    "to download from production": {
        "fr": "pour télécharger depuis la production",
        "en": "to download from production",
    },
    "Cannot retrieve the database from remote, please retry the migration.": {
        "fr": "Impossible de récupérer la base distante, veuillez relancer la migration.",
        "en": "Cannot retrieve the database from remote, please retry the migration.",
    },
    "Open file": {
        "fr": "Ouverture du fichier",
        "en": "Open file",
    },
    "Detected Odoo CE version": {
        "fr": "Version Odoo CE détectée",
        "en": "Detected Odoo CE version",
    },
    "Which version do you want to upgrade to?": {
        "fr": "Vers quelle version voulez-vous migrer ?",
        "en": "Which version do you want to upgrade to?",
    },
    "Search the Odoo version": {
        "fr": "Recherche de la version Odoo",
        "en": "Search the Odoo version",
    },
    "Find the right environment, read the .zip file": {
        "fr": "Recherche du bon environnement, lecture du fichier .zip",
        "en": "Find the right environment, read the .zip file",
    },
    "Would you like to install": {
        "fr": "Voulez-vous installer",
        "en": "Would you like to install",
    },
    "You need an installed system before": {
        "fr": "Il faut un système installé avant de",
        "en": "You need an installed system before",
    },
    "continuing, check your Odoo installation.": {
        "fr": "continuer, vérifiez votre installation Odoo.",
        "en": "continuing, check your Odoo installation.",
    },
    "Install the environment if missing": {
        "fr": "Installation de l'environnement s'il manque",
        "en": "Install the environment if missing",
    },
    "Search missing modules": {
        "fr": "Recherche des modules manquants",
        "en": "Search missing modules",
    },
    "Install the missing modules, search for them or": {
        "fr": "Installer les modules manquants, les chercher ou",
        "en": "Install the missing modules, search for them or",
    },
    "ask to uninstall them (can break data)": {
        "fr": "demander à les désinstaller (peut casser des données)",
        "en": "ask to uninstall them (can break data)",
    },
    "Cannot set up the environment to begin.": {
        "fr": "Impossible de préparer l'environnement pour commencer.",
        "en": "Cannot set up the environment to begin.",
    },
    "Missing module": {
        "fr": "Module manquant",
        "en": "Missing module",
    },
    "Duplicate module": {
        "fr": "Module en double",
        "en": "Duplicate module",
    },
    "Missing or duplicate module detected at init,": {
        "fr": "Module manquant ou en double détecté à l'init,",
        "en": "Missing or duplicate module detected at init,",
    },
    "do you want to continue?": {
        "fr": "voulez-vous continuer ?",
        "en": "do you want to continue?",
    },
    "Missing or duplicate module detected at init, do": {
        "fr": "Module manquant ou en double détecté à l'init,",
        "en": "Missing or duplicate module detected at init, do",
    },
    "you want to continue?": {
        "fr": "voulez-vous continuer ?",
        "en": "you want to continue?",
    },
    "Which database name do you want to work with?": {
        "fr": "Avec quel nom de base voulez-vous travailler ?",
        "en": "Which database name do you want to work with?",
    },
    "Ignore the database neutralization": {
        "fr": "Ignorer la neutralisation de la base",
        "en": "Ignore the database neutralization",
    },
    "Working with database": {
        "fr": "Travail sur la base",
        "en": "Working with database",
    },
    "will copy": {
        "fr": "va copier",
        "en": "will copy",
    },
    "a file already exists, do you want to": {
        "fr": "un fichier existe déjà, voulez-vous",
        "en": "a file already exists, do you want to",
    },
    "continue?": {
        "fr": "continuer ?",
        "en": "continue?",
    },
    "Restore the database": {
        "fr": "Restauration de la base",
        "en": "Restore the database",
    },
    "Update all addons before neutralizing (already": {
        "fr": "Mettre à jour tous les modules avant la neutralisation (déjà",
        "en": "Update all addons before neutralizing (already",
    },
    "neutralized by Odoo if supported)": {
        "fr": "neutralisée par Odoo si pris en charge)",
        "en": "neutralized by Odoo if supported)",
    },
    "Do you need to upgrade before neutralizing the": {
        "fr": "Faut-il mettre à jour avant de neutraliser la",
        "en": "Do you need to upgrade before neutralizing the",
    },
    "database? Press enter to ignore": {
        "fr": "base ? Entrée pour ignorer",
        "en": "database? Press enter to ignore",
    },
    "Update the database before neutralizing, by module": {
        "fr": "Mise à jour de la base avant neutralisation, par module",
        "en": "Update the database before neutralizing, by module",
    },
    "Neutralize the database": {
        "fr": "Neutralisation de la base",
        "en": "Neutralize the database",
    },
    "Modules to uninstall before the migration": {
        "fr": "Modules à désinstaller avant la migration",
        "en": "Modules to uninstall before the migration",
    },
    "Uninstall modules": {
        "fr": "Désinstallation des modules",
        "en": "Uninstall modules",
    },
    "Install modules": {
        "fr": "Installation des modules",
        "en": "Install modules",
    },
    "Go to Settings / Technical / Cleanup... / Purge and": {
        "fr": "Aller dans Configuration / Technique / Nettoyage... / Purger et",
        "en": "Go to Settings / Technical / Cleanup... / Purge and",
    },
    "purge the obsolete modules": {
        "fr": "purger les modules obsolètes",
        "en": "purge the obsolete modules",
    },
    "Press enter to continue step 3": {
        "fr": "Entrée pour continuer l'étape 3",
        "en": "Press enter to continue step 3",
    },
    "Inspect zip": {
        "fr": "Inspection du zip",
        "en": "Inspect zip",
    },
    "Import database from zip": {
        "fr": "Import de la base depuis le zip",
        "en": "Import database from zip",
    },
    "Succeed update all addons": {
        "fr": "Mise à jour de tous les modules",
        "en": "Succeed update all addons",
    },
    "Clean up database before data migration": {
        "fr": "Nettoyage de la base avant la migration des données",
        "en": "Clean up database before data migration",
    },
    "Upgrade version with OpenUpgrade": {
        "fr": "Montée de version avec OpenUpgrade",
        "en": "Upgrade version with OpenUpgrade",
    },
    "Cleaning up database after upgrade": {
        "fr": "Nettoyage de la base après la montée de version",
        "en": "Cleaning up database after upgrade",
    },
    "Migration finished": {
        "fr": "Migration terminée",
        "en": "Migration finished",
    },
    "Clone to Odoo": {
        "fr": "Clonage vers Odoo",
        "en": "Clone to Odoo",
    },
    "FAILED (status": {
        "fr": "ÉCHEC (statut",
        "en": "FAILED (status",
    },
    "Stopping:": {
        "fr": "Arrêt :",
        "en": "Stopping:",
    },
    "is not usable.": {
        "fr": "n'est pas utilisable.",
        "en": "is not usable.",
    },
    "Clone Odoo": {
        "fr": "Clonage Odoo",
        "en": "Clone Odoo",
    },
    "nothing": {
        "fr": "rien",
        "en": "nothing",
    },
    "Switch Odoo": {
        "fr": "Bascule Odoo",
        "en": "Switch Odoo",
    },
    "done with update": {
        "fr": "terminée avec mise à jour",
        "en": "done with update",
    },
    "Module upgrade Odoo": {
        "fr": "Mise à jour des modules Odoo",
        "en": "Module upgrade Odoo",
    },
    "Database upgrade Odoo": {
        "fr": "Migration de la base Odoo",
        "en": "Database upgrade Odoo",
    },
    "Modules to uninstall before Odoo": {
        "fr": "Modules à désinstaller avant Odoo",
        "en": "Modules to uninstall before Odoo",
    },
    "to redo the command": {
        "fr": "pour refaire la commande",
        "en": "to redo the command",
    },
    "Error detected, press enter to continue or": {
        "fr": "Erreur détectée, Entrée pour continuer ou",
        "en": "Error detected, press enter to continue or",
    },
    "to stop": {
        "fr": "pour arrêter",
        "en": "to stop",
    },
    "Clone done for Odoo": {
        "fr": "Clonage terminé pour Odoo",
        "en": "Clone done for Odoo",
    },
    "Clone already done for Odoo": {
        "fr": "Clonage déjà fait pour Odoo",
        "en": "Clone already done for Odoo",
    },
    "Switch already done for Odoo": {
        "fr": "Bascule déjà faite pour Odoo",
        "en": "Switch already done for Odoo",
    },
    "Switch done with update for Odoo": {
        "fr": "Bascule terminée avec mise à jour pour Odoo",
        "en": "Switch done with update for Odoo",
    },
    "Module upgrade done for Odoo": {
        "fr": "Mise à jour des modules terminée pour Odoo",
        "en": "Module upgrade done for Odoo",
    },
    "Module upgrade already done for Odoo": {
        "fr": "Mise à jour des modules déjà faite pour Odoo",
        "en": "Module upgrade already done for Odoo",
    },
    "Database upgrade done for Odoo": {
        "fr": "Migration de la base terminée pour Odoo",
        "en": "Database upgrade done for Odoo",
    },
    "Database upgrade already done for Odoo": {
        "fr": "Migration de la base déjà faite pour Odoo",
        "en": "Database upgrade already done for Odoo",
    },
    "Cloning to Odoo": {
        "fr": "Clonage vers Odoo",
        "en": "Cloning to Odoo",
    },
    "from": {
        "fr": "depuis",
        "en": "from",
    },
    "Duplicate module in Odoo": {
        "fr": "Module en double dans Odoo",
        "en": "Duplicate module in Odoo",
    },
    "Duplicate module error detected, handle it": {
        "fr": "Erreur de module en double détectée, la traiter",
        "en": "Duplicate module error detected, handle it",
    },
    "manually then press enter to continue.": {
        "fr": "manuellement puis Entrée pour continuer.",
        "en": "manually then press enter to continue.",
    },
    "Missing module error detected, missing in": {
        "fr": "Erreur de module manquant détectée, manquant dans",
        "en": "Missing module error detected, missing in",
    },
    "All of the list above": {
        "fr": "Toute la liste ci-dessus",
        "en": "All of the list above",
    },
    "Add an extra custom one": {
        "fr": "Ajouter un module personnalisé",
        "en": "Add an extra custom one",
    },
    "List the missing modules to delete,": {
        "fr": "Énumérer les modules manquants à supprimer,",
        "en": "List the missing modules to delete,",
    },
    "separated by commas. The others will be": {
        "fr": "séparés par des virgules. Les autres seront",
        "en": "separated by commas. The others will be",
    },
    "migrated": {
        "fr": "migrés",
        "en": "migrated",
    },
    "Migration fix for Odoo": {
        "fr": "Correctif de migration pour Odoo",
        "en": "Migration fix for Odoo",
    },
    "Migration fix done for Odoo": {
        "fr": "Correctif de migration terminé pour Odoo",
        "en": "Migration fix done for Odoo",
    },
    "No migration fix to run for Odoo": {
        "fr": "Aucun correctif de migration à exécuter pour Odoo",
        "en": "No migration fix to run for Odoo",
    },
    "Migration fix already done for Odoo": {
        "fr": "Correctif de migration déjà fait pour Odoo",
        "en": "Migration fix already done for Odoo",
    },
    "List the module names to delete,": {
        "fr": "Énumérer les noms de modules à supprimer,",
        "en": "List the module names to delete,",
    },
    "separated by commas": {
        "fr": "séparés par des virgules",
        "en": "separated by commas",
    },
    "Missing module error": {
        "fr": "Erreur de module manquant",
        "en": "Missing module error",
    },
    "Duplicate module error": {
        "fr": "Erreur de module en double",
        "en": "Duplicate module error",
    },
    "Module error": {
        "fr": "Erreur de module",
        "en": "Module error",
    },
    "Please validate the commits after the code": {
        "fr": "Veuillez valider les commits après la migration",
        "en": "Please validate the commits after the code",
    },
    "migration.": {
        "fr": "du code.",
        "en": "migration.",
    },
    "To show the repo status": {
        "fr": "Pour afficher l'état des dépôts",
        "en": "To show the repo status",
    },
    "Please validate this path in config.conf": {
        "fr": "Veuillez valider ce chemin dans config.conf",
        "en": "Please validate this path in config.conf",
    },
    "Database migration to Odoo": {
        "fr": "Migration de la base vers Odoo",
        "en": "Database migration to Odoo",
    },
    "is now half migrated: replaying the command on": {
        "fr": "est maintenant à moitié migrée : rejouer la commande dessus",
        "en": "is now half migrated: replaying the command on",
    },
    "it would never recover, so it is NOT offered.": {
        "fr": "ne s'en remettrait jamais, ce n'est donc PAS proposé.",
        "en": "it would never recover, so it is NOT offered.",
    },
    "The clone step has been reset. Fix the": {
        "fr": "L'étape de clonage a été réinitialisée. Corrigez la",
        "en": "The clone step has been reset. Fix the",
    },
    "cause, then relaunch the migration and answer": {
        "fr": "cause, puis relancez la migration et répondez",
        "en": "cause, then relaunch the migration and answer",
    },
    "continue": {
        "fr": "continuer",
        "en": "continue",
    },
    "will be dropped and rebuilt from the previous": {
        "fr": "sera supprimée et reconstruite depuis la version",
        "en": "will be dropped and rebuilt from the previous",
    },
    "version before retrying.": {
        "fr": "précédente avant de réessayer.",
        "en": "version before retrying.",
    },
    "Do you want to upgrade all": {
        "fr": "Voulez-vous tout mettre à jour",
        "en": "Do you want to upgrade all",
    },
    "Press y/Y to upgrade all addons of the": {
        "fr": "y/Y pour mettre à jour tous les modules de la",
        "en": "Press y/Y to upgrade all addons of the",
    },
    "Open the server with Selenium": {
        "fr": "Ouvrir le serveur avec Selenium",
        "en": "Open the server with Selenium",
    },
    "Do you want to test this upgrade? Choose": {
        "fr": "Voulez-vous tester cette migration ? Choisissez",
        "en": "Do you want to test this upgrade? Choose",
    },
    "or press enter to ignore it": {
        "fr": "ou Entrée pour ignorer",
        "en": "or press enter to ignore it",
    },
    "Press enter to continue": {
        "fr": "Entrée pour continuer",
        "en": "Press enter to continue",
    },
    "Re-update i18n, purge the data and the tables": {
        "fr": "Remise à jour de l'i18n, purge des données et des tables",
        "en": "Re-update i18n, purge the data and the tables",
    },
    "except mail_test and mail_test_full": {
        "fr": "sauf mail_test et mail_test_full",
        "en": "except mail_test and mail_test_full",
    },
    "A backup can be created": {
        "fr": "Une sauvegarde peut être créée",
        "en": "A backup can be created",
    },
    "Press y/Y or type filename.zip to export, or": {
        "fr": "y/Y ou un nom fichier.zip pour exporter, ou",
        "en": "Press y/Y or type filename.zip to export, or",
    },
    "enter to continue": {
        "fr": "Entrée pour continuer",
        "en": "enter to continue",
    },
    "Test the migration, press y/Y": {
        "fr": "Tester la migration, y/Y",
        "en": "Test the migration, press y/Y",
    },
    "Documentation for this version": {
        "fr": "Documentation de cette version",
        "en": "Documentation for this version",
    },
    "Command not found": {
        "fr": "Commande non trouvée",
        "en": "Command not found",
    },
    "Execute command": {
        "fr": "Exécution de la commande",
        "en": "Execute command",
    },
    "Textual is missing from this interpreter:": {
        "fr": "Textual manque à cet interpréteur :",
        "en": "Textual is missing from this interpreter:",
    },
    "Run it with": {
        "fr": "Le lancer avec",
        "en": "Run it with",
    },
    "No leftover for theme": {
        "fr": "Aucun reste pour le thème",
        "en": "No leftover for theme",
    },
    "attachment(s) still under": {
        "fr": "pièce(s) jointe(s) encore sous",
        "en": "attachment(s) still under",
    },
    "view(s) whose key still names it": {
        "fr": "vue(s) dont la clé le nomme encore",
        "en": "view(s) whose key still names it",
    },
    "Nothing was deleted: their content may be the only trace": {
        "fr": "Rien n'a été supprimé : leur contenu peut être la seule trace",
        "en": "Nothing was deleted: their content may be the only trace",
    },
    "of a customization. Read before removing.": {
        "fr": "d'une personnalisation. Lire avant de retirer.",
        "en": "of a customization. Read before removing.",
    },
    "Installed theme(s) on": {
        "fr": "Thème(s) installé(s) sur",
        "en": "Installed theme(s) on",
    },
    "A theme carries view copies and SCSS through every": {
        "fr": "Un thème traîne des copies de vues et des SCSS à travers chaque",
        "en": "A theme carries view copies and SCSS through every",
    },
    "version bump, and a bump can rename what they rely on.": {
        "fr": "palier de version, et un palier peut renommer ce dont ils dépendent.",
        "en": "version bump, and a bump can rename what they rely on.",
    },
    "Uninstall them properly before migrating?": {
        "fr": "Les désinstaller proprement avant de migrer ?",
        "en": "Uninstall them properly before migrating?",
    },
    "Kept. Nothing was uninstalled.": {
        "fr": "Conservés. Rien n'a été désinstallé.",
        "en": "Kept. Nothing was uninstalled.",
    },
    "No customized SCSS is at risk in": {
        "fr": "Aucun SCSS personnalisé n'est en danger dans",
        "en": "No customized SCSS is at risk in",
    },
    "customized SCSS use(s) a variable that": {
        "fr": "SCSS personnalisé(s) utilisent une variable que",
        "en": "customized SCSS use(s) a variable that",
    },
    "no longer defines: the bundle will not compile.": {
        "fr": "ne définit plus : le bundle ne compilera pas.",
        "en": "no longer defines: the bundle will not compile.",
    },
    "Each one is a copy frozen on an older version. Dropping it": {
        "fr": "Chacun est une copie figée sur une version antérieure. L'abandonner",
        "en": "Each one is a copy frozen on an older version. Dropping it",
    },
    "restores the module file:": {
        "fr": "rend le fichier du module :",
        "en": "restores the module file:",
    },
    "Read it first: what it holds beyond the stale variable is": {
        "fr": "Le lire d'abord : ce qu'il porte au-delà de la variable périmée est",
        "en": "Read it first: what it holds beyond the stale variable is",
    },
    "a real customization, to re-apply as a small file.": {
        "fr": "une vraie personnalisation, à réappliquer en petit fichier.",
        "en": "a real customization, to re-apply as a small file.",
    },
    "Read the customizations above before continuing.": {
        "fr": "Lire les personnalisations ci-dessus avant de continuer.",
        "en": "Read the customizations above before continuing.",
    },
    "Missing:": {
        "fr": "Manquantes :",
        "en": "Missing:",
    },
    "No module file of that name in": {
        "fr": "Aucun fichier de module de ce nom dans",
        "en": "No module file of that name in",
    },
    "the target no longer ships it, so there is nothing to": {
        "fr": "la cible ne le livre plus, il n'y a donc rien sur quoi",
        "en": "the target no longer ships it, so there is nothing to",
    },
    "fall back on. Read the copy before dropping it.": {
        "fr": "retomber. Lire la copie avant de l'abandonner.",
        "en": "fall back on. Read the copy before dropping it.",
    },
    "The copy is identical to the module file.": {
        "fr": "La copie est identique au fichier du module.",
        "en": "The copy is identical to the module file.",
    },
    "line(s): that is what resetting gives up.": {
        "fr": "ligne(s) : c'est ce que la réinitialisation abandonne.",
        "en": "line(s): that is what resetting gives up.",
    },
    "What do you want to do with these customizations?": {
        "fr": "Que voulez-vous faire de ces personnalisations ?",
        "en": "What do you want to do with these customizations?",
    },
    "Enter = nothing": {
        "fr": "Entrée = rien",
        "en": "Enter = nothing",
    },
    "what the copy changed": {
        "fr": "ce que la copie a changé",
        "en": "what the copy changed",
    },
    "reset them onto the module file": {
        "fr": "les réinitialiser sur le fichier du module",
        "en": "reset them onto the module file",
    },
    "Full screen view unavailable.": {
        "fr": "Vue plein écran indisponible.",
        "en": "Full screen view unavailable.",
    },
    "Saved before resetting": {
        "fr": "Sauvegardé avant réinitialisation",
        "en": "Saved before resetting",
    },
    "Reset failed, nothing was changed.": {
        "fr": "La réinitialisation a échoué, rien n'a été modifié.",
        "en": "Reset failed, nothing was changed.",
    },
    "Reset done.": {
        "fr": "Réinitialisation faite.",
        "en": "Reset done.",
    },
    "This copy uses variables that": {
        "fr": "Cette copie utilise des variables que",
        "en": "This copy uses variables that",
    },
    "no longer defines": {
        "fr": "ne définit plus",
        "en": "no longer defines",
    },
    "The copy was written against an older version and frozen": {
        "fr": "La copie a été écrite contre une version antérieure et figée",
        "en": "The copy was written against an older version and frozen",
    },
    "there. The module has since renamed what it relies on.": {
        "fr": "là. Le module a depuis renommé ce dont elle dépend.",
        "en": "there. The module has since renamed what it relies on.",
    },
    "Resetting restores": {
        "fr": "La réinitialisation rend",
        "en": "Resetting restores",
    },
    "(nothing: the target no longer ships this file)": {
        "fr": "(rien : la cible ne livre plus ce fichier)",
        "en": "(nothing: the target no longer ships this file)",
    },
    "Reset command copied.": {
        "fr": "Commande de réinitialisation copiée.",
        "en": "Reset command copied.",
    },
    "Resetting needs Odoo 13.0 or later; this checkout is on": {
        "fr": "La réinitialisation exige Odoo 13.0 ou plus ; ce checkout est sur",
        "en": "Resetting needs Odoo 13.0 or later; this checkout is on",
    },
    "The prediction stands, the fix does not: run it again once": {
        "fr": "La prédiction tient, pas la correction : relancer une fois",
        "en": "The prediction stands, the fix does not: run it again once",
    },
    "the bump is done, on the upgraded database.": {
        "fr": "le palier passé, sur la base montée de version.",
        "en": "the bump is done, on the upgraded database.",
    },
    "Applying it from here fails with": {
        "fr": "L'appliquer d'ici échoue sur",
        "en": "Applying it from here fails with",
    },
    "and changes nothing.": {
        "fr": "et ne change rien.",
        "en": "and changes nothing.",
    },
    "Reset one of them onto its module view": {
        "fr": "Réinitialiser l'une d'elles sur sa vue module",
        "en": "Reset one of them onto its module view",
    },
    "Drifted COW copies": {
        "fr": "Copies COW ayant dérivé",
        "en": "Drifted COW copies",
    },
    "Which one(s) to reset onto the module view?": {
        "fr": "Laquelle ou lesquelles réinitialiser sur la vue module ?",
        "en": "Which one(s) to reset onto the module view?",
    },
    "numbers separated by commas, a = all, empty =": {
        "fr": "numéros séparés par des virgules, a = toutes, vide =",
        "en": "numbers separated by commas, a = all, empty =",
    },
    "Kept. Nothing was reset.": {
        "fr": "Conservées. Rien n'a été réinitialisé.",
        "en": "Kept. Nothing was reset.",
    },
    "Unknown choice, nothing was reset.": {
        "fr": "Choix inconnu, rien n'a été réinitialisé.",
        "en": "Unknown choice, nothing was reset.",
    },
    "Delete these leftovers, or keep them?": {
        "fr": "Effacer ces restes, ou les garder ?",
        "en": "Delete these leftovers, or keep them?",
    },
    "Enter = keep": {
        "fr": "Entrée = garder",
        "en": "Enter = keep",
    },
    "delete, after saving them": {
        "fr": "effacer, après les avoir sauvegardés",
        "en": "delete, after saving them",
    },
    "Kept. Nothing was deleted.": {
        "fr": "Conservés. Rien n'a été effacé.",
        "en": "Kept. Nothing was deleted.",
    },
    "Saved before deleting": {
        "fr": "Sauvegardé avant effacement",
        "en": "Saved before deleting",
    },
    "Deletion failed, nothing was removed.": {
        "fr": "L'effacement a échoué, rien n'a été retiré.",
        "en": "Deletion failed, nothing was removed.",
    },
    "attachment(s) deleted.": {
        "fr": "pièce(s) jointe(s) effacée(s).",
        "en": "attachment(s) deleted.",
    },
    "Nothing to decide yet": {
        "fr": "Rien à décider pour l'instant",
        "en": "Nothing to decide yet",
    },
    "the migration will offer to neutralize these copies": {
        "fr": "la migration proposera de neutraliser ces copies",
        "en": "the migration will offer to neutralize these copies",
    },
    "at the version bump itself, showing what each one holds.": {
        "fr": "au moment du palier lui-même, en montrant ce que chacune"
        " contient.",
        "en": "at the version bump itself, showing what each one holds.",
    },
    "Press to continue": {
        "fr": "Appuyez pour continuer",
        "en": "Press to continue",
    },
    "(b = go back to a previous step)": {
        "fr": "(b = revenir à une étape précédente)",
        "en": "(b = go back to a previous step)",
    },
    "Neutralize database, press to continue": {
        "fr": "Neutraliser la base, appuyez pour continuer",
        "en": "Neutralize database, press to continue",
    },
    "Replay from which step? (empty to cancel)": {
        "fr": "Rejouer à partir de quelle étape ? (vide pour annuler)",
        "en": "Replay from which step? (empty to cancel)",
    },
    "Rewound.": {"fr": "Rembobiné.", "en": "Rewound."},
    "Relaunch the migration to resume from there.": {
        "fr": "Relancez la migration pour reprendre à partir de là.",
        "en": "Relaunch the migration to resume from there.",
    },
    "Go back to a step": {
        "fr": "Revenir à une étape",
        "en": "Go back to a step",
    },
    "Choose a step, Enter replays from there.": {
        "fr": "Choisissez une étape, Entrée rejoue à partir de là.",
        "en": "Choose a step, Enter replays from there.",
    },
    # --- script/analyse : vues personnalisées ---
    "Customised views": {
        "fr": "Vues personnalisées",
        "en": "Customised views",
    },
    "Views": {"fr": "Vues", "en": "Views"},
    "why": {"fr": "pourquoi", "en": "why"},
    "more": {"fr": "de plus", "en": "more"},
    "From an installed theme": {
        "fr": "Posée par un thème installé",
        "en": "From an installed theme",
    },
    "Website copy (COW)": {
        "fr": "Copie de site web (COW)",
        "en": "Website copy (COW)",
    },
    "Made with Studio": {"fr": "Faite avec Studio", "en": "Made with Studio"},
    "Imported or exported": {
        "fr": "Importée ou exportée",
        "en": "Imported or exported",
    },
    "Created from the interface": {
        "fr": "Créée depuis l'interface",
        "en": "Created from the interface",
    },
    "From a module, flagged as touched": {
        "fr": "D'un module, signalée comme retouchée",
        "en": "From a module, flagged as touched",
    },
    "Straight from a module": {
        "fr": "Telle quelle depuis un module",
        "en": "Straight from a module",
    },
    "Every view comes straight from a module.": {
        "fr": "Toutes les vues viennent telles quelles d'un module.",
        "en": "Every view comes straight from a module.",
    },
    "Views that did not come straight from a module": {
        "fr": "Vues qui ne viennent pas telles quelles d'un module",
        "en": "Views that did not come straight from a module",
    },
    "Website copies are user data: Odoo copies a view instead of editing it."
    " Whether they will survive the next version is another question, and"
    " these tools answer it:": {
        "fr": "Les copies de site web sont des données utilisateur : Odoo"
        " copie une vue au lieu de la modifier. Savoir si elles survivront à"
        " la prochaine version est une autre question, et ces outils y"
        " répondent :",
        "en": "Website copies are user data: Odoo copies a view instead of"
        " editing it. Whether they will survive the next version is another"
        " question, and these tools answer it:",
    },
    "Flags say a view was touched, not how. They are incomplete both ways: a"
    " direct SQL write does not set arch_updated, and reset_arch clears it."
    " Comparing with the module source is what settles it.": {
        "fr": "Les drapeaux disent qu'une vue a été touchée, pas comment. Ils"
        " sont incomplets dans les deux sens : un write SQL direct n'arme pas"
        " arch_updated, et reset_arch l'efface. Seule la comparaison avec la"
        " source du module tranche.",
        "en": "Flags say a view was touched, not how. They are incomplete"
        " both ways: a direct SQL write does not set arch_updated, and"
        " reset_arch clears it. Comparing with the module source is what"
        " settles it.",
    },
    "List the views of an Odoo database that did not come straight from a"
    " module, website copies included (read-only).": {
        "fr": "Lister les vues d'une base Odoo qui ne viennent pas telles"
        " quelles d'un module, copies de site web comprises (lecture seule).",
        "en": "List the views of an Odoo database that did not come straight"
        " from a module, website copies included (read-only).",
    },
    "only show this category": {
        "fr": "n'afficher que cette catégorie",
        "en": "only show this category",
    },
    "how many views to show (default: 20)": {
        "fr": "nombre de vues à afficher (défaut : 20)",
        "en": "how many views to show (default: 20)",
    },
    "list every view": {
        "fr": "afficher toutes les vues",
        "en": "list every view",
    },
    "which views to compare (default: flagged)": {
        "fr": "quelles vues comparer (défaut : celles qui sont signalées)",
        "en": "which views to compare (default: flagged)",
    },
    "From a module, silently drifted": {
        "fr": "D'un module, dérivée en silence",
        "en": "From a module, silently drifted",
    },
    "In --scope all, a difference is a lead, not a verdict:"
    " read_arch_from_file returns the raw file, while the database holds the"
    " arch AFTER load-time processing. Measured on a freshly installed 18.0"
    " database, 160 of its 974 views already differ this way.": {
        "fr": "En --scope all, un écart est une piste, pas un verdict :"
        " read_arch_from_file rend le fichier brut, alors que la base porte"
        " l'arch APRÈS traitement au chargement. Mesuré sur une base 18.0"
        " fraîchement installée, 160 de ses 974 vues diffèrent déjà ainsi.",
        "en": "In --scope all, a difference is a lead, not a verdict:"
        " read_arch_from_file returns the raw file, while the database holds"
        " the arch AFTER load-time processing. Measured on a freshly installed"
        " 18.0 database, 160 of its 974 views already differ this way.",
    },
    "Compare with the module source? (Y/n): ": {
        "fr": "Comparer avec la source du module ? (O/n) : ",
        "en": "Compare with the module source? (Y/n): ",
    },
    # --- Menu Analyse : les actions « aller plus loin ». Ce qui était
    # conseillé en options de ligne de commande est devenu des entrées :
    # dire « utilisez -v » à quelqu'un qui est dans un menu, c'est lui
    # demander d'en sortir pour obtenir ce que le menu pouvait offrir.
    "Browse the differences (TUI)": {
        "fr": "🖥  Naviguer dans les écarts (plein écran)",
        "en": "🖥  Browse the differences (TUI)",
    },
    "Compare every view (slower, noisier)": {
        "fr": "🔬 Comparer toutes les vues (plus long, plus bruyant)",
        "en": "🔬 Compare every view (slower, noisier)",
    },
    "Compare first, then browse.": {
        "fr": "Comparez d'abord, vous naviguerez ensuite.",
        "en": "Compare first, then browse.",
    },
    "Compare the flagged views with the module source": {
        "fr": "🔍 Comparer les vues signalées avec la source du module",
        "en": "🔍 Compare the flagged views with the module source",
    },
    "Count rows exactly (full scan)": {
        "fr": "🔢 Compter les lignes exactement (balayage complet)",
        "en": "🔢 Count rows exactly (full scan)",
    },
    "Counting rows exactly, one scan per table…": {
        "fr": "Comptage exact des lignes, un balayage par table…",
        "en": "Counting rows exactly, one scan per table…",
    },
    "Export as JSON": {"fr": "💾 Exporter en JSON", "en": "💾 Export as JSON"},
    "Go further": {"fr": "🔎 Aller plus loin", "en": "🔎 Go further"},
    "Loading the Odoo registry, this takes a moment…": {
        "fr": "Chargement du registre Odoo, cela prend un moment…",
        "en": "Loading the Odoo registry, this takes a moment…",
    },
    "No view differs from its module source.": {
        "fr": "Aucune vue ne diffère de la source de son module.",
        "en": "No view differs from its module source.",
    },
    "Show every table": {
        "fr": "📜 Afficher toutes les tables",
        "en": "📜 Show every table",
    },
    "Show every view": {
        "fr": "📜 Afficher toutes les vues",
        "en": "📜 Show every view",
    },
    "Written to: ": {"fr": "Écrit dans : ", "en": "Written to: "},
    "Flags say a view was touched, not how: only comparing with the module"
    " source settles it.": {
        "fr": "Les drapeaux disent qu'une vue a été touchée, pas comment :"
        " seule la comparaison avec la source du module tranche.",
        "en": "Flags say a view was touched, not how: only comparing with the"
        " module source settles it.",
    },
    "blocking": {"fr": "bloquants", "en": "blocking"},
    "Studio and hand-made x_ fields": {
        "fr": "🧩 Champs x_ (Studio et faits à la main)",
        "en": "🧩 Studio and hand-made x_ fields",
    },
    "Show every field": {
        "fr": "📜 Afficher tous les champs",
        "en": "📜 Show every field",
    },
    "A database": {"fr": "💾 Une base de données", "en": "💾 A database"},
    "A backup .zip, without restoring it": {
        "fr": "🗜  Une sauvegarde .zip, sans la restaurer",
        "en": "🗜  A backup .zip, without restoring it",
    },
    "Path to the backup .zip (empty to cancel): ": {
        "fr": "Chemin de la sauvegarde .zip (vide pour annuler) : ",
        "en": "Path to the backup .zip (empty to cancel): ",
    },
    "No such file: ": {"fr": "Fichier introuvable : ", "en": "No such file: "},
    "from a backup": {"fr": "depuis une sauvegarde", "en": "from a backup"},
    "Odoo backup .zip to inspect, without restoring it": {
        "fr": "sauvegarde Odoo .zip à examiner, sans la restaurer",
        "en": "Odoo backup .zip to inspect, without restoring it",
    },
    "Not an Odoo backup (no manifest.json): ": {
        "fr": "Pas une sauvegarde Odoo (aucun manifest.json) : ",
        "en": "Not an Odoo backup (no manifest.json): ",
    },
    "Cannot read the backup: ": {
        "fr": "Lecture impossible de la sauvegarde : ",
        "en": "Cannot read the backup: ",
    },
    "This backup holds no dump.sql: ": {
        "fr": "Cette sauvegarde ne contient aucun dump.sql : ",
        "en": "This backup holds no dump.sql: ",
    },
    # --- script/analyse : champs et modèles hors module ---
    "Nothing declares these in a file, so no module will "
    "recreate them. What a version upgrade keeps is what "
    "someone carried over.": {
        "fr": "Rien ne les déclare dans un fichier, donc aucun module "
        "ne les recréera. Ce qu'une montée de version conserve "
        "est ce que quelqu'un a reporté.",
        "en": "Nothing declares these in a file, so no module will "
        "recreate them. What a version upgrade keeps is what "
        "someone carried over.",
    },
    "A stored field without its column stops the registry "
    "from loading, so the upgrade will not even start. Settle "
    "these before anything else.": {
        "fr": "Un champ stocké sans sa colonne empêche le registre de "
        "charger, donc la montée de version ne démarrera même "
        "pas. Réglez cela avant tout le reste.",
        "en": "A stored field without its column stops the registry "
        "from loading, so the upgrade will not even start. Settle "
        "these before anything else.",
    },
    "Use -v to list them all, --json for the raw data.": {
        "fr": "Utilisez -v pour tout afficher, --json pour la donnée "
        "brute.",
        "en": "Use -v to list them all, --json for the raw data.",
    },
    "List the fields and models added outside a module — "
    "Studio or by hand (read-only).": {
        "fr": "Lister les champs et modèles ajoutés hors module — "
        "Studio ou faits à la main (lecture seule).",
        "en": "List the fields and models added outside a module — "
        "Studio or by hand (read-only).",
    },
    "how many to show (default: 30)": {
        "fr": "nombre à afficher (défaut : 30)",
        "en": "how many to show (default: 30)",
    },
    "list every one": {"fr": "tout afficher", "en": "list every one"},
    "Studio": {"fr": "Studio", "en": "Studio"},
    "Made by hand": {"fr": "Fait à la main", "en": "Made by hand"},
    "Declared by a module": {
        "fr": "Déclaré par un module",
        "en": "Declared by a module",
    },
    "stored, but its column is missing": {
        "fr": "stocké, mais sa colonne manque",
        "en": "stored, but its column is missing",
    },
    "points at a model that no longer exists": {
        "fr": "pointe vers un modèle qui n'existe plus",
        "en": "points at a model that no longer exists",
    },
    "its model no longer exists": {
        "fr": "son modèle n'existe plus",
        "en": "its model no longer exists",
    },
    "its table could not be resolved": {
        "fr": "sa table n'a pas pu être résolue",
        "en": "its table could not be resolved",
    },
    "origin": {"fr": "provenance", "en": "origin"},
    "Fields added outside a module": {
        "fr": "Champs ajoutés hors module",
        "en": "Fields added outside a module",
    },
    "Custom fields": {"fr": "Champs personnalisés", "en": "Custom fields"},
    "Custom models": {"fr": "Modèles personnalisés", "en": "Custom models"},
    "No field or model was added outside a module.": {
        "fr": "Aucun champ ni modèle n'a été ajouté hors module.",
        "en": "No field or model was added outside a module.",
    },
    "Blocking": {"fr": "Bloquant", "en": "Blocking"},
    "To carry over by hand": {
        "fr": "À reporter à la main",
        "en": "To carry over by hand",
    },
    # --- script/analyse : comparaison et navigation des écarts ---
    "Differences only": {
        "fr": "Écarts seuls",
        "en": "Differences only",
    },
    "Ignore indentation": {
        "fr": "Ignorer l'indentation",
        "en": "Ignore indentation",
    },
    "Copy": {
        "fr": "Copier",
        "en": "Copy",
    },
    "Reset command": {
        "fr": "Commande de réinitialisation",
        "en": "Reset command",
    },
    "module (file)": {
        "fr": "module (fichier)",
        "en": "module (file)",
    },
    "database": {
        "fr": "base",
        "en": "database",
    },
    "Difference copied.": {
        "fr": "Écart copié.",
        "en": "Difference copied.",
    },
    "No Odoo configuration file found.": {
        "fr": "Aucun fichier de configuration Odoo trouvé.",
        "en": "No Odoo configuration file found.",
    },
    "odoo_bin.sh not found.": {
        "fr": "odoo_bin.sh est introuvable.",
        "en": "odoo_bin.sh not found.",
    },
    "The Odoo shell returned no result: ": {
        "fr": "Le shell Odoo n'a rien renvoyé : ",
        "en": "The Odoo shell returned no result: ",
    },
    "The Odoo shell exceeded the timeout (s): ": {
        "fr": "Le shell Odoo a dépassé le délai imparti (s) : ",
        "en": "The Odoo shell exceeded the timeout (s): ",
    },
    "Unreadable JSON from the Odoo shell: ": {
        "fr": "JSON illisible en sortie du shell Odoo : ",
        "en": "Unreadable JSON from the Odoo shell: ",
    },
    "To restore a view to what its module declares — this "
    "WRITES to the database, so read the difference first:": {
        "fr": "Pour rendre à une vue ce que déclare son module — ceci "
        "ÉCRIT dans la base, lisez donc l'écart d'abord :",
        "en": "To restore a view to what its module declares — this "
        "WRITES to the database, so read the difference first:",
    },
    "compare with the module source (opens an Odoo shell)": {
        "fr": "comparer avec la source du module (ouvre un shell Odoo)",
        "en": "compare with the module source (opens an Odoo shell)",
    },
    "fail if the comparison could not be made": {
        "fr": "échouer si la comparaison n'a pas pu être faite",
        "en": "fail if the comparison could not be made",
    },
    "browse the differences in a full-screen view": {
        "fr": "naviguer dans les écarts en plein écran",
        "en": "browse the differences in a full-screen view",
    },
    "Flags say a view was touched, not how. They are incomplete "
    "both ways: a direct SQL write does not set arch_updated, "
    "and reset_arch clears it. Comparing with the module source "
    "is what settles it — add --diff.": {
        "fr": "Les drapeaux disent qu'une vue a été touchée, pas comment. "
        "Ils sont incomplets dans les deux sens : un write SQL "
        "direct n'arme pas arch_updated, et reset_arch l'efface. "
        "Seule la comparaison avec la source du module tranche — "
        "ajoutez --diff.",
        "en": "Flags say a view was touched, not how. They are incomplete "
        "both ways: a direct SQL write does not set arch_updated, "
        "and reset_arch clears it. Comparing with the module source "
        "is what settles it — add --diff.",
    },
    "Database is Odoo": {
        "fr": "La base est en Odoo",
        "en": "Database is Odoo",
    },
    "checkout is": {
        "fr": "le checkout est en",
        "en": "checkout is",
    },
    "views were flagged but hold exactly what their module "
    "declares: only the comparison could tell.": {
        "fr": "vues étaient signalées mais portent exactement ce que "
        "déclare leur module : seule la comparaison pouvait le "
        "dire.",
        "en": "views were flagged but hold exactly what their module "
        "declares: only the comparison could tell.",
    },
    "No reference arch, so nothing was compared: ": {
        "fr": "Aucune arch de référence, donc rien n'a été comparé : ",
        "en": "No reference arch, so nothing was compared: ",
    },
    "Not a terminal: showing the text report instead.": {
        "fr": "Pas un terminal : affichage du rapport texte à la place.",
        "en": "Not a terminal: showing the text report instead.",
    },
    "To restore this view to what its module declares:": {
        "fr": "Pour rendre à cette vue ce que déclare son module :",
        "en": "To restore this view to what its module declares:",
    },
    # --- script/analyse : erreurs du socle ---
    "Invalid database name: ": {
        "fr": "Nom de base invalide : ",
        "en": "Invalid database name: ",
    },
    "Cannot read from the database: ": {
        "fr": "Lecture impossible dans la base : ",
        "en": "Cannot read from the database: ",
    },
    "is not an Odoo database.": {
        "fr": "n'est pas une base Odoo.",
        "en": "is not an Odoo database.",
    },
    "psql is not installed or not in PATH.": {
        "fr": "psql n'est pas installé, ou absent du PATH.",
        "en": "psql is not installed or not in PATH.",
    },
    "Query exceeded the timeout (s): ": {
        "fr": "La requête a dépassé le délai imparti (s) : ",
        "en": "Query exceeded the timeout (s): ",
    },
    "Unreadable JSON from psql: ": {
        "fr": "JSON illisible en sortie de psql : ",
        "en": "Unreadable JSON from psql: ",
    },
    "shared library, nothing to run here.": {
        "fr": "bibliothèque partagée, rien à lancer ici.",
        "en": "shared library, nothing to run here.",
    },
    "Runnable tools in this directory:": {
        "fr": "Outils exécutables de ce répertoire :",
        "en": "Runnable tools in this directory:",
    },
    "No analysis tool here yet.": {
        "fr": "Aucun outil d'analyse ici pour l'instant.",
        "en": "No analysis tool here yet.",
    },
    "From the menu:": {"fr": "Depuis le menu :", "en": "From the menu:"},
    "in the dump": {"fr": "dans le dump", "en": "in the dump"},
    "Weight in the dump": {
        "fr": "Poids dans le dump",
        "en": "Weight in the dump",
    },
    # --- script/analyse : poids du schéma ---
    "Schema analysis": {
        "fr": "Analyse du schéma",
        "en": "Schema analysis",
    },
    "Database size": {
        "fr": "Poids de la base",
        "en": "Database size",
    },
    "Tables": {"fr": "Tables", "en": "Tables"},
    "Models": {"fr": "Modèles", "en": "Models"},
    "rows": {"fr": "lignes", "en": "rows"},
    "Models without table": {
        "fr": "Modèles sans table",
        "en": "Models without table",
    },
    "abstract models have none, by design": {
        "fr": "les modèles abstraits n'en ont pas, par construction",
        "en": "abstract models have none, by design",
    },
    "ir_model_relation is absent, so m2m tables cannot be told apart from"
    " orphans: the list below is unreliable.": {
        "fr": "ir_model_relation est absente : impossible de distinguer une"
        " table m2m d'une orpheline, la liste ci-dessous n'est pas fiable.",
        "en": "ir_model_relation is absent, so m2m tables cannot be told apart"
        " from orphans: the list below is unreliable.",
    },
    "Heaviest tables": {
        "fr": "Tables les plus lourdes",
        "en": "Heaviest tables",
    },
    "All tables, heaviest first": {
        "fr": "Toutes les tables, de la plus lourde à la plus légère",
        "en": "All tables, heaviest first",
    },
    "use -v to list them all": {
        "fr": "utilisez -v pour toutes les afficher",
        "en": "use -v to list them all",
    },
    "Every table belongs to an installed model.": {
        "fr": "Chaque table appartient à un modèle installé.",
        "en": "Every table belongs to an installed model.",
    },
    "Orphan tables": {
        "fr": "Tables orphelines",
        "en": "Orphan tables",
    },
    "No installed model claims these tables. They are usually left over from"
    " modules uninstalled without DROP TABLE, and every version upgrade"
    " carries them along.": {
        "fr": "Aucun modèle installé ne réclame ces tables. Ce sont le plus"
        " souvent des reliquats de modules désinstallés sans DROP TABLE, que"
        " chaque montée de version transporte avec elle.",
        "en": "No installed model claims these tables. They are usually left"
        " over from modules uninstalled without DROP TABLE, and every version"
        " upgrade carries them along.",
    },
    "Check what they hold before dropping anything.": {
        "fr": "Regardez ce qu'elles contiennent avant de supprimer quoi que ce"
        " soit.",
        "en": "Check what they hold before dropping anything.",
    },
    "Row counts are estimates from the last ANALYZE. Use --exact for real"
    " counts, at the cost of one full scan per table.": {
        "fr": "Les nombres de lignes sont estimés d'après le dernier ANALYZE."
        " Utilisez --exact pour un comptage réel, au prix d'un balayage"
        " complet par table.",
        "en": "Row counts are estimates from the last ANALYZE. Use --exact for"
        " real counts, at the cost of one full scan per table.",
    },
    "Report the size of an Odoo database and the tables no installed model"
    " claims (read-only).": {
        "fr": "Rapporter le poids d'une base Odoo et les tables qu'aucun"
        " modèle installé ne réclame (lecture seule).",
        "en": "Report the size of an Odoo database and the tables no installed"
        " model claims (read-only).",
    },
    "database to inspect": {
        "fr": "base à examiner",
        "en": "database to inspect",
    },
    "count rows exactly: one full scan per table": {
        "fr": "compter les lignes exactement : un balayage complet par table",
        "en": "count rows exactly: one full scan per table",
    },
    "how many tables to show (default: 20)": {
        "fr": "nombre de tables à afficher (défaut : 20)",
        "en": "how many tables to show (default: 20)",
    },
    "list every table": {
        "fr": "afficher toutes les tables",
        "en": "list every table",
    },
    "output JSON": {"fr": "sortie JSON", "en": "output JSON"},
    "path to an Odoo config file": {
        "fr": "chemin d'un fichier de configuration Odoo",
        "en": "path to an Odoo config file",
    },
    # Courriel
    "mail_menu": {
        "fr": "Courriel - Lire et envoyer du courriel",
        "en": "Mail - Read and send email",
    },
    "mail_ai_question": {
        "fr": "Question IA - Poser une question à un modèle",
        "en": "AI question - Ask a model a question",
    },
    "mail_open_tui": {
        "fr": "Ouvrir le client courriel (TUI)",
        "en": "Open the mail client (TUI)",
    },
    "mail_accounts_menu": {"fr": "Comptes", "en": "Accounts"},
    "mail_sync_now": {
        "fr": "Synchroniser maintenant",
        "en": "Synchronise now",
    },
    "mail_cache_menu": {"fr": "Cache", "en": "Cache"},
    "mail_account_list": {"fr": "Lister les comptes", "en": "List accounts"},
    "mail_account_add": {"fr": "Ajouter un compte", "en": "Add an account"},
    "mail_account_delete": {
        "fr": "Supprimer un compte",
        "en": "Delete an account",
    },
    "mail_account_template": {
        "fr": "Générer un modèle accounts.json",
        "en": "Generate an accounts.json template",
    },
    "mail_account_test": {
        "fr": "Tester la connexion d'un compte",
        "en": "Test an account connection",
    },
    "mail_cache_default_mode": {
        "fr": "Mode de cache par défaut",
        "en": "Default cache mode",
    },
    "mail_cache_account_mode": {
        "fr": "Mode de cache d'un compte",
        "en": "Cache mode of one account",
    },
    "mail_cache_size_purge": {
        "fr": "Taille du cache et purge",
        "en": "Cache size and purge",
    },
    "mail_no_account": {
        "fr": "Aucun compte configuré. Ajoutez-en un d'abord.",
        "en": "No account configured. Add one first.",
    },
    "mail_ask_name": {
        "fr": "Nom court du compte : ",
        "en": "Short account name: ",
    },
    "mail_ask_email": {"fr": "Adresse courriel : ", "en": "Email address: "},
    "mail_ask_display_name": {
        "fr": "Nom affiché (facultatif) : ",
        "en": "Display name (optional): ",
    },
    "mail_ask_preset": {"fr": "Fournisseur : ", "en": "Provider: "},
    "mail_ask_password": {"fr": "Mot de passe : ", "en": "Password: "},
    "mail_ask_imap_host": {"fr": "Serveur IMAP : ", "en": "IMAP server: "},
    "mail_ask_smtp_host": {"fr": "Serveur SMTP : ", "en": "SMTP server: "},
    "mail_ask_account": {"fr": "Quel compte ? ", "en": "Which account? "},
    "mail_ask_mode": {
        "fr": "Mode (clear / encrypted / ephemeral) : ",
        "en": "Mode (clear / encrypted / ephemeral): ",
    },
    "mail_app_password_note": {
        "fr": "Ce fournisseur exige un mot de passe d'application.",
        "en": "This provider requires an app password.",
    },
    "mail_account_saved": {"fr": "Compte enregistré.", "en": "Account saved."},
    "mail_account_save": {"fr": "Enregistrer", "en": "Save"},
    "mail_account_missing_fields": {
        "fr": "Nom, adresse et mot de passe sont requis.",
        "en": "Name, address and password are required.",
    },
    "mail_account_add_unavailable": {
        "fr": "Ajout de compte indisponible dans ce contexte.",
        "en": "Adding an account is unavailable in this context.",
    },
    "mail_account_deleted": {
        "fr": "Compte supprimé.",
        "en": "Account deleted.",
    },
    "mail_connection_ok": {
        "fr": "Connexion réussie.",
        "en": "Connection succeeded.",
    },
    "mail_connection_failed": {
        "fr": "Connexion échouée :",
        "en": "Connection failed:",
    },
    "mail_template_written": {
        "fr": "Modèle écrit dans",
        "en": "Template written to",
    },
    "mail_purge_confirm": {
        "fr": "Effacer tout le cache de ce compte ? (o/N) ",
        "en": "Erase this account's whole cache? (y/N) ",
    },
    "mail_purged": {"fr": "Cache effacé.", "en": "Cache erased."},
    "mail_no_vault": {
        "fr": "Aucun coffre disponible : installez pykeepass ou déverrouillez un trousseau système.",
        "en": "No vault available: install pykeepass or unlock a system keyring.",
    },
    # Coffre KeePass, côté infrastructure partagée (`kdbx_manager`) : ces
    # messages servent à TOUT le CLI, pas seulement au courriel.
    "kdbx_vault_is": {
        "fr": "Coffre KeePass :",
        "en": "KeePass vault:",
    },
    "kdbx_ask_password": {
        "fr": "Mot de passe du coffre (vide pour abandonner) : ",
        "en": "Vault password (empty to give up): ",
    },
    "kdbx_wrong_password": {
        "fr": "Mot de passe incorrect pour ce coffre KeePass.",
        "en": "Wrong password for this KeePass vault.",
    },
    "kdbx_give_up": {
        "fr": "Coffre non ouvert : on abandonne.",
        "en": "Vault not opened: giving up.",
    },
    "mail_kdbx_none_configured": {
        "fr": "Aucun fichier kdbx n'est configuré.",
        "en": "No kdbx file is configured.",
    },
    "mail_kdbx_menu_create": {
        "fr": "Créer un nouveau fichier .kdbx",
        "en": "Create a new .kdbx file",
    },
    "mail_kdbx_menu_choose": {
        "fr": "Choisir un fichier existant",
        "en": "Choose an existing file",
    },
    "mail_kdbx_menu_cancel": {"fr": "Annuler", "en": "Cancel"},
    "mail_kdbx_ask_choice": {"fr": "Votre choix : ", "en": "Your choice: "},
    "mail_kdbx_ask_path_new": {
        "fr": "Chemin du nouveau fichier kdbx",
        "en": "Path for the new kdbx file",
    },
    "mail_kdbx_ask_path_existing": {
        "fr": "Chemin du fichier kdbx existant : ",
        "en": "Path to the existing kdbx file: ",
    },
    "mail_kdbx_ask_password": {
        "fr": "Mot de passe du coffre : ",
        "en": "Vault password: ",
    },
    "mail_kdbx_ask_password_confirm": {
        "fr": "Confirmez le mot de passe : ",
        "en": "Confirm the password: ",
    },
    "mail_kdbx_password_mismatch": {
        "fr": "Les mots de passe ne correspondent pas.",
        "en": "Passwords do not match.",
    },
    "mail_kdbx_path_not_found": {
        "fr": "Ce fichier n'existe pas :",
        "en": "This file does not exist:",
    },
    "mail_kdbx_created": {
        "fr": "Fichier kdbx créé :",
        "en": "Kdbx file created:",
    },
    "mail_kdbx_path_recorded": {
        "fr": "Fichier kdbx configuré :",
        "en": "Kdbx file configured:",
    },
    "mail_no_password_stored": {
        "fr": "Aucun mot de passe enregistré pour ce compte.",
        "en": "No password stored for this account.",
    },
    "mail_install_textual": {
        "fr": "Installez textual pour le client courriel (pip).",
        "en": "Install textual for the mail client (pip).",
    },
    "mail_accounts": {"fr": "Comptes", "en": "Accounts"},
    "mail_search": {"fr": "Rechercher…", "en": "Search…"},
    "mail_search_clear": {
        "fr": "Effacer la recherche",
        "en": "Clear search",
    },
    "mail_from": {"fr": "De :", "en": "From:"},
    "mail_to": {"fr": "À :", "en": "To:"},
    "mail_cc": {"fr": "Cc :", "en": "Cc:"},
    "mail_subject": {"fr": "Objet :", "en": "Subject:"},
    "mail_date": {"fr": "Date", "en": "Date"},
    "mail_send": {"fr": "Envoyer", "en": "Send"},
    "mail_attachments": {"fr": "Pièces jointes :", "en": "Attachments:"},
    "mail_attachments_paths": {
        "fr": "Pièces jointes (chemins séparés par des points-virgules)",
        "en": "Attachments (semicolon-separated paths)",
    },
    "mail_browse": {"fr": "Parcourir…", "en": "Browse…"},
    "mail_browse_failed": {
        "fr": "Sélecteur de fichiers impossible :",
        "en": "File browser unavailable:",
    },
    "mail_no_subject": {"fr": "(sans objet)", "en": "(no subject)"},
    "mail_body_needs_network": {
        "fr": "Corps non téléchargé — connexion requise.",
        "en": "Body not downloaded — connection required.",
    },
    "mail_body_error": {
        "fr": "Lecture du corps impossible :",
        "en": "Cannot read the body:",
    },
    "mail_flag_error": {
        "fr": "Drapeau non transmis au serveur :",
        "en": "Flag not sent to the server:",
    },
    "mail_syncing": {"fr": "Synchronisation de", "en": "Synchronising"},
    "mail_new_messages": {"fr": "nouveaux messages", "en": "new messages"},
    "mail_errors": {"fr": "erreurs", "en": "errors"},
    "mail_folders_resynced": {
        "fr": "dossiers resynchronisés (UIDVALIDITY changé) :",
        "en": "folders resynchronised (UIDVALIDITY changed):",
    },
    "mail_offline_cannot_send": {
        "fr": "Compte hors ligne : envoi impossible.",
        "en": "Account offline: cannot send.",
    },
    "mail_sent_to": {"fr": "Envoyé à", "en": "Sent to"},
    "mail_sent_not_filed": {
        "fr": "envoyé, mais pas classé dans Envoyés",
        "en": "sent, but not filed in Sent",
    },
    "mail_nothing_to_reply_to": {
        "fr": "Aucun message sélectionné.",
        "en": "No message selected.",
    },
    "mail_nothing_to_forward": {
        "fr": "Aucun message à transférer.",
        "en": "No message to forward.",
    },
    "mail_attachment_not_found": {
        "fr": "Pièce jointe introuvable.",
        "en": "Attachment not found.",
    },
    "mail_no_attachment": {
        "fr": "Ce message n'a pas de pièce jointe.",
        "en": "This message has no attachment.",
    },
    "mail_save_failed": {
        "fr": "Enregistrement impossible :",
        "en": "Cannot save:",
    },
    "mail_saved_to": {"fr": "Enregistré dans", "en": "Saved to"},
    "mail_log_binding": {"fr": "Journal", "en": "Log"},
    "mail_log_close": {"fr": "Fermer", "en": "Close"},
    "mail_log_tail_heading": {
        "fr": "Journal (fin) :",
        "en": "Log (tail):",
    },
    "mail_log_errors_heading": {
        "fr": "Erreurs de synchronisation (session en cours) :",
        "en": "Sync errors (current session):",
    },
    "mail_log_missing": {
        "fr": "journal introuvable",
        "en": "log not found",
    },
    "mail_log_empty": {"fr": "journal vide", "en": "log empty"},
    "mail_log_unreadable": {
        "fr": "journal illisible",
        "en": "log unreadable",
    },
    "mail_log_no_errors": {
        "fr": "Aucune erreur de synchronisation dans cette session.",
        "en": "No sync errors in this session.",
    },
    "mail_layout_binding": {"fr": "Vue", "en": "View"},
    "mail_layout_switched": {"fr": "Disposition :", "en": "Layout:"},
    "mail_layout_columns": {"fr": "Colonnes", "en": "Columns"},
    "mail_layout_split": {"fr": "Partagée", "en": "Split"},
    "mail_layout_stacked": {"fr": "Empilée", "en": "Stacked"},
    "mail_pane_grow_binding": {"fr": "Agrandir volet", "en": "Grow pane"},
    "mail_pane_shrink_binding": {
        "fr": "Rétrécir volet",
        "en": "Shrink pane",
    },
    "mail_pane_reset_binding": {
        "fr": "Tailles par défaut",
        "en": "Reset sizes",
    },
    "mail_pane_reset_done": {
        "fr": "Tailles des volets réinitialisées.",
        "en": "Pane sizes reset.",
    },
    "mail_pane_splitter_tooltip": {
        "fr": "Glisser pour redimensionner",
        "en": "Drag to resize",
    },
    "mail_fullscreen_binding": {"fr": "Plein écran", "en": "Full screen"},
    # -- Libellés des raccourcis de MailApp (suffixe _binding) -------------
    # Ce sont les descriptions des `Binding` de `MailApp` : elles s'affichent
    # au pied d'écran ET, depuis la tâche 26, dans la fenêtre d'aide (`h`),
    # qui les lit directement dans `MailApp.BINDINGS`. Le français est repris
    # MOT POUR MOT de ce qui était écrit en dur avant cette tâche — le pied
    # d'écran d'un utilisateur francophone ne change pas.
    "mail_quit_binding": {"fr": "Quitter", "en": "Quit"},
    "mail_sync_current_binding": {"fr": "Sync", "en": "Sync"},
    "mail_sync_all_binding": {"fr": "Sync tout", "en": "Sync all"},
    "mail_back_binding": {"fr": "Retour", "en": "Back"},
    "mail_search_binding": {"fr": "Rechercher", "en": "Search"},
    "mail_mark_seen_binding": {"fr": "Lu", "en": "Read"},
    "mail_mark_unseen_binding": {"fr": "Non lu", "en": "Unread"},
    "mail_save_attachment_binding": {
        "fr": "Enregistrer PJ",
        "en": "Save attachment",
    },
    "mail_compose_binding": {"fr": "Écrire", "en": "Compose"},
    "mail_reply_binding": {"fr": "Répondre", "en": "Reply"},
    "mail_reply_all_binding": {"fr": "Répondre à tous", "en": "Reply all"},
    "mail_forward_binding": {"fr": "Transférer", "en": "Forward"},
    "mail_add_account_binding": {
        "fr": "Nouveau compte",
        "en": "New account",
    },
    # -- Fenêtre d'aide (touche h) -----------------------------------------
    # La liste des touches n'est PAS ici : elle est engendrée depuis
    # `MailApp.BINDINGS` (voir `HelpScreen`), avec les libellés ci-dessus.
    # Seul ce qu'une liste de touches ne peut pas dire est rédigé ici.
    "mail_help_binding": {"fr": "Aide", "en": "Help"},
    "mail_help_close": {"fr": "Fermer", "en": "Close"},
    "mail_help_title": {
        "fr": "Aide — client courriel",
        "en": "Help — mail client",
    },
    "mail_help_keys_heading": {
        "fr": "Raccourcis clavier :",
        "en": "Keyboard shortcuts:",
    },
    "mail_help_notes_heading": {"fr": "Bon à savoir :", "en": "Good to know:"},
    "mail_help_mouse": {
        "fr": (
            "Souris : glisser une barre entre deux volets les redimensionne."
            " Au clavier, + et - font de même sur le volet qui a le focus, et"
            " 0 remet les tailles par défaut. Les tailles sont retenues par"
            " disposition."
        ),
        "en": (
            "Mouse: drag a bar between two panes to resize them. From the"
            " keyboard, + and - do the same to the focused pane, and 0 resets"
            " the sizes. Sizes are remembered per layout."
        ),
    },
    "mail_help_layouts": {
        "fr": (
            "Dispositions : v passe de colonnes à partagée, puis empilée, puis"
            " revient à colonnes."
        ),
        "en": (
            "Layouts: v cycles columns, split, stacked, then back to columns."
        ),
    },
    "mail_help_sync": {
        "fr": (
            "Synchronisation : r synchronise le compte du dossier sélectionné"
            " (tous ses dossiers), R synchronise tous les comptes. La"
            " synchronisation automatique ne tourne QUE tant que le client est"
            " ouvert, à l'intervalle mail_refresh_sec (300 s par défaut ; 0 la"
            " désactive)."
        ),
        "en": (
            "Sync: r syncs the account of the selected folder (all its"
            " folders), R syncs every account. The automatic refresh runs ONLY"
            " while the client is open, at the mail_refresh_sec interval (300 s"
            " by default; 0 disables it)."
        ),
    },
    "mail_help_files": {
        "fr": (
            "Fichiers : le journal est dans ~/.erplibre/mail.log (la touche l"
            " en montre la fin), les comptes dans"
            " ~/.erplibre/mail/accounts.json. Les mots de passe n'y sont JAMAIS"
            " écrits : ils vivent dans le coffre kdbx ou le trousseau du"
            " système."
        ),
        "en": (
            "Files: the log lives in ~/.erplibre/mail.log (the l key shows its"
            " tail), the accounts in ~/.erplibre/mail/accounts.json. Passwords"
            " are NEVER written there: they live in the kdbx vault or in the"
            " system keyring."
        ),
    },
    "mail_help_close_hint": {
        "fr": "Échap ferme cette fenêtre.",
        "en": "Esc closes this window.",
    },
    # -- Exceptions internes au paquet courriel (préfixe mail_err_) --------
    # Label traduit, données dynamiques (chemins, texte serveur, valeurs de
    # config) concaténées crues : jamais de traduction d'un message serveur
    # ou d'un chemin de fichier.
    #
    # Quelques messages ont la donnée dynamique AU MILIEU de la phrase : ils
    # sont donc assemblés à partir de deux clés (voire trois), dans un ordre
    # FIXE codé au site d'appel plutôt que par une seule clé avec un
    # emplacement — mail_err_unknown_security + mail_err_expected,
    # mail_err_key_wrong_length + mail_err_octets_unit,
    # mail_err_mode_prefix + mail_err_mode_requires_key(_no_vault),
    # mail_err_imap_connection_prefix / mail_err_smtp_connection_prefix +
    # mail_err_connection_refused_suffix, et mail_err_keyring_plaintext +
    # mail_err_keyring_plaintext_hint. L'ordre des mots vit donc dans le
    # code, pas dans les chaînes traduisibles : une langue à l'ordre des
    # mots différent devra remplacer ces paires par une convention à
    # emplacement (ex. `.format()`), pas par une simple concaténation.
    "mail_err_envelope_too_short": {
        "fr": "enveloppe trop courte",
        "en": "envelope too short",
    },
    "mail_err_sealed_in_clear_mode": {
        "fr": "donnée chiffrée lue en mode clair : la clé du compte manque",
        "en": "encrypted data read in clear mode: the account key is missing",
    },
    "mail_err_unknown_envelope": {
        "fr": "enveloppe inconnue :",
        "en": "unknown envelope:",
    },
    "mail_err_key_wrong_length": {
        "fr": "la clé doit faire",
        "en": "the key must be",
    },
    "mail_err_octets_unit": {"fr": "octets", "en": "bytes"},
    "mail_err_cryptography_not_installed": {
        "fr": "le paquet cryptography n'est pas installé",
        "en": "the cryptography package is not installed",
    },
    "mail_err_decrypt_refused": {
        "fr": "déchiffrement refusé : clé fausse ou donnée altérée",
        "en": "decryption refused: wrong key or corrupted data",
    },
    "mail_err_envelope_unreadable": {
        "fr": "enveloppe illisible :",
        "en": "unreadable envelope:",
    },
    "mail_err_mode_prefix": {"fr": "le mode", "en": "mode"},
    "mail_err_mode_requires_key": {
        "fr": "exige une clé",
        "en": "requires a key",
    },
    "mail_err_unknown_cache_mode": {
        "fr": "mode de cache inconnu :",
        "en": "unknown cache mode:",
    },
    "mail_err_file_already_exists": {
        "fr": "le fichier existe déjà :",
        "en": "the file already exists:",
    },
    "mail_err_invalid_secret_ref": {
        "fr": "référence de secret invalide :",
        "en": "invalid secret reference:",
    },
    # Notes par fournisseur. Affichées à l'ajout d'un compte ET juste avant
    # de redemander un mot de passe après un refus : elles doivent donner
    # l'adresse EXACTE, pas un chemin de menu — Google et Apple déplacent
    # régulièrement ces pages, et Google cache la sienne.
    "mail_preset_note_gmail": {
        "fr": (
            "Générez-le sur https://myaccount.google.com/apppasswords"
            " (16 caractères, les espaces sont acceptés). La validation en"
            " deux étapes doit être active, sinon la page est vide."
        ),
        "en": (
            "Generate one at https://myaccount.google.com/apppasswords"
            " (16 characters, spaces are accepted). Two-step verification"
            " must be on, otherwise the page is empty."
        ),
    },
    "mail_preset_note_outlook": {
        "fr": (
            "Générez-le sur https://account.microsoft.com/security."
            " Microsoft ferme l'authentification simple sur les comptes"
            " grand public : sans mot de passe d'application, il faudra"
            " OAuth (phase 2, non implémentée)."
        ),
        "en": (
            "Generate one at https://account.microsoft.com/security."
            " Microsoft is closing basic authentication on consumer"
            " accounts: without an app password this needs OAuth (phase 2,"
            " not implemented)."
        ),
    },
    "mail_preset_note_icloud": {
        "fr": (
            "Générez-le sur https://account.apple.com, section « Connexion"
            " et sécurité ». L'authentification à deux facteurs doit être"
            " active."
        ),
        "en": (
            'Generate one at https://account.apple.com, under "Sign-In and'
            ' Security". Two-factor authentication must be on.'
        ),
    },
    "mail_preset_note_generic": {
        "fr": "Saisissez les serveurs de votre fournisseur.",
        "en": "Enter your provider's servers.",
    },
    "mail_ask_app_password": {
        "fr": "Mot de passe d'application : ",
        "en": "App password: ",
    },
    "mail_err_password_not_ascii": {
        "fr": (
            "le mot de passe contient un caractère non ASCII, que ce client"
            " IMAP ne sait pas transmettre — il n'a pas été envoyé au"
            " serveur"
        ),
        "en": (
            "the password contains a non-ASCII character this IMAP client"
            " cannot transmit — it was never sent to the server"
        ),
    },
    "mail_err_no_kdbx_configured": {
        "fr": "aucun fichier kdbx configuré",
        "en": "no kdbx file configured",
    },
    "mail_err_kdbx_unreadable": {
        "fr": "le fichier kdbx n'a pas pu être ouvert",
        "en": "the kdbx file could not be opened",
    },
    "mail_err_no_vault_available": {
        "fr": "aucun coffre disponible : ni kdbx, ni trousseau système",
        "en": "no vault available: neither kdbx nor system keyring",
    },
    "mail_err_keyring_plaintext": {
        "fr": (
            "le trousseau du système écrirait le mot de passe en clair"
            " (backend"
        ),
        "en": (
            "the system keyring would store the password in plaintext"
            " (backend"
        ),
    },
    "mail_err_keyring_plaintext_hint": {
        "fr": "Utilisez un fichier kdbx, ou déverrouillez un vrai trousseau.",
        "en": "Use a kdbx file, or unlock a real keyring.",
    },
    "mail_err_unknown_security": {
        "fr": "sécurité inconnue :",
        "en": "unknown security:",
    },
    "mail_err_expected": {"fr": "(attendu", "en": "(expected"},
    "mail_err_account_needs_name": {
        "fr": "un compte doit avoir un nom",
        "en": "an account must have a name",
    },
    "mail_err_invalid_account_name": {
        "fr": "nom de compte invalide :",
        "en": "invalid account name:",
    },
    "mail_err_account_name_reason": {
        "fr": "(il sert de nom de dossier et de référence de coffre)",
        "en": "(it is used as a folder name and vault reference)",
    },
    "mail_err_account_unreadable": {
        "fr": "compte illisible :",
        "en": "unreadable account:",
    },
    "mail_err_unknown_preset": {
        "fr": "préréglage inconnu :",
        "en": "unknown preset:",
    },
    "mail_err_not_valid_json": {
        "fr": "n'est pas du JSON valide :",
        "en": "is not valid JSON:",
    },
    "mail_err_should_contain_json_object": {
        "fr": "devrait contenir un objet JSON",
        "en": "should contain a JSON object",
    },
    "mail_err_duplicate_account_names": {
        "fr": "noms de compte en double :",
        "en": "duplicate account names:",
    },
    "mail_err_already_exists_relaunch": {
        "fr": "existe déjà — relancez avec l'option de remplacement",
        "en": "already exists — rerun with the overwrite option",
    },
    "mail_err_symlink_refused": {
        "fr": "est un lien symbolique : cache refusé",
        "en": "is a symlink: cache refused",
    },
    "mail_err_owned_by_other_user": {
        "fr": "appartient à un autre utilisateur : cache refusé",
        "en": "belongs to another user: cache refused",
    },
    "mail_err_cache_unreadable": {
        "fr": "cache illisible, purgez-le et resynchronisez :",
        "en": "unreadable cache, purge it and resynchronise:",
    },
    "mail_err_mode_requires_key_no_vault": {
        "fr": "exige une clé : aucun coffre fourni",
        "en": "requires a key: no vault provided",
    },
    "mail_err_cache_not_open": {
        "fr": "cache non ouvert : appelez open() d'abord",
        "en": "cache not open: call open() first",
    },
    "mail_err_unknown_folder_fields": {
        "fr": "champs de dossier inconnus :",
        "en": "unknown folder fields:",
    },
    "mail_err_unterminated_ampersand": {
        "fr": "séquence & non terminée",
        "en": "unterminated & sequence",
    },
    "mail_err_server_replied": {
        "fr": ": le serveur a répondu",
        "en": ": the server replied",
    },
    "mail_err_no_body_for_uid": {
        "fr": "aucun corps rendu pour l'UID",
        "en": "no body returned for UID",
    },
    "mail_err_imap_connection_prefix": {
        "fr": "connexion IMAP à",
        "en": "IMAP connection to",
    },
    "mail_err_smtp_connection_prefix": {
        "fr": "connexion SMTP à",
        "en": "SMTP connection to",
    },
    "mail_err_connection_refused_suffix": {
        "fr": "refusée :",
        "en": "refused:",
    },
    "mail_err_message_needs_recipient": {
        "fr": "un message doit avoir au moins un destinataire",
        "en": "a message must have at least one recipient",
    },
    "mail_err_attachment_missing": {
        "fr": "pièce jointe introuvable :",
        "en": "attachment not found:",
    },
    "mail_err_no_recipient_nothing_sent": {
        "fr": "aucun destinataire : rien n'a été envoyé",
        "en": "no recipient: nothing was sent",
    },
    "mail_err_send_refused": {"fr": "envoi refusé :", "en": "send refused:"},
}


def get_lang() -> str:
    global _current_lang
    if _current_lang is not None:
        return _current_lang

    # 1. Check env_var.sh file
    if os.path.exists(ENV_VAR_FILE):
        try:
            with open(ENV_VAR_FILE) as f:
                content = f.read()
            match = re.search(
                r'^EL_LANG=["\']?(\w+)["\']?', content, re.MULTILINE
            )
            if match:
                lang = match.group(1)
                if lang in ("fr", "en"):
                    _current_lang = lang
                    return _current_lang
        except OSError:
            pass

    # 2. Check env var
    env_lang = os.environ.get("EL_LANG")
    if env_lang in ("fr", "en"):
        _current_lang = env_lang
        return _current_lang

    # 3. Default
    _current_lang = "fr"
    return _current_lang


def set_lang(lang: str) -> None:
    global _current_lang
    _current_lang = lang

    # Persist to env_var.sh
    if os.path.exists(ENV_VAR_FILE):
        try:
            with open(ENV_VAR_FILE) as f:
                content = f.read()
        except OSError:
            return

        new_line = f'EL_LANG="{lang}"'
        if re.search(r"^EL_LANG=", content, re.MULTILINE):
            content = re.sub(
                r'^EL_LANG=["\']?\w*["\']?',
                new_line,
                content,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            content = content.rstrip("\n") + "\n" + new_line + "\n"

        with open(ENV_VAR_FILE, "w") as f:
            f.write(content)


def lang_is_configured() -> bool:
    """Check if a language has been explicitly set."""
    if os.path.exists(ENV_VAR_FILE):
        try:
            with open(ENV_VAR_FILE) as f:
                content = f.read()
            return bool(re.search(r"^EL_LANG=", content, re.MULTILINE))
        except OSError:
            pass
    return False


def t(key: str) -> str:
    entry = TRANSLATIONS.get(key)
    if entry is None:
        return key
    lang = get_lang()
    return entry.get(lang, entry.get("fr", key))
