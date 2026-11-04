
# Installation Ubuntu 24.04

 sudo apt install libcairo2-dev

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