#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La télémétrie des agents : d'où vient chaque chiffre, et ce qu'il vaut.

Trois sources cohabitent dans ce paquet, et elles ne se valent pas. L'écran
doit dire laquelle il montre, parce qu'un tableau qui mélange une mesure et
une approximation fait accuser le mauvais composant quand un chiffre surprend.

**Ce que le disque sait exactement.** Chaque message d'assistant d'une
transcription porte son propre `usage` — jetons d'entrée, de sortie, de
réflexion, lus en cache, créés en cache. Les additionner est EXACT et couvre
toute la transcription. Les jetons de ce paquet viennent de là.

**Ce que Claude Code rapporte lui-même.** Une ligne `cost-state` porte le
coût en dollars, la durée d'horloge, celle d'API, celle des outils et les
lignes de code. Le coût ne se calcule pas sans le prix par modèle, que ce
dépôt n'a pas à inventer, donc il est LU. Mais ces lignes ne sont pas
monotones : une compaction remet le compteur à zéro, et une transcription en
porte plusieurs segments. La dernière est ce que Claude Code considère comme
l'état courant, et c'est ce qui est montré — jamais une somme de segments,
dont rien ne dit que les champs s'additionnent.

**Ce que personne ne sait.** La répartition du contexte entre système,
outils, fichiers et messages n'est nulle part sur le disque. Ce qui la
remplace est exact : la TAILLE de l'invite à chaque tour — entrée plus cache
lu plus cache créé — donc sa croissance, son taux de réutilisation du cache,
et le décrochement qu'une compaction y laisse.

**Le coût de lecture commande la forme du paquet.** Une transcription pèse
des dizaines de mégaoctets et la dernière `cost-state` peut être à quatre
mégaoctets de la fin, donc aucune lecture de queue ne suffit. Une TUI qui se
rafraîchit toutes les deux secondes ne peut pas relire tout : l'agrégat est
donc INCRÉMENTAL, il retient l'offset où il s'est arrêté, et un rafraîchisse-
ment ne replie que les octets ajoutés depuis.
"""
