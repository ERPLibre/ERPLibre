
# Set-OPS — le moteur déclaré et l'état de l'intégration

Quatre modules, un partage : **le relevé touche le système, la décision ne le
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

## `ansible_env` — ce que le moteur exige, et comment le poser

Le moteur ne pose pas de contrôleur : son rôle `serveur_ops` équipe une CIBLE,
et non le poste qui la pilote. Ce module pose le venv du contrôleur,
`.venv.todo.setops`, en LISANT dans le moteur tout ce qui s'y lit — la plage
d'ansible-core, les bibliothèques Python épinglées, les collections
épinglées. Aucune de ces valeurs n'est recopiée ici.

**Le mineur de Python est une contrainte, pas un goût.** `serveur_ops` exige
que contrôleur et cible partagent leur `major.minor`, et il fabrique le cache
de roues hors ligne avec le `python3` du PATH — pas avec l'interpréteur
d'Ansible. Un contrôleur en 3.14 produit donc des roues `cp314` qu'une cible
en 3.13 refuse. D'où deux exigences que ce module tient ensemble : le venv est
posé dans `MINEUR_CIBLE`, et `environnement(racine, moteur, base)` met son `bin` en TÊTE du PATH.

Les collections vont sous le moteur, dans un dossier que son propre
`.gitignore` couvre : son arbre reste propre, et elles ne se mêlent pas à ce
que le poste porte déjà. L'`ansible.cfg` du moteur ne déclare aucun
`collections_path`, donc l'environnement le nomme.

Deux lectures sont distinguées exprès : un tuple vide dit « le moteur
n'épingle rien », `None` dit « on ne sait pas ». Les confondre ferait porter
la ligne d'état sur un fichier illisible, en annonçant zéro écart — le pire
des verdicts, puisqu'il rassure.

Ce que le moteur déclare, lu comme du texte :

- `plage_ansible(moteur)` : l'exigence `serveur_ops_ansible`, telle que le
  moteur l'écrit — elle part à pip sans être reformulée, pour qu'un désaccord
  se voie plutôt que de se corriger en silence ;
- `bibliotheques_epinglees(moteur)` et `collections_epinglees(moteur)` : les
  (nom, version) que le moteur épingle, `None` quand le fichier ne se lit pas ;
- `specifieur(texte)`, `version(texte)` et
  `dans_la_plage(version_texte, plage_texte)` : les lectures que l'écran
  d'état et la vérification partagent, pour que les deux disent la même
  chose de la même version.

Ce que le poste offre, et ce que la pose coûte :

- `interprete(mineur)` : un Python utilisable et d'où il vient — le PATH
  d'abord, un gestionnaire de versions ensuite, rien du tout en dernier ;
- `geste_mise(mineur)` : la commande qui le poserait, NOMMÉE pour être
  montrée ; le menu ne pose aucun gestionnaire de versions dans votre dos ;
- `chemin_venv(racine)` : le venv, en chemin ABSOLU — les sondes tournent
  avec `cwd` dedans, et un argv relatif s'y résoudrait sous lui-même ;
- `etapes(racine, moteur, python, plage, refaire)` : les gestes, dans
  l'ordre. `refaire` ouvre par la suppression, seule façon de changer
  l'INTERPRÉTEUR d'un venv déjà là ;
- `montre(etape)` : la ligne à imprimer, DÉRIVÉE de l'argv — ce qui est
  montré est ce qui est lancé ;
- `environnement(racine, moteur, base)` : le venv en tête du PATH, et les
  collections nommées ;
- `version_posee(racine, paquet)`, `version_collection(moteur, nom)` et
  `mineur_du_path(racine, moteur)` : ce qui est réellement là. La dernière
  interroge un `python3` NU, ce que fait la garde du moteur ;
- `poser(etape, racine, env)` : joue une étape et rend son code ; la sortie
  n'est pas capturée, une pose durant des minutes. Le lancement lui-même
  passe par `runner`, en dessous — une seule façon de lancer un geste.

## `runner` — une seule façon de lancer un geste

Trois règles, et chacune répare une façon précise de se tromper.

**L'environnement est construit à neuf**, jamais hérité. Hérité, il porte
trois choses qui décident à la place de l'opérateur : un `CONFIRMER=true`
resté d'un geste précédent, que les applicateurs du moteur lisent comme un
ordre d'écrire au lieu de simuler ; les surcharges du make parent
(`MAKEFLAGS`, `MAKELEVEL`), puisque TODO se lance lui-même par `make todo` ;
et les `ANSIBLE_*` ou `SETOPS_*` que le moteur laisse gagner sur ses propres
défauts — dont celui qui désigne la grappe qu'un geste destructeur viserait.

**La commande porte son `CONFIRMER`**, en clair, sur la ligne qu'on affiche.
Une variable passée à `make` sur la ligne de commande arrive dans
l'environnement du script appelé ET l'emporte sur celle qui serait héritée :
la ligne montrée est la ligne qui décide.

**Le verdict se lit**, code ET sortie. Plusieurs gestes du moteur rendent 0
en ayant trouvé un écart : le code seul ne suffit pas.

Cette couche ignore Ansible : l'environnement d'un geste du moteur se compose
chez l'appelant, `environnement(racine, moteur, base)` par-dessus `base(source)`.
Il n'y a ainsi qu'un lanceur dans le paquet, et la dépendance ne va que dans
un sens.

- `base(source)` : la liste blanche seule, PATH débarrassé du venv
  d'ERPLibre ;
- `sans_venv_erplibre(path)` : ce retrait, jugé sur des SEGMENTS de chemin
  entiers — juger par sous-chaîne couperait un dossier voisin ;
- `cible(moteur, nom, variables, confirmer)` : l'argv d'une cible `make`,
  `CONFIRMER` toujours écrit, en dernier ;
- `cite(argv)` : la ligne à montrer, dérivée de l'argv ;
- `jouer(argv, env, cwd, capture, delai, fusionner)` : joue et rend un
  `Verdict` dont
  le `code` vaut `None` quand le processus n'a pas pu tourner — c'est un
  verdict, pas l'absence de verdict.
