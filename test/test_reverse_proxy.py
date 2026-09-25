#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le mandataire de développement devant Odoo, éprouvé sur de vrais sockets.

Chaque amont est un faux Odoo local qui note ce qu'il reçoit : le routage,
les en-têtes réécrits et le relais se vérifient sur les octets, pas sur une
maquette de la bibliothèque réseau.
"""

import asyncio
import gzip
import hashlib
import os
import shutil
import ssl
import tempfile
import unittest
from unittest.mock import patch

from script.reverse_proxy import main as rp


async def lire_tete(reader):
    """La tête d'un message HTTP, jusqu'à la ligne vide comprise."""
    return await reader.readuntil(b"\r\n\r\n")


def entetes(tete):
    """Les en-têtes d'une tête brute, en liste (nom en minuscules, valeur)."""
    lignes = tete.decode("latin-1").split("\r\n")[1:]
    out = []
    for ligne in lignes:
        if ":" in ligne:
            nom, valeur = ligne.split(":", 1)
            out.append((nom.strip().lower(), valeur.strip()))
    return out


class FauxOdoo:
    """Un amont qui retient chaque tête reçue et répond par `repondre`."""

    def __init__(self, repondre):
        self.repondre = repondre
        self.tetes = []
        self.serveur = None
        self.port = None

    async def _servir(self, reader, writer):
        try:
            tete = await lire_tete(reader)
            self.tetes.append(tete)
            await self.repondre(tete, reader, writer)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    async def demarrer(self):
        self.serveur = await asyncio.start_server(self._servir, "127.0.0.1", 0)
        self.port = self.serveur.sockets[0].getsockname()[1]
        return self

    async def arreter(self):
        self.serveur.close()
        await self.serveur.wait_closed()


def reponse_fixe(corps=b"ok", extra=b""):
    async def repondre(tete, reader, writer):
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: "
            + str(len(corps)).encode()
            + b"\r\n"
            + extra
            + b"\r\n"
            + corps
        )
        await writer.drain()

    return repondre


class BaseProxy(unittest.IsolatedAsyncioTestCase):
    async def monter(self, web, ws, **options):
        # Muet par défaut : le journal a ses propres tests.
        options.setdefault("log", None)
        self.config = rp.ProxyConfig(
            odoo_host="127.0.0.1",
            web_port=web.port,
            websocket_port=ws.port,
            **options,
        )
        self.serveur = await rp.serve(self.config, "127.0.0.1", 0)
        self.port = self.serveur.sockets[0].getsockname()[1]
        self.addCleanup(self._fermer)

    async def _fermer(self):
        self.serveur.close()
        await self.serveur.wait_closed()

    async def requete(self, brut):
        """Envoie une requête brute et rend la réponse entière."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(brut)
        await writer.drain()
        reponse = await asyncio.wait_for(reader.read(), timeout=10)
        writer.close()
        return reponse


class TestRoutage(BaseProxy):
    async def asyncSetUp(self):
        self.web = await FauxOdoo(reponse_fixe(b"web")).demarrer()
        self.ws = await FauxOdoo(reponse_fixe(b"ws")).demarrer()
        self.addAsyncCleanup(self.web.arreter)
        self.addAsyncCleanup(self.ws.arreter)
        await self.monter(self.web, self.ws)

    async def corps_pour(self, chemin):
        rep = await self.requete(
            b"GET " + chemin + b" HTTP/1.1\r\nHost: odoo.test\r\n\r\n"
        )
        return rep.split(b"\r\n\r\n", 1)[1]

    async def test_une_page_va_au_port_web(self):
        self.assertEqual(await self.corps_pour(b"/web/login"), b"web")

    async def test_websocket_va_au_port_du_bus(self):
        self.assertEqual(await self.corps_pour(b"/websocket?v=1"), b"ws")

    async def test_longpolling_n_est_plus_route_vers_le_bus(self):
        # Le bus d'Odoo 18 ne sert que /websocket ; /longpolling reste une
        # page ordinaire, sauf --websocket-path explicite.
        self.assertEqual(await self.corps_pour(b"/longpolling/poll"), b"web")

    async def test_un_prefixe_seul_ne_suffit_pas(self):
        # « /websocketX » n'est pas « /websocket » : le segment entier compte.
        self.assertEqual(await self.corps_pour(b"/websocketX"), b"web")


class TestEntetes(BaseProxy):
    async def asyncSetUp(self):
        self.web = await FauxOdoo(reponse_fixe()).demarrer()
        self.ws = await FauxOdoo(reponse_fixe()).demarrer()
        self.addAsyncCleanup(self.web.arreter)
        self.addAsyncCleanup(self.ws.arreter)

    async def test_les_en_tetes_du_mandataire_sont_poses(self):
        await self.monter(self.web, self.ws, forwarded_proto="https")
        await self.requete(
            b"GET /web HTTP/1.1\r\nHost: odoo.test:8080\r\n\r\n"
        )
        recus = dict(entetes(self.web.tetes[0]))
        self.assertEqual(recus["x-forwarded-host"], "odoo.test:8080")
        self.assertEqual(recus["x-forwarded-proto"], "https")
        self.assertEqual(recus["x-forwarded-for"], "127.0.0.1")
        self.assertEqual(recus["x-real-ip"], "127.0.0.1")

    async def test_un_x_forwarded_for_du_client_est_remplace(self):
        # Odoo en proxy_mode croit cet en-tête : venu du client, il lui
        # ferait prendre une adresse inventée pour celle du visiteur.
        await self.monter(self.web, self.ws)
        await self.requete(
            b"GET /web HTTP/1.1\r\nHost: h\r\n"
            b"X-Forwarded-For: 203.0.113.9\r\nX-Real-IP: 203.0.113.9\r\n\r\n"
        )
        recus = entetes(self.web.tetes[0])
        self.assertEqual(
            [v for n, v in recus if n == "x-forwarded-for"], ["127.0.0.1"]
        )
        self.assertEqual(
            [v for n, v in recus if n == "x-real-ip"], ["127.0.0.1"]
        )

    async def test_une_requete_ordinaire_ferme_sa_connexion_amont(self):
        await self.monter(self.web, self.ws)
        await self.requete(
            b"GET /web HTTP/1.1\r\nHost: h\r\nConnection: keep-alive\r\n"
            b"Keep-Alive: timeout=5\r\n\r\n"
        )
        recus = entetes(self.web.tetes[0])
        self.assertEqual([v for n, v in recus if n == "connection"], ["close"])
        self.assertNotIn("keep-alive", [n for n, _ in recus])


class TestRelais(BaseProxy):
    async def test_une_reponse_gzip_en_morceaux_passe_intacte(self):
        corps = gzip.compress(b"x" * 50_000)
        taille = hex(len(corps))[2:].encode()
        brut_amont = (
            b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n"
            + taille
            + b"\r\n"
            + corps
            + b"\r\n0\r\n\r\n"
        )

        async def repondre(tete, reader, writer):
            writer.write(brut_amont)
            await writer.drain()

        web = await FauxOdoo(repondre).demarrer()
        ws = await FauxOdoo(reponse_fixe()).demarrer()
        self.addAsyncCleanup(web.arreter)
        self.addAsyncCleanup(ws.arreter)
        await self.monter(web, ws)
        rep = await self.requete(b"GET /web HTTP/1.1\r\nHost: h\r\n\r\n")
        self.assertEqual(rep, brut_amont)

    async def test_un_gros_corps_arrive_entier(self):
        envoye = bytes(range(256)) * 20_000  # 5 Mo

        async def repondre(tete, reader, writer):
            n = int(dict(entetes(tete))["content-length"])
            recu = await reader.readexactly(n)
            empreinte = hashlib.sha256(recu).hexdigest().encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Length: "
                + str(len(empreinte)).encode()
                + b"\r\n\r\n"
                + empreinte
            )
            await writer.drain()

        web = await FauxOdoo(repondre).demarrer()
        ws = await FauxOdoo(reponse_fixe()).demarrer()
        self.addAsyncCleanup(web.arreter)
        self.addAsyncCleanup(ws.arreter)
        await self.monter(web, ws)
        rep = await self.requete(
            b"POST /web/binary/upload HTTP/1.1\r\nHost: h\r\nContent-Length: "
            + str(len(envoye)).encode()
            + b"\r\n\r\n"
            + envoye
        )
        self.assertEqual(
            rep.split(b"\r\n\r\n", 1)[1],
            hashlib.sha256(envoye).hexdigest().encode(),
        )

    async def test_le_websocket_relaie_dans_les_deux_sens(self):
        async def repondre(tete, reader, writer):
            writer.write(
                b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                b"Connection: Upgrade\r\n\r\n"
            )
            await writer.drain()
            # Écho tant que le client parle : ce que l'ancien script,
            # requête puis réponse, ne pouvait pas porter.
            while data := await reader.read(65536):
                writer.write(data)
                await writer.drain()

        web = await FauxOdoo(reponse_fixe()).demarrer()
        ws = await FauxOdoo(repondre).demarrer()
        self.addAsyncCleanup(web.arreter)
        self.addAsyncCleanup(ws.arreter)
        await self.monter(web, ws)

        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(
            b"GET /websocket HTTP/1.1\r\nHost: h\r\nUpgrade: websocket\r\n"
            b"Connection: Upgrade\r\nSec-WebSocket-Key: x\r\n\r\n"
        )
        await writer.drain()
        tete = await asyncio.wait_for(lire_tete(reader), timeout=10)
        self.assertTrue(tete.startswith(b"HTTP/1.1 101"))
        for message in (b"premier", b"second"):
            writer.write(message)
            await writer.drain()
            self.assertEqual(
                await asyncio.wait_for(
                    reader.readexactly(len(message)), timeout=10
                ),
                message,
            )
        writer.close()

        recus = dict(entetes(ws.tetes[0]))
        self.assertEqual(recus["upgrade"], "websocket")
        self.assertEqual(recus["connection"], "Upgrade")


class TestErreurs(BaseProxy):
    async def asyncSetUp(self):
        self.web = await FauxOdoo(reponse_fixe()).demarrer()
        self.ws = await FauxOdoo(reponse_fixe()).demarrer()
        self.addAsyncCleanup(self.ws.arreter)

    async def test_un_odoo_arrete_rend_502(self):
        await self.monter(self.web, self.ws)
        await self.web.arreter()
        rep = await self.requete(b"GET /web HTTP/1.1\r\nHost: h\r\n\r\n")
        self.assertTrue(rep.startswith(b"HTTP/1.1 502"), rep[:40])

    async def test_une_tete_illisible_rend_400(self):
        self.addAsyncCleanup(self.web.arreter)
        await self.monter(self.web, self.ws)
        rep = await self.requete(b"n'importe quoi\r\n\r\n")
        self.assertTrue(rep.startswith(b"HTTP/1.1 400"), rep[:40])
        self.assertEqual(self.web.tetes, [])

    async def test_une_tete_demesuree_rend_431(self):
        self.addAsyncCleanup(self.web.arreter)
        await self.monter(self.web, self.ws)
        rep = await self.requete(
            b"GET /web HTTP/1.1\r\nX-Long: "
            + b"a" * (rp.MAX_HEAD + 10)
            + b"\r\n\r\n"
        )
        self.assertTrue(rep.startswith(b"HTTP/1.1 431"), rep[:40])


class TestDelais(BaseProxy):
    async def asyncSetUp(self):
        self.web = await FauxOdoo(reponse_fixe()).demarrer()
        self.ws = await FauxOdoo(reponse_fixe()).demarrer()
        self.addAsyncCleanup(self.web.arreter)
        self.addAsyncCleanup(self.ws.arreter)

    async def test_un_client_muet_recoit_408(self):
        # Sans délai, une connexion ouverte sans requête garderait sa tâche
        # pour toujours.
        await self.monter(self.web, self.ws, head_timeout=0.2)
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        rep = await asyncio.wait_for(reader.read(), timeout=5)
        writer.close()
        self.assertTrue(rep.startswith(b"HTTP/1.1 408"), rep[:40])

    async def test_un_odoo_qui_ne_repond_pas_a_la_connexion_rend_504(self):
        async def jamais(host, port):
            await asyncio.sleep(3600)

        await self.monter(self.web, self.ws, connect_timeout=0.2)
        with patch.object(rp, "_open_upstream", jamais):
            rep = await self.requete(b"GET /web HTTP/1.1\r\nHost: h\r\n\r\n")
        self.assertTrue(rep.startswith(b"HTTP/1.1 504"), rep[:40])

    async def test_une_websocket_n_est_pas_coupee_par_les_delais(self):
        async def repondre(tete, reader, writer):
            writer.write(
                b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                b"Connection: Upgrade\r\n\r\n"
            )
            await writer.drain()
            while data := await reader.read(65536):
                writer.write(data)
                await writer.drain()

        ws = await FauxOdoo(repondre).demarrer()
        self.addAsyncCleanup(ws.arreter)
        await self.monter(self.web, ws, head_timeout=0.2, connect_timeout=0.2)
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(
            b"GET /websocket HTTP/1.1\r\nHost: h\r\nUpgrade: websocket\r\n"
            b"Connection: Upgrade\r\n\r\n"
        )
        await writer.drain()
        await asyncio.wait_for(lire_tete(reader), timeout=5)
        await asyncio.sleep(0.6)  # plus long que les deux délais
        writer.write(b"toujours")
        await writer.drain()
        self.assertEqual(
            await asyncio.wait_for(reader.readexactly(8), timeout=5),
            b"toujours",
        )
        writer.close()


class TestJournal(BaseProxy):
    async def asyncSetUp(self):
        self.lignes = []
        self.web = await FauxOdoo(reponse_fixe()).demarrer()
        self.ws = await FauxOdoo(reponse_fixe()).demarrer()
        self.addAsyncCleanup(self.ws.arreter)

    async def test_une_ligne_par_requete_avec_route_et_statut(self):
        self.addAsyncCleanup(self.web.arreter)
        await self.monter(self.web, self.ws, log=self.lignes.append)
        await self.requete(b"GET /web/login HTTP/1.1\r\nHost: h\r\n\r\n")
        await asyncio.sleep(0.05)
        self.assertEqual(len(self.lignes), 1, self.lignes)
        ligne = self.lignes[0]
        for attendu in ("GET /web/login", "web", "200", "ms"):
            self.assertIn(attendu, ligne)

    async def test_un_echec_de_connexion_se_journalise(self):
        await self.monter(self.web, self.ws, log=self.lignes.append)
        await self.web.arreter()
        await self.requete(b"GET /web HTTP/1.1\r\nHost: h\r\n\r\n")
        await asyncio.sleep(0.05)
        self.assertTrue(any("502" in ligne for ligne in self.lignes))

    async def test_quiet_ne_journalise_rien(self):
        self.addAsyncCleanup(self.web.arreter)
        await self.monter(self.web, self.ws, log=None)
        rep = await self.requete(b"GET /web HTTP/1.1\r\nHost: h\r\n\r\n")
        self.assertTrue(rep.startswith(b"HTTP/1.1 200"))


class TestUn502QuiExplique(BaseProxy):
    async def asyncSetUp(self):
        self.web = await FauxOdoo(reponse_fixe()).demarrer()
        self.ws = await FauxOdoo(reponse_fixe()).demarrer()

    async def test_le_bus_ferme_nomme_le_port_et_workers(self):
        self.addAsyncCleanup(self.web.arreter)
        await self.monter(self.web, self.ws)
        port = self.ws.port
        await self.ws.arreter()
        rep = await self.requete(b"GET /websocket HTTP/1.1\r\nHost: h\r\n\r\n")
        self.assertTrue(rep.startswith(b"HTTP/1.1 502"))
        self.assertIn(f":{port}".encode(), rep)
        self.assertIn(b"workers", rep)

    async def test_le_web_ferme_nomme_son_port(self):
        self.addAsyncCleanup(self.ws.arreter)
        await self.monter(self.web, self.ws)
        port = self.web.port
        await self.web.arreter()
        rep = await self.requete(b"GET /web HTTP/1.1\r\nHost: h\r\n\r\n")
        self.assertIn(f":{port}".encode(), rep)
        self.assertNotIn(b"workers", rep)


class TestSondeAuDemarrage(unittest.IsolatedAsyncioTestCase):
    async def test_un_bus_ferme_se_signale_des_le_demarrage(self):
        web = await FauxOdoo(reponse_fixe()).demarrer()
        self.addAsyncCleanup(web.arreter)
        ferme = await FauxOdoo(reponse_fixe()).demarrer()
        port_ferme = ferme.port
        await ferme.arreter()
        config = rp.ProxyConfig(web_port=web.port, websocket_port=port_ferme)
        etat = await rp.probe(config)
        self.assertEqual(etat, {"web": True, "bus": False})
        avis = " ".join(rp.startup_warnings(etat, config))
        self.assertIn(str(port_ferme), avis)
        self.assertIn("workers", avis)

    async def test_rien_a_dire_quand_tout_repond(self):
        web = await FauxOdoo(reponse_fixe()).demarrer()
        ws = await FauxOdoo(reponse_fixe()).demarrer()
        self.addAsyncCleanup(web.arreter)
        self.addAsyncCleanup(ws.arreter)
        config = rp.ProxyConfig(web_port=web.port, websocket_port=ws.port)
        self.assertEqual(
            rp.startup_warnings(await rp.probe(config), config), []
        )


class TestConfianceEnAmont(BaseProxy):
    async def asyncSetUp(self):
        self.web = await FauxOdoo(reponse_fixe()).demarrer()
        self.ws = await FauxOdoo(reponse_fixe()).demarrer()
        self.addAsyncCleanup(self.web.arreter)
        self.addAsyncCleanup(self.ws.arreter)

    async def test_la_chaine_est_prolongee_et_non_remplacee(self):
        await self.monter(self.web, self.ws, trust_forwarded=True)
        await self.requete(
            b"GET /web HTTP/1.1\r\nHost: interne\r\n"
            b"X-Forwarded-For: 203.0.113.9\r\nX-Forwarded-Proto: https\r\n"
            b"X-Forwarded-Host: public.test\r\n\r\n"
        )
        recus = entetes(self.web.tetes[0])
        self.assertEqual(
            [v for n, v in recus if n == "x-forwarded-for"],
            ["203.0.113.9, 127.0.0.1"],
        )
        self.assertEqual(
            [v for n, v in recus if n == "x-forwarded-proto"], ["https"]
        )
        self.assertEqual(
            [v for n, v in recus if n == "x-forwarded-host"], ["public.test"]
        )
        self.assertEqual(
            [v for n, v in recus if n == "x-real-ip"], ["203.0.113.9"]
        )


@unittest.skipUnless(shutil.which("openssl"), "openssl absent")
class TestTLS(BaseProxy):
    async def test_une_requete_https_arrive_a_odoo_marquee_https(self):
        from script.reverse_proxy import local_cert

        dossier = os.path.join(tempfile.mkdtemp(), "tls")
        self.addCleanup(shutil.rmtree, os.path.dirname(dossier))
        chemins = local_cert.issue(dossier, ["localhost", "127.0.0.1"])
        web = await FauxOdoo(reponse_fixe(b"secret")).demarrer()
        ws = await FauxOdoo(reponse_fixe()).demarrer()
        self.addAsyncCleanup(web.arreter)
        self.addAsyncCleanup(ws.arreter)
        args = rp.get_config(
            [
                "--tls-cert",
                chemins["server_crt"],
                "--tls-key",
                chemins["server_key"],
            ]
        )
        self.config = rp.config_from_args(args)
        self.assertEqual(self.config.forwarded_proto, "https")
        self.config = rp.ProxyConfig(
            web_port=web.port,
            websocket_port=ws.port,
            forwarded_proto=self.config.forwarded_proto,
        )
        serveur = await rp.serve(
            self.config,
            "127.0.0.1",
            0,
            ssl_context=rp.make_ssl_context(
                chemins["server_crt"], chemins["server_key"]
            ),
        )
        self.addAsyncCleanup(self._arreter, serveur)
        port = serveur.sockets[0].getsockname()[1]
        client = ssl.create_default_context(cafile=chemins["ca_crt"])
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", port, ssl=client
        )
        writer.write(b"GET /web HTTP/1.1\r\nHost: localhost\r\n\r\n")
        await writer.drain()
        rep = await asyncio.wait_for(reader.read(), timeout=10)
        writer.close()
        self.assertTrue(rep.endswith(b"secret"), rep[-40:])
        recus = dict(entetes(web.tetes[0]))
        self.assertEqual(recus["x-forwarded-proto"], "https")

    async def _arreter(self, serveur):
        serveur.close()
        await serveur.wait_closed()

    def test_un_certificat_sans_cle_est_refuse(self):
        with self.assertRaises(SystemExit):
            rp.get_config(["--tls-cert", "/tmp/x.crt"])


class TestLectureDeConfig(unittest.TestCase):
    """Les ports et réglages lus dans un config.conf d'Odoo."""

    def ecrire(self, contenu):
        import tempfile

        f = tempfile.NamedTemporaryFile(
            "w", suffix=".conf", delete=False, encoding="utf-8"
        )
        f.write(contenu)
        f.close()
        self.addCleanup(__import__("os").unlink, f.name)
        return f.name

    def test_ports_et_reglages_d_odoo_18(self):
        chemin = self.ecrire(
            "[options]\nhttp_port = 9069\ngevent_port = 9072\n"
            "proxy_mode = True\nworkers = 2\n"
        )
        self.assertEqual(
            rp.read_odoo_config(chemin),
            {
                "web_port": 9069,
                "websocket_port": 9072,
                "proxy_mode": True,
                "workers": 2,
            },
        )

    def test_les_anciens_noms_servent_de_repli(self):
        # xmlrpc_port et longpolling_port : les anciens noms d'Odoo.
        chemin = self.ecrire(
            "[options]\nxmlrpc_port = 7069\nlongpolling_port = 7072\n"
        )
        lu = rp.read_odoo_config(chemin)
        self.assertEqual((lu["web_port"], lu["websocket_port"]), (7069, 7072))

    def test_un_fichier_absent_rend_les_defauts_d_odoo(self):
        self.assertEqual(
            rp.read_odoo_config("/nexiste/pas/config.conf"),
            {
                "web_port": 8069,
                "websocket_port": 8072,
                "proxy_mode": False,
                "workers": 0,
            },
        )

    def test_une_valeur_illisible_garde_le_defaut(self):
        chemin = self.ecrire(
            "[options]\nhttp_port = False\nworkers = beaucoup\n"
        )
        lu = rp.read_odoo_config(chemin)
        self.assertEqual((lu["web_port"], lu["workers"]), (8069, 0))


class TestLigneDeCommande(unittest.TestCase):
    def test_les_defauts_ecoutent_en_local(self):
        args = rp.get_config([])
        self.assertEqual(args.listen, "127.0.0.1")
        self.assertEqual(args.port, 8080)
        self.assertEqual(args.web_port, 8069)
        self.assertEqual(args.websocket_port, 8072)

    def test_les_chemins_du_bus_se_remplacent(self):
        args = rp.get_config(["--websocket-path", "/bus"])
        self.assertEqual(rp.config_from_args(args).websocket_paths, ("/bus",))


if __name__ == "__main__":
    unittest.main()
