#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que le listage des sessions Claude Code doit voir, et ne pas lire.

Deux frontières se jouent ici, et les deux sont vérifiables sans toucher à une
session réelle.

**Un pid ne prouve pas qu'une session vit.** Les pids se recyclent, et une
entrée laissée par un arrêt brutal désignerait alors le processus de quelqu'un
d'autre — donc proposerait d'écrire dedans. La vivacité exige le pid ET le
moment de démarrage du processus.

**Le contenu d'une transcription ne sort pas.** Le système ferme ce répertoire
à son propriétaire seul ; le listage n'y lit que deux champs de STRUCTURE, et
un titre ou un message ne doit atteindre aucun affichage. La fixture porte
donc un marqueur dans un message, et les tests affirment qu'il ne ressort
nulle part.

Le répertoire de travail se lit dans la transcription et jamais dans le nom du
répertoire qui la contient : la transformation qui produit ce nom change les
séparateurs, les points et les tirets bas en tirets, donc elle ne s'inverse
pas et confondrait deux dépôts voisins. La fixture le prouve avec un nom qui
porte les trois.

Aucun test ne lance `claude`, ne lit le registre de la machine, ni n'ouvre une
transcription réelle : le lanceur, le registre, l'état des processus et la
lecture d'en-tête sont tous injectés.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from script.todo.assistant import claude_sessions as CS  # noqa: E402

# Des identifiants et des pids inventés. Les répertoires portent un point, un
# tiret bas et un séparateur, précisément ce que la transformation du nom de
# répertoire écrase.
VIVANTE = "aaaaaaaa-1111-4111-8111-111111111111"
DORMANTE = "bbbbbbbb-2222-4222-8222-222222222222"
PID = 4242
DEMARRAGE = "987654"
CHEMIN = "/opt/atelier/projet.essai_v2"

# Ce que le listage de l'outil annonce.
AGENTS = json.dumps(
    [
        {
            "pid": PID,
            "cwd": CHEMIN,
            "kind": "interactive",
            "startedAt": 0,
            "sessionId": VIVANTE,
            "name": "atelier",
            "status": "busy",
        }
    ]
)

# Ce que le registre ajoute : la version, et le moment de démarrage qui
# distingue un pid recyclé d'un pid vivant.
REGISTRE = [
    {
        "pid": PID,
        "sessionId": VIVANTE,
        "cwd": CHEMIN,
        "procStart": DEMARRAGE,
        "version": "9.9.999",
    }
]


# Un extrait de « /proc/<pid>/stat ». Le nom du programme est entre
# parenthèses et peut contenir des espaces : c'est ce qui interdit de compter
# les champs depuis le début de la ligne.
def stat_avec(demarrage):
    # L'état est le champ 3 et le démarrage le champ 22 : entre les deux il y
    # a donc DIX-HUIT champs de remplissage, et non dix-neuf. Un de trop
    # déplacerait le démarrage au champ 23, et le test passerait ou
    # échouerait pour une raison qui n'est pas la sienne.
    champs = [str(n) for n in range(4, 22)]
    return f"{PID} (claude code) S " + " ".join(champs) + f" {demarrage} 0 0"


# Un marqueur posé dans un MESSAGE. Il ne doit ressortir d'aucun champ : le
# listage ne lit que la structure.
SECRET = "marqueur-de-message-qui-ne-doit-pas-sortir"

TRANSCRIPT = [
    json.dumps({"type": "custom-title", "customTitle": SECRET}) + "\n",
    json.dumps(
        {
            "type": "user",
            "cwd": CHEMIN,
            "gitBranch": "dev/essai",
            "message": {"role": "user", "content": SECRET},
        }
    )
    + "\n",
]


class LaVivacite(unittest.TestCase):
    """Un pid vivant ne suffit pas : le démarrage tranche."""

    def test_un_pid_absent_n_est_pas_vivant(self):
        self.assertFalse(CS.is_live(PID, DEMARRAGE, read_stat=lambda pid: ""))

    def test_un_pid_vivant_au_bon_demarrage_est_vivant(self):
        self.assertTrue(
            CS.is_live(
                PID, DEMARRAGE, read_stat=lambda pid: stat_avec(DEMARRAGE)
            )
        )

    def test_un_pid_recycle_n_est_pas_vivant(self):
        """Le cas que le pid seul laisserait passer : le processus existe,
        mais ce n'est plus celui que le registre y attachait."""
        self.assertFalse(
            CS.is_live(
                PID, DEMARRAGE, read_stat=lambda pid: stat_avec("111111")
            )
        )

    def test_sans_demarrage_connu_la_presence_du_pid_suffit(self):
        """Le prétendre mort serait plus faux que de le croire vivant : le
        listage de l'outil affirme déjà qu'il tourne."""
        self.assertTrue(
            CS.is_live(PID, None, read_stat=lambda pid: stat_avec("0"))
        )

    def test_un_nom_de_programme_a_espaces_ne_decale_pas_le_champ(self):
        """Le nom est entre parenthèses et peut contenir des espaces, ce qui
        interdit de compter les champs depuis le début de la ligne."""
        ligne = f"{PID} (un nom avec des espaces) S " + " ".join(
            str(n) for n in range(3, 22)
        )
        self.assertTrue(CS.is_live(PID, "21", read_stat=lambda pid: ligne))


class LeListageDesVivantes(unittest.TestCase):
    """Ce que le registre et le listage de l'outil rendent ensemble."""

    def _live(self, agents=AGENTS, registre=None, demarrage=DEMARRAGE):
        return CS.live(
            run=lambda argv: agents,
            read_registry=lambda: (REGISTRE if registre is None else registre),
            read_stat=lambda pid: stat_avec(demarrage),
        )

    def test_une_session_vivante_se_lit_dans_le_registre(self):
        sessions = self._live()
        self.assertEqual(len(sessions), 1)
        session = sessions[0]
        self.assertEqual(session.session_id, VIVANTE)
        self.assertEqual(session.pid, PID)
        self.assertEqual(session.kind, "interactive")
        self.assertEqual(session.status, "busy")
        self.assertEqual(session.version, "9.9.999")
        self.assertTrue(session.live)

    def test_une_session_occupee_est_etiquetee_avant_d_etre_proposee(self):
        """L'état décide du risque : une session occupée acceptera quand même
        une écriture, et se mettra en concurrence avec elle-même."""
        self.assertEqual(self._live()[0].status, "busy")

    def test_un_registre_absent_ne_cache_pas_la_session(self):
        """Sans entrée de registre il n'y a ni version ni démarrage, mais le
        listage de l'outil affirme la session : elle reste."""
        session = self._live(registre=[])[0]
        self.assertEqual(session.session_id, VIVANTE)
        self.assertEqual(session.version, "")
        self.assertTrue(session.live)

    def test_un_outil_absent_rend_une_liste_vide(self):
        self.assertEqual(self._live(agents=""), [])

    def test_un_listage_illisible_rend_une_liste_vide(self):
        self.assertEqual(self._live(agents="pas du json"), [])

    def test_un_listage_qui_n_est_pas_une_liste_rend_une_liste_vide(self):
        self.assertEqual(self._live(agents='{"pid": 1}'), [])

    def test_le_pid_detenteur_ne_se_donne_que_pour_une_vivante(self):
        vivante = self._live()[0]
        self.assertEqual(CS.held_by(vivante), str(PID))
        dormante = CS.Session(session_id=DORMANTE, pid=PID, live=False)
        self.assertEqual(CS.held_by(dormante), "")


class LesTranscriptions(unittest.TestCase):
    """Deux champs de structure, et rien d'autre."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.racine = Path(self.tmp.name)
        # Le nom de répertoire est la transformation À PERTE du chemin : le
        # séparateur, le point et le tiret bas y sont tous devenus des tirets.
        projet = self.racine / "-opt-atelier-projet-essai-v2"
        projet.mkdir()
        (projet / f"{DORMANTE}.jsonl").write_text("".join(TRANSCRIPT))

    def _resumable(self):
        return CS.resumable(
            projects_root=self.racine, read_head=lambda chemin: TRANSCRIPT
        )

    def test_le_repertoire_vient_du_transcript_pas_du_slug(self):
        """Le nom du répertoire a perdu le point, le tiret bas et les
        séparateurs ; seul le transcript porte le chemin exact."""
        session = self._resumable()[0]
        self.assertEqual(session.cwd, CHEMIN)
        self.assertEqual(session.branch, "dev/essai")

    def test_aucun_contenu_de_message_ne_ressort(self):
        """La frontière que le système a posée sur le répertoire : le listage
        lit la structure, jamais ce qui a été dit."""
        sessions = self._resumable()
        self.assertTrue(sessions, "aucune session lue")
        for session in sessions:
            for valeur in vars(session).values():
                self.assertNotIn(SECRET, str(valeur))

    def test_aucun_titre_de_transcript_n_est_affiche(self):
        vue = CS.displayable(self._resumable()[0])
        for valeur in vue.values():
            self.assertNotIn(SECRET, str(valeur))

    def test_une_transcription_n_est_pas_chargee_en_entier(self):
        """Une transcription se compte en mégaoctets : la lecture s'arrête en
        tête, et le nombre de lignes lues est borné."""
        lignes = CS._lire_en_tete(next(self.racine.glob("*/*.jsonl")))
        self.assertLessEqual(len(lignes), CS.LIGNES_EN_TETE)

    def test_une_ligne_illisible_n_arrete_pas_la_lecture(self):
        abimee = ["{ pas du json\n"] + TRANSCRIPT
        faits = CS._structure(abimee)
        self.assertEqual(faits.get("cwd"), CHEMIN)

    def test_une_racine_absente_rend_une_liste_vide(self):
        self.assertEqual(
            CS.resumable(projects_root=self.racine / "nulle-part"), []
        )


class LaFlotte(unittest.TestCase):
    """Les deux listages se recouvrent : la fusion garde la vivante."""

    def _fleet(self):
        return CS.fleet(
            run=lambda argv: AGENTS,
            read_registry=lambda: REGISTRE,
            read_stat=lambda pid: stat_avec(DEMARRAGE),
            projects_root="/nulle-part",
            read_head=lambda chemin: TRANSCRIPT,
        )

    def test_une_session_ne_parait_pas_deux_fois(self):
        sessions = CS.fleet(
            run=lambda argv: AGENTS,
            read_registry=lambda: REGISTRE,
            read_stat=lambda pid: stat_avec(DEMARRAGE),
            projects_root="/nulle-part",
        )
        identifiants = [session.session_id for session in sessions]
        self.assertEqual(len(identifiants), len(set(identifiants)))

    def test_les_vivantes_ouvrent_la_liste(self):
        """Ce sont celles où écrire coûte quelque chose."""
        sessions = self._fleet()
        self.assertTrue(sessions)
        vivantes = [s.live for s in sessions]
        self.assertEqual(vivantes, sorted(vivantes, reverse=True))


class LAffichage(unittest.TestCase):
    """Ce qui a le droit de paraître, et sous quelle forme."""

    SESSION = CS.Session(
        session_id=VIVANTE,
        pid=PID,
        kind="interactive",
        status="idle",
        cwd=CHEMIN,
        name="atelier",
        version="9.9.999",
        branch="dev/essai",
        live=True,
    )

    def test_l_identifiant_est_reduit_a_son_prefixe(self):
        self.assertEqual(CS.displayable(self.SESSION)["id"], VIVANTE[:8])

    def test_le_repertoire_est_reduit_a_son_dernier_segment(self):
        """Un chemin complet porte un nom de compte, que le détecteur du
        dépôt compte parmi les données identifiantes."""
        vue = CS.displayable(self.SESSION)
        self.assertEqual(vue["dir"], "projet.essai_v2")
        self.assertNotIn("/", vue["dir"])

    def test_un_repertoire_vide_ne_devient_pas_un_point(self):
        vide = CS.Session(session_id=VIVANTE, cwd="")
        self.assertEqual(CS.displayable(vide)["dir"], "")


class LaFrontiere(unittest.TestCase):
    """Le paquet doit rester importable sans le CLI."""

    def test_le_listage_n_importe_pas_todo(self):
        self.assertNotIn("script.todo.todo", sys.modules)


if __name__ == "__main__":
    unittest.main()
