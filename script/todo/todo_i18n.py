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
    "Question": {
        "fr": "❓ Question",
        "en": "❓ Question",
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
        "fr": "🗑 Effacer une ou plusieurs VM",
        "en": "🗑 Delete VM(s)",
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
        "fr": "QEMU - Exemple dry-run (demo-vm, Ubuntu 24.04)",
        "en": "QEMU - Sample dry-run (demo-vm, Ubuntu 24.04)",
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
