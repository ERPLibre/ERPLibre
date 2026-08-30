# Conventions de code

Le formatage et le lint sont entièrement décrits par les fichiers de
configuration du dépôt — les lire plutôt que de supposer : `.flake8`,
`.editorconfig`, et les sections `[tool.black]` / `[tool.isort]` de
`pyproject.toml`. `make format` applique l'ensemble.

Prettier (via npm) formate XML/JSON/YAML ; `.editorconfig` donne les
indentations par type de fichier.

## Commentaires

Un commentaire dit COMMENT le code fonctionne : ce que la fonction prend, ce
qu'elle rend, l'invariant qu'elle tient, ses effets de bord, la contrainte
technique qu'on ne devine pas en lisant la ligne d'à côté. Il doit se lire
dans dix ans sans rien savoir de la semaine où il a été écrit. La règle vaut
pour les docstrings autant que pour les lignes `#`.

**L'épreuve : le sujet et le temps.** Chaque phrase a le CODE pour sujet, au
présent de ce qu'il fait. Une phrase dont le sujet est un incident, une
machine, une date ou une personne est à couper, où qu'elle se trouve dans le
paragraphe. Le MODE DE DÉFAILLANCE que le code empêche est du fonctionnement
et reste — « une VM renommée se voit attribuer la passerelle ». L'INCIDENT où
on l'a observé est du récit et part — « vécu sur telle VM, annoncée à telle
adresse ».

**Les chiffres.** Une mesure qui établit un fait durable reste, dépouillée de
sa date, de son lieu et de son opérateur : une limite, un seuil, une valeur
que documente l'éditeur. Un relevé de ce qui répondait ce jour-là part.

**Rien d'identifiant, jamais** : nom d'un client ou d'une organisation tierce,
nom de base de données réelle, nom de VM ou d'hôte, adresse IP, courriel,
chemin portant un nom d'utilisateur, libellé ou chiffre tiré des données d'un
client. La seule exception est l'en-tête de copyright : le dépôt nomme son
propriétaire, pas ses clients. Généraliser plutôt que censurer — « sur une
base de production », « sur un hôte qui exige une authentification sudo
interactive » — dit la CLASSE de situation, qui est ce qui sert au lecteur.

Le récit n'est pas perdu, il change de place : l'enquête, les mesures datées
et les impasses vivent dans `tasks/`, qui n'est pas versionné. Ni le fichier
ni le corps du commit ne les portent.

Cela vaut aussi pour l'existant, mais **au fur et à mesure** : on corrige les
commentaires du fichier qu'on touche, au moment où on le touche, et non en une
passe qui réécrirait le dépôt. Le hook `pre-commit` liste ce qui est à relire
dans les fichiers indexés, sans jamais bloquer le commit ; le même outil se
lance à la main :

```bash
python3 script/analyse/check_comment_hygiene.py script/todo/todo.py
python3 script/analyse/check_comment_hygiene.py --staged
```

🔴 `identifiant` est une trouvaille, à retirer. 🟡 `récit` est un signal à
relire : l'outil ne sait pas si la phrase énonce un fait durable ou raconte
une journée, et ne tranche pas à votre place.

Trois exemples pris dans ce dépôt, leurs noms propres masqués — une règle qui
interdit de nommer ne se cite pas elle-même en clair.

`qemu_manage.py` — la dernière phrase, « Vécu sur « <VM> », annoncée en
<adresse> au lieu de <adresse> », part en entier. Les deux qui la précèdent
disent déjà tout, une fois l'imparfait du récit passé au présent : « une VM
renommée, dont le bail porte encore l'ancien nom d'hôte, SE VOIT attribuer la
passerelle ».

`todo.py` — « recopier « <base_client>_neutralize_upgrade_18 » oblige à
regarder ce qu'on détruit » devient « recopier un nom long oblige à regarder
ce qu'on détruit, là où « o » se tape par réflexe ». L'exemple ne servait qu'à
illustrer « long ».

`qemu_install.py` — le relevé daté des miroirs, qui répondait et qui non tel
jour, part : c'est l'état d'une journée. « Aucun miroir ne réplique tout,
d'où plusieurs entrées plutôt qu'une » reste : c'est la raison d'être de la
liste, et elle est vraie demain.

## Git
- Branches : `develop` (développement), `master` (production)
- Pas de submodules Git — utilise **Google Repo** pour les addons
- Manifests XML dans `manifest/` pour chaque version Odoo
- Format de commit : `[TYPE] portée : sujet`, sujet à l'impératif, 72
  caractères au plus. Tags réellement utilisés : `[UPD]`, `[FIX]`, `[ADD]`,
  `[IMP]`, `[REF]`.

### Le sujet

Le sujet est lu cent fois pour une fois que le corps l'est — `git log
--oneline`, un blame, une note de version, un bisect. Il a une seule tâche :
dire **sur quoi porte le code**.

L'épreuve : le lire seul, sans diff ni corps. Sait-on quelle partie du système
est en jeu, et ce qui y est désormais différent ? Sinon il n'est pas fini.

Nommer la chose, puis ce qui change pour elle. Le symptôme, le message d'erreur
cité et la métaphore sont des PREUVES, et une preuve va dans le corps — un
sujet bâti sur elles se lit bien et n'apprend rien. La portée dit OÙ, les mots
après le deux-points doivent dire QUOI.

Le sujet résume le commit ENTIER, pas sa plus grosse pièce. S'il lui faut un
« et » entre deux choses sans rapport, c'étaient deux commits.

Si le travail n'entre décidément pas dans une phrase de 72 caractères, ne pas
en écrire une amputée : des **mots-clés qui résument**, séparés par des
virgules, en disent plus dans la même place — `[FIX] proxmox : pmxcfs à terre,
pvesm muet, diagnostic à la source`. C'est un repli, pas un défaut : la phrase
reste préférable quand elle tient.

Un garde-fou refuse le mécanique. Sur le sujet : tag absent, plus de 72
caractères, ouverture sur une citation. Sur le corps : plus de 10 lignes pour
une langue, une adresse IP, un courriel, un chemin de compte, et tout terme de
`private/noms_interdits.txt` — la liste des clients et des machines, qui ne
peut pas vivre dans git puisque c'est ce qu'elle protège. Absente, ce dernier
contrôle est muet. Ce qui reste un jugement — « ce corps raconte-t-il
l'enquête » — n'est vérifié par personne.

```bash
git config core.hooksPath script/git/hooks   # une fois par clone
git commit --no-verify                       # exception légitime
```

Le mode d'emploi complet, avec des exemples avant/après pris dans l'historique
de ce dépôt, est dans `conf/template_claude_commands_commit.md`.

### Tout commit assisté par IA

Trois exigences, sans exception — `AI_POLICY.md` en donne la raison :

- Trailer `Assisted-by: <modèle>`, une ligne par modèle. C'est **binaire** :
  il y a eu IA ou non, aucun seuil à apprécier.
- **Jamais** d'IA dans `Co-authored-by:` — ce champ est réservé aux humains.
- Corps **bilingue** : le corps, puis `--- FR ---` (ou `--- EN ---`, le
  marqueur nomme la langue de ce qui SUIT), puis la traduction.

Court et direct : **8 lignes par langue**, 10 est un plafond. Le corps dit
pourquoi c'était nécessaire, puis s'arrête. Rien de ce que le diff montre
déjà ; on garde le mode de défaillance, le chiffre qui borne et la
vérification. Le bilinguisme achète la concision, il ne l'excuse pas.

Le corps obéit aux mêmes deux règles que les commentaires : **rien
d'identifiant**, et **le fonctionnement plutôt que l'enquête**. Le corps dit
ce que le code fait ou refuse DÉSORMAIS ; il ne raconte ni la séance, ni les
hypothèses écartées, ni qui s'est trompé. Une mesure se généralise à sa classe
de situation — « sur une base de production », jamais son nom.

Le mode d'emploi complet — résolution dynamique du modèle, gabarit, identité
git, taille des correctifs — est dans
`conf/template_claude_commands_commit.md`, déployable en `/commit` par
`TODO › Execute › GPT code › Claude configs`.
