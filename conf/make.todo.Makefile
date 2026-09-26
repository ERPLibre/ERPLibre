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

# Interface web de TODO : un hub local par checkout, sur 127.0.0.1. « open »
# le démarre ou le réutilise et ouvre le navigateur par un lien à usage
# unique, aussi affiché ici pour un navigateur qui ne l'aurait pas ouvert.
.PHONY: todo_web
todo_web:
	./.venv.erplibre/bin/python -m script.todo.web.launcher open

.PHONY: todo_web_stop
todo_web_stop:
	./.venv.erplibre/bin/python -m script.todo.web.launcher stop
