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
        "fr": "Exécution",
        "en": "Execute",
    },
    "Install": {
        "fr": "Installation",
        "en": "Install",
    },
    "Question": {
        "fr": "Question",
        "en": "Question",
    },
    "Fork - Open TODO in a new tab": {
        "fr": "Fork - Ouvre TODO dans une nouvelle tabulation",
        "en": "Fork - Open TODO in a new tab",
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
        "fr": "Retour",
        "en": "Back",
    },
    # Execute submenu
    "Run - Execute and install an instance": {
        "fr": "Run - Exécuter et installer une instance",
        "en": "Run - Execute and install an instance",
    },
    "Automation - Demonstration of developed features": {
        "fr": "Automatisation - Demonstration des fonctions développées",
        "en": "Automation - Demonstration of developed features",
    },
    "Update - Update all developed staging source code": {
        "fr": "Mise à jour - Update all developed staging source code",
        "en": "Update - Update all developed staging source code",
    },
    "Code - Developer tools": {
        "fr": "Code - Outil pour développeur",
        "en": "Code - Developer tools",
    },
    "Doc - Documentation search": {
        "fr": "Doc - Recherche de documentation",
        "en": "Doc - Documentation search",
    },
    "Database - Database tools": {
        "fr": "Database - Outils sur les bases de données",
        "en": "Database - Database tools",
    },
    "Process - Execution tools": {
        "fr": "Process - Outils sur les executions",
        "en": "Process - Execution tools",
    },
    "Config - Configuration file management": {
        "fr": "Config - Traitement du fichier de configuration",
        "en": "Config - Configuration file management",
    },
    "Network - Network tools": {
        "fr": "Réseau - Outil réseautique",
        "en": "Network - Network tools",
    },
    "Security - Dependency security audit": {
        "fr": "Sécurité - Audit de sécurité des dépendances",
        "en": "Security - Dependency security audit",
    },
    "RTK - CLI proxy to reduce LLM token consumption": {
        "fr": "RTK - Proxy CLI pour réduire la consommation de tokens LLM",
        "en": "RTK - CLI proxy to reduce LLM token consumption",
    },
    "Language - Change language / Changer la langue": {
        "fr": "Langue - Changer la langue / Change language",
        "en": "Language - Change language / Changer la langue",
    },
    # Deploy section
    "Deploy - Deploy ERPLibre locally": {
        "fr": "Déploiement - Déployer ERPLibre localement",
        "en": "Deploy - Deploy ERPLibre locally",
    },
    "Deploy ERPLibre to a local directory!": {
        "fr": "Déployer ERPLibre dans un répertoire local!",
        "en": "Deploy ERPLibre to a local directory!",
    },
    "Clone ERPLibre locally (git clone)": {
        "fr": "Cloner ERPLibre localement (git clone)",
        "en": "Clone ERPLibre locally (git clone)",
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
        "fr": "Mise à jour de tous les erplibre_base sur la base de données test",
        "en": "Update all erplibre_base on database test",
    },
    "Show code status": {
        "fr": "Afficher le statut du code",
        "en": "Show code status",
    },
    "Stash all code": {
        "fr": "Remiser tout le code",
        "en": "Stash all code",
    },
    "Format modified code": {
        "fr": "Formater le code modifié",
        "en": "Format modified code",
    },
    # todo.py hardcoded prompt_descriptions
    "Mobile - Compile and run software": {
        "fr": "Mobile - Compiler et exécuter le logiciel",
        "en": "Mobile - Compile and run software",
    },
    "Upgrade Odoo - Migration Database": {
        "fr": "Mise à jour Odoo - Migration de base de données",
        "en": "Upgrade Odoo - Migration Database",
    },
    "Upgrade Poetry - Dependency of Odoo": {
        "fr": "Mise à jour Poetry - Dépendances d'Odoo",
        "en": "Upgrade Poetry - Dependency of Odoo",
    },
    "Open SHELL": {
        "fr": "Ouvrir le SHELL",
        "en": "Open SHELL",
    },
    "Upgrade Module": {
        "fr": "Mise à jour de module",
        "en": "Upgrade Module",
    },
    "Debug": {
        "fr": "Débogage",
        "en": "Debug",
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
        "fr": "Test - Tester un module Odoo",
        "en": "Test - Test an Odoo module",
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
        "fr": "Conserver la base de données temporaire? (o/N) : ",
        "en": "Keep the temporary database? (y/N): ",
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
        "fr": "Git - Outils Git",
        "en": "Git - Git tools",
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
        "fr": "GPT code - Outils d'assistant IA",
        "en": "GPT code - AI assistant tools",
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
    "Total:": {
        "fr": "Total :",
        "en": "Total:",
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
