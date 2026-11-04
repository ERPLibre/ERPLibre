<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
# Installation Ubuntu 24.04

<!-- [fr] -->
# Installation Ubuntu 24.04

<!-- [common] -->
 sudo apt install libcairo2-dev

<!-- [en] -->
# Requirement tours

`run_requirement_tours.py` plays the `web_tour` tours linked to DevSecOps
requirements and writes each verdict back to Odoo. It reads the
`devops.requirement.test` lines of kind `tour` over XML-RPC, logs in once,
plays every tour in `auto` mode from `/odoo`, then calls
`devops.requirement.test.record_result`. A failed tour leaves a screenshot,
and a JSON report sums up the run, both under `./screencasts/requirement_tours`.

```bash
export ERPLIBRE_REQUIREMENT_RUNNER_LOGIN=<runner login>
export ERPLIBRE_REQUIREMENT_RUNNER_PASSWORD=<runner password>
make robot_libre_requirement_tours bd=<database>
# or, to choose the requirements and keep the run readable:
.venv.erplibre/bin/python script/selenium/run_requirement_tours.py \
  --headless --no_dark_mode --db <database> --code <CODE> --step_delay 800
```

- The RPC account belongs to the group "Requirement test runner" or is a
  system user. Its credentials go through environment variables only, and the
  browser logs in with the same account unless `--default_email_auth` is
  given. Without these variables, the RPC uses the browser account only if its
  password comes from `--default_password_auth_env`; otherwise the run stops
  with exit code 2. Never put a password in `ARGS`: make prints the recipe,
  and any user on the machine can read a process's arguments.
- Exit code: 0 every tour passes, 1 a tour fails, 2 the tool fails (browser,
  login, RPC, missing tour, no verdict, verdict not recorded, nothing to play).
  What fails after the verdicts — the Onboarding not switched back on, the
  browser not closed — is listed under `alertes` in the report and leaves
  the exit code as it is.
- The tour must be in `web.assets_backend`: `/odoo` loads `web.assets_tests`
  only in test mode.
- Side effects on the target database: the browser account's Onboarding is
  switched off during the run and back on at the end if it was on; when it
  cannot be read, the run stops before touching it. The records a tour
  creates stay there.

<!-- [fr] -->
# Tours des requis

`run_requirement_tours.py` joue les tours `web_tour` liés aux requis
DevSecOps et écrit chaque verdict dans Odoo. Il lit par XML-RPC les lignes
`devops.requirement.test` de type `tour`, se connecte une fois, joue chaque
tour en mode `auto` depuis `/odoo`, puis appelle
`devops.requirement.test.record_result`. Un tour en échec laisse une capture
d'écran, et un rapport JSON résume la passe, tous deux sous
`./screencasts/requirement_tours`.

```bash
export ERPLIBRE_REQUIREMENT_RUNNER_LOGIN=<login de l'exécutant>
export ERPLIBRE_REQUIREMENT_RUNNER_PASSWORD=<mot de passe de l'exécutant>
make robot_libre_requirement_tours bd=<base>
# ou, pour choisir les requis et garder la passe lisible :
.venv.erplibre/bin/python script/selenium/run_requirement_tours.py \
  --headless --no_dark_mode --db <base> --code <CODE> --step_delay 800
```

- Le compte RPC appartient au groupe « Lanceur de tests de requis » ou
  est un utilisateur système. Ses identifiants passent par des variables
  d'environnement seulement, et le navigateur se connecte avec le même compte
  sauf `--default_email_auth` explicite. Sans ces variables, le RPC prend le
  compte du navigateur seulement si son mot de passe vient de
  `--default_password_auth_env` ; sinon la passe s'arrête en code 2. Jamais
  de mot de passe dans `ARGS` : make affiche la recette, et tout utilisateur
  de la machine lit les arguments d'un processus.
- Code de sortie : 0 tous les tours passent, 1 un tour échoue, 2 l'outil
  échoue (navigateur, connexion, RPC, tour absent, sans verdict, verdict non
  remonté, rien à jouer). Ce qui rate après les verdicts — l'Onboarding non
  rallumé, le navigateur non fermé — figure sous `alertes` dans le rapport,
  sans changer le code de sortie.
- Le tour doit être dans `web.assets_backend` : `/odoo` ne charge
  `web.assets_tests` qu'en mode test.
- Effets de bord sur la base visée : l'Onboarding du compte navigateur est
  coupé pendant la passe et rallumé à la fin s'il était allumé ; illisible,
  il arrête la passe avant qu'on y touche. Les enregistrements qu'un tour
  crée y restent.
