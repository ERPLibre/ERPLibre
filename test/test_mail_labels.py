#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un serveur qui range par ÉTIQUETTES, et non par dossiers.

Chez ce genre de fournisseur, un message n'est détenu qu'une fois : les
dossiers en sont des VUES. Le même message répond dans « tous les messages »
et dans la boîte de réception, sous un UID différent dans chacun, et un
drapeau posé dans l'un vaut dans l'autre.

Ce que cela change pour un client qui synchronise TOUS les dossiers : il
rapporte le même message autant de fois qu'il porte d'étiquettes. Trois vues
d'une boîte de trente mille messages font quatre-vingt-dix mille lignes de
cache pour trente mille courriels.

Le client écarte donc les vues qui ne redisent qu'un autre dossier — les
« suivis » et les « importants » se trouvent tous dans `\\All`. Il garde
`\\All` : archiver un message lui retire l'étiquette de la boîte de
réception, et il ne vit alors plus que là.

Le seul discriminant légitime est la capacité `X-GM-EXT-1`, que le serveur
annonce. Un nom de dossier ne prouve rien : le préfixe et la casse sont
propres au fournisseur et changent avec la langue du compte, et `\\All`
désigne une archive ordinaire — des messages DISTINCTS — sur un serveur qui
n'étiquette pas.
"""

import unittest

try:
    import twisted  # noqa: F401

    SANDBOX_MISSING = ""
except ImportError as exc:  # pragma: no cover - dépend de l'installation
    SANDBOX_MISSING = str(exc)

if SANDBOX_MISSING:  # pragma: no cover - dépend de l'installation
    MailSandboxCase = unittest.TestCase
else:
    from mail_sandbox import MailSandboxCase, sandbox_account

requires_servers = unittest.skipIf(
    bool(SANDBOX_MISSING),
    f"serveurs de test absents ({SANDBOX_MISSING})"
    " : pip install -r requirement/erplibre_require-ments.txt",
)

TOUS = "[Boîte]/Tous les messages"
SUIVIS = "[Boîte]/Suivis"
CORBEILLE = "[Boîte]/Corbeille"


def courriel(n: int) -> bytes:
    return (
        f"From: ana@exemple.ca\r\n"
        f"To: moi@exemple.ca\r\n"
        f"Subject: Message {n}\r\n"
        f"Date: Wed, 06 Aug 2026 10:0{n}:00 +0000\r\n"
        f"Message-ID: <{n}@exemple.ca>\r\n"
        f"\r\n"
        f"Corps {n}.\r\n"
    ).encode()


@requires_servers
class LabelCase(MailSandboxCase):
    """Trois messages, chacun étiqueté « tous les messages » ET « boîte de
    réception » ; le premier est aussi « suivi ». Sept étiquettes en tout
    pour trois courriels."""

    def setUp(self):
        self.imap = self.imap_server(etiquettes=True)
        self.dossiers = self.imap.profil_etiquettes()
        self.originaux = [
            self.dossiers[TOUS].deliver(courriel(n)) for n in (1, 2, 3)
        ]
        for message in self.originaux:
            self.dossiers["INBOX"].etiqueter(message)
        self.dossiers[SUIVIS].etiqueter(self.originaux[0])
        self.account = sandbox_account(imap_port=self.imap.port)
        self.transport = self.imap_transport(self.imap, self.account)
        # Le nom BRUT de chaque dossier, indexé par son libellé lisible :
        # c'est le brut qu'il faut renvoyer au serveur pour sélectionner, la
        # hiérarchie arrivant en UTF-7 modifié dès qu'elle porte un accent.
        self.brut = {f.display: f.name for f in self.transport.list_folders()}

    def _entetes(self, dossier):
        """Les en-têtes de tout un dossier, désigné par son libellé."""
        self.transport.select(self.brut[dossier])
        return self.transport.fetch_headers(self.transport.search_uids(1))


class TestWhatTheServerShows(LabelCase):
    """Le bac à sable doit d'abord se comporter comme le fournisseur, sinon
    ce qu'on mesure ensuite ne vaut rien."""

    def test_the_same_message_answers_in_two_folders(self):
        self.assertEqual(
            {h.msgid for h in self._entetes("INBOX")},
            {h.msgid for h in self._entetes(TOUS)},
        )

    def test_its_uid_differs_from_one_folder_to_the_other(self):
        """C'est ce qui interdit de reconnaître un doublon par son UID."""
        boite = {h.msgid: h.uid for h in self._entetes("INBOX")}
        tous = {h.msgid: h.uid for h in self._entetes(TOUS)}
        self.assertTrue(
            all(boite[m] != tous[m] for m in boite),
            f"UID identiques : {boite} / {tous}",
        )

    def test_a_flag_set_under_one_label_is_read_under_the_other(self):
        """Un seul message est détenu : le lire quelque part le lit partout.
        Un client qui l'ignorerait croirait ses drapeaux perdus."""
        uid = self._entetes("INBOX")[0].uid
        self.transport.store_flags(uid, ["\\Seen"], [])
        vus = [h for h in self._entetes(TOUS) if "\\Seen" in (h.flags or "")]
        self.assertEqual(len(vus), 1)

    def test_the_server_says_it_files_by_label(self):
        self.assertIn(
            "X-GM-EXT-1", str(self.transport.client.capabilities).upper()
        )

    def test_the_roles_come_from_the_attributes_not_the_names(self):
        """Les noms portent un préfixe et une casse propres au fournisseur,
        et changent avec la langue du compte. Seul l'attribut est stable."""
        roles = {f.display: f.role for f in self.transport.list_folders()}
        self.assertEqual(roles[TOUS], "archive")
        self.assertEqual(roles[CORBEILLE], "trash")
        self.assertEqual(roles["INBOX"], "inbox")


class TestWhatTheSyncBringsBack(LabelCase):
    def _sync(self):
        from script.todo.mail.imap_sync import Syncer

        store = self.temp_store(self.account)
        Syncer(store, self.transport).sync()
        return store

    def test_a_redundant_view_is_not_brought_back(self):
        """« Suivis » ne contient que des messages que `\\All` contient
        aussi : le rapporter les paierait une fois de plus chacun."""
        store = self._sync()
        self.assertNotIn(
            SUIVIS, {d["display"] or d["name"] for d in store.folders()}
        )

    def test_the_archive_is_brought_back(self):
        """Le dossier `\\All` RESTE, et c'est ce qui distingue ce tri d'un
        simple « sauter les gros dossiers » : archiver un message lui retire
        l'étiquette de la boîte de réception, et il ne vit alors plus que
        là. Le sauter rendrait toute l'archive invisible."""
        store = self._sync()
        noms = {d["display"] or d["name"] for d in store.folders()}
        self.assertIn(TOUS, noms)
        self.assertIn(CORBEILLE, noms)

    def test_what_the_labels_still_cost(self):
        """Le surcoût qui RESTE, et qui ne se supprime pas : la boîte de
        réception et `\\All` montrent les mêmes trois messages sous des UID
        différents, donc six lignes pour trois courriels. Rien dans IMAP ne
        permet de les reconnaître comme un seul sans comparer les
        Message-ID entre dossiers.
        """
        store = self._sync()
        lignes = sum(store.count_messages(d["id"]) for d in store.folders())
        self.assertEqual(lignes, 6)

    def test_the_distinct_messages_are_three(self):
        """Ce que l'utilisateur, lui, compte : trois courriels."""
        store = self._sync()
        vus = set()
        for dossier in store.folders():
            for meta in store.list_messages(dossier["id"]):
                vus.add(meta.msgid)
        self.assertEqual(len(vus), 3)


class TestAServerThatDoesNotLabel(MailSandboxCase):
    """Le contrôle indispensable : ailleurs, un dossier `\\Flagged` peut
    contenir des messages qui ne sont nulle part d'autre, et l'écarter les
    perdrait. Le tri ne se déclenche que sur l'annonce du serveur."""

    def setUp(self):
        self.imap = self.imap_server(etiquettes=False)
        self.imap.folder("INBOX").deliver(courriel(1), uid=1)
        self.imap.folder("Suivis", attributs=["\\Flagged"]).deliver(
            courriel(2), uid=1
        )
        self.account = sandbox_account(imap_port=self.imap.port)
        self.transport = self.imap_transport(self.imap, self.account)

    def test_the_server_does_not_say_it_files_by_label(self):
        self.assertFalse(self.transport.range_par_etiquettes())

    def test_a_flagged_folder_is_still_synced(self):
        from script.todo.mail.imap_sync import Syncer

        store = self.temp_store(self.account)
        Syncer(store, self.transport).sync()
        noms = {d["display"] or d["name"] for d in store.folders()}
        self.assertIn("Suivis", noms)
        lignes = sum(store.count_messages(d["id"]) for d in store.folders())
        self.assertEqual(lignes, 2)


if __name__ == "__main__":
    unittest.main()
