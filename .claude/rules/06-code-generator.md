# Code Generator

ERPLibre inclut un système de génération de modules Odoo :
- `script/code_generator/new_project.py` — Créer un nouveau module
- `script/code_generator/create_from_existing_module.py` — Cloner un module existant
- `addons/TechnoLibre_odoo-code-generator/` — Moteur de génération
- `addons/TechnoLibre_odoo-code-generator-template/` — Templates

Documentation : `doc/CODE_GENERATOR.md`

## Les commentaires du code produit

Le code généré porte des commentaires comme le reste, et la même règle : ils
disent COMMENT ça marche, ils ne portent rien d'identifiant et ils ne
racontent pas l'enquête. Voir `.claude/rules/04-code-conventions.md`.

Un module généré à partir d'une base existante hérite de ce qu'elle contient :
relire ses commentaires et ses docstrings avant de committer, un nom de client
ou de base y arrive tout seul.

## Le nettoyage au fur et à mesure

Rien ne se nettoie en une passe : on corrige les commentaires du fichier qu'on
touche, au moment où on le touche. Deux outils le rappellent.

Le hook `pre-commit` liste ce qui est à relire dans les fichiers indexés,
SANS bloquer le commit :

```bash
git config core.hooksPath script/git/hooks   # une fois par clone
```

L'outil se lance aussi à la main, sur un fichier, un répertoire ou l'index :

```bash
python3 script/analyse/check_comment_hygiene.py script/todo/todo.py
python3 script/analyse/check_comment_hygiene.py --staged
python3 script/analyse/check_comment_hygiene.py script --identifying-only
```

🔴 `identifiant` — adresse, courriel, chemin de compte : à retirer.
🟡 `récit` — témoignage, date, première personne : à RELIRE, l'outil ne
tranche pas. Un fait durable reste ; l'incident
où on l'a observé part. Codes de sortie : 0 rien, 1 des trouvailles, 2 l'outil
a échoué.
