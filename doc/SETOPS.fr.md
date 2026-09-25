
# Set-OPS : piloter le moteur depuis TODO

`TODO › Execute › Deploy › Set-OPS` pilote Set-OPS, un moteur qui construit
un écosystème souverain à partir d'un plan déclaratif, avec Ansible et
Proxmox. **TODO lance le moteur ; il ne le recopie pas.** Le moteur reste la
seule source de vérité de ses gestes, et toute commande que TODO nomme se
rejoue à la main, sans TODO.

Le menu n'affiche que ce qui existe : aujourd'hui, l'état de l'intégration
et la pose de l'environnement Ansible. Les gestes du moteur s'y ajoutent à
mesure qu'ils sont écrits.

## Obtenir le moteur

Le moteur est **sur demande**. `manifest/git_manifest_setops.xml` le déclare
— son chemin sous `private/repo/` et sa révision, un SHA de commit complet —
et aucun manifeste fusionné par défaut ne le nomme : une installation
ERPLibre ordinaire ne contacte jamais la forge du moteur. Le moteur se
rapatrie par :


```bash
./script/manifest/update_manifest_local_setops.sh
```

Le script rapatrie le moteur seul, à la révision épinglée, par Google Repo.
Ses trois gardes passent avant tout effet de bord — démon git, fusion des
manifestes, `.repo/` — et ne font que lire : un refus ne laisse rien
derrière lui. Toutes parlent dans la même exécution : un seul lancement
nomme chaque refus.

- `.venv.erplibre/bin/repo` absent ou non exécutable : il nomme
  `./script/install/install_git_repo.sh` ;
- un dossier que Google Repo n'a pas posé occupe le chemin du moteur : il
  nomme la commande qui le met de côté. Ce dossier est un clone manuel —
  un vrai dossier `.git` — ou un dossier sans `.git`, même à un chemin que
  `.repo/project.list` porte : Google Repo écrit cette liste même quand le
  rapatriement échoue ;
- le HEAD d'ERPLibre est détaché et aucune branche locale ne le contient :
  sur un espace de travail neuf, `repo init` exige un nom de branche,
  jamais un SHA nu.

La garde du chemin tourne dans `.venv.erplibre/bin/python` : absent ou non
exécutable, le script refuse (code `1`) en disant que l'emplacement du
moteur n'a pas pu être vérifié ; c'est le lancement suivant, ERPLibre
installé, qui nomme ce qui l'occupe.

Son code de sortie est `3` quand un dossier que Google Repo n'a pas posé
occupe le chemin du moteur, `2` sans déclaration lisible du moteur, et `1`
pour les autres refus. Les gardes passées, c'est celui de la fusion des
manifestes, de `repo init` ou de `repo sync`, le premier qui échoue.

Les gardes ne suppriment ni ne déplacent jamais rien. Google Repo, lui,
aligne `.repo/project.list` sur le manifeste fusionné à chaque sync, celui-ci
compris : un projet que ce manifeste ne nomme plus perd son arbre si
l'arbre est propre — ses objets restent sous `.repo/projects/` — et fait
échouer le sync, en le nommant, s'il porte des modifications. Le script
fusionne les mêmes manifestes que
`./script/manifest/update_manifest_local_dev.sh`, plus le moteur.

Faire avancer l'épingle est un geste délibéré : un nouveau SHA dans le
manifeste, relu et commité.

### Quand un sync tourne sans le moteur

Une fois rapatrié, le moteur fait partie de l'espace de travail : les
fusions de manifestes suivantes le reprennent d'elles-mêmes, puisque
`.repo/project.list` porte son chemin, et `repo forall` — donc
`make repo_do_stash` — le parcourt comme les autres projets. La seule liste
de groupes que le dépôt passe à `repo init`,
`make repo_configure_group_code_generator` (`-g base,code_generator,setops`),
le nomme.

Un sync qui tourne SANS lui supprime son arbre : après un `repo init -g`
dont la liste n'a pas `setops`, sur une branche d'ERPLibre qui n'a pas
`manifest/git_manifest_setops.xml`, ou après une fusion lancée avec
`--with_new_manifest` et sans `--with_setops`. Google Repo supprime
chaque fichier de l'arbre, ceux que cache le `.gitignore` du moteur
compris ; seules les cibles des liens `instance` et `underlay.yml`
survivent, parce qu'elles vivent hors de lui.
Les fusions suivantes laissent alors le moteur de côté : le poste n'est
plus opté, et `./script/manifest/update_manifest_local_setops.sh` l'opte
de nouveau.

Un arbre qui porte des modifications, fichiers non suivis compris, fait
plutôt échouer ce sync (`uncommitted changes are present`), et l'arbre
reste. Le sync passe une fois les modifications commitées, ou remisées par
`git stash --include-untracked`, dans le moteur lui-même :
`make repo_do_stash` ne l'atteint pas alors, puisque `repo forall` ne
parcourt que les projets que nomment le manifeste et ses groupes.

Rien d'irremplaçable n'a donc sa place dans `private/repo/Set-OPS-Public` :
les écosystèmes et les sites vivent dans ses dossiers frères, et les clés
de voûte sous `~/.config`.

### Migrer un clone manuel

Un clone fait à la main se met de côté, puis le moteur se rapatrie par le
manifeste :


```bash
mv private/repo/Set-OPS-Public private/repo/Set-OPS-Public.manuel
./script/manifest/update_manifest_local_setops.sh
```

Le clone mis de côté garde ce qui vit DANS le dossier du moteur : le lien
`instance` et `underlay.yml`. L'écran d'état nomme alors les gestes qui
montent de nouveau un écosystème et un site.

## Où vivent les données

Le moteur trouve ses écosystèmes et ses sites parmi ses dossiers **frères**.
C'est pourquoi il se pose sous `private/repo/`, que le `.gitignore`
d'ERPLibre ignore : un écosystème posé à côté du moteur porte les données
d'un client et n'entre jamais dans un commit d'ERPLibre.

- l'**écosystème actif** est le lien `instance` du moteur, vers un dossier
  frère ; TODO le lit et ne tient aucun registre à lui ;
- le **site monté** est le lien `underlay.yml` du moteur, vers le
  `underlay.yml` d'un dossier frère ;
- les **clés de voûte** restent hors de tout dépôt, sous le dossier de
  configuration de l'utilisateur (`~/.config`, ou `$XDG_CONFIG_HOME`).

## L'écran d'état

`Set-OPS - État de l'intégration, ligne par ligne` est en LECTURE SEULE : ni
`make`, ni réseau, ni écriture. `git` lit sans ses verrous facultatifs, si
bien qu'il ne réécrit pas l'index du moteur. Au-delà de `git`, l'écran lance
quelques sous-processus bornés, dans un environnement construit à neuf :

- la version d'ansible-core, et celle de chaque bibliothèque que le moteur
  épingle, demandées au Python du venv dédié, quand le venv a son
  `ansible-playbook` ;
- le `major.minor` que rend `python3` sur le PATH du geste. Il est demandé
  à un `python3` NU, parce que c'est exactement ce que fait la garde du
  moteur : un venv appelé par chemin absolu répondrait là où le geste,
  lui, échouerait ;
- `scripts/voutes.py etat`, seulement avec un écosystème monté ET son
  `plan/serveurs.yml`, le préalable de la ligne de la clé de voûte. Il est
  lancé avec `-B` : rien ne s'écrit dans le moteur, pas même le bytecode de
  ses modules. Seul son code de retour est lu — sa sortie nomme
  l'écosystème et n'est pas même capturée.

Dix lignes, dans l'ordre où l'on règle le poste : plateforme, manifeste du
moteur, emplacement privé, Google Repo, moteur, environnement Ansible,
écosystème monté, site monté, clé de voûte de l'écosystème, outils du poste.
Chaque ligne dit son état, le geste qui la règle, et la source qu'elle lit
(`↳`), ses chemins relatifs à la racine d'ERPLibre. Quand une ligne trouve
plusieurs choses à régler, elle les nomme toutes sur une ligne, pour que
régler la première ne fasse pas découvrir la suivante au lancement d'après.

Trois états, parce que « le dépôt sait le faire » et « ce poste l'a réglé »
sont deux questions distinctes :

| marque | au compte | sens |
|---|---|---|
| ✓ | portés | réglé ici, comme sa source le montre |
| ◐ | à régler ici | le dépôt sait le faire ; la ligne nomme le geste |
| ○ | absent du dépôt | ce que le dépôt ne porte pas : par exemple aucune déclaration, une révision non épinglée, un emplacement que git n'ignore pas, ou le venv Ansible `.venv.todo.setops` qu'il ne sait pas encore poser |

Une ligne dont le préalable n'est pas tenu dit seulement
`d'abord : <segment>` : la ligne du moteur attend la ligne du manifeste
portée ; Ansible, l'écosystème et le site attendent le dossier du moteur
présent ; la clé de voûte attend la ligne de l'écosystème portée. Un
verdict inconnu n'est jamais ✓ : une sonde qui échoue fait passer sa ligne
à ◐ ou ○ avec « verdict illisible » ou « impossible de savoir », jamais à
une trace Python.

Ligne par ligne :

- **Plateforme** : portée sous Linux ; ○ ailleurs, le moteur supposant bash
  et l'outillage GNU.
- **Manifeste du moteur** : porté quand
  `manifest/git_manifest_setops.xml` déclare exactement un projet du groupe
  `setops`, à un SHA de commit complet ; ○ sans déclaration lisible, ou sur
  une révision non épinglée.
- **Emplacement privé** : porté quand git ignore ce qui se pose à côté du
  moteur. Sa source est la question même que la ligne pose à git, à
  rejouer depuis la racine d'ERPLibre :
  `git check-ignore -v --no-index -- private/repo/.sonde-setops-ignore`
  — code de retour `0`, ignoré ; `1`, non ignoré (○) ; tout autre,
  « impossible de savoir » (○). La question porte sur un nom inventé sous
  `private/repo/` : posée sur le dossier lui-même, sans `--no-index`, git
  répond « non ignoré », puisque le dossier porte le fichier suivi
  `private/repo/.gitkeep`.
- **Google Repo** : porté quand `.venv.erplibre/bin/repo` est exécutable,
  la règle qu'applique le script de rapatriement, et que
  `.repo/manifest.xml` existe — `repo init` l'écrit, alors que la seule
  fusion des manifestes crée le dossier `.repo/`. Sinon ◐ : sans `repo`, la
  ligne nomme `./script/install/install_git_repo.sh` ; sans
  `.repo/manifest.xml`, le script de rapatriement, qui initialise `.repo/`
  — et d'abord, quand ce que Google Repo n'a pas posé occupe le chemin du
  moteur, le `mv` qui le met de côté.
- **Moteur** : porté seulement quand Google Repo le gère, à l'épingle,
  arbre propre. Géré suit la règle du script de rapatriement :
  `.repo/project.list` porte le chemin ET Google Repo y a posé l'arbre, son
  `.git` menant sous `.repo/`. ◐ quand rien n'occupe le chemin, en nommant
  le script de rapatriement ; ◐ pour un clone manuel — tout autre occupant
  du chemin, même listé : un autre dossier, un fichier, un lien brisé — en
  nommant son `mv`, ou quand il est impossible de savoir si
  Google Repo gère le chemin ; ◐ en avance ou en retard sur l'épingle,
  sur un HEAD qui ne descend pas de l'épingle, sur une épingle que le clone
  ne porte pas (« resynchroniser »), quand il est « impossible de savoir
  où HEAD se tient face à l'épingle », et sur des fichiers modifiés. Une
  épingle que le clone ne porte pas est un constat : git lit le clone et
  l'objet épinglé n'y est pas, ce que la resynchronisation règle.
  « Impossible de savoir » est l'absence de constat — git cesse de
  répondre, ou l'épingle désigne un objet qui n'est pas un commit — et la
  ligne ne nomme donc aucun geste : rien n'établit qu'il manque quelque
  chose. Quand git ne sait pas lire le clone, la ligne le dit, et ne dit
  rien ni de l'épingle ni des fichiers modifiés.
- **Environnement Ansible** : ○ tant que `.venv.todo.setops` n'a pas
  d'`ansible-playbook` — le dépôt ne sait pas encore le poser — et quand la
  plage du moteur (`serveur_ops_ansible`) n'est pas une exigence
  d'ansible-core bornée : un autre paquet, une URL, des extras, un
  marqueur, ou aucune borne. Porté quand la version que le venv importe est
  dans la plage ; ◐ hors de la plage ou illisible. Une pré-version n'est
  dans la plage que si la plage en nomme elle-même une, quelle que soit la
  version de `packaging` installée.
- **Écosystème monté** : porté quand `instance` est un lien vers un dossier
  qui porte son `plan/serveurs.yml`. ◐ sinon : sans lien, la ligne nomme
  `make -C private/repo/Set-OPS-Public instance-utiliser NOM=…` ; un vrai
  dossier `instance` est un dossier que le moteur refuse de basculer.
- **Site monté** : porté quand `underlay.yml` mène à un fichier, et la
  ligne nomme le dossier qui le porte. Sinon ◐, un lien qui ne mène à
  aucun fichier — brisé, ou vers un dossier — étant nommé comme tel, avec
  le même geste, tapé depuis la racine d'ERPLibre :
  `ln -sfn ../<site>/underlay.yml private/repo/Set-OPS-Public/underlay.yml`
  — `<site>` est le dossier frère, sous `private/repo/`, qui porte le
  `underlay.yml` du site, et la cible est relative au dossier du lien. La
  source renvoie au `docs/implanter-un-tenant-sur-un-site.md` du moteur.
- **Clé de voûte de l'écosystème** : code de retour `0` de
  `scripts/voutes.py etat`, portée. ◐ sur `1`, la clé manque : la ligne
  nomme la commande qui montre pourquoi, puisqu'un script qui lève sort
  aussi en `1`. ◐ « verdict illisible » sur tout autre code, ou aucun.
- **Outils du poste** : portés dès que `make`, `git` et `ssh` se trouvent,
  ◐ sans l'un d'eux. Un outil facultatif absent est listé en note, avec les
  cibles du moteur qu'il bloque.

## L'environnement Ansible

`Set-OPS - Environnement Ansible (le poser)` construit le venv qui pilote le
moteur, `.venv.todo.setops` sous la racine d'ERPLibre. **Il montre chaque
commande avant de demander**, et chacune se rejoue à la main.

Tout ce qu'il pose est LU dans le moteur : la plage d'ansible-core
(`serveur_ops_ansible`), les bibliothèques Python épinglées
(`requirements-python.txt`) et les collections épinglées
(`requirements.yml`). Aucune version n'est écrite ici. Les collections vont
sous le moteur, dans `.ansible/collections`, un dossier que son propre
`.gitignore` couvre : l'arbre du moteur reste propre, et elles ne se mêlent
pas à ce que le poste porte déjà.

**Pourquoi un mineur de Python dédié.** Le rôle `serveur_ops` du moteur exige
que contrôleur et cible partagent leur `major.minor`, et il fabrique le cache
de roues hors ligne avec le `python3` du PATH — pas avec l'interpréteur
d'Ansible. Un contrôleur en 3.14 produit donc des roues `cp314` qu'une cible
en 3.13 refuse d'installer, et la garde arrête le geste avant d'en arriver
là. Le venv est posé dans un Python 3.13 : celui du poste s'il y en a un,
sinon celui que fournit `mise install python@3.13`. Quand il n'y en a nulle
part, l'écran nomme la commande et ne pose rien dans votre dos.

**Poser le venv ne suffit pas, il faut l'ACTIVER.** La garde et le
téléchargement des roues lancent tous deux un `python3` NU. Le même venv en
3.13, appelé par chemin absolu sur un poste dont le `python3` de shell est en
3.14, est refusé ; avec son `bin` en tête du PATH, il passe. Chaque geste
tourne donc avec ce PATH, et la vérification mesure ce que rend `python3` à
travers lui plutôt que de croire le venv qu'elle vient de poser.

Un venv hors plage est proposé à la reprise, après que l'écran a nommé ce
qu'il a trouvé et montré ce qu'il effacerait. Réinstaller par-dessus
laisserait le mauvais INTERPRÉTEUR, et c'est ce cas-là qui casse.

## Les écosystèmes

Un écosystème est un dépôt frère du moteur, et le moteur travaille sur UN
seul à la fois : le lien `instance` le désigne, et tous les gestes portent
sur lui. Trois écrans pilotent les cibles du moteur.

`Set-OPS - Écosystèmes découverts à côté du moteur` liste ce que le moteur
trouve, le monté marqué. Le moteur refuse quand deux écosystèmes FÉDÉRÉS
réclament le même index — mêmes VLAN, mêmes VMID sur le trunk. La liste est
montrée quand même, avec les mots du moteur : la cacher priverait de ce qui
explique le refus.

`Set-OPS - Basculer l'écosystème actif` demande un NUMÉRO dans la liste,
jamais le nom. Un nom retapé est un nom retapé de travers, et le moteur
refuse alors sur un dossier absent sans dire si c'est la frappe ou
l'écosystème qui manque.

`Set-OPS - Créer un écosystème depuis un modèle` demande un nom, un modèle
choisi parmi ceux que le moteur propose, et un index. L'index libre est
PROPOSÉ, lu dans les index fédérés déjà pris ; le moteur valide ce qu'il
reçoit et refuse une collision. La suite — identité, voûte, première
application — est imprimée par le moteur lui-même.

Chaque écran s'ouvre sur l'écosystème monté, lu sur le lien sans rien lancer,
et montre chaque commande avant de la jouer. Ce qui lit part avec
`CONFIRMER=false`, ce qui écrit avec `CONFIRMER=true`, sur la ligne même.
