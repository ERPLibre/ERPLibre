#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le client de l'API Forgejo, contre une fausse session : aucun réseau.

Tous les hôtes, comptes, organisations et jetons sont inventés.
"""

import unittest

from script.git import forgejo_client as fc

BASE = "https://forge.example.invalid:3000"
API = f"{BASE}/api/v1"


class Reponse:
    def __init__(self, statut, corps=None, headers=None, brut=False):
        self.status_code = statut
        self._corps = corps if corps is not None else {}
        self.headers = headers or {}
        self._brut = brut

    def json(self):
        if self._brut:
            raise ValueError("Expecting value")
        return self._corps


class FausseSession:
    """Rend, pour (méthode, chemin), la réponse de la table ; note chaque
    appel avec ses en-têtes, son auth, ses paramètres et son corps. Une
    entrée absente répond 404. Une valeur appelable reçoit les arguments."""

    def __init__(self, table):
        self.table = table
        self.appels = []

    def request(self, methode, url, **kw):
        assert url.startswith(API), url
        chemin = url[len(API) :]
        self.appels.append(
            {
                "methode": methode,
                "chemin": chemin,
                "json": kw.get("json"),
                "params": kw.get("params"),
                "headers": kw.get("headers"),
                "auth": kw.get("auth"),
            }
        )
        rep = self.table.get((methode, chemin), Reponse(404))
        return rep(kw) if callable(rep) else rep


def client(table, **kw):
    session = FausseSession(table)
    return fc.ClientForgejo(BASE, session=session, **kw), session


class TestUrls(unittest.TestCase):
    def test_base_web(self):
        for url, attendu in (
            (BASE, BASE),
            (BASE + "/", BASE),
            (BASE + "/api/v1", BASE),
            ("http://10.example.invalid", "http://10.example.invalid"),
            (
                "https://h.example.invalid/sous/chemin/",
                "https://h.example.invalid/sous/chemin",
            ),
        ):
            with self.subTest(url=url):
                self.assertEqual(fc.base_web(url), attendu)
        for url in (
            None,
            "",
            "ssh://git@h.example.invalid:2222",
            "h.example.invalid",
        ):
            with self.subTest(url=url):
                self.assertIsNone(fc.base_web(url))

    def test_hote(self):
        self.assertEqual(fc.hote_de(BASE), "forge.example.invalid")
        self.assertEqual(
            fc.hote_de("ssh://git@Forge.Example.invalid:2222/o/d.git"),
            "forge.example.invalid",
        )
        self.assertEqual(
            fc.hote_de("git@forge.example.invalid:o/d"),
            "forge.example.invalid",
        )

    def test_une_url_qui_n_est_pas_web_est_refusee(self):
        with self.assertRaises(fc.ErreurForgejo):
            fc.ClientForgejo(
                "ssh://git@forge.example.invalid:2222", session=object()
            )


class TestJeton(unittest.TestCase):
    def test_l_environnement_d_abord(self):
        appels = []
        valeur = fc.jeton(
            "h", environ={"EL_FORGEJO_TOKEN": " env\r\n"}, coffre=appels.append
        )
        self.assertEqual((valeur, appels), (("env", "env"), []))

    def test_puis_le_coffre_par_forge(self):
        self.assertEqual(
            fc.jeton("h:3000", environ={}, coffre=lambda forge: f"c-{forge} "),
            ("c-h:3000", "coffre"),
        )

    def test_rien(self):
        self.assertEqual(fc.jeton("h", environ={}), ("", ""))
        self.assertEqual(
            fc.jeton("h", environ={}, coffre=lambda h: None), ("", "")
        )

    def test_cle_forge_garde_le_port(self):
        self.assertEqual(
            fc.cle_forge(BASE + "/api/v1"), "forge.example.invalid:3000"
        )
        self.assertEqual(
            fc.cle_forge("https://u@Forge.example.invalid"),
            "forge.example.invalid",
        )
        self.assertEqual(fc.cle_forge("ssh://git@f.invalid:2222"), "")

    def test_est_locale(self):
        self.assertTrue(fc.est_locale("http://localhost:3000"))
        self.assertTrue(fc.est_locale("http://127.0.0.1:3000"))
        self.assertFalse(fc.est_locale("http://forge.example.invalid"))


class TestAuthentification(unittest.TestCase):
    def test_le_jeton_passe_dans_l_en_tete_jamais_dans_l_url(self):
        c, s = client(
            {("GET", "/user"): Reponse(200, {"login": "moi"})},
            jeton_api="secret",
        )
        self.assertEqual(c.identite(), "moi")
        appel = s.appels[0]
        self.assertEqual(appel["headers"]["Authorization"], "token secret")
        self.assertIsNone(appel["auth"])
        self.assertNotIn("secret", appel["chemin"])

    def test_identifiants_en_basique_sans_jeton(self):
        c, s = client(
            {("GET", "/user"): Reponse(200, {"login": "admin"})},
            identifiants=("admin", "mdp"),
        )
        c.identite()
        self.assertEqual(s.appels[0]["auth"], ("admin", "mdp"))
        self.assertNotIn("Authorization", s.appels[0]["headers"])

    def test_un_refus_porte_son_statut_et_le_message(self):
        c, _ = client(
            {("GET", "/user"): Reponse(401, {"message": "token is required"})}
        )
        with self.assertRaises(fc.ErreurForgejo) as ctx:
            c.identite()
        self.assertEqual(ctx.exception.statut, 401)
        self.assertIn("token is required", str(ctx.exception))

    def test_une_erreur_reseau_devient_une_erreur_forgejo(self):
        class Coupee:
            def request(self, *a, **kw):
                raise ConnectionError("refusée")

        c = fc.ClientForgejo(BASE, session=Coupee())
        with self.assertRaises(fc.ErreurForgejo) as ctx:
            c.version()
        self.assertIsNone(ctx.exception.statut)

    def test_version(self):
        c, _ = client(
            {("GET", "/version"): Reponse(200, {"version": "11.0.0"})}
        )
        self.assertEqual(c.version(), "11.0.0")


class TestOrganisations(unittest.TestCase):
    def test_existante_n_est_ni_recreee_ni_modifiee(self):
        c, s = client(
            {("GET", "/orgs/Proprio"): Reponse(200, {"username": "Proprio"})}
        )
        self.assertEqual(c.assurer_organisation("Proprio")[0], "existante")
        self.assertEqual([a["methode"] for a in s.appels], ["GET"])

    def test_absente_est_creee_privee(self):
        c, s = client(
            {("POST", "/orgs"): Reponse(201, {"username": "Proprio"})}
        )
        self.assertEqual(c.assurer_organisation("Proprio")[0], "creee")
        self.assertEqual(
            s.appels[-1]["json"],
            {"username": "Proprio", "visibility": "private"},
        )

    def test_le_nom_est_echappe_dans_le_chemin(self):
        c, s = client({})
        c.organisation("a/b")
        self.assertEqual(s.appels[0]["chemin"], "/orgs/a%2Fb")

    def test_requises_sans_egard_a_la_casse(self):
        self.assertEqual(
            fc.organisations_requises(
                ["TechnoLibre", "OCA", "technolibre", None, "", "Autre"]
            ),
            ["Autre", "OCA", "TechnoLibre"],
        )

    def test_une_erreur_n_arrete_pas_les_suivantes(self):
        c, _ = client(
            {
                ("GET", "/orgs/A"): Reponse(200, {}),
                ("POST", "/orgs"): Reponse(403, {"message": "forbidden"}),
            }
        )
        res = fc.assurer_organisations(c, ["A", "B"])
        self.assertEqual(res["A"], ("existante", ""))
        self.assertEqual(res["B"][0], "erreur")
        self.assertIn("403", res["B"][1])


class TestDepots(unittest.TestCase):
    def test_existant(self):
        c, s = client({("GET", "/repos/P/d"): Reponse(200, {"name": "d"})})
        self.assertEqual(c.assurer_depot("P", "d.git")[0], "existant")
        self.assertEqual(len(s.appels), 1)

    def test_absent_est_cree_vide_et_prive_dans_l_organisation(self):
        c, s = client(
            {
                ("GET", "/orgs/P"): Reponse(200, {}),
                ("POST", "/orgs/P/repos"): Reponse(201, {"name": "d"}),
            }
        )
        self.assertEqual(c.assurer_depot("P", "d.git")[0], "cree")
        self.assertEqual(
            s.appels[-1]["json"],
            {"name": "d", "private": True, "auto_init": False},
        )

    def test_sur_le_compte(self):
        c, s = client({("POST", "/user/repos"): Reponse(201, {})})
        c.creer_depot("moi", "d", organisation=False)
        self.assertEqual(s.appels[-1]["chemin"], "/user/repos")

    def test_cle_ssh_deja_presente_sur_ce_compte(self):
        c, s = client(
            {
                ("POST", "/user/keys"): Reponse(
                    422, {"message": "Key content has been used"}
                ),
                ("GET", "/user/keys"): Reponse(
                    200, [{"key": "ssh-ed25519 AAAA autre-commentaire"}]
                ),
            }
        )
        self.assertFalse(
            c.ajouter_cle_ssh("erplibre", "ssh-ed25519 AAAA cle\n")
        )
        self.assertEqual(s.appels[0]["json"]["key"], "ssh-ed25519 AAAA cle")

    def test_un_autre_422_est_une_erreur(self):
        """Titre pris, clé invalide ou portée par un autre compte : la clé
        n'est pas sur ce compte, ce n'est pas « déjà présente »."""
        c, _ = client(
            {
                ("POST", "/user/keys"): Reponse(
                    422, {"message": "Key title has been used"}
                ),
                ("GET", "/user/keys"): Reponse(
                    200, [{"key": "ssh-ed25519 BBBB x"}]
                ),
            }
        )
        with self.assertRaises(fc.ErreurForgejo):
            c.ajouter_cle_ssh("erplibre", "ssh-ed25519 AAAA cle")

    def test_le_compte_du_jeton_recoit_ses_depots_sur_lui_meme(self):
        c, s = client(
            {
                ("GET", "/user"): Reponse(200, {"login": "Moi"}),
                ("POST", "/user/repos"): Reponse(201, {"name": "d"}),
            }
        )
        self.assertEqual(c.assurer_depot("moi", "d")[0], "cree")
        self.assertEqual(s.appels[-1]["chemin"], "/user/repos")

    def test_un_autre_compte_est_refuse(self):
        c, s = client(
            {
                ("GET", "/user"): Reponse(200, {"login": "moi"}),
                ("GET", "/users/lui"): Reponse(200, {"login": "lui"}),
            }
        )
        with self.assertRaises(fc.ErreurForgejo) as ctx:
            c.assurer_depot("lui", "d")
        self.assertIn("another user account", str(ctx.exception))
        self.assertNotIn("POST", [a["methode"] for a in s.appels])

    def test_nature_des_proprietaires(self):
        c, _ = client(
            {
                ("GET", "/user"): Reponse(200, {"login": "moi"}),
                ("GET", "/orgs/Org"): Reponse(200, {}),
                ("GET", "/users/lui"): Reponse(200, {}),
                ("GET", "/orgs/Panne"): Reponse(500, {"message": "boom"}),
            }
        )
        self.assertEqual(
            fc.plan_proprietaires(c, ["Org", "MOI", "lui", "rien", "Panne"]),
            {
                "Org": "organisation",
                "MOI": "compte",
                "lui": "utilisateur",
                "rien": "absent",
                "Panne": "erreur: GET /orgs/Panne : 500 boom",
            },
        )


class TestTransport(unittest.TestCase):
    """Ce que la revue a montré : .netrc, redirections, réponses qui ne
    sont pas du JSON, jeton illisible ou masqué dans les messages."""

    def test_la_session_creee_ignore_l_environnement(self):
        """Une entrée ~/.netrc remplacerait sinon le jeton par un mot de
        passe."""
        c = fc.ClientForgejo(BASE, jeton_api="jeton")
        self.assertFalse(c.session.trust_env)

    def test_aucune_redirection_n_est_suivie(self):
        vus = []

        def creer(kw):
            vus.append(kw.get("allow_redirects"))
            return Reponse(
                301,
                headers={"Location": "https://ailleurs.invalid/api/v1/orgs"},
            )

        c, _ = client({("POST", "/orgs"): creer}, jeton_api="jeton")
        with self.assertRaises(fc.ErreurForgejo) as ctx:
            c.creer_organisation("P")
        self.assertEqual(vus, [False])
        self.assertEqual(ctx.exception.statut, 301)
        self.assertIn("https://ailleurs.invalid", str(ctx.exception))

    def test_une_page_html_en_200_est_une_erreur_forgejo(self):
        c, _ = client({("GET", "/version"): Reponse(200, brut=True)})
        with self.assertRaises(fc.ErreurForgejo) as ctx:
            c.version()
        self.assertIn("not a Forgejo API response", str(ctx.exception))

    def test_un_corps_du_mauvais_type_est_une_erreur_forgejo(self):
        c, _ = client({("GET", "/orgs/P"): Reponse(200, ["liste"])})
        with self.assertRaises(fc.ErreurForgejo):
            c.organisation("P")

    def test_un_jeton_avec_un_blanc_est_refuse_sans_etre_affiche(self):
        for jeton in ("s3cr3t\r", "s3c r3t", "s3cr3t\n"):
            with self.subTest(jeton=repr(jeton)):
                with self.assertRaises(fc.ErreurForgejo) as ctx:
                    fc.ClientForgejo(BASE, jeton_api=jeton, session=object())
                self.assertNotIn("s3c", str(ctx.exception))

    def test_le_jeton_est_masque_dans_une_erreur_de_transport(self):
        class Bavarde:
            def request(self, *a, **kw):
                raise OSError(
                    f"header {kw['headers']['Authorization']} refused"
                )

        c = fc.ClientForgejo(BASE, jeton_api="s3cr3t", session=Bavarde())
        with self.assertRaises(fc.ErreurForgejo) as ctx:
            c.version()
        self.assertNotIn("s3cr3t", str(ctx.exception))
        self.assertIn("***", str(ctx.exception))


class TestPullRequests(unittest.TestCase):
    def test_lecture_jusqu_a_une_page_vide(self):
        """Le serveur plafonne la taille des pages : une page plus courte
        que demandé n'est pas la dernière, seule une page vide l'est."""
        pages = {1: [{"number": 1}, {"number": 2}], 2: [{"number": 3}]}

        def lister(kw):
            return Reponse(200, pages.get(kw["params"]["page"], []))

        c, s = client({("GET", "/repos/P/d/pulls"): lister})
        self.assertEqual(
            [p["number"] for p in c.pull_requests("P", "d")], [1, 2, 3]
        )
        self.assertEqual([a["params"]["page"] for a in s.appels], [1, 2, 3])
        self.assertEqual(s.appels[0]["params"]["state"], "open")

    def test_le_filtre_est_reverifie_sur_chaque_reponse(self):
        """Un serveur qui ignore « head » et « base » rend toutes les
        pull requests ouvertes : seule celle qui correspond est reprise."""
        autre = {"number": 3, "head": {"ref": "autre"}, "base": {"ref": "X.0"}}
        bonne = {"number": 4, "head": {"ref": "maj"}, "base": {"ref": "X.0"}}

        def lister(kw):
            return Reponse(
                200, [autre, bonne] if kw["params"]["page"] == 1 else []
            )

        c, s = client({("GET", "/repos/P/d/pulls"): lister})
        self.assertEqual(c.pull_request_ouverte("P", "d", "maj", "X.0"), bonne)
        self.assertEqual(
            (s.appels[0]["params"]["head"], s.appels[0]["params"]["base"]),
            ("maj", "X.0"),
        )

    def test_un_serveur_qui_ignore_la_pagination_ne_boucle_pas(self):
        """Chaque page rend la même liste : la lecture s'arrête à la
        deuxième, sans doublon."""
        c, s = client(
            {("GET", "/repos/P/d/pulls"): Reponse(200, [{"number": 1}])}
        )
        self.assertEqual(c.pull_requests("P", "d"), [{"number": 1}])
        self.assertEqual(len(s.appels), 2)

    def test_une_pull_request_ouverte_est_reprise(self):
        ouverte = {"number": 7, "head": {"ref": "maj"}, "base": {"ref": "X.0"}}
        c, s = client({("GET", "/repos/P/d/pulls"): Reponse(200, [ouverte])})
        self.assertEqual(
            c.assurer_pull_request("P", "d", "maj", "X.0", "t"),
            ("existante", ouverte),
        )
        self.assertNotIn("POST", [a["methode"] for a in s.appels])

    def test_sinon_elle_est_creee(self):
        c, s = client(
            {
                ("GET", "/repos/P/d/pulls"): Reponse(200, []),
                ("POST", "/repos/P/d/pulls"): Reponse(
                    201, {"number": 1, "html_url": f"{BASE}/P/d/pulls/1"}
                ),
            }
        )
        etat, pr = c.assurer_pull_request(
            "P", "d", "maj", "X.0", "Titre", "Corps"
        )
        self.assertEqual((etat, pr["number"]), ("creee", 1))
        self.assertEqual(
            s.appels[-1]["json"],
            {"head": "maj", "base": "X.0", "title": "Titre", "body": "Corps"},
        )


class TestCreationsConcurrentes(unittest.TestCase):
    """Entre la lecture et la création, un autre client a créé la même
    chose : la réponse « existe déjà » fait relire l'existant."""

    def test_organisation_422_puis_existante(self):
        lectures = iter([Reponse(404), Reponse(200, {"username": "P"})])
        c, _ = client(
            {
                ("GET", "/orgs/P"): lambda kw: next(lectures),
                ("POST", "/orgs"): Reponse(
                    422, {"message": "user already exists"}
                ),
            }
        )
        self.assertEqual(
            c.assurer_organisation("P"), ("existante", {"username": "P"})
        )

    def test_organisation_422_sans_existant_reste_une_erreur(self):
        c, _ = client(
            {("POST", "/orgs"): Reponse(422, {"message": "name is reserved"})}
        )
        with self.assertRaises(fc.ErreurForgejo):
            c.assurer_organisation("P")

    def test_depot_409_puis_existant(self):
        lectures = iter([Reponse(404), Reponse(200, {"name": "d"})])
        c, _ = client(
            {
                ("GET", "/repos/P/d"): lambda kw: next(lectures),
                ("GET", "/orgs/P"): Reponse(200, {}),
                ("POST", "/orgs/P/repos"): Reponse(409, {}),
            }
        )
        self.assertEqual(c.assurer_depot("P", "d")[0], "existant")

    def test_pull_request_409_puis_existante(self):
        pr = {"number": 9, "head": {"ref": "maj"}, "base": {"ref": "X.0"}}
        appels = {"n": 0}

        def lister_pages(kw):
            # Première lecture : vide ; seconde lecture : la PR, puis vide.
            appels["n"] += 1
            return Reponse(200, {1: [], 2: [pr], 3: []}[appels["n"]])

        c, _ = client(
            {
                ("GET", "/repos/P/d/pulls"): lister_pages,
                ("POST", "/repos/P/d/pulls"): Reponse(409, {}),
            }
        )
        self.assertEqual(
            c.assurer_pull_request("P", "d", "maj", "X.0", "t"),
            ("existante", pr),
        )


class TestNoms(unittest.TestCase):
    def test_organisations_acceptees(self):
        for nom in ("OCA", "ERPLibre", "muk-it", "a.b_c", "x" * 40, "7up"):
            with self.subTest(nom=nom):
                self.assertTrue(fc.nom_organisation_valide(nom))

    def test_organisations_refusees(self):
        for nom in (
            "",
            None,
            "-a",
            "a-",
            "a--b",
            "a._b",
            "x" * 41,
            "é",
            "a b",
            "a/b",
        ):
            with self.subTest(nom=nom):
                self.assertFalse(fc.nom_organisation_valide(nom))

    def test_depots(self):
        self.assertTrue(fc.nom_depot_valide("odoo-modules_1.x"))
        for nom in ("", "a b", "é", "a/b", "x" * 101):
            with self.subTest(nom=nom):
                self.assertFalse(fc.nom_depot_valide(nom))

    def test_un_nom_refuse_n_est_pas_envoye(self):
        c, s = client({})
        res = fc.assurer_organisations(c, ["a--b"])
        self.assertEqual(res["a--b"][0], "erreur")
        self.assertEqual(s.appels, [])


class TestMain(unittest.TestCase):
    """La ligne de commande, avec un faux client et des projets injectés."""

    PROJETS = [
        {"proprietaire": "OCA", "nom": "a.git"},
        {"proprietaire": "Autre", "nom": "b.git"},
        {"proprietaire": None, "nom": "c.git"},
    ]

    def lancer(self, argv, table, avec_client=True):
        from unittest.mock import patch

        from script.git import push_remote

        c, s = client(table)
        with patch.object(
            push_remote, "projets_actifs", return_value=self.PROJETS
        ), patch("os.chdir"), patch("builtins.print") as imprime:
            code = fc.main(argv, client=c if avec_client else None)
        self.sortie = " ".join(
            str(a) for x in imprime.mock_calls for a in x.args
        )
        return code, s

    def table(self):
        creees = set()

        def lire_org(nom):
            return lambda kw: (
                Reponse(200, {}) if nom in creees else Reponse(404)
            )

        def creer_org(kw):
            creees.add(kw["json"]["username"])
            return Reponse(201, {})

        return {
            ("GET", "/version"): Reponse(200, {"version": "1"}),
            ("GET", "/user"): Reponse(200, {"login": "moi"}),
            ("GET", "/orgs/OCA"): Reponse(200, {}),
            ("GET", "/orgs/Autre"): lire_org("Autre"),
            ("POST", "/orgs"): creer_org,
            ("POST", "/orgs/OCA/repos"): Reponse(201, {}),
            ("POST", "/orgs/Autre/repos"): Reponse(201, {}),
        }

    def test_cree_les_organisations_absentes_seulement(self):
        code, s = self.lancer(["--url", BASE], self.table())
        self.assertEqual(code, 0)
        posts = [a for a in s.appels if a["methode"] == "POST"]
        self.assertEqual([a["json"]["username"] for a in posts], ["Autre"])

    def test_a_sec_ne_cree_rien(self):
        _code, s = self.lancer(
            ["--url", BASE, "--dry-run", "--create-repos"], self.table()
        )
        self.assertNotIn("POST", [a["methode"] for a in s.appels])

    def test_depots_sur_demande(self):
        code, s = self.lancer(["--url", BASE, "--create-repos"], self.table())
        self.assertEqual(code, 0)
        chemins = [a["chemin"] for a in s.appels if a["methode"] == "POST"]
        self.assertIn("/orgs/OCA/repos", chemins)
        self.assertIn("/orgs/Autre/repos", chemins)

    def test_forge_injoignable(self):
        code, _ = self.lancer(["--url", BASE], {})
        self.assertEqual(code, 1)

    def test_une_lecture_refusee_rend_2_sans_traceback(self):
        table = self.table()
        table[("GET", "/orgs/OCA")] = Reponse(500, {"message": "boom"})
        code, _ = self.lancer(["--url", BASE], table)
        self.assertEqual(code, 2)
        self.assertIn("boom", self.sortie)

    def test_http_en_clair_refuse_hors_de_la_machine(self):
        code, s = self.lancer(
            ["--url", "http://forge.example.invalid"], {}, avec_client=False
        )
        self.assertEqual(code, 1)
        self.assertEqual(s.appels, [])
        self.assertIn("--allow-http", self.sortie)


class TestJetonEtBranche(unittest.TestCase):
    def test_creer_un_jeton_avec_le_mot_de_passe(self):
        c, s = client(
            {("POST", "/users/admin/tokens"): Reponse(201, {"sha1": "neuf"})},
            identifiants=("admin", "mdp"),
        )
        self.assertEqual(c.creer_jeton("t", ["write:repository"]), "neuf")
        self.assertEqual(s.appels[0]["auth"], ("admin", "mdp"))
        self.assertEqual(
            s.appels[0]["json"], {"name": "t", "scopes": ["write:repository"]}
        )
        # La valeur neuve est masquée comme le mot de passe.
        self.assertEqual(c._masque("x neuf mdp"), "x *** ***")

    def test_sans_mot_de_passe_pas_de_jeton(self):
        c, s = client({}, jeton_api="jeton")
        with self.assertRaises(fc.ErreurForgejo):
            c.creer_jeton("t", [])
        self.assertEqual(s.appels, [])

    def test_commit_d_une_branche_a_barre(self):
        c, s = client(
            {
                ("GET", "/repos/P/d/branches/dev/x"): Reponse(
                    200, {"commit": {"id": "abc"}}
                )
            }
        )
        self.assertEqual(c.commit_de_branche("P", "d", "dev/x"), "abc")
        self.assertIsNone(c.commit_de_branche("P", "d", "absente"))


if __name__ == "__main__":
    unittest.main()
