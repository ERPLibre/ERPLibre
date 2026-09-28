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


def prompt_execute_sms(todo) -> None:
    while True:
        state = spec_mod.load()
        mode = state.spec.mode
        help_info = f"""{todo._menu_header()}
{steps_mod.render(state)}

[1] {t("sms_run_all")}
{_lignes_etapes(state.spec)}
[8] {t("sms_phone_menu")}
[9] {t("sms_call_menu")}
[10] {t("sms_open_tui")}
[11] {t("sms_test_number_menu")} : {state.spec.test_number or t("sms_test_number_none")}
[12] {t("sms_mode_menu")} ({mode} / {state.spec.transport})
[14] {t("sms_materiel_menu")} : {t("sms_materiel_" + state.spec.materiel)}
[13] {t("sms_reset_local") if mode == "local" else t("sms_reset")}
[0] {t("Back")}"""
        status = click.prompt(help_info)
        print()
        if status == "0":
            return
        if status == "1":
            enchainer(todo, state)
        elif status in ("2", "3", "4", "5", "6", "7"):
            _run_one(todo, state, STEPS[int(status) - 2])
        elif status == "8":
            _read_phone()
        elif status == "9":
            _place_test_call(todo, state)
        elif status == "10":
            _open_tui(todo)
        elif status == "11":
            _choose_test_number(state)
        elif status == "12":
            _choose_mode(state)
            _choose_transport(spec_mod.load())
        elif status == "13":
            _reset(todo, state)
        elif status == "14":
            _choose_materiel(state)
        else:
            print(t("Command not found !"))


# ----------------------------------------------------------------------
# Exécution
# ----------------------------------------------------------------------


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
    print(f"  {t('sms_test_number_file')} {spec_mod.STATE_PATH}")


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


def poser_materiel(state, materiel: str) -> bool:
    """Pose le materiel et oublie ce qu'il invalide. Rend True s'il a change.

    Les etapes serveur — VM et Odoo — tiennent : c'est la meme installation.
    La fiche passerelle, elle, PORTE le materiel, et les criteres de sante en
    dependent : la garder ferait juger un modem sur ceux d'un telephone.

    Un seul endroit sait cela, parce que deux chemins y mènent — le choix
    explicite, et l'entree du menu Modem qui impose son materiel. Deux listes
    d'etapes a oublier finiraient par diverger, et l'une des deux laisserait
    une coche verte sur une fiche a refaire.
    """
    from dataclasses import replace

    if materiel == state.spec.materiel:
        return False
    state.spec = replace(state.spec, materiel=materiel)
    for etape in ("gateway", "mobile", "verify", "confirm"):
        if etape in state.done:
            state.done.remove(etape)
    spec_mod.save(state)
    return True


def _choose_materiel(state) -> None:
    """Telephone ou modem."""
    print(f"  {t('sms_materiel_current')} : {t('sms_materiel_' + state.spec.materiel)}")
    print(f"  [1] {t('sms_materiel_mobile')}")
    print(f"  [2] {t('sms_materiel_modem')}")
    choix = input(f"  {t('sms_materiel_ask')}").strip()
    nouveau = {"1": "mobile", "2": "modem"}.get(choix)
    if nouveau is None:
        return
    if poser_materiel(state, nouveau):
        print(f"  ⚠️  {t('sms_materiel_changed')}")


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
        state.spec, spec_mod.ensure_secret(), state.vm_ip
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

    Quand rien ne vient, on ne dit pas « echec » : on lit le journal du
    serveur et on nomme la cause. Secret, identifiant, horloge et silence
    reseau produisent le meme symptome a l'ecran et demandent trois gestes
    differents.
    """
    import time

    if state.spec.mode != "local":
        # En mode VM, le journal du serveur n'est pas sous la main.
        return True, t("sms_mobile_done")

    depart = local_backend.gateway_poll_age(state.spec)
    print(f"  {t('sms_mobile_waiting')}")
    debut = time.time()
    while time.time() - debut < 120:
        age = local_backend.gateway_poll_age(state.spec)
        if age is not None and (depart is None or age < depart):
            return True, f"{t('sms_mobile_done')} — {t('sms_mobile_polled')}"
        time.sleep(5)

    causes = local_backend.refus_recents()
    if causes:
        return False, " | ".join(t(c) for c in causes)
    return False, t("sms_diag_silence")


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

    Publique parce que deux entrees y menent : « tout enchainer » de ce menu,
    et celle du menu Modem qui n'ouvre rien et lance directement la chaine.
    """
    for step in STEPS:
        if state.is_done(step.id):
            continue
        if not _run_one(todo, state, step):
            return
    print(f"\n  ✅ {t('sms_all_done')}")


# ----------------------------------------------------------------------
# Tableau de bord et remise à zéro
# ----------------------------------------------------------------------


def _open_tui(todo) -> None:
    from script.todo.sms.tui import run_sms_tui

    try:
        run_sms_tui(todo)
    except ImportError:
        from script.todo import textual_setup

        if textual_setup.ensure():
            run_sms_tui(todo)
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
        _, detail = local_backend.stop_server()
        print(f"  {detail}")
        subprocess.run(
            ["dropdb", "--if-exists", state.spec.db_name],
            capture_output=True,
            text=True,
            timeout=60,
        )
        state.reset()
        spec_mod.save(state)
        spec_mod.forget_secret()
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
    spec_mod.forget_secret()
    print(f"  ✅ {t('sms_reset_done')}")
