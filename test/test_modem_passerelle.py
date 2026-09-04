#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'agent passerelle, éprouvé sans modem, sans réseau et sans Odoo.

Ce qui est vérifié ici n'est pas « le code s'exécute » mais les trois
invariants dont dépend l'absence de silence : la séquence des rapports
survit à un redémarrage, un travail déjà envoyé se re-rapporte au lieu
d'être ignoré, et tout appel réclamé reçoit une réponse.
"""
import hashlib
import hmac
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from script.todo.modem import passerelle as pa  # noqa: E402

SECRET = "secret-de-test-non-reel"
APPAREIL = "appareil-de-test"


class FauxModem:
    """Un modem qui obéit et qui se souvient de ce qu'on lui a demandé."""

    def __init__(self, pret=True, echoue=False, entrants=None):
        self._pret = pret
        self.echoue = echoue
        self.envoyes = []
        self._entrants = list(entrants or [])
        self.oublies = []

    def pret(self):
        return (self._pret, "" if self._pret else "SIM absente.")

    def envoyer(self, numero, texte):
        self.envoyes.append((numero, texte))
        if self.echoue:
            return False, "GATEWAY_MODEM_ERROR", "le modem a refuse"
        return True, "", ""

    def entrants(self):
        return list(self._entrants)

    def oublier(self, interne):
        self.oublies.append(interne)
        return True


class FauxServeur:
    """Répond aux trois routes et garde ce qu'on lui a posté."""

    def __init__(self, groupes=None, appels=None, **reglages):
        self.groupes = groupes if groupes is not None else []
        self.appels = appels or []
        self.reglages = reglages
        self.recu = []
        self.statut = 200
        #: Route sur laquelle tomber en panne. None = toutes.
        self.route_en_panne = None

    def __call__(self, url, corps, entetes):
        charge = json.loads(corps.decode("utf-8"))
        self.recu.append((url, charge, entetes, corps))
        en_panne = self.statut != 200 and (
            self.route_en_panne is None or url.endswith(self.route_en_panne)
        )
        if en_panne:
            return self.statut, b'{"ok": false}'
        if url.endswith(pa.ROUTE_POLL):
            reponse = {
                "ok": True, "groups": self.groupes, "calls": self.appels,
                "poll_interval": self.reglages.get("poll_interval", 60),
                "segments_per_minute": self.reglages.get("segments_per_minute", 24),
            }
            # Le serveur ne repropose un travail que tant qu'il ne l'a pas vu
            # confirme : une fois offert, on n'offre plus, sauf mise en scene.
            if not self.reglages.get("repeter"):
                self.groupes = []
                self.appels = []
        else:
            reponse = {"ok": True}
        return 200, json.dumps(reponse).encode("utf-8")

    def postes(self, route):
        return [c for u, c, _e, _b in self.recu if u.endswith(route)]


class Horloge:
    def __init__(self, debut=1_700_000_000.0):
        self.t = debut

    def __call__(self):
        return self.t

    def avancer(self, secondes):
        self.t += secondes


def _travail(uuid, numero="+15145550142", texte="Cours annule"):
    return {"body": texte, "to": [{"u": uuid, "n": numero}]}


class Montage(unittest.TestCase):
    def monter(self, serveur=None, modem=None, fichier=None):
        self.horloge = Horloge()
        self.serveur = serveur or FauxServeur()
        self.modem = modem or FauxModem()
        if fichier is None:
            fichier = os.path.join(self.dossier.name, "etat.json")
        self.fichier = fichier
        transport = pa.Transport(
            "https://exemple.invalide", SECRET, APPAREIL,
            ouvrir=self.serveur, horloge=self.horloge,
        )
        return pa.Passerelle(
            transport, self.modem, pa.Etat(fichier),
            horloge=self.horloge, dormir=lambda _s: None,
        )

    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self.dossier.cleanup)


class TestSignature(Montage):
    """La signature porte sur les octets transmis, pas sur la structure."""

    def test_la_signature_couvre_le_corps_reellement_envoye(self):
        agent = self.monter()
        agent.cycle()
        _url, _charge, entetes, corps = self.serveur.recu[0]
        attendu = hmac.new(
            SECRET.encode("utf-8"), corps, hashlib.sha256
        ).hexdigest()
        self.assertEqual(entetes[pa.ENTETE_SIGNATURE], "sha256=" + attendu)

    def test_un_octet_change_invalide_la_signature(self):
        corps = b'{"a":1}'
        self.assertNotEqual(pa.signer(SECRET, corps), pa.signer(SECRET, b'{"a":2}'))

    def test_chaque_message_porte_appareil_horodatage_et_nonce_unique(self):
        agent = self.monter(FauxServeur(groupes=[_travail("u1")]))
        agent.cycle()
        charges = [c for _u, c, _e, _b in self.serveur.recu]
        self.assertGreaterEqual(len(charges), 2)
        for charge in charges:
            self.assertEqual(charge["device"], APPAREIL)
            self.assertIsInstance(charge["ts"], int)
        nonces = [c["nonce"] for c in charges]
        self.assertEqual(len(nonces), len(set(nonces)),
                         "un nonce rejoue serait refuse par le serveur")


class TestSegments(unittest.TestCase):
    """Sous-estimer envoie trop vite ; surestimer ralentit une alerte."""

    def test_gsm7_tient_dans_un_segment_jusqua_160(self):
        self.assertEqual(pa.segments("a" * 160), 1)
        self.assertEqual(pa.segments("a" * 161), 2)

    def test_la_cedille_minuscule_fait_basculer_en_ucs2(self):
        # « ç » n'est pas dans l'alphabet GSM de base, « Ç » y est.
        self.assertEqual(pa.segments("ç" * 70), 1)
        self.assertEqual(pa.segments("ç" * 71), 2)

    def test_texte_vide(self):
        self.assertEqual(pa.segments(""), 0)


class TestCycle(Montage):
    def test_un_travail_offert_part_et_se_rapporte(self):
        agent = self.monter(FauxServeur(groupes=[_travail("u1")]))
        compte = agent.cycle()

        self.assertEqual(compte["recus"], 1)
        self.assertEqual(self.modem.envoyes, [("+15145550142", "Cours annule")])
        evenements = self.serveur.postes(pa.ROUTE_RAPPORT)[0]["events"]
        self.assertEqual(len(evenements), 1)
        self.assertEqual(evenements[0]["uuid"], "u1")
        self.assertEqual(evenements[0]["state"], "delivered")
        self.assertGreaterEqual(evenements[0]["seq"], 1)

    def test_un_refus_du_modem_se_rapporte_en_echec(self):
        agent = self.monter(FauxServeur(groupes=[_travail("u1")]),
                            FauxModem(echoue=True))
        agent.cycle()
        evenement = self.serveur.postes(pa.ROUTE_RAPPORT)[0]["events"][0]
        self.assertEqual(evenement["state"], "failed")
        self.assertEqual(evenement["code"], "GATEWAY_MODEM_ERROR")
        self.assertIn("refuse", evenement["reason"])

    def test_linterrogation_precede_tout_le_reste(self):
        """Elle vaut signal de vie : un modem fache ne doit pas la retarder."""
        agent = self.monter(FauxServeur(groupes=[_travail("u1")]))
        agent.cycle()
        self.assertTrue(self.serveur.recu[0][0].endswith(pa.ROUTE_POLL))

    def test_le_serveur_pilote_le_rythme(self):
        agent = self.monter(FauxServeur(poll_interval=15, segments_per_minute=9))
        agent.cycle()
        self.assertEqual(agent.intervalle, 15)
        self.assertEqual(agent.segments_par_minute, 9)


class TestSequence(Montage):
    def test_la_sequence_survit_a_un_redemarrage(self):
        """Un compteur en memoire ferait rejeter tous les rapports d'apres."""
        agent = self.monter(FauxServeur(groupes=[_travail("u1")]))
        agent.cycle()
        premier = self.serveur.postes(pa.ROUTE_RAPPORT)[0]["events"][0]["seq"]

        agent = self.monter(FauxServeur(groupes=[_travail("u2")]),
                            fichier=self.fichier)
        agent.cycle()
        second = self.serveur.postes(pa.ROUTE_RAPPORT)[0]["events"][0]["seq"]
        self.assertGreater(second, premier)

    def test_les_sequences_dun_meme_lot_sont_croissantes(self):
        groupes = [{"body": "Cours annule",
                    "to": [{"u": "u1", "n": "+15145550142"},
                           {"u": "u2", "n": "+15145550143"}]}]
        agent = self.monter(FauxServeur(groupes=groupes))
        agent.cycle()
        seqs = [e["seq"] for e in self.serveur.postes(pa.ROUTE_RAPPORT)[0]["events"]]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(set(seqs)), len(seqs))


class TestRedites(Montage):
    def test_un_travail_deja_envoye_se_re_rapporte_sans_repartir(self):
        """Le serveur le repropose : son rapport s'etait perdu."""
        agent = self.monter(FauxServeur(groupes=[_travail("u1")]))
        agent.cycle()
        self.assertEqual(len(self.modem.envoyes), 1)

        self.serveur.groupes = [_travail("u1")]
        agent.cycle()
        self.assertEqual(len(self.modem.envoyes), 1, "le SMS est reparti deux fois")
        dernier = self.serveur.postes(pa.ROUTE_RAPPORT)[-1]["events"]
        self.assertEqual([e["uuid"] for e in dernier], ["u1"])
        self.assertEqual(dernier[0]["state"], "delivered")

    def test_un_travail_encore_en_attente_ne_se_dedouble_pas(self):
        agent = self.monter(
            FauxServeur(groupes=[_travail("u1")]), FauxModem(pret=False)
        )
        agent.cycle()
        self.serveur.groupes = [_travail("u1")]
        agent.cycle()
        self.assertEqual(len(agent.etat.travaux), 1)


class TestInterruption(Montage):
    """Ce qui se passe quand l'agent meurt entre la remise et la trace."""

    def test_un_envoi_interrompu_ne_repart_pas_et_se_dit_incertain(self):
        class ModemQuiMeurt(FauxModem):
            def envoyer(self, numero, texte):
                raise KeyboardInterrupt

        agent = self.monter(FauxServeur(groupes=[_travail("u1")]),
                            ModemQuiMeurt())
        with self.assertRaises(KeyboardInterrupt):
            agent.cycle()
        self.assertEqual(agent.etat.travaux["u1"]["etat"], "en_cours")

        # Un agent relance reprend le meme fichier d'etat.
        agent = self.monter(FauxServeur(), fichier=self.fichier)
        agent.cycle()
        self.assertEqual(self.modem.envoyes, [], "le SMS serait parti deux fois")
        evenement = self.serveur.postes(pa.ROUTE_RAPPORT)[0]["events"][0]
        self.assertEqual(evenement["uuid"], "u1")
        self.assertEqual(evenement["state"], "submitted",
                         "ni « delivered » ni « failed » : on ne sait pas")

    def test_un_incertain_repropose_redit_la_meme_chose(self):
        agent = self.monter(FauxServeur())
        agent.etat.travaux["u1"] = {
            "numero": "+15145550142", "texte": "Cours annule",
            "etat": "incertain", "recu_a": self.horloge(), "fini_a": self.horloge(),
        }
        self.serveur.groupes = [_travail("u1")]
        agent.cycle()
        evenement = self.serveur.postes(pa.ROUTE_RAPPORT)[0]["events"][0]
        self.assertEqual(evenement["state"], "submitted")
        self.assertEqual(self.modem.envoyes, [])


class TestModemAbsent(Montage):
    def test_rien_ne_part_et_rien_nest_declare_perdu(self):
        """L'echec est TERMINAL cote serveur : le modem peut encore revenir."""
        agent = self.monter(FauxServeur(groupes=[_travail("u1")]),
                            FauxModem(pret=False))
        agent.cycle()
        self.assertEqual(self.modem.envoyes, [])
        self.assertEqual(self.serveur.postes(pa.ROUTE_RAPPORT), [])
        self.assertEqual(agent.etat.travaux["u1"]["etat"], "attente")

    def test_letat_annonce_au_serveur_dit_la_verite(self):
        agent = self.monter(modem=FauxModem(pret=False))
        agent.cycle()
        statut = self.serveur.postes(pa.ROUTE_POLL)[0]["status"]
        self.assertFalse(statut["sms_permission"])
        self.assertFalse(statut["sim_ready"])

    def test_letat_declare_le_materiel_et_rien_dinvente(self):
        """Le serveur juge alors sur les criteres du modem, pas d'un telephone."""
        agent = self.monter()
        agent.cycle()
        statut = self.serveur.postes(pa.ROUTE_POLL)[0]["status"]
        self.assertEqual(statut["kind"], "modem")
        self.assertEqual(statut["app_version"], pa.VERSION)
        for invente in ("battery", "charging", "doze_exempt", "exact_alarms"):
            self.assertNotIn(invente, statut,
                             "une valeur inventee finit par etre lue comme une mesure")


class TestCadence(Montage):
    def test_le_budget_de_segments_est_respecte(self):
        groupes = [{"body": "court", "to": [
            {"u": "u1", "n": "+15145550142"},
            {"u": "u2", "n": "+15145550143"},
            {"u": "u3", "n": "+15145550144"},
        ]}]
        agent = self.monter(FauxServeur(groupes=groupes, segments_per_minute=2))
        agent.cycle()
        self.assertEqual(len(self.modem.envoyes), 2)

        # La fenetre d'une minute passee, le reste part.
        self.horloge.avancer(61)
        agent.cycle()
        self.assertEqual(len(self.modem.envoyes), 3)


class TestAppels(Montage):
    def test_tout_appel_reclame_recoit_une_reponse(self):
        """Sans cron d'expiration cote module, un silence dure pour toujours."""
        agent = self.monter(FauxServeur(
            appels=[{"uuid": "a1", "number": "+15145550142"}]
        ))
        agent.cycle()
        appels = self.serveur.postes(pa.ROUTE_RAPPORT)[0]["calls"]
        self.assertEqual(len(appels), 1)
        self.assertEqual(appels[0]["uuid"], "a1")
        self.assertEqual(appels[0]["state"], "failed")
        self.assertTrue(appels[0]["reason"])
        self.assertGreaterEqual(appels[0]["seq"], 1)

    def test_un_appel_place_se_rapporte_connecte(self):
        class Telephone:
            def placer(self, numero):
                return True, ""

        agent = self.monter(FauxServeur(
            appels=[{"uuid": "a1", "number": "+15145550142"}]
        ))
        agent.appels = Telephone()
        agent.cycle()
        appels = self.serveur.postes(pa.ROUTE_RAPPORT)[0]["calls"]
        self.assertEqual(appels[0]["state"], "connected")


class TestEntrants(Montage):
    def _message(self, texte="STOP", numero="+15145550142", horodatage="2026-09-01T10:00:00-0400"):
        return {
            "id": pa._identifiant(
                {"numero": numero, "texte": texte, "horodatage": horodatage}
            ),
            "interne": "3", "from": numero, "body": texte,
            "at": pa._epoque(horodatage),
        }

    def test_un_entrant_remonte_puis_seffacce_du_modem(self):
        modem = FauxModem(entrants=[self._message()])
        agent = self.monter(modem=modem)
        compte = agent.cycle()

        self.assertEqual(compte["entrants"], 1)
        messages = self.serveur.postes(pa.ROUTE_ENTRANTS)[0]["messages"]
        self.assertEqual(messages[0]["body"], "STOP")
        self.assertEqual(modem.oublies, ["3"], "la memoire du modem se remplirait")

    def test_leffacement_ne_precede_jamais_lenregistrement(self):
        """Seule la route des entrants tombe : le reste du cycle doit aboutir."""
        modem = FauxModem(entrants=[self._message()])
        agent = self.monter(modem=modem)
        self.serveur.statut = 500
        self.serveur.route_en_panne = pa.ROUTE_ENTRANTS
        with self.assertRaises(pa.ErreurTransport):
            agent.cycle()
        self.assertTrue(self.serveur.postes(pa.ROUTE_POLL),
                        "le cycle n'est meme pas alle jusqu'aux entrants")
        self.assertEqual(modem.oublies, [],
                         "un STOP efface avant d'etre enregistre est perdu")
        # Rien n'est retenu comme vu : le message doit repartir au tour suivant.
        self.assertEqual(agent.etat.entrants_vus, [])

    def test_un_entrant_deja_vu_ne_remonte_pas_deux_fois(self):
        modem = FauxModem(entrants=[self._message()])
        agent = self.monter(modem=modem)
        agent.cycle()
        agent.cycle()
        self.assertEqual(len(self.serveur.postes(pa.ROUTE_ENTRANTS)), 1)

    def test_lidentifiant_vient_du_contenu_et_non_de_lindex(self):
        """ModemManager reutilise ses index : le serveur jetterait le nouveau."""
        premier = pa._identifiant({"numero": "+15145550142", "texte": "STOP",
                                   "horodatage": "2026-09-01T10:00:00-0400"})
        second = pa._identifiant({"numero": "+15145550142", "texte": "OUI",
                                  "horodatage": "2026-09-01T10:05:00-0400"})
        self.assertNotEqual(premier, second)


class TestModemManager(unittest.TestCase):
    """Le seul morceau qui parle vraiment a ModemManager."""

    class FauxDevice:
        def __init__(self, index="0", etats=None):
            self.index = index
            self.etats = etats or {}
            self.appels = 0

        def mmcli_present(self):
            return True

        def premier_modem(self):
            self.appels += 1
            return self.index

        def etat(self, index):
            return self.etats.get(index, {})

    def test_un_modem_muet_fait_oublier_son_index(self):
        """ModemManager renumerote un appareil rebranche."""
        device = self.FauxDevice(index="0", etats={"1": {"etat": "registered"}})
        modem = pa.ModemManagerSMS(device=device, messaging=object())
        self.assertFalse(modem.pret()[0])

        # L'appareil revient sous un autre index : on doit le retrouver.
        device.index = "1"
        self.assertTrue(modem.pret()[0])
        self.assertEqual(device.appels, 2)

    def test_un_modem_non_enregistre_nest_pas_pret(self):
        device = self.FauxDevice(etats={"0": {"etat": "searching"}})
        modem = pa.ModemManagerSMS(device=device, messaging=object())
        pret, motif = modem.pret()
        self.assertFalse(pret)
        self.assertIn("searching", motif)


class TestPannes(Montage):
    def test_un_serveur_a_terre_leve_plutot_que_de_mentir(self):
        agent = self.monter()
        self.serveur.statut = 503
        with self.assertRaises(pa.ErreurTransport):
            agent.cycle()

    def test_la_boucle_encaisse_la_panne_et_reessaie(self):
        agent = self.monter()
        self.serveur.statut = 503
        agent.boucle(tours=3, journal=lambda _m: None)
        self.assertEqual(len(self.serveur.postes(pa.ROUTE_POLL)), 3)


class TestFichierDEtat(Montage):
    def test_il_nest_lisible_que_par_son_proprietaire(self):
        """Il porte des numeros et le texte des messages."""
        agent = self.monter(FauxServeur(groupes=[_travail("u1")]))
        agent.cycle()
        self.assertEqual(os.stat(self.fichier).st_mode & 0o777, 0o600)

    def test_un_fichier_illisible_ne_bloque_pas_le_demarrage(self):
        chemin = os.path.join(self.dossier.name, "casse.json")
        with open(chemin, "w", encoding="utf-8") as fichier:
            fichier.write("{ceci n'est pas du JSON")
        etat = pa.Etat(chemin)
        self.assertEqual(etat.sequence, 0)
        self.assertEqual(etat.travaux, {})


if __name__ == "__main__":
    unittest.main()
