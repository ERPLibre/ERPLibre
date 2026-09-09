#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Parler à UNE destination : un serveur HTTP, ou le CLI `claude`.

Un backend ne connaît ni l'historique, ni les commandes, ni l'affichage : il
prend une liste de messages, rend le texte de la réponse et un dictionnaire de
faits (modèle qui a répondu, jetons, raison d'arrêt). `chat.py` tient la
conversation au-dessus, le menu demande et affiche.

Deux formes, et la différence porte un piège que `keeps_history` nomme :
`HttpBackend` est SANS mémoire — l'historique complet repart à chaque tour —
là où une session `claude` tient sa propre histoire côté processus. Renvoyer
l'historique local à une session qui la garde déjà la doublerait.

**La clé ne quitte jamais le processus.** Elle va à `openai.OpenAI(api_key=…)`
en mémoire, jamais sur une ligne de commande ni dans une variable
d'environnement : un argv se lit par n'importe quel compte local dès que
`/proc` est monté sans `hidepid`, et AUCUN masquage n'atteint argv. Celui de
`script/execute/execute.py` couvre `OPENAI_API_KEY=` et `Authorization:
Bearer` dans une TRACE, ce qui est le dernier rempart et non le premier.

**L'invite de `claude` part sur l'entrée standard**, jamais en positionnel,
pour la même raison. `claude_argv` bâtit donc l'argv SANS l'invite, et
l'appelant écrit la question sur stdin.

Onze des douze familles de serveurs exposent `/v1/chat/completions` à
l'identique : un seul client `openai` les couvre toutes, pointé sur ce que
`servers.base_url()` rend. C'est aussi ce client qu'un test injecte pour
parler à un vrai serveur de boucle locale plutôt qu'à un double.
"""
from __future__ import annotations

import json
import subprocess
from typing import Protocol

# La lecture est plafonnée pour qu'un corps d'erreur de plusieurs mégaoctets
# reste un message d'une ligne.
MAX_DETAIL = 500

# `openai.OpenAI` refuse de se construire sans clé, et un serveur local n'en
# vérifie aucune : cette chaîne occupe la place sans rien ouvrir.
NO_KEY = "no-key"

# Un modèle local qui rend 700 jetons sur un processeur prend des minutes ;
# le délai n'est là que pour borner un serveur qui ne répondra jamais.
TIMEOUT = 300.0

# Une seule reprise : au-delà d'une panne de connexion, réessayer un envoi
# relance une génération entière chez qui la paie.
MAX_RETRIES = 1

# Le budget d'un aller-retour `claude -p`, qui inclut le démarrage du CLI.
CLAUDE_TIMEOUT = 600

# Les outils de lecture, et rien d'autre. Ce sont des drapeaux, et non une
# phrase d'invite système : un drapeau est ce qui tient l'engagement.
READ_ONLY_TOOLS = "Read,Glob,Grep"


class BackendError(Exception):
    """Une panne à montrer sur une ligne : le corps du serveur y est repris.

    Le texte porte déjà le détail utile — code de statut, message du serveur,
    cause de la connexion refusée — pour que l'appelant l'imprime tel quel
    sans avoir à lire une trace.
    """


class Interrupted(Exception):
    """Une lecture de flux coupée en route, qui porte ce qui est déjà arrivé.

    `partial` est le texte reçu avant la coupure et `meta` les faits déjà
    connus. Ce qui a été reçu a été payé : l'appelant le garde plutôt que de
    le jeter.
    """

    def __init__(self, partial: str = "", meta: dict | None = None):
        super().__init__(partial)
        self.partial = partial
        self.meta = meta or {}


class Backend(Protocol):
    """Ce qu'une destination doit savoir faire.

    `keeps_history` dit si la destination garde l'histoire de son côté : quand
    il vaut vrai, l'appelant n'envoie QUE le nouveau tour.

    `send` rend `(texte, faits)`. Quand `on_chunk` est fourni, chaque fragment
    lui est passé au fil de l'arrivée et la somme des fragments EST le texte
    rendu — l'appelant imprime les fragments ou le texte, jamais les deux.
    Une panne lève `BackendError` ; une coupure lève `Interrupted`.
    """

    keeps_history: bool

    def send(
        self, messages, *, on_chunk=None
    ) -> tuple[str, dict]:  # pragma: no cover - contrat
        ...


def one_line(texte: str) -> str:
    """Un texte de panne ramené à une ligne et coupé à `MAX_DETAIL`.

    Un serveur qui rend une page d'erreur entière ne doit pas dérouler
    l'écran, et un message sur plusieurs lignes se confond avec une trace.
    """
    plat = " ".join((texte or "").split())
    if len(plat) > MAX_DETAIL:
        return f"{plat[:MAX_DETAIL]} …"
    return plat


def readable(exc: Exception) -> str:
    """Une panne réduite à une ligne, cause comprise, jamais une trace.

    La cause est ajoutée quand elle apprend quelque chose : une erreur de
    connexion du client `openai` ne dit que « Connection error. », et c'est
    sa cause qui nomme le refus.
    """
    detail = str(exc).strip() or type(exc).__name__
    cause = exc.__cause__
    if cause is not None:
        extra = str(cause).strip()
        if extra and extra not in detail:
            detail = f"{detail} ({extra})"
    return one_line(detail)


def _usage(usage) -> dict:
    """Les compteurs de jetons en types simples, {} quand ils manquent.

    Un serveur local en omet souvent une partie, et le menu doit pouvoir les
    imprimer sans vérifier chaque champ.
    """
    if usage is None:
        return {}
    faits = {}
    for champ in ("prompt_tokens", "completion_tokens", "total_tokens"):
        valeur = getattr(usage, champ, None)
        if isinstance(valeur, int):
            faits[champ] = valeur
    return faits


class HttpBackend:
    """Un serveur qui expose `/v1/chat/completions`.

    Sans mémoire : l'historique complet part à chaque tour, ce que
    `keeps_history = False` annonce à l'appelant.

    `client` est le client `openai` injecté ; laissé à `None`, il se construit
    paresseusement sur `servers.base_url(server)` au premier envoi, ce qui
    rend cette classe importable et testable sans serveur ni socket.
    `params` porte les réglages du gpt (`temperature`, `max_tokens`) et part
    tel quel dans l'appel.
    """

    keeps_history = False

    def __init__(
        self, server, model, *, api_key=None, params=None, client=None
    ):
        self.server = server
        self.model = model
        self.params = dict(params or {})
        self._api_key = api_key
        self._client = client

    def client(self):
        """Le client `openai`, construit au premier besoin.

        La clé va dans le constructeur, en mémoire ; l'absence de clé devient
        `NO_KEY` parce que le client refuse de se bâtir sans rien et qu'un
        serveur local n'en lit aucune.
        """
        if self._client is None:
            from openai import OpenAI

            from script.todo.assistant.servers import base_url

            self._client = OpenAI(
                base_url=base_url(self.server),
                api_key=self._api_key or NO_KEY,
                timeout=TIMEOUT,
                max_retries=MAX_RETRIES,
            )
        return self._client

    def send(self, messages, *, on_chunk=None) -> tuple[str, dict]:
        """Un aller-retour de génération. Lève `BackendError` sur panne."""
        from openai import OpenAIError

        # Le modèle et les messages écrasent `params` : le serveur choisi
        # décide du modèle, et un `params` de gpt qui nommerait l'un des deux
        # ferait lever le constructeur au lieu de répondre.
        appel = dict(self.params)
        appel["model"] = self.model
        appel["messages"] = list(messages)
        try:
            if on_chunk is None:
                return self._whole(appel)
            return self._streamed(appel, on_chunk)
        except OpenAIError as panne:
            raise BackendError(readable(panne)) from panne

    def _create(self, appel, **extra):
        """L'appel de génération, avec un refus de paramètre nommé.

        Un `params` de gpt qui porte un réglage propre à un serveur — `num_ctx`
        pour l'un, `top_k` pour un autre — fait lever le client sur un argument
        inattendu : nommer le paramètre vaut mieux qu'une trace, et c'est le
        fichier du gpt qui se corrige.
        """
        try:
            reponse = self.client().chat.completions.create(**appel, **extra)
        except TypeError as refus:
            raise BackendError(one_line(f"{self.model}: {refus}")) from refus
        if isinstance(reponse, (str, bytes)):
            # Un corps qui n'est pas du JSON — la page d'administration d'un
            # routeur sur un port partagé — traverse le client comme du
            # texte : il n'a ni choix à lire ni flux à dérouler.
            raise BackendError(one_line(f"{self.model}: {reponse!r}"))
        return reponse

    def _whole(self, appel) -> tuple[str, dict]:
        """La réponse d'un seul bloc, quand personne n'écoute les fragments."""
        reponse = self._create(appel)
        choix = list(getattr(reponse, "choices", None) or ())
        if not choix:
            raise BackendError(
                one_line(f"{self.model}: no choice in the answer — {reponse}")
            )
        texte = getattr(choix[0].message, "content", None) or ""
        raison = getattr(choix[0], "finish_reason", "") or ""
        if not texte.strip():
            # Un serveur dont le moteur de modèle s'arrête en cours de route
            # rend un 200 avec un contenu VIDE, et l'afficher tel quel se
            # confond avec un modèle qui n'a rien à dire. La cause du silence
            # est dans `finish_reason`, donc il est nommé : sans cela, une
            # panne de ressources sur l'hôte du modèle se lit comme un défaut
            # du menu.
            raise BackendError(
                one_line(
                    f"{self.model}: empty answer"
                    f" (finish_reason: {raison or 'none'})"
                )
            )
        faits = {
            "model": getattr(reponse, "model", "") or self.model,
            "usage": _usage(getattr(reponse, "usage", None)),
            "finish_reason": raison,
        }
        return texte, faits

    def _streamed(self, appel, on_chunk) -> tuple[str, dict]:
        """La réponse fragment par fragment.

        Une interruption ferme le flux et lève `Interrupted` avec ce qui est
        déjà arrivé : la socket ne doit pas rester ouverte derrière, et le
        texte reçu est gardé.
        """
        morceaux: list[str] = []
        faits = {"model": self.model, "usage": {}, "finish_reason": ""}
        flux = self._create(appel, stream=True)
        try:
            for evenement in flux:
                faits["model"] = (
                    getattr(evenement, "model", "") or faits["model"]
                )
                usage = _usage(getattr(evenement, "usage", None))
                if usage:
                    faits["usage"] = usage
                for choix in evenement.choices or ():
                    delta = getattr(choix, "delta", None)
                    morceau = getattr(delta, "content", None) or ""
                    if morceau:
                        morceaux.append(morceau)
                        on_chunk(morceau)
                    fin = getattr(choix, "finish_reason", None)
                    if fin:
                        faits["finish_reason"] = fin
        except KeyboardInterrupt:
            # La fermeture rend la socket ; l'échec de cette fermeture ne doit
            # pas coûter le texte déjà reçu, qui est ce qu'on vient garder.
            try:
                flux.close()
            except Exception:
                pass
            raise Interrupted("".join(morceaux), faits) from None
        return "".join(morceaux), faits


def claude_argv(*, session_id, cwd, fork, read_only=True) -> list[str]:
    """L'argv d'un `claude -p`, SANS l'invite : elle part sur stdin.

    `--output-format json` rend une enveloppe qui nomme la session, le
    résultat, l'erreur, le nombre de tours, le coût et le modèle qui a
    répondu ; c'est la seule forme lisible par un programme.

    `fork` ajoute `--fork-session`, et c'est le défaut pour questionner une
    session vivante : reprendre une session tenue par un terminal interactif
    n'est PAS refusée par le CLI, et deux écritures concurrentes sur un même
    identifiant forkent la transcription en silence — une branche devient
    orpheline. Sans `session_id` il n'y a rien à brancher, donc rien à
    ajouter.

    `read_only` impose la lecture seule par des DRAPEAUX — `--tools` et
    `--permission-mode dontAsk` — et non par une phrase d'invite système, qui
    n'engage rien. `--add-dir` ouvre le répertoire à lire quand il est connu.
    """
    argv = ["claude", "-p", "--output-format", "json"]
    if session_id:
        argv += ["--resume", str(session_id)]
        if fork:
            argv.append("--fork-session")
    if read_only:
        argv += ["--tools", READ_ONLY_TOOLS]
        argv += ["--permission-mode", "dontAsk"]
        if cwd:
            argv += ["--add-dir", str(cwd)]
    return argv


def _run_stdin(argv, stdin_text):
    """Lance `argv` en écrivant `stdin_text` sur son entrée standard.

    Rend `(code, sortie, erreur)`. Le sous-processus n'hérite d'aucun terminal
    et l'invite ne passe par aucun argument : c'est tout l'intérêt de ce
    chemin.
    """
    fini = subprocess.run(
        argv,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=CLAUDE_TIMEOUT,
        check=False,
    )
    return fini.returncode, fini.stdout, fini.stderr


class ClaudeCliBackend:
    """Une session `claude` locale, questionnée par `claude -p`.

    `keeps_history = True` : la session garde son histoire côté processus,
    donc seul le nouveau tour lui est envoyé.

    Après un envoi réussi, la session adoptée est celle que l'enveloppe
    nomme et `fork` retombe à faux : sans cela, chaque tour re-brancherait la
    session d'origine et le second tour ne verrait pas le premier.

    `run` est le lanceur injecté — `(argv, stdin) -> (code, sortie, erreur)` ;
    laissé à `None`, il lance un vrai sous-processus.
    """

    keeps_history = True

    def __init__(self, *, session_id=None, cwd=None, fork=True, run=None):
        self.session_id = session_id
        self.cwd = cwd
        self.fork = fork
        self._run = run

    def argv(self) -> list[str]:
        return claude_argv(
            session_id=self.session_id, cwd=self.cwd, fork=self.fork
        )

    def send(self, messages, *, on_chunk=None) -> tuple[str, dict]:
        """Envoie le dernier tour utilisateur et rend `(résultat, faits)`.

        Un message `system` n'est pas transmis : la session porte son propre
        système, et pousser du contexte en masse par `--append-system-prompt`
        est refusé.

        `claude -p --output-format json` ne diffuse rien ; `on_chunk` reçoit
        donc le résultat en un fragment, pour que l'appelant garde un seul
        chemin d'affichage.
        """
        invite = self._prompt(messages)
        lanceur = self._run or _run_stdin
        try:
            code, sortie, erreur = lanceur(self.argv(), invite)
        except FileNotFoundError as absent:
            raise BackendError("claude is not on the PATH.") from absent
        except subprocess.TimeoutExpired as expire:
            raise BackendError(readable(expire)) from expire
        enveloppe = self._envelope(code, sortie, erreur)
        resultat = str(enveloppe.get("result") or "")
        if enveloppe.get("is_error"):
            raise BackendError(one_line(resultat or erreur))
        session = enveloppe.get("session_id")
        if session:
            self.session_id = session
            self.fork = False
        faits = {
            "session_id": self.session_id or "",
            "num_turns": enveloppe.get("num_turns"),
            "total_cost_usd": enveloppe.get("total_cost_usd"),
            "modelUsage": enveloppe.get("modelUsage") or {},
        }
        if on_chunk is not None and resultat:
            on_chunk(resultat)
        return resultat, faits

    @staticmethod
    def _prompt(messages) -> str:
        """Le texte du dernier tour utilisateur, "" s'il n'y en a aucun."""
        for message in reversed(list(messages or ())):
            if message.get("role") == "user":
                return str(message.get("content") or "")
        return ""

    @staticmethod
    def _envelope(code, sortie, erreur) -> dict:
        """L'enveloppe JSON de `claude -p`, ou une panne qui cite la sortie.

        Une sortie qui n'est pas du JSON est le cas d'un CLI qui a refusé
        avant de commencer : le début du texte est ce qui l'explique, et il
        vaut mieux le montrer que de lever sur l'analyse.
        """
        texte = (sortie or "").strip()
        try:
            enveloppe = json.loads(texte)
        except ValueError:
            detail = texte or (erreur or "").strip()
            raise BackendError(
                one_line(f"claude rc={code}: {detail}")
            ) from None
        if not isinstance(enveloppe, dict):
            raise BackendError(f"claude rc={code}: unexpected envelope")
        return enveloppe
