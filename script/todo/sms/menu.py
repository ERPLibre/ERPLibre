#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu SMS du CLI TODO.

Branche les étapes de `steps` sur les exécutions de `runner`, et affiche
l'état à chaque tour de boucle. L'état est relu du disque à chaque passage :
une étape lancée ailleurs — un tableau de bord ouvert dans un autre terminal,
une installation détachée qui s'est terminée — apparaît sans qu'on ait à
quitter le menu.
"""
from __future__ import annotations

import click

from script.todo.sms import local as local_backend
from script.todo.sms import runner
from script.todo.sms import spec as spec_mod
from script.todo.sms import steps as steps_mod
from script.todo.sms.steps import STEPS

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


def prompt_execute_sms(todo, materiel: str = "mobile") -> None:
    """La démonstration de la passerelle de CE matériel.

    Le matériel vient de la porte d'entrée et ne se choisit pas ici : chacun
    a son état, sa base, son port et sa fiche, et les deux démonstrations
    tiennent côte à côte sur le même poste. Le proposer en réglage ferait
    qu'arriver par une section afficherait le travail de l'autre.
    """
    while True:
        state = spec_mod.load(materiel)
        queue = _entrees_de_queue(todo, state, materiel)
        help_info = f"""{todo._menu_header()}
  {t("sms_materiel_current")} : {t("sms_materiel_" + materiel)}
{steps_mod.render(state)}

[1] {t("sms_run_all")}
{_lignes_etapes(state.spec)}
{_lignes_de_queue(queue)}
[0] {t("Back")}"""
        status = click.prompt(help_info)
        print()
        if status == "0":
            return
        if status == "1":
            enchainer(todo, state)
        elif status in ("2", "3", "4", "5", "6", "7"):
            _run_one(todo, state, STEPS[int(status) - 2])
        elif status.isdigit() and 8 <= int(status) < 8 + len(queue):
            suite = queue[int(status) - 8][1]()
            # Une entree qui rend un materiel demande de changer de
            # demonstration : elle ne peut pas le faire elle-meme, la boucle
            # tient cette variable.
            if suite in spec_mod.MATERIELS:
                materiel = suite
        else:
            print(t("Command not found !"))


# ----------------------------------------------------------------------
# Exécution
# ----------------------------------------------------------------------


def _reglage_courant(spec) -> str:
    """Le mode, et le transport quand il veut dire quelque chose."""
    if spec.materiel == "mobile":
        return f"{spec.mode} / {spec.transport}"
    return spec.mode


def _autre_materiel(materiel: str) -> str:
    """Le matériel qui n'est pas celui-ci."""
    return "modem" if materiel == "mobile" else "mobile"


def _lignes_etapes(spec) -> str:
    """Les étapes, numérotées à la suite de « tout enchaîner ».

    Générées plutôt qu'écrites à la main : ajouter une étape ne doit pas
    obliger à renuméroter le menu, ni risquer un décalage entre ce qui est
    affiché et ce qui est exécuté.
    """
    return "\n".join(
        f"[{index + 2}] {step.label_for(spec)}"
        for index, step in enumerate(STEPS)
    )


def _entrees_de_queue(todo, state, materiel: str) -> list:
    """Les entrées qui suivent les étapes : (libellé, action).

    Générées, et non écrites avec leur numéro : une entrée qui n'existe que
    pour un matériel décalerait toutes les suivantes, et un décalage de menu
    ne se voit pas — il déclenche l'action d'à côté.

    Une action qui rend le nom d'un matériel demande d'aller à l'autre
    démonstration ; les autres rendent None.
    """
    entrees = []
    if materiel == "mobile":
        entrees.append((t("sms_phone_menu"), _read_phone))
    else:
        # Lire les messages de l'appareil QU'ON DEMONTRE : sur le modem, le
        # telephone n'est pas branche, et `adb` ne repondrait rien.
        entrees.append((t("modem_sms_list"), _lister_sms_du_modem))
    entrees.append(
        (t("sms_call_menu"), lambda: _place_test_call(todo, state))
    )
    entrees.append((t("sms_open_tui"), lambda: _open_tui(todo, materiel)))
    numero = state.spec.test_number or t("sms_test_number_none")
    entrees.append(
        (
            f"{t('sms_test_number_menu')} : {numero}",
            lambda: _choose_test_number(state),
        )
    )
    entrees.append(
        (
            f"{t('sms_mode_menu')} ({_reglage_courant(state.spec)})",
            lambda: _choisir_mode_et_transport(materiel),
        )
    )
    if materiel == "mobile":
        entrees.append(
            (t("sms_pair_menu"), lambda: _appairer_par_usb(state))
        )
    autre = _autre_materiel(materiel)
    entrees.append(
        (
            f"{t('sms_switch_materiel')} : {t('sms_materiel_' + autre)}",
            lambda: autre,
        )
    )
    # L'entree qui detruit se lit en DERNIER, ou l'on ne tombe pas dessus en
    # visant sa voisine.
    efface = (
        t("sms_reset_local") if state.spec.mode == "local" else t("sms_reset")
    )
    entrees.append((efface, lambda: _reset(todo, state)))
    return entrees


def _lignes_de_queue(entrees) -> str:
    """Les entrées de queue, numérotées à la suite des étapes."""
    return "\n".join(
        f"[{index + 8}] {libelle}" for index, (libelle, _a) in enumerate(entrees)
    )


def _lister_sms_du_modem() -> None:
    from script.todo.modem.menu import _lister_sms

    _lister_sms()


def _choisir_mode_et_transport(materiel: str) -> None:
    """Le mode, puis le transport quand il veut dire quelque chose.

    Le transport dit comment le TELEPHONE joint Odoo. L'agent du modem tourne
    sur le poste et joint la boucle locale : la question n'a pas de reponse
    de ce cote.
    """
    _choose_mode(spec_mod.load(materiel))
    if materiel == "mobile":
        _choose_transport(spec_mod.load(materiel))


def url_pour_le_telephone(spec) -> str:
    """L'adresse que le telephone doit viser, selon son transport.

    En CABLE, la boucle locale, et elle seule : la politique reseau d'un APK
    ordinaire refuse le HTTP en clair partout ailleurs. Le refus vient
    d'ANDROID, avant que l'application ne voie la requete — « Cleartext HTTP
    traffic to <adresse> not permitted » — et aucun reglage dans
    l'application ne le leve. Le renvoi USB fait pointer cette boucle vers ce
    poste, ce qui satisfait la politique sans l'affaiblir.

    En WI-FI, l'adresse de l'interface, qui exige alors un APK construit avec
    `-PlanCleartext` et l'exception cochee a l'ecran.
    """
    from script.todo.sms import gateway as gw
    from script.todo.sms import phone

    if spec.transport == "wifi":
        hote = phone.host_lan_ip()
        if hote:
            return gw.server_url(spec, hote)
    return f"http://127.0.0.1:{spec.odoo_port}"


def poser_la_config_par_usb(state) -> tuple:
    """Pose URL, identifiant et secret dans l'application. Rend (ok, detail).

    Ne demande rien et n'affiche rien : deux chemins y menent — l'entree du
    menu, qui demande d'abord, et l'enchainement, qui ne demande jamais. Les
    y faire differer ferait que la chaine poserait autre chose que l'entree.
    """
    from script.todo.sms import appairage

    url = url_pour_le_telephone(state.spec)
    if "127.0.0.1" in url:
        # Sans le renvoi, le 127.0.0.1 du telephone designe le telephone, et
        # la passerelle n'atteint rien. On le pose ici plutot que de laisser
        # decouvrir la panne deux minutes plus tard, dans une attente muette.
        ouvert, detail = runner.adb_reverse(state.spec)
        if not ouvert:
            return False, detail

    try:
        return appairage.appairer(
            state.spec,
            spec_mod.ensure_secret(state.spec.materiel),
            url,
            copie_vers=spec_mod.dossier(state.spec.materiel)
            / appairage.COPIE,
        )
    except appairage.AppairageError as exc:
        return False, str(exc)


def _appairer_par_usb(state) -> None:
    """L'entree de menu : annonce, demande, puis pose.

    Le secret fait soixante-quatre caracteres : une faute de frappe y donne un
    403 que rien a l'ecran ne distingue d'une panne de reseau.
    """
    print(f"  {t('sms_pair_target')} : {url_pour_le_telephone(state.spec)}")
    print(f"  {t('sms_pair_warning')}")
    reponse = input(f"  {t('sms_pair_confirm')} ").strip().lower()
    if reponse not in ("o", "y", "oui", "yes"):
        return
    ok, detail = poser_la_config_par_usb(state)
    print(f"  {'✅' if ok else '❌'} {detail}")


def _verifier_wifi(state) -> None:
    """Dit tot ce qui empechera le Wi-Fi de marcher.

    Les deux pannes courantes n'ont rien a voir l'une avec l'autre et se
    ressemblent a l'ecran : le telephone sur un autre reseau, ou l'exception
    « reseau local en clair » pas cochee. Les distinguer ici evite de chercher
    au mauvais endroit.
    """
    from script.todo.sms import phone

    poste = phone.host_lan_ip()
    appareil = phone.phone_lan_ip()
    if not poste:
        print(f"  ⚠️  {t('sms_wifi_no_host_ip')}")
        return
    print(f"  {t('sms_wifi_host')} : {poste}")
    if not appareil:
        # Sans cable on ne peut pas lire l'adresse du telephone ; ce n'est
        # pas une panne, juste une verification qu'on ne peut pas faire.
        print(f"  ℹ️  {t('sms_wifi_unknown_phone')}")
        return
    print(f"  {t('sms_wifi_phone')} : {appareil}")
    if phone.same_subnet(poste, appareil):
        print(f"  ✅ {t('sms_wifi_same_net')}")
    else:
        print(f"  ⚠️  {t('sms_wifi_other_net')}")


def _choose_transport(state) -> None:
    """Cable ou Wi-Fi. Change l'URL, donc invalide le lien deja fait."""
    from dataclasses import replace

    print(f"  {t('sms_transport_current')} : {state.spec.transport}")
    print(f"  [1] {t('sms_transport_cable')}")
    print(f"  [2] {t('sms_transport_wifi')}")
    choix = input(f"  {t('sms_transport_ask')}").strip()
    nouveau = {"1": "cable", "2": "wifi"}.get(choix)
    if nouveau is None or nouveau == state.spec.transport:
        return
    state.spec = replace(state.spec, transport=nouveau)
    # L'URL change : le telephone doit etre reconfigure, donc l'etape de
    # liaison n'est plus valable. Les etapes serveur, elles, tiennent.
    for etape in ("mobile", "verify", "confirm"):
        if etape in state.done:
            state.done.remove(etape)
    spec_mod.save(state)
    print(f"  ⚠️  {t('sms_transport_changed')}")


def _place_test_call(todo, state) -> None:
    """Met un appel d'essai en file, et suit son etat jusqu'au bout.

    Le seul chemin qu'aucun essai automatique n'a pu couvrir : un appel qui
    ABOUTIT. Tous les essais du developpement visaient le telephone lui-meme,
    qui refuse — seuls les chemins d'echec etaient donc prouves. Celui-ci
    demande un vrai correspondant, donc une decision humaine.
    """
    import subprocess
    import time
    import uuid as _uuid

    numero = state.spec.test_number
    if not numero:
        print(f"  ❌ {t('sms_call_no_number')}")
        return
    print(f"  {t('sms_call_warning')}")
    reponse = input(f"  {t('sms_call_confirm')} [{numero}] ").strip().lower()
    if reponse not in ("o", "y", "oui", "yes"):
        return

    identifiant = _uuid.uuid4().hex
    script = f"""
gw = env["erplibre.sms.gateway"].search([("active", "=", True)], limit=1)
if not gw:
    print("RESULTAT_ERREUR=aucune passerelle active")
else:
    env["erplibre.mobile.call"].create({{
        "call_uuid": {identifiant!r},
        "number": {numero!r},
        "direction": "out",
        "source": "queued",
        "company_id": env.company.id,
        "gateway_id": gw.id,
        "state": "queued",
    }})
    env.cr.commit()
    print("RESULTAT_UUID={identifiant}")
"""
    dos = _backend(state)
    try:
        res = (
            dos._run_odoo(
                state.spec,
                [
                    "shell",
                    "-c",
                    "config.conf",
                    "-d",
                    state.spec.db_name,
                    "--no-http",
                    "--log-level=error",
                ],
                timeout=300,
                stdin_text=script,
            )
            if state.spec.mode == "local"
            else None
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ {exc}")
        return
    if res is None:
        print(f"  ❌ {t('sms_call_local_only')}")
        return
    if "RESULTAT_UUID" not in (res.stdout or ""):
        print(f"  ❌ {(res.stderr or res.stdout).strip()[-300:]}")
        return
    print(f"  ✅ {t('sms_call_queued')}")

    dernier = ""
    debut = time.time()
    while time.time() - debut < 300:
        sortie = subprocess.run(
            [
                "psql",
                "-d",
                state.spec.db_name,
                "-tAc",
                "SELECT state || '|' || duration_seconds || '|'"
                " || coalesce(duration_source,'') || '|'"
                " || coalesce(failure_reason,'') FROM erplibre_mobile_call"
                f" WHERE call_uuid = '{identifiant}'",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        if sortie and sortie != dernier:
            dernier = sortie
            etat, duree, origine, motif = (sortie.split("|") + ["", "", ""])[
                :4
            ]
            ligne = f"    {int(time.time() - debut):>3}s  {etat}"
            if duree and duree != "0":
                ligne += f"  —  {duree} s ({origine or '?'})"
            if motif:
                ligne += f"  —  {motif}"
            print(ligne)
            if etat in ("ended", "failed", "expired"):
                break
        time.sleep(3)


def _choose_test_number(state) -> None:
    """Retient le numero vers lequel partent les essais.

    Vide par defaut, et il le reste tant que quelqu'un ne le donne pas :
    un essai atteint une vraie personne et coute de l'argent. Un numero
    d'exemple laisse dans un fichier de configuration finit toujours par
    partir pour de vrai.
    """
    from dataclasses import replace

    actuel = state.spec.test_number
    print(
        f"  {t('sms_test_number_current')} : {actuel or t('sms_test_number_none')}"
    )
    print(f"  {t('sms_test_number_hint')}")
    saisi = input(f"  {t('sms_test_number_ask')}").strip()
    if not saisi:
        return
    if saisi in ("-", "0"):
        state.spec = replace(state.spec, test_number="")
        spec_mod.save(state)
        print(f"  {t('sms_test_number_cleared')}")
        return
    if not saisi.startswith("+") or not saisi[1:].isdigit():
        # Le module valide le format avant l'envoi, mais son refus arrive
        # trois etapes plus loin dans une trace Odoo. Autant le dire ici.
        print(f"  ❌ {t('sms_err_number_format')}")
        return
    state.spec = replace(state.spec, test_number=saisi)
    spec_mod.save(state)
    print(f"  ✅ {t('sms_test_number_set')} {saisi}")
    print(
        f"  {t('sms_test_number_file')} "
        f"{spec_mod.chemin_etat(state.spec.materiel)}"
    )


def _read_phone() -> None:
    """Lit une boîte SMS du téléphone branché.

    C'est le seul endroit qui dit ce que la pile téléphonique a réellement
    enregistré. Odoo rapporte ce qu'il a demandé, le journal de la passerelle
    ce que l'application a fait — mais entre les deux, un message peut encore
    être refusé par l'opérateur.
    """
    from script.todo.sms import phone

    boites = {"1": "sent", "2": "inbox", "3": "all"}
    while True:
        choix = input(f"  {t('sms_phone_ask')}").strip()
        if choix == "0" or not choix:
            return
        boite = boites.get(choix)
        if boite is None:
            print(f"  {t('Command not found !')}")
            continue
        try:
            messages = phone.read_sms(boite, limit=15)
        except phone.PhoneError as exc:
            print(f"  ❌ {exc}")
            continue
        print()
        print(phone.render(messages, boite))
        print()


def _run_one(todo, state, step) -> bool:
    """Joue une étape, enregistre son issue, et la raconte.

    Renvoie True si l'étape a réussi — `enchainer` s'en sert pour s'arrêter
    au premier échec plutôt que d'empiler des erreurs dérivées.
    """
    manquant = steps_mod.blocked_by(step, state)
    if manquant:
        print(f"  ❌ {t('sms_blocked_by')} : {', '.join(manquant)}")
        return False

    # `label_for` et non `label` : sur un modem, l'etape de liaison porte un
    # autre nom, et annoncer celui du telephone ferait chercher un appareil
    # que personne n'a en main.
    print(f"  ⏳ {t('sms_step_running')} : {step.label_for(state.spec)}")
    try:
        ok, message = _dispatch(todo, state, step)
    except KeyboardInterrupt:
        # Une interruption n'est pas un échec de l'étape : ne rien marquer
        # laisse l'étape reprenable telle quelle.
        print(f"\n  {t('Back')}")
        return False
    except Exception as exc:  # noqa: BLE001 - on rapporte, on ne masque pas
        ok, message = False, f"{type(exc).__name__}: {exc}"

    if ok:
        state.mark_done(step.id)
        print(f"  ✅ {t('sms_step_ok')} : {message}")
    else:
        state.mark_failed(step.id, message)
        print(f"  ❌ {t('sms_step_ko')} : {message}")
    spec_mod.save(state)
    return ok


def _backend(state):
    """Le module qui sait exécuter les étapes pour ce mode.

    Les deux exposent la même interface — `step_odoo`, `step_gateway`,
    `step_verify` — ce qui permet au menu, au tableau de bord et aux tests
    de ne rien savoir du mode choisi.
    """
    return local_backend if state.spec.mode == "local" else runner


def _dispatch(todo, state, step):
    """Aiguille vers l'exécution de l'étape demandée."""
    dos = _backend(state)
    if step.id == "vm":
        # Seule étape dont le SENS change avec le mode : créer une machine,
        # ou vérifier celle qu'on a déjà sous les pieds.
        if state.spec.mode == "local":
            return local_backend.step_env(todo, state)
        return runner.step_vm(todo, state)
    if step.id == "odoo":
        return dos.step_odoo(todo, state)
    if step.id == "gateway":
        return dos.step_gateway(todo, state)
    if step.id == "mobile":
        # Le SEUL endroit ou le materiel change ce qu'on fait : relier un
        # telephone se fait a la main, lancer l'agent du modem ne se fait
        # pas du tout — il part seul.
        if state.spec.materiel == "modem":
            return _step_modem(state)
        return _step_mobile(state)
    if step.id == "verify":
        return _step_verify(todo, state, dos)
    if step.id == "confirm":
        return _step_confirm(todo, state, dos)
    raise RuntimeError(f"etape inconnue : {step.id}")


def _choose_mode(state) -> None:
    """Demande le mode, et oublie les étapes faites s'il change.

    Changer de mode invalide tout : une base installée dans une VM n'existe
    pas sur le poste, et l'inverse est vrai aussi. Garder les coches vertes
    ferait croire à un travail déjà fait qu'aucune machine n'a jamais vu.
    """
    from dataclasses import replace

    print(f"  {t('sms_mode_current')} : {state.spec.mode}")
    print(f"  [1] {t('sms_mode_local')}")
    print(f"  [2] {t('sms_mode_vm')}")
    choix = input(f"  {t('sms_mode_ask')}").strip()
    nouveau = {"1": "local", "2": "vm"}.get(choix)
    if nouveau is None or nouveau == state.spec.mode:
        return
    state.spec = replace(state.spec, mode=nouveau)
    state.reset()
    spec_mod.save(state)
    print(f"  ⚠️  {t('sms_mode_changed')}")


def _step_modem(state):
    """Lance l'agent qui mene le modem, et attend sa premiere interrogation.

    Aucune saisie, aucun appareil en main : c'est ce qui distingue cette voie
    de celle du telephone. On refuse tot si le modem ne repond pas — decouvrir
    au moment de l'envoi d'essai qu'aucune SIM n'est enregistree ferait
    chercher la panne dans Odoo.
    """
    from script.todo.sms import agent as agent_mod

    if state.spec.mode == "local":
        vivant, detail_serveur = local_backend.start_server(state.spec)
        print(f"  {'✅' if vivant else '❌'} Odoo : {detail_serveur}")
        if not vivant:
            return False, detail_serveur

    pret, motif = agent_mod.modem_pret()
    print(f"  {'✅' if pret else '❌'} {t('sms_modem_ready') if pret else motif}")
    if not pret:
        return False, motif

    print()
    print(agent_mod.render_agent_config(
        state.spec,
        spec_mod.ensure_secret(state.spec.materiel),
        state.vm_ip,
    ))
    print()
    parti, detail = agent_mod.start_agent(state)
    print(f"  {'✅' if parti else '❌'} {t('sms_agent_label')} : {detail}")
    if not parti:
        return False, detail
    return _attendre_interrogation(state)


def _step_mobile(state):
    """Affiche ce qu'il faut saisir, et ouvre le renvoi USB si possible.

    L'étape ne peut pas se terminer toute seule : c'est un humain qui tape
    trois valeurs sur un téléphone. On lui demande donc de confirmer, plutôt
    que de marquer l'étape réussie sur la seule foi d'un affichage.
    """
    if state.spec.mode == "local":
        # Le telephone interroge Odoo toutes les trente secondes : sans
        # serveur en vie, la passerelle reste grise et rien ne dit pourquoi.
        vivant, detail_serveur = local_backend.start_server(state.spec)
        print(f"  {'✅' if vivant else '❌'} Odoo : {detail_serveur}")
        if not vivant:
            return False, detail_serveur

    # Le cable d'abord, et sans rien demander : il pose les memes trois
    # valeurs que l'ecran, sans la faute de frappe dans les soixante-quatre
    # caracteres du secret. Le pense-bete ne sert que lorsqu'il ne peut pas.
    from script.todo.sms import appairage

    joignable, motif = appairage.possible()
    if joignable:
        pose, detail = poser_la_config_par_usb(state)
        print(f"  {'✅' if pose else '❌'} {t('sms_pair_label')} : {detail}")
        if pose:
            return _attendre_interrogation(state)
        print(f"  {t('sms_pair_fallback')}")
    else:
        print(f"  ℹ️  {t('sms_pair_unavailable')} : {motif}")
    print()
    print(runner.mobile_instructions(state))
    print()
    if state.spec.transport == "wifi":
        _verifier_wifi(state)
    else:
        ok, detail = runner.adb_reverse(state.spec)
        print(f"  {'✅' if ok else '⚠️ '} {detail}")
    print()
    reponse = input(f"  {t('sms_confirm_mobile')}").strip().lower()
    if reponse not in ("o", "y", "oui", "yes"):
        return False, t("sms_mobile_pending")
    return _attendre_interrogation(state)


def _attendre_interrogation(state):
    """Attend que le telephone interroge VRAIMENT le serveur.

    L'etape se contentait auparavant d'un « oui » humain. Consequence vecue :
    le telephone signait avec un secret perime, Odoo le refusait en 403 a
    chaque cycle, et la chaine annoncait cinq etapes sur six reussies. Une
    confirmation humaine prouve la bonne volonte, pas la configuration.

    Quand rien ne vient, on ne dit pas « echec » : on nomme la cause. Secret,
    identifiant, horloge et silence reseau produisent le meme symptome a
    l'ecran et demandent trois gestes differents.

    L'appareil est interroge PENDANT l'attente, pas seulement a la fin : il
    inscrit son refus des le premier cycle, soit une trentaine de secondes.
    Attendre les deux minutes entieres pour lire ce qu'il savait deja fait
    payer quatre-vingt-dix secondes a chaque essai.
    """
    import time

    if state.spec.mode != "local":
        # En mode VM, le journal du serveur n'est pas sous la main.
        return True, t("sms_mobile_done")

    depart = local_backend.gateway_poll_age(state.spec)
    # Ce que le journal porte DEJA ne decrit pas cette attente : il est
    # partage par tout ce qui interroge ce serveur.
    marque = local_backend.taille_journal(state.spec)
    # L'appareil d'abord : c'est la seule source qui parle de LUI. Le journal
    # du serveur est partage par tout ce qui l'interroge, et le refus d'un
    # autre agent s'y lit comme le sien.
    from script.todo.sms import appairage

    print(f"  {t('sms_mobile_waiting')}")
    debut = time.time()
    prochaine_lecture = debut + 20
    while time.time() - debut < 120:
        age = local_backend.gateway_poll_age(state.spec)
        if age is not None and (depart is None or age < depart):
            return True, f"{t('sms_mobile_done')} — {t('sms_mobile_polled')}"
        if time.time() >= prochaine_lecture:
            defaut = appairage.dernier_defaut()
            if defaut:
                return False, _avec_remede(defaut)
            prochaine_lecture = time.time() + 20
        time.sleep(5)

    defaut = appairage.dernier_defaut()
    if defaut:
        return False, _avec_remede(defaut)
    causes = local_backend.refus_recents(state.spec, depuis_octet=marque)
    if causes:
        return False, " | ".join(t(c) for c in causes)
    return False, t("sms_diag_silence")


def _avec_remede(defaut: str) -> str:
    """Ajoute le geste qui leve ce refus, quand il en existe un.

    « Cleartext HTTP traffic not permitted » vient de la politique reseau
    d'Android, et aucun reglage de l'application ne la leve : il faut l'APK
    de demonstration. Le motif seul laisse chercher du cote du serveur.
    """
    if "cleartext" in defaut.lower():
        return f"{defaut} — {t('sms_remede_cleartext')}"
    return defaut


def _step_verify(todo, state, dos):
    defaut = state.spec.test_number
    invite = f"  {t('sms_ask_number')}"
    if defaut:
        invite = f"  {t('sms_ask_number')}[{defaut}] "
    numero = input(invite).strip() or defaut
    if not numero:
        return False, t("sms_mobile_pending")
    if not numero.startswith("+"):
        # Le module valide le format avant d'atteindre la passerelle : autant
        # le dire ici, où le message est lisible.
        return False, t("sms_err_number_format")
    ok, etat = dos.step_verify(todo, state, numero)
    if ok:
        print(f"  {t('sms_dispatch_state')} : {etat}")
    return ok, etat


def _step_confirm(todo, state, dos):
    """Guette l'envoi jusqu'a son etat definitif.

    C'est l'etape qui distingue « le serveur a accepte » de « le message est
    parti ». Sans elle, la chaine s'arretait sur `queued` — un etat qui a
    l'air d'une reussite et n'en est pas une : c'est exactement l'etat qu'on
    obtient quand le telephone n'interroge jamais.
    """
    import time

    uuid = state.last_uuid
    if not uuid:
        return False, t("sms_confirm_sans_envoi")

    from script.todo.sms import phone

    debut = time.time()
    dernier = ""
    while time.time() - debut < dos.CONFIRM_TIMEOUT_S:
        if state.spec.transport == "cable":
            # Le renvoi USB saute tout seul et en silence. Le reposer ici
            # evite de conclure a une panne d'envoi devant un simple cable.
            phone.ensure_reverse(state.spec.odoo_port)
        try:
            etat, code = _etat_envoi(dos, state, todo, uuid)
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"
        if etat is None:
            return False, t("sms_confirm_introuvable")
        if etat != dernier:
            dernier = etat
            ecoule = int(time.time() - debut)
            print(f"    {ecoule:>3}s  {etat}" + (f" ({code})" if code else ""))
        if etat in dos.TERMINAUX:
            if etat == "delivered":
                return True, t("sms_confirm_livre")
            return False, f"{etat}" + (f" ({code})" if code else "")
        time.sleep(3)

    # Ni livre ni echoue : le telephone n'a pas repondu. On le dit tel quel
    # plutot que de trancher a sa place.
    return False, f"{t('sms_confirm_delai')} ({dernier or 'inconnu'})"


def _etat_envoi(dos, state, todo, uuid):
    """Appelle la bonne lecture d'etat selon le mode."""
    if state.spec.mode == "local":
        return dos.dispatch_state(state.spec, uuid)
    return dos.dispatch_state(state.spec, uuid, todo=todo, state=state)


def enchainer(todo, state) -> None:
    """Joue les etapes qui restent, et s'arrete au premier echec.

    Les etapes deja faites sont sautees : la chaine se reprend donc a
    mi-parcours sans refaire une installation de plusieurs minutes.

    L'avertissement sur le RCS est pose AVANT la premiere etape, et non a la
    fin : la chaine s'arrete au premier echec, et ce qui ne s'affiche qu'en
    cas de reussite n'est jamais lu par qui en a le plus besoin.
    """
    if state.spec.materiel == "mobile":
        print(f"\n  {t('sms_avis_rcs')}\n")
    for step in STEPS:
        if state.is_done(step.id):
            continue
        if not _run_one(todo, state, step):
            return
    print(f"\n  ✅ {t('sms_all_done')}")


# ----------------------------------------------------------------------
# Tableau de bord et remise à zéro
# ----------------------------------------------------------------------


def _open_tui(todo, materiel: str = "mobile") -> None:
    from script.todo.sms.tui import run_sms_tui

    try:
        run_sms_tui(todo, materiel=materiel)
    except ImportError:
        from script.todo import textual_setup

        if textual_setup.ensure():
            run_sms_tui(todo, materiel=materiel)
    except Exception as exc:  # noqa: BLE001
        print(f"{t('Command failed: ')}{exc}")


def _reset(todo, state) -> None:
    """Détruit la VM et oublie le secret.

    La destruction passe par `virsh` : la VM est jetable par construction, et
    laisser une VM orpheline consommer 20 Go serait le pire souvenir qu'une
    démonstration puisse laisser.
    """
    reponse = input(f"  {t('sms_confirm_reset')}").strip().lower()
    if reponse not in ("o", "y", "oui", "yes"):
        return
    import subprocess

    if state.spec.mode == "local":
        _, detail = local_backend.stop_server(state.spec)
        print(f"  {detail}")
        subprocess.run(
            ["dropdb", "--if-exists", state.spec.db_name],
            capture_output=True,
            text=True,
            timeout=60,
        )
        state.reset()
        spec_mod.save(state)
        spec_mod.forget_secret(state.spec.materiel)
        print(f"  ✅ {t('sms_reset_done')}")
        return

    nom = state.spec.vm_name
    # `sudo` et `qemu:///system` : sans eux, virsh parle a la session de
    # l'utilisateur, ou le domaine n'existe pas — la destruction echouerait
    # en silence et laisserait vingt gigaoctets derriere elle.
    detruit = True
    for argv in (
        ["sudo", "virsh", "--connect", "qemu:///system", "destroy", nom],
        [
            "sudo",
            "virsh",
            "--connect",
            "qemu:///system",
            "undefine",
            nom,
            "--remove-all-storage",
        ],
    ):
        res = subprocess.run(argv, capture_output=True, text=True, timeout=120)
        detail = (res.stdout or res.stderr).strip().splitlines()
        print(f"  {' '.join(argv[1:])} → {detail[0] if detail else 'ok'}")
        # `destroy` echoue legitimement sur une VM deja eteinte ; c'est
        # `undefine` qui fait foi.
        if argv[-1] != nom and "undefine" in argv:
            detruit = res.returncode == 0
    if not detruit:
        # Ne PAS oublier l'etat : la VM existe encore, et effacer le suivi
        # rendrait cette VM orpheline invisible.
        print(f"  ❌ {t('sms_reset_failed')}")
        return
    state.reset()
    spec_mod.save(state)
    spec_mod.forget_secret(state.spec.materiel)
    print(f"  ✅ {t('sms_reset_done')}")
