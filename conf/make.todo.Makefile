########
# TODO #
########

# Par todo.sh, et non todo.py directement : la chaîne passe par install.sh,
# qui choisit un interpréteur capable de LIRE le code avant de le lancer et
# pose le venv s'il manque. Le nom dit ce qui se passe : make affiche la
# recette, et « ./install.sh » y donnait à lire une installation là où l'on
# ouvre un menu.
.PHONY: todo
todo:
	./todo.sh

# Le TODO du terminal, qui écrit aussi chacune de ses questions, réponses et
# commandes dans ~/.erplibre/todo_web/<empreinte>/record-*.jsonl (0600), un
# secret masqué : ce que la page web lira d'une session.
.PHONY: todo_record
todo_record:
	./.venv.erplibre/bin/python -m script.todo.ui.record

# Interface web de TODO : un hub local par checkout, sur 127.0.0.1. « open »
# le démarre ou le réutilise et ouvre le navigateur par un lien à usage
# unique, aussi affiché ici pour un navigateur qui ne l'aurait pas ouvert.
.PHONY: todo_web
todo_web:
	./.venv.erplibre/bin/python -m script.todo.web.launcher open

.PHONY: todo_web_stop
todo_web_stop:
	./.venv.erplibre/bin/python -m script.todo.web.launcher stop

# La même page dans une fenêtre native (pywebview), sur le même hub. Sans
# pywebview ou sans moteur web, dit quoi installer et ouvre le navigateur ;
# sans affichage, dit seulement « no display on this host » et ouvre le
# navigateur. Fermer la fenêtre laisse le hub et ses sessions.
.PHONY: todo_desktop
todo_desktop:
	./.venv.erplibre/bin/python -m script.todo.web.desktop open

# Entrée « ERPLibre TODO » de ce checkout dans le menu des applications du
# bureau, un fichier 0600 sous $XDG_DATA_HOME/applications, sinon sous
# ~/.local/share/applications : elle lance le python de .venv.erplibre,
# « -m script.todo.web.desktop open », depuis la racine du checkout.
.PHONY: todo_desktop_install
todo_desktop_install:
	./.venv.erplibre/bin/python -m script.todo.web.desktop install

# Journal des tâches des sessions web : retire les jours de plus de 30 jours,
# sauf une tâche en cours. « launcher purge --all » les retire tous.
.PHONY: todo_web_purge
todo_web_purge:
	./.venv.erplibre/bin/python -m script.todo.web.launcher purge
