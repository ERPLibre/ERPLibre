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
