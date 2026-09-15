#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce qui est téléchargé puis EXÉCUTÉ doit d'abord avoir été obtenu.

« curl … | bash » est l'idiome de la moitié des installateurs. Sans « -f »,
curl rend 0 sur une erreur HTTP et livre le CORPS de l'erreur à bash, qui
l'exécute : une page de miroir en panne, un portail captif ou le 504 d'un
cache hors ligne devient une suite de commandes. Le lecteur reçoit alors
« command not found » et la cause véritable ne se lit plus nulle part.

Et « -f » ne suffit pas à tout. Le statut d'un tube est celui de son DERNIER
membre : sans pipefail, « curl -f … | sh || repli » rend celui de sh, 0 sur
une entrée vide, et le repli ne se déclenche jamais. Il en va de même de
« tube && a || repli » et du « else » d'un « if » dont le tube est la
condition. Un téléchargement raté passe alors pour une pose réussie. Là où
un échec doit avoir une suite, le téléchargement va dans un fichier, et
c'est le statut de curl qu'on lit.

Le contrôle porte sur la PROPRIÉTÉ et non sur un fichier : tout script du
dépôt, et toute commande distante que l'hôte compose pour une VM, qui tube
un téléchargement dans un interpréteur doit demander à curl d'échouer, et
ne rien attendre d'un « || » posé derrière le tube.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

sys.argv = ["todo.py"]
from script.todo import dev_tools  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

# « curl » suivi de ce qui n'est pas une nouvelle commande, jusqu'à un tube
# vers un interpréteur. Le « \\ » de continuation de ligne est traversé.
#
# Entre le tube et l'interpréteur, un « sudo » éventuel, avec ses options
# (« -E », « -n ») et ses affectations (« VAR=valeur ») : c'est la forme d'un
# installateur qui doit écrire hors du HOME. Limite connue : une option qui
# prend son argument à part — « sudo -u compte bash » — n'est pas reconnue,
# faute de savoir, sans la table des options de sudo, quel mot est un argument
# et lequel est la commande.
#
# Puis un « timeout » éventuel, avec ses options et sa durée : la borne d'un
# installateur root se pose derrière sudo, seule place d'où elle peut le tuer.
TUBE = re.compile(
    r"curl\s+((?:[^\n|;&]|\\\n)*?)"
    r"\|\s*(?:sudo(?:\s+(?:-\S+|\w+=\S+))*\s+)?"
    r"(?:timeout(?:\s+(?:-[ks]\s+\S+|-\S+))*\s+\d+(?:\.\d+)?[smhd]?\s+)?"
    r"(?:ba)?sh\b"
)

# Ce qui suit le tube jusqu'à la fin de la liste de commandes — « ; », fin de
# ligne non continuée —, puis un « || » et le repli qu'il porte. Un « | » seul
# prolonge le tube, un « & » seul appartient à une redirection (« >&2 »). Un
# « && » est traversé : dans « tube && a || repli », le repli suit aussi un
# tube qui a « réussi » sur une entrée vide, c'est-à-dire jamais.
REPLI = re.compile(r"(?:[^\n;&|]|\\\n|\|(?!\|)|&&|&(?!&))*\|\|\s*([^\n;]*)")

# Un « set » et ses arguments, jusqu'à la fin de la commande.
SET = re.compile(r"\bset((?:[ \t]+[^\s;&|()]+)+)")

# Le tube est-il la condition d'un « if » ou d'un « elif » ? Rien ne sépare
# le mot-clé du tube, sinon un « && » ou un « || ». Groupe 1 : un « ! » qui
# nie la condition.
SI = re.compile(r"\b(?:if|elif)\s+(!\s+)?([^;\n]*)$")

# Jusqu'au « then » de ce « if » : la fin de la condition.
ALORS = re.compile(r"(?:[^\n;]|\\\n)*[;\n]\s*then\b")

MOTS_SI = re.compile(r"\b(if|elif|else|fi)\b")


def bascules_pipefail(texte: str):
    """(position, allumé) de chaque réglage de pipefail, hors commentaire.

    « set -o pipefail » et ses formes groupées (« -eo », « -euo ») allument :
    le « o » est la dernière lettre d'une option à MOINS, et le mot suivant
    est « pipefail ». « set +o pipefail » éteint. Dans un même « set », le
    dernier réglage l'emporte, comme pour le shell.
    """
    for m in SET.finditer(texte):
        debut_ligne = texte.rfind("\n", 0, m.start()) + 1
        if re.search(r"(?:^|\s)#", texte[debut_ligne : m.start()]):
            continue
        mots = m.group(1).split()
        for mot, suivant in zip(mots, mots[1:]):
            if suivant == "pipefail" and re.fullmatch(r"[-+]\w*o", mot):
                yield m.start(), mot[0] == "-"


def debut_de_ligne_logique(src: str, pos: int) -> int:
    """Le début de la ligne qui porte `pos`, continuations « \\ » comprises."""
    i = src.rfind("\n", 0, pos)
    while i > 0 and src[i - 1] == "\\":
        i = src.rfind("\n", 0, i - 1)
    return i + 1


def prologue(src: str) -> int:
    """La fin de l'en-tête du fichier : lignes vides, commentaires et « set »
    qui précèdent la première autre commande."""
    fin = 0
    for ligne in src.splitlines(keepends=True):
        nue = ligne.strip()
        if nue and not nue.startswith("#") and not re.match(r"set\b", nue):
            break
        fin += len(ligne)
    return fin


def pipefail_actif(src: str, pos: int) -> bool:
    """pipefail vaut-il pour le tube qui commence à `pos` ?

    Deux portées, et deux seulement. D'abord la ligne logique du tube, avant
    lui : le dernier réglage l'emporte. Les sous-shells refermés « ( … ) »,
    « $( … ) » et les chaînes refermées « '…' » en sont retirés, parce qu'un
    « set » posé là ne vaut que pour eux. Sans réglage sur la ligne, l'en-tête
    du fichier : il doit allumer pipefail, et aucun « set +o pipefail » ne
    doit l'éteindre entre lui et le tube.

    Un pipefail posé ailleurs — dans une fonction, plus bas dans le fichier —
    ne compte pas. L'erreur penche du côté du signalement : un repli exempté
    à tort serait un repli sans effet que plus rien ne signale.
    """
    ligne = src[debut_de_ligne_logique(src, pos) : pos]
    retire = 1
    while retire:
        ligne, retire = re.subn(r"\([^()]*\)", "", ligne)
    ligne = re.sub(r"'[^']*'", "", ligne)
    sur_la_ligne = list(bascules_pipefail(ligne))
    if sur_la_ligne:
        return sur_la_ligne[-1][1]
    fin = prologue(src)
    en_tete = list(bascules_pipefail(src[:fin]))
    if not en_tete or not en_tete[-1][1]:
        return False
    return all(allume for _p, allume in bascules_pipefail(src[fin:pos]))


def branche_de_repli(src: str, debut: int, niee: bool):
    """La branche qu'un « if » réserve à l'échec de sa condition.

    `debut` suit le « then ». Condition niée (« if ! … »), c'est la branche
    « then » elle-même ; sinon, le « else » ou l'« elif » de ce même « if »,
    les « if » imbriqués étant sautés. None s'il n'y en a pas.
    """
    profondeur = 0
    for m in MOTS_SI.finditer(src, debut):
        mot = m.group(1)
        if mot == "if":
            profondeur += 1
        elif mot == "fi" and profondeur:
            profondeur -= 1
        elif profondeur == 0 and niee:
            return src[debut : m.start()].strip(" \t\n;")
        elif mot == "fi":
            return None
        elif profondeur == 0:
            fin = src.find("\n", m.end())
            corps = src[m.end() : fin if fin >= 0 else len(src)]
            corps = corps.strip(" \t;")
            return corps if mot == "else" else f"elif {corps}"
    return None


def repli_du_tube(src: str, m):
    """Le texte du repli qui lit le statut du tube `m`, ou None.

    Deux formes : un « || » derrière le tube, et un « if » dont le tube est
    la condition."""
    suite = REPLI.match(src, m.end())
    if suite:
        return suite.group(1)
    debut = debut_de_ligne_logique(src, m.start())
    si = SI.search(src[debut : m.start()].replace("\\\n", " "))
    if not si:
        return None
    alors = ALORS.match(src, m.end())
    if not alors:
        return None
    niee = bool(si.group(1)) and not re.search(r"&&|\|\|", si.group(2))
    return branche_de_repli(src, alors.end(), niee)


def demande_lechec(options: str) -> bool:
    """« -f » y est-il demandé, sous l'une de ses formes ?

    Les options courtes se GROUPENT : « -sSf » vaut « -s -S -f », et
    chercher le seul jeton « -f » manquerait la moitié des appels du dépôt.
    """
    for mot in options.split():
        if mot == "--fail" or mot.startswith("--fail-"):
            return True
        if mot.startswith("-") and not mot.startswith("--") and "f" in mot[1:]:
            return True
    return False


def replis_sans_effet(src: str):
    """Les replis qui lisent le statut d'un tube vers un shell, sans pipefail.

    Rend le texte de chaque repli. « || true » et « || : » n'en sont pas :
    ils absorbent un échec, ils n'y réagissent pas, et ne promettent donc
    rien que le tube ne tienne.
    """
    trouves = []
    for m in TUBE.finditer(src):
        if pipefail_actif(src, m.start()):
            continue
        repli = repli_du_tube(src, m)
        if repli is None:
            continue
        mots = repli.split()
        premier = mots[0].strip("'\")") if mots else ""
        if premier not in ("true", ":"):
            trouves.append(repli.strip())
    return trouves


def scripts():
    for chemin in sorted(RACINE.glob("script/**/*.sh")):
        yield chemin, chemin.read_text(encoding="utf-8", errors="replace")


def commandes_de_lhote():
    """Les commandes que l'hôte compose et envoie à une VM, par leur nom.

    Elles ne vivent dans aucun .sh : un tube y est coupé entre plusieurs
    littéraux Python, qu'une lecture ligne à ligne du source ne recolle pas.
    On les construit donc, comme le fait le déploiement.
    """
    todo = TODO.__new__(TODO)
    yield "dev_tools.RTK_UPSTREAM", dev_tools.RTK_UPSTREAM
    yield "dev_tools.STARSHIP_UPSTREAM", dev_tools.STARSHIP_UPSTREAM
    yield "dev_tools.STARSHIP_UPSTREAM_VM", dev_tools.STARSHIP_UPSTREAM_VM
    for agent, (commande, _repertoire) in sorted(dev_tools.AGENTS.items()):
        yield f"dev_tools.AGENTS[{agent}]", commande
        yield (
            f"_qemu_aidev_remote_cmd({agent})",
            todo._qemu_aidev_remote_cmd(agent),
        )
    yield "_qemu_mise_remote_cmd(mise)", todo._qemu_mise_remote_cmd("mise")
    yield "_qemu_gnome_ext_remote_cmd", todo._qemu_gnome_ext_remote_cmd()
    yield "_qemu_pycharm_remote_cmd", todo._qemu_pycharm_remote_cmd()
    yield (
        "_qemu_android_studio_remote_cmd",
        todo._qemu_android_studio_remote_cmd(),
    )


def sources():
    for chemin, src in scripts():
        yield str(chemin.relative_to(RACINE)), src
    yield from commandes_de_lhote()


class TestUnTelechargementTubeDansUnShell(unittest.TestCase):
    def test_curl_doit_echouer_sur_une_erreur_http(self):
        fautifs = []
        for nom, src in sources():
            for options in TUBE.findall(src):
                if not demande_lechec(options):
                    fautifs.append(f"{nom} : curl {options.strip()}")
        self.assertEqual(
            fautifs,
            [],
            "le corps d'une erreur HTTP y serait exécuté :\n  "
            + "\n  ".join(fautifs),
        )

    def test_aucun_repli_derriere_un_tube_sans_pipefail(self):
        """Le repli d'un tube sans pipefail ne se déclenche jamais : c'est
        le statut de l'interpréteur qu'il lit, 0 sur une entrée vide."""
        fautifs = [
            f"{nom} : || {repli}"
            for nom, src in sources()
            for repli in replis_sans_effet(src)
        ]
        self.assertEqual(
            fautifs,
            [],
            "repli sans effet, télécharger dans un fichier :\n  "
            + "\n  ".join(fautifs),
        )

    def test_les_options_groupees_sont_reconnues(self):
        """« -sSf » vaut « -s -S -f » : les traiter comme un seul jeton
        signalerait à tort la moitié des appels du dépôt."""
        for bon in ("-fsSL", "-sSf", "-f", "--fail", "--fail-with-body"):
            self.assertTrue(demande_lechec(f"{bon} https://x"), bon)
        for mauvais in ("-L", "-sSL", "", "--silent"):
            self.assertFalse(demande_lechec(f"{mauvais} https://x"), mauvais)

    def test_le_motif_voit_un_sudo_devant_linterpreteur(self):
        """Un installateur qui écrit hors du HOME passe par sudo, avec ses
        options et ses variables : le motif doit le voir quand même."""
        for tube in (
            "curl -sL https://example.invalid/i | sh",
            "curl -sL https://example.invalid/i | bash -s -- -y",
            "curl -sL https://example.invalid/i | sudo sh",
            "curl -sL https://example.invalid/i | sudo -E bash",
            "curl -sL https://example.invalid/i | sudo -n -E bash",
            "curl -sL https://example.invalid/i | sudo A=/opt/a sh",
            "curl -sL https://example.invalid/i | sudo -E A=1 B=2 sh -s",
            "curl -sL https://example.invalid/i | sudo timeout 280 sh -s -- -y",
            "curl -sL https://example.invalid/i"
            " | sudo timeout -k 10 280 sh -s -- -y",
            "curl -sL https://example.invalid/i | timeout 60 bash",
            "curl -sL https://example.invalid/i | sudo -n timeout -k 5 9m sh",
            "curl -sL https://example.invalid/i | sudo timeout --kill-after=5"
            " 280 sh",
        ):
            self.assertEqual(
                ["-sL https://example.invalid/i "], TUBE.findall(tube), tube
            )
        for pas_un_shell in (
            "curl -sL https://example.invalid/i | shasum",
            "curl -sL https://example.invalid/i | sudo tee /x",
            "curl -sL https://example.invalid/i | sudo timeout 280 tee /x",
            "curl -sL https://example.invalid/i -o /tmp/i; sh /tmp/i",
        ):
            self.assertEqual([], TUBE.findall(pas_un_shell), pas_un_shell)

    def test_un_repli_derriere_le_tube_est_reconnu(self):
        """Les formes qui promettent un repli qu'elles ne tiennent pas."""
        for tube in (
            "curl -fsSL https://example.invalid/i | sh || echo repli",
            "curl -fsSL https://example.invalid/i | bash >&2 || return 1",
            "curl -fsSL https://example.invalid/i | sudo A=1 sh || exit 1",
            "curl -fsSL https://example.invalid/i \\\n  | bash \\\n  || return 1",
            "timeout 9 sh -c 'curl -fsSL https://example.invalid/i | sh'"
            " </dev/null || echo repli",
            # « && » : le repli ne suit qu'un échec de `ok`, jamais du tube.
            "curl -fsSL https://example.invalid/i | sh && echo ok"
            " || echo repli",
            # La condition d'un « if » est le statut de l'interpréteur.
            "if curl -fsSL https://example.invalid/i | sh; then echo ok;"
            " else echo repli; fi",
            "if curl -fsSL https://example.invalid/i | sh\nthen\n  echo ok\n"
            "else\n  echo repli\nfi",
            "if curl -fsSL https://example.invalid/i | sh; then echo ok;"
            " elif x; then echo repli; fi",
            "if ! curl -fsSL https://example.invalid/i | sh; then"
            " echo repli; fi",
            "if timeout 9 sh -c 'curl -fsSL https://example.invalid/i | sh'"
            " </dev/null; then echo ok; else echo repli; fi",
            # Le « else » est celui du « if » du tube, pas d'un imbriqué.
            "if curl -fsSL https://example.invalid/i | sh; then"
            " if a; then b; fi; else echo repli; fi",
            # « +o » ÉTEINT pipefail, et le dernier réglage l'emporte.
            "set +o pipefail\n"
            "curl -fsSL https://example.invalid/i | sh || echo repli",
            "set +eo pipefail\n"
            "curl -fsSL https://example.invalid/i | sh || echo repli",
            "set -euo pipefail\nset +o pipefail\n"
            "curl -fsSL https://example.invalid/i | sh || echo repli",
            "set -euo pipefail\nx=1\nset +o pipefail\n"
            "curl -fsSL https://example.invalid/i | sh || echo repli",
            "set -o pipefail; set +o pipefail; "
            "curl -fsSL https://example.invalid/i | sh || echo repli",
            # Un pipefail qui ne vaut pas pour le tube.
            "x=1\nset -o pipefail\n"
            "curl -fsSL https://example.invalid/i | sh || echo repli",
            "f() { set -o pipefail; }\n"
            "curl -fsSL https://example.invalid/i | sh || echo repli",
            "(set -o pipefail; true); "
            "curl -fsSL https://example.invalid/i | sh || echo repli",
            "x=$(set -o pipefail; echo); "
            "curl -fsSL https://example.invalid/i | sh || echo repli",
            "sh -c 'set -o pipefail; true'; "
            "curl -fsSL https://example.invalid/i | sh || echo repli",
        ):
            self.assertEqual(1, len(replis_sans_effet(tube)), tube)

    def test_ce_qui_nest_pas_un_repli_passe(self):
        """« || true » n'attend rien du tube ; après « ; » ou une fin de
        ligne, le « || » porte sur une autre commande ; pipefail rend le
        repli effectif ; un tube hors de la condition d'un « if », ou un
        « if » sans « else », ne promet rien ; un téléchargement dans un
        fichier n'est pas un tube."""
        for correct in (
            "curl -fsSL https://example.invalid/i | sh || true",
            "timeout 9 sh -c 'curl -fsSL https://example.invalid/i | sh'"
            " </dev/null || true",
            "curl -fsSL https://example.invalid/i | sh && echo ok || true",
            "curl -fsSL https://example.invalid/i | sh; x || echo autre",
            "curl -fsSL https://example.invalid/i | sh\nx || echo autre",
            "set -euo pipefail\n"
            "curl -fsSL https://example.invalid/i | sh || echo repli",
            "#!/bin/bash\n# en-tête\n\nset -eu\nset -o pipefail\nx=1\n"
            "curl -fsSL https://example.invalid/i | sh || echo repli",
            "set -o pipefail; "
            "curl -fsSL https://example.invalid/i | sh || echo repli",
            "set -e -o pipefail; "
            "curl -fsSL https://example.invalid/i | sh || echo repli",
            "set -o errexit -o pipefail; "
            "curl -fsSL https://example.invalid/i | sh || echo repli",
            "set +o pipefail; set -o pipefail; "
            "curl -fsSL https://example.invalid/i | sh || echo repli",
            "timeout 9 sh -c 'set -o pipefail; "
            "curl -fsSL https://example.invalid/i | sh' </dev/null"
            " || echo repli",
            "set -o pipefail; if curl -fsSL https://example.invalid/i | sh;"
            " then echo ok; else echo repli; fi",
            "if curl -fsSL https://example.invalid/i | sh; then echo ok; fi",
            "if x; then curl -fsSL https://example.invalid/i | sh;"
            " else echo autre; fi",
            "if curl -fsSL https://example.invalid/i | sh; then"
            " if a; then b; else c; fi; fi",
            "if ! curl -fsSL https://example.invalid/i | sh; then true; fi",
            'if ! curl -fsSL https://example.invalid/i -o "$f"; then'
            " echo repli; fi",
        ):
            self.assertEqual([], replis_sans_effet(correct), correct)

    def test_un_pipefail_en_commentaire_ne_compte_pas(self):
        """Un commentaire qui parle de pipefail ne le pose pas."""
        src = (
            "# sans set -o pipefail, voir plus bas\n"
            "curl -fsSL https://example.invalid/i | sh || echo repli\n"
        )
        self.assertEqual(1, len(replis_sans_effet(src)))

    def test_le_motif_trouve_bien_les_tubes_existants(self):
        """Une expression qui ne trouve rien passerait tous les contrôles.

        Le dépôt en porte plusieurs : si ce compte tombe à zéro, c'est
        l'expression qu'il faut relire, pas le dépôt qu'il faut féliciter.
        """
        trouves = sum(len(TUBE.findall(src)) for _c, src in scripts())
        self.assertGreaterEqual(trouves, 3, f"seulement {trouves} trouvés")

    def test_les_commandes_de_lhote_sont_bien_lues(self):
        """Même garde pour les commandes composées par l'hôte : rtk,
        starship et l'agent sont trois tubes par bloc d'outils d'assistance.
        Si ce compte tombe, c'est la construction qui ne voit plus rien."""
        for agent in dev_tools.AGENTS:
            with self.subTest(agent=agent):
                cmd = TODO.__new__(TODO)._qemu_aidev_remote_cmd(agent)
                self.assertEqual(3, len(TUBE.findall(cmd)))


class TestLeReplisDePyenvSeDeclenche(unittest.TestCase):
    """lib_python_provider.sh pose pyenv par son installateur amont.

    Un téléchargement raté doit s'arrêter LÀ, en le disant : sinon la suite
    part sur « pyenv: command not found » puis sur un échec de compilation,
    deux messages qui accusent la mauvaise étape.

    Tout ce que la fonction appelle est remplacé dans un PATH qui ne porte
    rien d'autre : curl, pyenv, git, gcc sont des faux. Aucun réseau, aucune
    compilation, rien hors du répertoire temporaire du test.
    """

    LIB = RACINE / "script" / "install" / "lib_python_provider.sh"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.faux = self.dir / "bin"
        self.faux.mkdir()
        for outil in ("bash", "mktemp", "rm", "yes", "cat", "touch"):
            os.symlink(shutil.which(outil), self.faux / outil)
        self.trace = self.dir / "pyenv.trace"
        for nom in ("pyenv", "git", "gcc"):
            self._faux(nom, f'echo "{nom} $*" >> "{self.trace}"\nexit 1\n')

    def _faux(self, nom, corps):
        chemin = self.faux / nom
        chemin.write_text("#!/bin/bash\n" + corps, encoding="utf-8")
        chemin.chmod(0o755)

    def _installer(self):
        env = {
            "PATH": str(self.faux),
            "HOME": str(self.dir),
            "TMPDIR": str(self.dir),
            "PYENV_ROOT": str(self.dir / "pyenv"),
        }
        return subprocess.run(
            [
                str(self.faux / "bash"),
                "-c",
                f'source "{self.LIB}"; el_pyenv_install 3.12.10',
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_un_telechargement_rate_sarrete_et_le_dit(self):
        self._faux(
            "curl",
            'echo "curl: (22) The requested URL returned error: 504" >&2\n'
            "exit 22\n",
        )
        fini = self._installer()
        self.assertNotEqual(0, fini.returncode)
        self.assertIn("installateur pyenv impossible", fini.stderr)
        self.assertFalse(
            self.trace.exists(),
            "la suite a tourné sans pyenv : "
            + (self.trace.read_text() if self.trace.exists() else ""),
        )

    def test_un_installateur_qui_echoue_sarrete_et_le_dit(self):
        """Le fichier téléchargé est bien celui qui s'exécute, et son échec
        arrête la fonction avant toute compilation."""
        marque = self.dir / "installateur.a.tourne"
        self._faux(
            "curl",
            # curl … -o FICHIER URL : on écrit l'installateur dans FICHIER.
            'while [ "$#" -gt 0 ]; do [ "$1" = -o ] && dest="$2"; shift;'
            " done\n"
            f"printf 'touch \"%s\"\\nexit 3\\n' '{marque}' > \"$dest\"\n",
        )
        fini = self._installer()
        self.assertNotEqual(0, fini.returncode)
        self.assertTrue(marque.exists(), fini.stderr)
        self.assertIn("installateur de pyenv a echoue", fini.stderr)
        self.assertFalse(self.trace.exists())


class TestLeReplisDeMiseSeDeclenche(unittest.TestCase):
    """La pose de mise dans une VM, composée par l'hôte.

    Deux échecs, deux messages, et aucun ne fait tomber « set -e » : pyenv
    prend le relais. La commande tourne pour de vrai dans un PATH où curl et
    sudo sont faux — et où mise n'est PAS, pour que la pose soit tentée même
    sur un hôte qui l'a.
    """

    def setUp(self):
        from unittest import mock

        with mock.patch("script.todo.qemu_install.t", lambda k: k):
            self.cmd = TODO.__new__(TODO)._qemu_mise_remote_cmd("mise")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.faux = self.dir / "bin"
        self.faux.mkdir()
        for outil in ("sh", "bash", "env", "mktemp", "rm", "cat", "touch"):
            os.symlink(shutil.which(outil), self.faux / outil)
        self.marque = self.dir / "installateur.a.tourne"
        self.trace = self.dir / "sudo.trace"
        self._faux(
            "curl",
            'if [ -n "$ECHEC" ]; then exit 22; fi\n'
            'while [ "$#" -gt 0 ]; do [ "$1" = -o ] && dest="$2"; shift;'
            " done\n"
            f"printf 'touch \"%s\"\\nexit ${{RC_INSTALL:-0}}\\n' "
            f"'{self.marque}' > \"$dest\"\n",
        )
        # Trace, puis exécute SANS privilège ; « env » lit les
        # « VAR=valeur » de tête comme le fait sudo.
        self._faux("sudo", f'echo "$*" >> "{self.trace}"\nexec env "$@"\n')

    def _faux(self, nom, corps):
        chemin = self.faux / nom
        chemin.write_text("#!/bin/sh\n" + corps, encoding="utf-8")
        chemin.chmod(0o755)

    def _lancer(self, **env_en_plus):
        env = {
            "PATH": str(self.faux),
            "HOME": str(self.dir),
            "TMPDIR": str(self.dir),
            **env_en_plus,
        }
        script = (
            "set -e\n" + self.cmd + '\necho "PROVIDER=$EL_PYTHON_PROVIDER"'
        )
        return subprocess.run(
            [str(self.faux / "bash"), "-c", script],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_un_telechargement_rate_le_dit_sans_rien_lancer(self):
        fini = self._lancer(ECHEC="1")
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertIn("⚠ mise download impossible", fini.stdout)
        self.assertIn("PROVIDER=auto", fini.stdout)
        self.assertFalse(self.trace.exists(), "sudo lancé sans installateur")

    def test_un_installateur_qui_echoue_le_dit(self):
        fini = self._lancer(RC_INSTALL="5")
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertTrue(self.marque.exists())
        self.assertIn("⚠ mise installer failed", fini.stdout)
        self.assertIn("PROVIDER=auto", fini.stdout)
        self.assertIn(
            "MISE_INSTALL_PATH=/usr/local/bin/mise sh", self.trace.read_text()
        )

    def test_une_pose_reussie_se_tait(self):
        fini = self._lancer()
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertTrue(self.marque.exists())
        self.assertNotIn("⚠", fini.stdout)
        self.assertIn("PROVIDER=auto", fini.stdout)

    def test_sans_mktemp_rien_nest_telecharge_ni_lance(self):
        """Aucun nom de repli ne remplace mktemp : root exécuterait ce qu'un
        autre compte aurait pu déposer d'avance sous ce nom."""
        # Le lien vers le vrai mktemp est retiré AVANT d'écrire le faux :
        # écrire à travers le lien viserait le binaire de l'hôte.
        (self.faux / "mktemp").unlink()
        self._faux("mktemp", "exit 1\n")
        fini = self._lancer()
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertIn("⚠ mise download impossible", fini.stdout)
        self.assertIn("PROVIDER=auto", fini.stdout)
        self.assertFalse(self.marque.exists(), "installateur lancé")
        self.assertFalse(self.trace.exists(), "sudo lancé sans installateur")

    def test_aucun_chemin_fixe_dans_tmp(self):
        """Le fichier que root exécute ne vient que de mktemp."""
        self.assertNotIn("/tmp/", self.cmd)
        self.assertIn("f=$(mktemp 2>/dev/null)", self.cmd)


if __name__ == "__main__":
    unittest.main()
