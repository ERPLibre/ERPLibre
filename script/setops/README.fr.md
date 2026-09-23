
# Set-OPS — le moteur déclaré et l'état de l'intégration

Deux modules, un partage : **le relevé touche le système, la décision ne le
touche pas.** Aucun n'importe le code du moteur : il se lit par fichiers et
sous-processus. Rien ici ne pose de question ; le menu vit dans
`script/todo/setops_menu.py`, et le mode d'emploi dans
[../../doc/SETOPS.fr.md](../../doc/SETOPS.fr.md).

## `engine` — le manifeste est la seule autorité

`manifest/git_manifest_setops.xml` porte le chemin du moteur et sa révision
épinglée. La fusion des manifestes, le script de rapatriement et l'écran
d'état les LISENT ici au lieu d'en garder une copie, qui divergerait au
premier déplacement.

Ces fonctions ne travaillent que sur du texte :

- `parse_manifest(texte)` : la `Declaration` du moteur — chemin, révision,
  upstream, remote — ou `None`. Le moteur est LE projet du groupe
  `setops` : aucun, ou deux, et rien n'est déclaré. Son chemin reste sous
  la racine de l'espace de travail, ni absolu ni remontant par `..`, et
  revient normalisé ;
- `groups_of(texte)` : les groupes d'un attribut `groups`, découpés comme
  Google Repo les découpe, sur les virgules ET les blancs ;
- `mise_de_cote(chemin)` : le `mv` qui met de côté le dossier posé en
  `chemin` sous `<chemin>.manuel`, cité pour être recopié tel quel ;
- `is_pinned(revision)` : vrai pour un SHA complet de 40 hex seulement —
  une branche, un tag ou un SHA abrégé désignent demain autre chose ;
- `ignore_probe(chemin)` : le chemin sur lequel `parent_is_ignored`
  interroge git — un nom inventé directement sous le parent, parce qu'une
  règle `dossier/` ne vaut que pour un dossier et que git ne sait pas qu'un
  chemin absent du disque en est un : la sonde répond aussi sur un clone
  neuf.

Les autres lisent le disque ou lancent `git`, et ne lèvent jamais : un
verdict inconnu vaut `None` — ou la relation `inconnue` —, et l'appelant
décide quoi en dire. Git ne remonte jamais au-dessus du dossier qu'on lui
donne (`GIT_CEILING_DIRECTORIES`) : un dossier sans `.git` sous le checkout
d'ERPLibre répondrait sinon avec le HEAD d'ERPLibre lui-même.

- `declaration(racine)` : `parse_manifest` appliqué au manifeste sous
  `racine` ;
- `managed_by_repo(racine, chemin)` : `.repo/project.list` porte-t-il
  `chemin` ? `None` sans `.repo/` ou devant une liste illisible, `False`
  tant qu'il n'y a pas de liste. La liste dit ce que le dernier sync
  VISAIT : Google Repo l'écrit même quand le rapatriement échoue ;
- `repo_worktree(racine, chemin)` : Google Repo y a-t-il POSÉ l'arbre ?
  Vrai quand son `.git` — un lien, ou un fichier `gitdir:` — mène sous
  `.repo/` ; faux pour un vrai dossier `.git`, celui d'un clone manuel, ou
  sans `.git` du tout ; `None` quand le fichier `gitdir:` ne se lit pas ;
- `relation_to_pin(moteur, sha)` : où se tient le HEAD du clone face à
  l'épingle, et à combien de commits ;
- `dirty_count(moteur)` : les entrées de `git status --porcelain`, fichiers
  non suivis compris ;
- `parent_is_ignored(racine, chemin)` : les dossiers frères du moteur
  sont-ils ignorés par les règles du dépôt `racine`, question posée par
  `git check-ignore --no-index` sur `ignore_probe(chemin)` ?

Où se tient le HEAD du clone face à l'épingle, lu dans les seuls objets
locaux et sans réseau, est un vocabulaire clos : `egal`, `avance`, `retard`, `diverge`, `absente`, `inconnue`.
Seule `absente` est un constat sur l'épingle — git lit le clone et le
commit épinglé n'y est pas, ce qu'une resynchronisation règle ; le
dernier terme, `inconnue`, n'établit rien.

Le point d'entrée, `main`, sert le script de rapatriement, lancé depuis la
racine d'ERPLibre. `chemin` écrit le chemin déclaré ;
`verifier-emplacement` rend `0` quand le chemin est libre, ou quand Google
Repo le liste ET y a posé l'arbre, et `3` sinon — un clone manuel, même à
un chemin listé, ou un dossier sans `.git` —, en écrivant la commande qui
le met de côté. Les deux rendent `2` sans déclaration lisible. Rien n'est
jamais supprimé ni déplacé ici.

## `state` — dix lignes, décidées sur un relevé

`releve(racine)` touche le système une fois — fichiers, `git`, et au plus
deux sous-processus bornés dans un environnement construit à neuf — et ne
lève jamais. La version d'ansible-core n'est demandée au Python du venv
dédié que si le venv a son `ansible-playbook`. `scripts/voutes.py etat` ne
se lance qu'avec un écosystème monté ET son `plan/serveurs.yml`, le
préalable de la seule ligne qui lit son code, et avec `-B` : le relevé
n'écrit rien dans le moteur, pas même le bytecode de ses modules.

`lignes(vu)` est PURE : chaque verdict s'éprouve sans machine, y compris
ceux qu'on ne sait pas provoquer sur le poste. Les préalables se déclarent
une fois, dans `PREALABLES` ; une ligne dont le préalable n'est pas tenu le
nomme sans autre verdict, et un verdict inconnu n'est jamais porté. Chaque
ligne nomme sa source, ses chemins relatifs à la racine d'ERPLibre.

Les lignes s'impriment par `script/todo/state_screen.py`, le rendu commun
avec l'écran d'état Devstack : deux rendus diraient tôt ou tard deux choses
différentes avec les mêmes marques.