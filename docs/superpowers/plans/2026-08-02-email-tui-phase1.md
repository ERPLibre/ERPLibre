# Client courriel TUI — plan d'implémentation, phase 1

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lire, écrire et envoyer du courriel sur plusieurs comptes IMAP/SMTP depuis le CLI TODO, avec un cache local dont l'utilisateur choisit le niveau de confidentialité.

**Architecture:** Un paquet `script/todo/mail/` de huit modules à responsabilité unique. `todo.py` ne gagne qu'un import et un branchement de menu. Le réseau est derrière un protocole (`ImapTransport`, `SmtpTransport`) pour que le moteur de synchronisation et l'envoi soient testables sans serveur. Le chiffrement est une boîte enfichable (`MailCrypto`) que le stockage traverse sans jamais savoir quel mode est actif.

**Tech Stack:** Python 3.13 (`.venv.erplibre`), `imaplib`/`smtplib`/`email`/`sqlite3` de la stdlib, Textual pour le TUI, `cryptography` (AES-256-GCM), `pykeepass` et `keyring` pour les secrets, `unittest` pour les tests.

**Spec :** `docs/superpowers/specs/2026-08-02-email-tui-design.md`

## Global Constraints

- Interpréteur : `.venv.erplibre/bin/python` (Python 3.13.5). **Ne jamais** utiliser un venv `.venv.odoo*` pour ce code.
- Commandes de test lancées **depuis la racine du dépôt**, sinon les imports `script.todo.*` échouent : `.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_*.py" -v`
- **Baseline connue**, mesurée au commit `0d87957` : `unittest discover -s test` donne **262 tests, 6 échecs** préexistants et sans rapport avec ce travail — `test_todo.TestSetupClaudeCommit.test_existing_file_skips` (erreur), `test_execute.TestExecCommandLive.test_single_source_odoo_no_version_returns_error`, `test_todo.TestExecuteFromConfiguration.test_with_command`, et trois de `test_todo_i18n.TestT`. Ne pas les corriger ici, ne pas s'en alarmer. La cible est : aucun **nouvel** échec.
- `pytest` n'est pas installé. Tout est en `unittest`, comme le reste de `test/`.
- Toute chaîne affichée à l'utilisateur passe par `t("clé")` de `script.todo.todo_i18n`, avec une entrée `fr` **et** `en`. `test/test_todo_i18n.py::TestTranslations::test_all_entries_have_fr_and_en` l'impose déjà.
- Clés i18n de ce travail : préfixe `mail_`, groupées sous un commentaire `# Courriel` dans `TRANSLATIONS`.
- En-tête de chaque nouveau fichier Python, identique au reste de `script/todo/` :
  ```python
  #!/usr/bin/env python3
  # © 2026 TechnoLibre (http://www.technolibre.ca)
  # License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
  ```
- Formatage : `make format` (Black + isort, config dans `pyproject.toml`). Lancer avant chaque commit.
- Format de message de commit : `[TYPE] description` — `[ADD]`, `[IMP]`, `[FIX]`, `[REF]`.
- `textual` s'importe **à l'intérieur** de la fonction qui en a besoin, jamais au niveau module — c'est le motif de `todo_telemetry.py:737` et `qemu_deploy_form.py:197`. Un module courriel doit rester importable sans Textual, sinon les tests exigent le TUI.
- Aucun test ne touche le réseau, ni le trousseau réel, ni `~/.erplibre` de la machine. Toujours `tempfile.TemporaryDirectory()` et injection de chemin.
- Aucun mot de passe, aucune clé, dans `accounts.json` ni dans un log.

---

## Structure des fichiers

| Fichier | Responsabilité | Tâche |
|---------|----------------|-------|
| `script/todo/mail/__init__.py` | API publique du paquet | 1 |
| `script/todo/mail/crypto.py` | `MailCrypto.seal/open`, enveloppe auto-descriptive | 1 |
| `script/todo/mail/secrets.py` | `SecretStore` kdbx → repli keyring, refus du backend en clair | 2 |
| `script/todo/mail/accounts.py` | `Account`, `accounts.json`, préréglages, générateur de modèle | 3 |
| `script/todo/mail/store.py` | cache par compte : SQLite + `.eml`, résolution du mode, éphémère | 4 |
| `script/todo/mail/imap_sync.py` | protocole `ImapTransport`, `Syncer` incrémental | 5 |
| `script/todo/mail/imap_transport.py` | `ImaplibTransport` — la seule couche qui parle vraiment IMAP | 6 |
| `script/todo/mail/smtp_send.py` | construction MIME, réponse, transfert, envoi | 7 |
| `script/todo/mail/tui_text.py` | fonctions pures d'affichage (HTML dépouillé, dates, troncature) | 8 |
| `script/todo/mail/tui.py` | application Textual : 3 volets, plein écran, composition | 9, 10 |
| `script/todo/mail/menu.py` | `prompt_execute_mail()` et sous-menus | 11 |
| `script/todo/todo.py` | `prompt_assistant()`, branchement `[3]` | 11 |
| `script/todo/todo_i18n.py` | clés `mail_*` | 11 |
| `script/todo/todo_prefs.py` | `mail_cache_mode`, `mail_refresh_sec` | 4, 11 |
| `requirement/erplibre_require-ments.txt` | `cryptography`, `keyring` | 1 |
| `doc/EMAIL.base.md` | documentation bilingue | 12 |

`imap_sync.py` et `imap_transport.py` sont séparés à dessein : le moteur (testable, pur) ne doit pas cohabiter avec le décodage des réponses `imaplib`, qui est verbeux et ne se teste bien que contre des octets figés.

---

### Task 1: Dépendances, squelette du paquet, chiffrement

**Files:**
- Create: `script/todo/mail/__init__.py`
- Create: `script/todo/mail/crypto.py`
- Create: `test/test_mail_crypto.py`
- Modify: `requirement/erplibre_require-ments.txt`

**Interfaces:**
- Consumes: rien.
- Produces:
  - `CLEAR_MAGIC: bytes = b"P0"`, `SEALED_MAGIC: bytes = b"E1"`
  - `class CryptoError(Exception)`
  - `new_key() -> bytes` (32 octets)
  - `class MailCrypto` avec `seal(data: bytes) -> bytes` et `open(blob: bytes) -> bytes`
  - `class NullCrypto(MailCrypto)`
  - `class AesGcmCrypto(MailCrypto)`, `__init__(self, key: bytes)`
  - `build_crypto(mode: str, key: bytes | None) -> MailCrypto`

- [ ] **Step 1: Installer les dépendances**

Ajouter à `requirement/erplibre_require-ments.txt`, juste après la ligne `pykeepass` :

```
cryptography
keyring
```

Puis :

```bash
.venv.erplibre/bin/pip install cryptography keyring
```

- [ ] **Step 2: Créer le paquet**

`script/todo/mail/__init__.py` :

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Client courriel du CLI TODO.

Le paquet est découpé par responsabilité : `crypto` scelle, `secrets` garde
les mots de passe, `accounts` décrit les comptes, `store` cache localement,
`imap_sync` synchronise, `smtp_send` envoie, `tui` affiche, `menu` branche le
tout sur le CLI. Aucun de ces modules n'importe `todo.py` ; c'est `todo.py`
qui importe `menu`.
"""
```

- [ ] **Step 3: Écrire les tests qui échouent**

`test/test_mail_crypto.py` :

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import unittest

from script.todo.mail.crypto import (
    CLEAR_MAGIC,
    SEALED_MAGIC,
    AesGcmCrypto,
    CryptoError,
    NullCrypto,
    build_crypto,
    new_key,
)


class TestNullCrypto(unittest.TestCase):
    def test_roundtrip(self):
        box = NullCrypto()
        self.assertEqual(box.open(box.seal(b"bonjour")), b"bonjour")

    def test_envelope_is_marked_clear(self):
        self.assertTrue(NullCrypto().seal(b"x").startswith(CLEAR_MAGIC))

    def test_cannot_open_sealed_blob(self):
        blob = AesGcmCrypto(new_key()).seal(b"secret")
        with self.assertRaises(CryptoError):
            NullCrypto().open(blob)


class TestAesGcmCrypto(unittest.TestCase):
    def setUp(self):
        self.key = new_key()

    def test_key_is_32_bytes(self):
        self.assertEqual(len(self.key), 32)

    def test_roundtrip(self):
        box = AesGcmCrypto(self.key)
        self.assertEqual(box.open(box.seal(b"bonjour")), b"bonjour")

    def test_envelope_is_marked_sealed(self):
        self.assertTrue(AesGcmCrypto(self.key).seal(b"x").startswith(SEALED_MAGIC))

    def test_ciphertext_hides_plaintext(self):
        blob = AesGcmCrypto(self.key).seal(b"sujet confidentiel")
        self.assertNotIn(b"confidentiel", blob)

    def test_nonce_differs_each_call(self):
        box = AesGcmCrypto(self.key)
        self.assertNotEqual(box.seal(b"meme texte"), box.seal(b"meme texte"))

    def test_wrong_key_raises(self):
        blob = AesGcmCrypto(self.key).seal(b"secret")
        with self.assertRaises(CryptoError):
            AesGcmCrypto(new_key()).open(blob)

    def test_tampered_blob_raises(self):
        blob = bytearray(AesGcmCrypto(self.key).seal(b"secret"))
        blob[-1] ^= 0xFF
        with self.assertRaises(CryptoError):
            AesGcmCrypto(self.key).open(bytes(blob))

    def test_reads_clear_blob(self):
        """Une base écrite en clair reste lisible après passage en chiffré."""
        clear = NullCrypto().seal(b"ancien")
        self.assertEqual(AesGcmCrypto(self.key).open(clear), b"ancien")

    def test_rejects_bad_key_length(self):
        with self.assertRaises(CryptoError):
            AesGcmCrypto(b"trop court")

    def test_rejects_unknown_magic(self):
        with self.assertRaises(CryptoError):
            AesGcmCrypto(self.key).open(b"ZZdonnees")

    def test_unexpected_error_is_not_disguised_as_a_bad_key(self):
        """Un bug de programmation doit remonter tel quel, pas en CryptoError."""
        box = AesGcmCrypto(self.key)
        blob = box.seal(b"secret")

        class Boom:
            # AESGCM est adossé à Rust : `decrypt` y est en lecture seule.
            # On remplace donc l'objet entier, pas sa méthode.
            def decrypt(self, *args, **kwargs):
                raise RuntimeError("bug interne")

        box._aes = Boom()
        with self.assertRaises(RuntimeError):
            box.open(blob)


class TestBuildCrypto(unittest.TestCase):
    def test_clear_mode(self):
        self.assertIsInstance(build_crypto("clear", None), NullCrypto)

    def test_encrypted_mode(self):
        self.assertIsInstance(build_crypto("encrypted", new_key()), AesGcmCrypto)

    def test_ephemeral_mode(self):
        self.assertIsInstance(build_crypto("ephemeral", new_key()), AesGcmCrypto)

    def test_encrypted_without_key_raises(self):
        with self.assertRaises(CryptoError):
            build_crypto("encrypted", None)

    def test_unknown_mode_raises(self):
        with self.assertRaises(CryptoError):
            build_crypto("magique", None)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils échouent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_crypto.py" -v
```

Attendu : `ModuleNotFoundError: No module named 'script.todo.mail.crypto'`.

- [ ] **Step 5: Implémenter `crypto.py`**

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Scellement du cache courriel.

Une enveloppe AUTO-DESCRIPTIVE précède chaque donnée : le premier octet-paire
dit comment lire la suite. Conséquence voulue : une base écrite en clair reste
lisible après passage en mode chiffré, et l'inverse échoue bruyamment plutôt
que de rendre du charabia.

    clair    b"P0" + donnees
    chiffre  b"E1" + nonce(12) + AES-256-GCM(chiffre || tag)
"""
from __future__ import annotations

import os

CLEAR_MAGIC = b"P0"
SEALED_MAGIC = b"E1"
NONCE_LEN = 12
KEY_LEN = 32


class CryptoError(Exception):
    """Clé absente, clé fausse, enveloppe inconnue ou donnée altérée."""


def new_key() -> bytes:
    """Une clé AES-256 tirée du générateur du système."""
    return os.urandom(KEY_LEN)


class MailCrypto:
    """Interface commune. `open` sait toujours lire une enveloppe en clair."""

    def seal(self, data: bytes) -> bytes:
        raise NotImplementedError

    def open(self, blob: bytes) -> bytes:
        raise NotImplementedError

    @staticmethod
    def _split(blob: bytes) -> tuple[bytes, bytes]:
        if not isinstance(blob, (bytes, bytearray)) or len(blob) < 2:
            raise CryptoError("enveloppe trop courte")
        return bytes(blob[:2]), bytes(blob[2:])


class NullCrypto(MailCrypto):
    """Mode `clear` : on marque, on ne chiffre pas."""

    def seal(self, data: bytes) -> bytes:
        return CLEAR_MAGIC + data

    def open(self, blob: bytes) -> bytes:
        magic, body = self._split(blob)
        if magic == CLEAR_MAGIC:
            return body
        if magic == SEALED_MAGIC:
            raise CryptoError(
                "donnée chiffrée lue en mode clair : la clé du compte manque"
            )
        raise CryptoError(f"enveloppe inconnue : {magic!r}")


class AesGcmCrypto(MailCrypto):
    """Modes `encrypted` et `ephemeral` : AES-256-GCM, nonce neuf à chaque appel."""

    def __init__(self, key: bytes) -> None:
        if not isinstance(key, (bytes, bytearray)) or len(key) != KEY_LEN:
            raise CryptoError(f"la clé doit faire {KEY_LEN} octets")
        try:
            from cryptography.exceptions import InvalidTag
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:  # pragma: no cover - dépendance absente
            raise CryptoError("le paquet cryptography n'est pas installé") from exc
        self._aes = AESGCM(bytes(key))
        self._invalid_tag = InvalidTag

    def seal(self, data: bytes) -> bytes:
        nonce = os.urandom(NONCE_LEN)
        return SEALED_MAGIC + nonce + self._aes.encrypt(nonce, data, None)

    def open(self, blob: bytes) -> bytes:
        magic, body = self._split(blob)
        if magic == CLEAR_MAGIC:
            return body
        if magic != SEALED_MAGIC:
            raise CryptoError(f"enveloppe inconnue : {magic!r}")
        nonce, payload = body[:NONCE_LEN], body[NONCE_LEN:]
        try:
            return self._aes.decrypt(nonce, payload, None)
        except self._invalid_tag as exc:
            raise CryptoError(
                "déchiffrement refusé : clé fausse ou donnée altérée"
            ) from exc
        except ValueError as exc:
            raise CryptoError(f"enveloppe illisible : {exc}") from exc
        # Toute autre exception remonte telle quelle : un bug de programmation
        # ne doit JAMAIS se déguiser en « mauvaise clé ».


def build_crypto(mode: str, key: bytes | None) -> MailCrypto:
    """La boîte qui correspond au mode de cache d'un compte."""
    if mode == "clear":
        return NullCrypto()
    if mode in ("encrypted", "ephemeral"):
        if key is None:
            raise CryptoError(f"le mode {mode} exige une clé")
        return AesGcmCrypto(key)
    raise CryptoError(f"mode de cache inconnu : {mode}")
```

- [ ] **Step 6: Lancer les tests, vérifier qu'ils passent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_crypto.py" -v
```

Attendu : `OK`, 18 tests.

- [ ] **Step 7: Formater et commiter**

```bash
make format
git add script/todo/mail/__init__.py script/todo/mail/crypto.py \
        test/test_mail_crypto.py requirement/erplibre_require-ments.txt
git commit -m "[ADD] mail: self-describing envelope for the cache at rest"
```

---

### Task 2: Coffre à secrets

**Files:**
- Create: `script/todo/mail/secrets.py`
- Create: `test/test_mail_secrets.py`

**Interfaces:**
- Consumes: rien (`KdbxManager` est injecté, pas importé en dur pour les tests).
- Produces:
  - `class SecretError(Exception)`
  - `keyring_backend_name() -> str` — nom pleinement qualifié de la classe du backend actif
  - `keyring_is_safe() -> bool` — faux pour `keyrings.alt.*` et `keyring.backends.fail.*`
  - `create_kdbx(path: str, password: str) -> None`
  - `class SecretStore` :
    - `__init__(self, kdbx_manager=None, use_keyring: bool = True)`
    - `get(self, ref: str) -> str | None`
    - `set(self, ref: str, secret: str) -> None`
    - `delete(self, ref: str) -> None`
    - `available_backends(self) -> list[str]`
  - Format de référence : `"kdbx:ERPLibre/Mail/<compte>"` ou `"keyring:<compte>"`

- [ ] **Step 1: Écrire les tests qui échouent**

`test/test_mail_secrets.py` :

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from script.todo.mail.secrets import (
    SecretError,
    SecretStore,
    create_kdbx,
    keyring_is_safe,
)


class FakeKeyringBackend:
    """Imite un backend keyring, sans toucher au trousseau de la machine."""

    def __init__(self, name="keyring.backends.SecretService.Keyring"):
        self.__class__.__module__ = name.rsplit(".", 1)[0]
        self._name = name
        self.store = {}


class TestKeyringSafety(unittest.TestCase):
    def _with_backend(self, module_name, class_name):
        backend = MagicMock()
        type(backend).__module__ = module_name
        type(backend).__qualname__ = class_name
        return backend

    def test_secretservice_is_safe(self):
        backend = self._with_backend("keyring.backends.SecretService", "Keyring")
        with patch("keyring.get_keyring", return_value=backend):
            self.assertTrue(keyring_is_safe())

    def test_macos_is_safe(self):
        backend = self._with_backend("keyring.backends.macOS", "Keyring")
        with patch("keyring.get_keyring", return_value=backend):
            self.assertTrue(keyring_is_safe())

    def test_windows_is_safe(self):
        backend = self._with_backend("keyring.backends.Windows", "WinVaultKeyring")
        with patch("keyring.get_keyring", return_value=backend):
            self.assertTrue(keyring_is_safe())

    def test_plaintext_alt_is_refused(self):
        backend = self._with_backend("keyrings.alt.file", "PlaintextKeyring")
        with patch("keyring.get_keyring", return_value=backend):
            self.assertFalse(keyring_is_safe())

    def test_fail_backend_is_refused(self):
        backend = self._with_backend("keyring.backends.fail", "Keyring")
        with patch("keyring.get_keyring", return_value=backend):
            self.assertFalse(keyring_is_safe())

    def test_unknown_backend_is_refused(self):
        """Par défaut on refuse : un backend qu'on ne connaît pas peut écrire en clair."""
        backend = self._with_backend("un.paquet.inconnu", "Keyring")
        with patch("keyring.get_keyring", return_value=backend):
            self.assertFalse(keyring_is_safe())


class TestKdbxRoundtrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "test.kdbx")
        create_kdbx(self.path, "motdepasse")
        from pykeepass import PyKeePass

        self.kp = PyKeePass(self.path, password="motdepasse")
        manager = MagicMock()
        manager.get_kdbx.return_value = self.kp
        self.store = SecretStore(kdbx_manager=manager, use_keyring=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_created_file_exists(self):
        self.assertTrue(os.path.exists(self.path))

    def test_set_then_get(self):
        self.store.set("kdbx:ERPLibre/Mail/perso", "hunter2")
        self.assertEqual(self.store.get("kdbx:ERPLibre/Mail/perso"), "hunter2")

    def test_set_creates_nested_groups(self):
        self.store.set("kdbx:ERPLibre/Mail/travail", "s3cr3t")
        groups = [g.name for g in self.kp.groups]
        self.assertIn("ERPLibre", groups)
        self.assertIn("Mail", groups)

    def test_set_twice_overwrites(self):
        self.store.set("kdbx:ERPLibre/Mail/perso", "ancien")
        self.store.set("kdbx:ERPLibre/Mail/perso", "nouveau")
        self.assertEqual(self.store.get("kdbx:ERPLibre/Mail/perso"), "nouveau")

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.store.get("kdbx:ERPLibre/Mail/absent"))

    def test_delete(self):
        self.store.set("kdbx:ERPLibre/Mail/perso", "hunter2")
        self.store.delete("kdbx:ERPLibre/Mail/perso")
        self.assertIsNone(self.store.get("kdbx:ERPLibre/Mail/perso"))

    def test_binary_key_survives_base64(self):
        """La clé de cache est stockée en base64 : 32 octets bruts doivent revenir intacts."""
        import base64

        raw = bytes(range(32))
        self.store.set("kdbx:ERPLibre/Mail/perso/cache-key", base64.b64encode(raw).decode())
        got = self.store.get("kdbx:ERPLibre/Mail/perso/cache-key")
        self.assertEqual(base64.b64decode(got), raw)


class TestKeyringBranch(unittest.TestCase):
    def setUp(self):
        self.store = SecretStore(kdbx_manager=None, use_keyring=True)

    def test_set_and_get_through_keyring(self):
        vault = {}
        with patch("script.todo.mail.secrets.keyring_is_safe", return_value=True), patch(
            "keyring.set_password", side_effect=lambda s, u, p: vault.__setitem__((s, u), p)
        ), patch("keyring.get_password", side_effect=lambda s, u: vault.get((s, u))):
            self.store.set("keyring:perso", "hunter2")
            self.assertEqual(self.store.get("keyring:perso"), "hunter2")

    def test_refuses_unsafe_backend(self):
        # `keyring.get_keyring` est patché AUSSI : le message d'erreur passe par
        # keyring_backend_name(), qui interrogerait sinon le vrai trousseau.
        with patch(
            "script.todo.mail.secrets.keyring_is_safe", return_value=False
        ), patch("keyring.get_keyring", return_value=MagicMock()):
            with self.assertRaises(SecretError) as ctx:
                self.store.set("keyring:perso", "hunter2")
        self.assertIn("clair", str(ctx.exception))


class TestRefParsing(unittest.TestCase):
    def setUp(self):
        self.store = SecretStore(kdbx_manager=None, use_keyring=False)

    def test_unknown_scheme_raises(self):
        with self.assertRaises(SecretError):
            self.store.get("magique:perso")

    def test_missing_scheme_raises(self):
        with self.assertRaises(SecretError):
            self.store.get("perso")

    def test_no_backend_available_raises(self):
        with self.assertRaises(SecretError):
            self.store.set("keyring:perso", "x")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_secrets.py" -v
```

Attendu : `ModuleNotFoundError: No module named 'script.todo.mail.secrets'`.

- [ ] **Step 3: Implémenter `secrets.py`**

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Où vivent les mots de passe courriel.

Deux coffres, dans cet ordre : le kdbx du dépôt (déjà utilisé par le CLI pour
OpenAI et les comptes Odoo), puis le trousseau du système.

Le trousseau système n'est accepté QUE si son backend chiffre vraiment. Sans
service de secrets — SSH, conteneur, poste sans session graphique — `keyring`
retombe sur `keyrings.alt`, qui écrit le mot de passe en clair dans un fichier.
L'accepter en silence serait un piège, donc on refuse et on le dit.

Référence de secret : "<coffre>:<chemin>"
    kdbx:ERPLibre/Mail/perso              -> groupe ERPLibre > Mail, entrée perso
    kdbx:ERPLibre/Mail/perso/cache-key    -> ... entrée cache-key
    keyring:perso                         -> service "erplibre-mail", user perso
"""
from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)

KEYRING_SERVICE = "erplibre-mail"

# Backends dont on sait qu'ils chiffrent. Liste blanche volontaire : un
# backend inconnu est refusé, parce qu'on ne peut pas prouver qu'il chiffre.
SAFE_BACKENDS = {
    ("keyring.backends.SecretService", "Keyring"),
    ("keyring.backends.macOS", "Keyring"),
    ("keyring.backends.Windows", "WinVaultKeyring"),
    ("keyring.backends.kwallet", "DBusKeyring"),
}


class SecretError(Exception):
    """Aucun coffre utilisable, ou référence malformée."""


def keyring_backend_name() -> str:
    """Nom pleinement qualifié du backend keyring actif, "" s'il est absent."""
    try:
        import keyring
    except ImportError:
        return ""
    backend = keyring.get_keyring()
    cls = type(backend)
    return f"{cls.__module__}.{cls.__qualname__}"


def keyring_is_safe() -> bool:
    """Vrai seulement si le backend actif chiffre pour de bon."""
    try:
        import keyring
    except ImportError:
        return False
    cls = type(keyring.get_keyring())
    return (cls.__module__, cls.__qualname__) in SAFE_BACKENDS


def create_kdbx(path: str, password: str) -> None:
    """Crée une base KeePass vide. Refuse d'écraser un fichier existant."""
    import os

    from pykeepass import create_database

    if os.path.exists(path):
        raise SecretError(f"le fichier existe déjà : {path}")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    create_database(path, password=password)
    os.chmod(path, 0o600)


class SecretStore:
    """Lecture et écriture de secrets, par référence."""

    def __init__(self, kdbx_manager=None, use_keyring: bool = True) -> None:
        self._kdbx_manager = kdbx_manager
        self._use_keyring = use_keyring

    # -- API publique ---------------------------------------------------

    def available_backends(self) -> list[str]:
        found = []
        if self._kdbx_manager is not None:
            found.append("kdbx")
        if self._use_keyring and keyring_is_safe():
            found.append("keyring")
        return found

    def get(self, ref: str) -> str | None:
        scheme, path = self._parse(ref)
        if scheme == "kdbx":
            entry = self._kdbx_entry(path, create=False)
            return entry.password if entry else None
        return self._keyring_call("get_password", path)

    def set(self, ref: str, secret: str) -> None:
        scheme, path = self._parse(ref)
        if scheme == "kdbx":
            entry = self._kdbx_entry(path, create=True)
            entry.password = secret
            self._kdbx().save()
            return
        self._keyring_call("set_password", path, secret)

    def delete(self, ref: str) -> None:
        scheme, path = self._parse(ref)
        if scheme == "kdbx":
            entry = self._kdbx_entry(path, create=False)
            if entry:
                self._kdbx().delete_entry(entry)
                self._kdbx().save()
            return
        self._keyring_call("delete_password", path)

    # -- Détail ---------------------------------------------------------

    @staticmethod
    def _parse(ref: str) -> tuple[str, str]:
        scheme, sep, path = (ref or "").partition(":")
        if not sep or scheme not in ("kdbx", "keyring") or not path:
            raise SecretError(f"référence de secret invalide : {ref!r}")
        return scheme, path

    def _kdbx(self):
        if self._kdbx_manager is None:
            raise SecretError("aucun fichier kdbx configuré")
        kp = self._kdbx_manager.get_kdbx()
        if kp is None:
            raise SecretError("le fichier kdbx n'a pas pu être ouvert")
        return kp

    def _kdbx_entry(self, path: str, create: bool):
        """`path` = "Groupe/SousGroupe/Titre". Crée les groupes au besoin."""
        kp = self._kdbx()
        *group_names, title = path.split("/")
        group = kp.root_group
        for name in group_names:
            found = next(
                (g for g in group.subgroups if g.name == name), None
            )
            if found is None:
                if not create:
                    return None
                found = kp.add_group(group, name)
            group = found
        entry = next((e for e in group.entries if e.title == title), None)
        if entry is None and create:
            entry = kp.add_entry(group, title, "", "")
        return entry

    def _keyring_call(self, func_name: str, *args):
        if not self._use_keyring:
            raise SecretError("aucun coffre disponible : ni kdbx, ni trousseau système")
        if not keyring_is_safe():
            raise SecretError(
                "le trousseau du système écrirait le mot de passe en clair "
                f"(backend {keyring_backend_name() or 'absent'}). "
                "Utilisez un fichier kdbx, ou déverrouillez un vrai trousseau."
            )
        import keyring

        return getattr(keyring, func_name)(KEYRING_SERVICE, *args)
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_secrets.py" -v
```

Attendu : `OK`, 18 tests. La signature `pykeepass.create_database(filename, password=None, keyfile=None, transformed_key=None)` a été vérifiée dans `.venv.erplibre` — pas d'ajustement d'import à prévoir.

- [ ] **Step 5: Formater et commiter**

```bash
make format
git add script/todo/mail/secrets.py test/test_mail_secrets.py
git commit -m "[ADD] mail: secret store, kdbx first and a keyring that must prove it encrypts"
```

---

### Task 3: Comptes, préréglages, générateur de modèle

**Files:**
- Create: `script/todo/mail/accounts.py`
- Create: `test/test_mail_accounts.py`

**Interfaces:**
- Consumes: rien de la tâche 2 (le `secret_ref` n'est qu'une chaîne ici).
- Produces:
  - `PRESETS: dict[str, dict]` — clés `gmail`, `outlook`, `icloud`, `generic`
  - `@dataclass ServerConf(host: str, port: int, security: str, user: str)`, `security` ∈ `{"ssl", "starttls", "none"}`
  - `@dataclass Account(name, email, display_name, preset, imap: ServerConf, smtp: ServerConf, secret_ref, cache_mode: str | None, sent_folder: str, enabled: bool)`
  - `Account.from_dict(d: dict) -> Account`, `Account.to_dict(self) -> dict`
  - `Account.cache_key_ref(self) -> str` — `f"{secret_ref}/cache-key"`
  - `accounts_path() -> Path` — `~/.erplibre/mail/accounts.json`
  - `load(path: Path | None = None) -> list[Account]`
  - `save(accounts: list[Account], path: Path | None = None) -> None`
  - `find(accounts: list[Account], name: str) -> Account | None`
  - `account_from_preset(name, email, preset_key, *, user=None, display_name="", vault="kdbx") -> Account`
  - `write_template(path: Path | None = None, force: bool = False) -> Path`
  - `class AccountError(Exception)`

- [ ] **Step 1: Écrire les tests qui échouent**

`test/test_mail_accounts.py` :

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import (
    PRESETS,
    Account,
    AccountError,
    account_from_preset,
    find,
    load,
    save,
    write_template,
)


class TestPresets(unittest.TestCase):
    def test_four_presets(self):
        self.assertEqual(
            set(PRESETS), {"gmail", "outlook", "icloud", "generic"}
        )

    def test_gmail_servers(self):
        self.assertEqual(PRESETS["gmail"]["imap"]["host"], "imap.gmail.com")
        self.assertEqual(PRESETS["gmail"]["imap"]["port"], 993)
        self.assertEqual(PRESETS["gmail"]["smtp"]["host"], "smtp.gmail.com")
        self.assertEqual(PRESETS["gmail"]["smtp"]["port"], 587)

    def test_security_values_are_known(self):
        for key, preset in PRESETS.items():
            for proto in ("imap", "smtp"):
                self.assertIn(
                    preset[proto]["security"],
                    ("ssl", "starttls", "none"),
                    f"{key}.{proto}",
                )

    def test_app_password_flag(self):
        self.assertTrue(PRESETS["gmail"]["app_password"])
        self.assertTrue(PRESETS["icloud"]["app_password"])
        self.assertFalse(PRESETS["generic"]["app_password"])


class TestAccountFromPreset(unittest.TestCase):
    def test_fills_servers_and_user(self):
        acc = account_from_preset("perso", "moi@gmail.com", "gmail")
        self.assertEqual(acc.imap.host, "imap.gmail.com")
        self.assertEqual(acc.imap.user, "moi@gmail.com")
        self.assertEqual(acc.smtp.user, "moi@gmail.com")

    def test_user_override(self):
        acc = account_from_preset(
            "perso", "moi@x.ca", "generic", user="login-different"
        )
        self.assertEqual(acc.imap.user, "login-different")

    def test_secret_ref_defaults_to_kdbx(self):
        acc = account_from_preset("perso", "moi@x.ca", "generic")
        self.assertEqual(acc.secret_ref, "kdbx:ERPLibre/Mail/perso")

    def test_secret_ref_keyring(self):
        acc = account_from_preset(
            "perso", "moi@x.ca", "generic", vault="keyring"
        )
        self.assertEqual(acc.secret_ref, "keyring:perso")

    def test_cache_key_ref(self):
        acc = account_from_preset("perso", "moi@x.ca", "generic")
        self.assertEqual(
            acc.cache_key_ref(), "kdbx:ERPLibre/Mail/perso/cache-key"
        )

    def test_cache_mode_inherits_by_default(self):
        self.assertIsNone(
            account_from_preset("perso", "moi@x.ca", "generic").cache_mode
        )

    def test_unknown_preset_raises(self):
        with self.assertRaises(AccountError):
            account_from_preset("perso", "moi@x.ca", "aol")

    def test_empty_name_raises(self):
        with self.assertRaises(AccountError):
            account_from_preset("", "moi@x.ca", "generic")

    def test_name_with_slash_raises(self):
        """Le nom sert de segment de chemin et de référence kdbx."""
        with self.assertRaises(AccountError):
            account_from_preset("per/so", "moi@x.ca", "generic")


class TestRoundtrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "accounts.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_then_load(self):
        acc = account_from_preset("perso", "moi@gmail.com", "gmail")
        save([acc], self.path)
        loaded = load(self.path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].to_dict(), acc.to_dict())

    def test_file_is_0600(self):
        save([account_from_preset("perso", "moi@x.ca", "generic")], self.path)
        mode = stat.S_IMODE(os.stat(self.path).st_mode)
        self.assertEqual(mode, 0o600)

    def test_parent_dir_is_0700(self):
        nested = Path(self.tmp.name) / "mail" / "accounts.json"
        save([account_from_preset("perso", "moi@x.ca", "generic")], nested)
        mode = stat.S_IMODE(os.stat(nested.parent).st_mode)
        self.assertEqual(mode, 0o700)

    def test_load_missing_file_returns_empty(self):
        self.assertEqual(load(Path(self.tmp.name) / "absent.json"), [])

    def test_no_password_key_is_written(self):
        save([account_from_preset("perso", "moi@x.ca", "generic")], self.path)
        raw = self.path.read_text()
        self.assertNotIn("password", raw.lower())

    def test_corrupt_json_raises(self):
        self.path.write_text("{ pas du json")
        with self.assertRaises(AccountError):
            load(self.path)

    def test_duplicate_name_raises_on_save(self):
        acc = account_from_preset("perso", "moi@x.ca", "generic")
        with self.assertRaises(AccountError):
            save([acc, acc], self.path)

    def test_find(self):
        accs = [
            account_from_preset("perso", "a@x.ca", "generic"),
            account_from_preset("travail", "b@x.ca", "generic"),
        ]
        self.assertEqual(find(accs, "travail").email, "b@x.ca")
        self.assertIsNone(find(accs, "absent"))


class TestTemplate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "accounts.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_valid_json(self):
        write_template(self.path)
        data = json.loads(self.path.read_text())
        self.assertEqual(data["version"], 1)

    def test_has_one_example_per_preset(self):
        write_template(self.path)
        data = json.loads(self.path.read_text())
        presets = {a["preset"] for a in data["accounts"]}
        self.assertEqual(presets, set(PRESETS))

    def test_examples_are_disabled(self):
        """Un modèle ne doit rien tenter de synchroniser tel quel."""
        write_template(self.path)
        data = json.loads(self.path.read_text())
        self.assertTrue(all(not a["enabled"] for a in data["accounts"]))

    def test_carries_comments(self):
        write_template(self.path)
        data = json.loads(self.path.read_text())
        self.assertIn("_comment", data)

    def test_refuses_to_overwrite(self):
        self.path.write_text("{}")
        with self.assertRaises(AccountError):
            write_template(self.path)

    def test_force_overwrites(self):
        self.path.write_text("{}")
        write_template(self.path, force=True)
        self.assertIn("accounts", json.loads(self.path.read_text()))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_accounts.py" -v
```

Attendu : `ModuleNotFoundError: No module named 'script.todo.mail.accounts'`.

- [ ] **Step 3: Implémenter `accounts.py`**

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les comptes courriel : description, préréglages, fichier de config.

`accounts.json` ne contient QUE ce qui n'est pas secret. Le mot de passe vit
dans le coffre (voir `secrets.py`) et le fichier n'en garde qu'une référence.
Le fichier reste donc lisible, éditable à la main et réparable, sans devenir
un endroit d'où une fuite ferait mal.

Les préréglages `gmail`, `outlook` et `icloud` supposent un MOT DE PASSE
D'APPLICATION : l'authentification simple ne passe plus autrement chez ces
fournisseurs. C'est la limite assumée de la phase 1 ; la phase 2 apporte OAuth.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1
SECURITIES = ("ssl", "starttls", "none")

PRESETS: dict[str, dict] = {
    "gmail": {
        "label": "Google / Gmail",
        "imap": {"host": "imap.gmail.com", "port": 993, "security": "ssl"},
        "smtp": {"host": "smtp.gmail.com", "port": 587, "security": "starttls"},
        "sent_folder": "[Gmail]/Sent Mail",
        "app_password": True,
        "note": (
            "Exige la validation en deux étapes puis un mot de passe"
            " d'application (myaccount.google.com > Sécurité)."
        ),
    },
    "outlook": {
        "label": "Microsoft / Outlook",
        "imap": {"host": "outlook.office365.com", "port": 993, "security": "ssl"},
        "smtp": {"host": "smtp.office365.com", "port": 587, "security": "starttls"},
        "sent_folder": "Sent Items",
        "app_password": True,
        "note": (
            "Microsoft ferme l'authentification simple sur les comptes grand"
            " public : OAuth arrive en phase 2."
        ),
    },
    "icloud": {
        "label": "Apple / iCloud",
        "imap": {"host": "imap.mail.me.com", "port": 993, "security": "ssl"},
        "smtp": {"host": "smtp.mail.me.com", "port": 587, "security": "starttls"},
        "sent_folder": "Sent Messages",
        "app_password": True,
        "note": (
            "Exige un mot de passe pour application"
            " (account.apple.com > Connexion et sécurité)."
        ),
    },
    "generic": {
        "label": "Serveur standard (IMAP/SMTP)",
        "imap": {"host": "", "port": 993, "security": "ssl"},
        "smtp": {"host": "", "port": 587, "security": "starttls"},
        "sent_folder": "Sent",
        "app_password": False,
        "note": "Saisissez les serveurs de votre fournisseur.",
    },
}


class AccountError(Exception):
    """Configuration de compte invalide, illisible ou en conflit."""


@dataclass
class ServerConf:
    host: str
    port: int
    security: str
    user: str

    def __post_init__(self) -> None:
        if self.security not in SECURITIES:
            raise AccountError(
                f"sécurité inconnue : {self.security!r} (attendu {SECURITIES})"
            )


@dataclass
class Account:
    name: str
    email: str
    imap: ServerConf
    smtp: ServerConf
    secret_ref: str
    display_name: str = ""
    preset: str = "generic"
    cache_mode: str | None = None
    sent_folder: str = "Sent"
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.name:
            raise AccountError("un compte doit avoir un nom")
        if "/" in self.name or os.sep in self.name or self.name.startswith("."):
            raise AccountError(
                f"nom de compte invalide : {self.name!r}"
                " (il sert de nom de dossier et de référence de coffre)"
            )
        if self.cache_mode not in (None, "clear", "encrypted", "ephemeral"):
            raise AccountError(f"mode de cache inconnu : {self.cache_mode!r}")

    def cache_key_ref(self) -> str:
        """Référence de la clé de chiffrement, distincte du mot de passe."""
        return f"{self.secret_ref}/cache-key"

    def from_header(self) -> str:
        return f"{self.display_name} <{self.email}>" if self.display_name else self.email

    def to_dict(self) -> dict:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, d: dict) -> "Account":
        try:
            return cls(
                name=d["name"],
                email=d["email"],
                imap=ServerConf(**d["imap"]),
                smtp=ServerConf(**d["smtp"]),
                secret_ref=d["secret_ref"],
                display_name=d.get("display_name", ""),
                preset=d.get("preset", "generic"),
                cache_mode=d.get("cache_mode"),
                sent_folder=d.get("sent_folder", "Sent"),
                enabled=d.get("enabled", True),
            )
        except (KeyError, TypeError) as exc:
            raise AccountError(f"compte illisible : {exc}") from exc


def accounts_path() -> Path:
    return Path(os.path.expanduser("~/.erplibre/mail/accounts.json"))


def _prepare_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)


def account_from_preset(
    name: str,
    email: str,
    preset_key: str,
    *,
    user: str | None = None,
    display_name: str = "",
    vault: str = "kdbx",
) -> Account:
    preset = PRESETS.get(preset_key)
    if preset is None:
        raise AccountError(f"préréglage inconnu : {preset_key!r}")
    login = user or email
    ref = (
        f"kdbx:ERPLibre/Mail/{name}" if vault == "kdbx" else f"keyring:{name}"
    )
    return Account(
        name=name,
        email=email,
        display_name=display_name,
        preset=preset_key,
        imap=ServerConf(user=login, **preset["imap"]),
        smtp=ServerConf(user=login, **preset["smtp"]),
        secret_ref=ref,
        cache_mode=None,
        sent_folder=preset["sent_folder"],
        enabled=True,
    )


def load(path: Path | None = None) -> list[Account]:
    path = Path(path) if path else accounts_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except ValueError as exc:
        raise AccountError(f"{path} n'est pas du JSON valide : {exc}") from exc
    if not isinstance(data, dict):
        raise AccountError(f"{path} devrait contenir un objet JSON")
    return [Account.from_dict(d) for d in data.get("accounts", [])]


def save(accounts: list[Account], path: Path | None = None) -> None:
    path = Path(path) if path else accounts_path()
    names = [a.name for a in accounts]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise AccountError(f"noms de compte en double : {sorted(duplicates)}")
    _prepare_parent(path)
    payload = {
        "version": SCHEMA_VERSION,
        "default_account": names[0] if names else None,
        "accounts": [a.to_dict() for a in accounts],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    os.chmod(path, 0o600)


def find(accounts: list[Account], name: str) -> Account | None:
    return next((a for a in accounts if a.name == name), None)


def write_template(path: Path | None = None, force: bool = False) -> Path:
    """Écrit un accounts.json d'exemple, un compte désactivé par préréglage.

    JSON n'a pas de commentaires : les explications passent par des clés
    `_comment`, que `Account.from_dict` ignore.
    """
    path = Path(path) if path else accounts_path()
    if path.exists() and not force:
        raise AccountError(
            f"{path} existe déjà — relancez avec l'option de remplacement"
        )
    examples = []
    for key, preset in PRESETS.items():
        acc = account_from_preset(
            f"exemple-{key}", f"vous@exemple.ca", key
        ).to_dict()
        acc["enabled"] = False
        acc["_comment"] = preset["note"]
        examples.append(acc)
    payload = {
        "version": SCHEMA_VERSION,
        "_comment": (
            "Modèle ERPLibre. Aucun mot de passe ici : `secret_ref` pointe"
            " vers le coffre. Passez `enabled` à true une fois rempli."
            " `cache_mode` à null hérite du réglage général."
        ),
        "default_account": None,
        "accounts": examples,
    }
    _prepare_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    os.chmod(path, 0o600)
    return path
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_accounts.py" -v
```

Attendu : `OK`, 25 tests.

- [ ] **Step 5: Formater et commiter**

```bash
make format
git add script/todo/mail/accounts.py test/test_mail_accounts.py
git commit -m "[ADD] mail: account model, provider presets and a template generator"
```

---

### Task 4: Cache local — SQLite, fichiers `.eml`, trois modes

**Files:**
- Create: `script/todo/mail/store.py`
- Create: `test/test_mail_store.py`
- Modify: `script/todo/todo_prefs.py` (dictionnaire `DEFAULTS`)

**Interfaces:**
- Consumes: `crypto.build_crypto`, `crypto.new_key`, `crypto.CryptoError` (tâche 1) ; `accounts.Account` (tâche 3) ; `secrets.SecretStore` (tâche 2, injecté et optionnel).
- Produces:
  - `SCHEMA_VERSION: int = 1`
  - `EPHEMERAL_PREFIX: str = "erplibre-mail-"`
  - `resolve_mode(account: Account, prefs_get=None) -> str`
  - `cache_root(account: Account, mode: str, base: Path | None = None) -> Path`
  - `sweep_orphan_ephemeral(base: Path | None = None) -> int`
  - `folder_dirname(imap_name: str) -> str`
  - `@dataclass MessageMeta(uid: int, date: int, size: int, flags: str, msgid: str, frm: str, to: str, subject: str, snippet: str, has_body: bool = False)`
  - `class StoreError(Exception)`
  - `class Store` :
    - `__init__(self, account, *, mode=None, key=None, secrets=None, base=None)`
    - `open() -> None`, `close() -> None`, contexte `with`
    - `mode: str`, `root: Path` (attributs)
    - `upsert_folder(name, display="", role=None, uidvalidity=None, uidnext=None) -> int`
    - `folders() -> list[dict]`
    - `folder_state(name) -> dict | None`
    - `set_folder_state(name, **fields) -> None`
    - `purge_folder(name) -> None`
    - `upsert_messages(folder_id, metas: list[MessageMeta]) -> int`
    - `update_flags(folder_id, uid, flags: str) -> None`
    - `list_messages(folder_id, limit=500, offset=0) -> list[MessageMeta]`
    - `known_uids(folder_id, last_n=500) -> list[int]`
    - `write_body(folder_name, uid, raw: bytes) -> None`
    - `read_body(folder_name, uid) -> bytes | None`
    - `size_bytes() -> int`
    - `purge_all() -> None`
    - `cleanup() -> None`

- [ ] **Step 1: Ajouter les préférences**

Dans `script/todo/todo_prefs.py`, à la fin du dictionnaire `DEFAULTS` :

```python
    # Cache courriel : mode par DÉFAUT. Un compte peut le surcharger via
    # sa clé `cache_mode` dans accounts.json ; `null` là-bas veut dire
    # « hérite d'ici ». Valeurs : clear | encrypted | ephemeral.
    "mail_cache_mode": "clear",
    # Rafraîchissement automatique des boîtes, en secondes, ACTIF seulement
    # tant que le TUI courriel est à l'écran. 0 désactive.
    "mail_refresh_sec": 300,
```

- [ ] **Step 2: Écrire les tests qui échouent**

`test/test_mail_store.py` :

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.crypto import CryptoError, new_key
from script.todo.mail.store import (
    EPHEMERAL_PREFIX,
    MessageMeta,
    Store,
    StoreError,
    cache_root,
    folder_dirname,
    resolve_mode,
    sweep_orphan_ephemeral,
)


def meta(uid, subject="Sujet", frm="a@x.ca", date=1000, flags=""):
    return MessageMeta(
        uid=uid,
        date=date,
        size=42,
        flags=flags,
        msgid=f"<{uid}@x.ca>",
        frm=frm,
        to="moi@x.ca",
        subject=subject,
        snippet="debut du corps",
    )


class TestResolveMode(unittest.TestCase):
    def test_account_override_wins(self):
        acc = account_from_preset("perso", "a@x.ca", "generic")
        acc.cache_mode = "encrypted"
        self.assertEqual(resolve_mode(acc, lambda k, d=None: "clear"), "encrypted")

    def test_falls_back_to_general_default(self):
        acc = account_from_preset("perso", "a@x.ca", "generic")
        self.assertEqual(
            resolve_mode(acc, lambda k, d=None: "ephemeral"), "ephemeral"
        )

    def test_unknown_general_default_falls_back_to_clear(self):
        acc = account_from_preset("perso", "a@x.ca", "generic")
        self.assertEqual(resolve_mode(acc, lambda k, d=None: "magique"), "clear")


class TestFolderDirname(unittest.TestCase):
    def test_slash_is_escaped(self):
        self.assertNotIn("/", folder_dirname("[Gmail]/Sent Mail"))

    def test_is_reversible_enough_to_be_unique(self):
        self.assertNotEqual(
            folder_dirname("A/B"), folder_dirname("A_B")
        )

    def test_traversal_collapses_to_one_component(self):
        self.assertNotIn("/", folder_dirname("../../etc"))

    def test_degenerate_names_cannot_designate_the_parent(self):
        """`racine / ".."` remonterait d'un cran : ces noms sont réécrits."""
        for hostile in ("", ".", ".."):
            self.assertNotIn(folder_dirname(hostile), ("", ".", ".."))

    def test_dotted_hierarchy_stays_readable(self):
        """Le point sépare la hiérarchie chez beaucoup de serveurs IMAP."""
        self.assertEqual(folder_dirname("INBOX.Sent"), "INBOX.Sent")


class TestCacheRoot(unittest.TestCase):
    def test_persistent_modes_use_base(self):
        acc = account_from_preset("perso", "a@x.ca", "generic")
        with tempfile.TemporaryDirectory() as tmp:
            root = cache_root(acc, "clear", Path(tmp))
            self.assertEqual(root, Path(tmp) / "perso")

    def test_ephemeral_root_carries_the_pid(self):
        acc = account_from_preset("perso", "a@x.ca", "generic")
        with tempfile.TemporaryDirectory() as tmp:
            root = cache_root(acc, "ephemeral", Path(tmp))
            self.assertIn(f"{EPHEMERAL_PREFIX}{os.getpid()}", str(root))


class StoreCase(unittest.TestCase):
    """Socle commun : un compte, une base temporaire, mode paramétrable."""

    mode = "clear"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "moi@x.ca", "generic")
        self.key = new_key() if self.mode != "clear" else None
        self.store = Store(
            self.account,
            mode=self.mode,
            key=self.key,
            base=Path(self.tmp.name),
        )
        self.store.open()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()


class TestSchema(StoreCase):
    def test_db_file_created(self):
        self.assertTrue((self.store.root / "cache.db").exists())

    def test_root_is_0700(self):
        import stat

        self.assertEqual(
            stat.S_IMODE(os.stat(self.store.root).st_mode), 0o700
        )

    def test_reopen_is_idempotent(self):
        self.store.close()
        again = Store(
            self.account, mode=self.mode, key=self.key, base=Path(self.tmp.name)
        )
        again.open()
        again.close()


class TestFolders(StoreCase):
    def test_upsert_returns_id(self):
        fid = self.store.upsert_folder("INBOX", "INBOX", "inbox", 1, 10)
        self.assertIsInstance(fid, int)

    def test_upsert_twice_keeps_same_id(self):
        first = self.store.upsert_folder("INBOX")
        second = self.store.upsert_folder("INBOX")
        self.assertEqual(first, second)

    def test_folder_state(self):
        self.store.upsert_folder("INBOX", uidvalidity=7)
        state = self.store.folder_state("INBOX")
        self.assertEqual(state["uidvalidity"], 7)
        self.assertEqual(state["last_uid"], 0)

    def test_set_folder_state(self):
        self.store.upsert_folder("INBOX")
        self.store.set_folder_state("INBOX", last_uid=99, unseen=3)
        state = self.store.folder_state("INBOX")
        self.assertEqual(state["last_uid"], 99)
        self.assertEqual(state["unseen"], 3)

    def test_unknown_folder_state_is_none(self):
        self.assertIsNone(self.store.folder_state("ABSENT"))

    def test_folders_lists_them(self):
        self.store.upsert_folder("INBOX")
        self.store.upsert_folder("Sent")
        self.assertEqual({f["name"] for f in self.store.folders()}, {"INBOX", "Sent"})

    def test_display_is_null_until_one_is_known(self):
        """NULL veut dire « inconnu » : le lecteur retombe sur le nom IMAP."""
        self.store.upsert_folder("INBOX")
        self.assertIsNone(self.store.folder_state("INBOX")["display"])

    def test_partial_upsert_keeps_the_display_name(self):
        """Une resync qui ne repasse que le nom IMAP ne doit rien écraser."""
        self.store.upsert_folder("INBOX", "Boîte de réception")
        self.store.upsert_folder("INBOX")
        self.assertEqual(
            self.store.folder_state("INBOX")["display"], "Boîte de réception"
        )


class TestMessages(StoreCase):
    def setUp(self):
        super().setUp()
        self.fid = self.store.upsert_folder("INBOX")

    def test_upsert_then_list(self):
        self.store.upsert_messages(self.fid, [meta(1), meta(2)])
        got = self.store.list_messages(self.fid)
        self.assertEqual({m.uid for m in got}, {1, 2})

    def test_subject_survives_roundtrip(self):
        self.store.upsert_messages(self.fid, [meta(1, subject="Devis révisé")])
        self.assertEqual(self.store.list_messages(self.fid)[0].subject, "Devis révisé")

    def test_upsert_same_uid_updates(self):
        self.store.upsert_messages(self.fid, [meta(1, subject="ancien")])
        self.store.upsert_messages(self.fid, [meta(1, subject="nouveau")])
        got = self.store.list_messages(self.fid)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].subject, "nouveau")

    def test_sorted_by_date_desc(self):
        self.store.upsert_messages(
            self.fid, [meta(1, date=100), meta(2, date=300), meta(3, date=200)]
        )
        self.assertEqual([m.uid for m in self.store.list_messages(self.fid)], [2, 3, 1])

    def test_update_flags(self):
        self.store.upsert_messages(self.fid, [meta(1)])
        self.store.update_flags(self.fid, 1, "\\Seen")
        self.assertEqual(self.store.list_messages(self.fid)[0].flags, "\\Seen")

    def test_known_uids(self):
        self.store.upsert_messages(self.fid, [meta(1), meta(2), meta(3)])
        self.assertEqual(sorted(self.store.known_uids(self.fid)), [1, 2, 3])

    def test_limit_and_offset(self):
        self.store.upsert_messages(
            self.fid, [meta(i, date=i) for i in range(1, 6)]
        )
        self.assertEqual(
            [m.uid for m in self.store.list_messages(self.fid, limit=2)], [5, 4]
        )
        self.assertEqual(
            [m.uid for m in self.store.list_messages(self.fid, limit=2, offset=2)],
            [3, 2],
        )


class TestBodies(StoreCase):
    def test_write_then_read(self):
        self.store.upsert_folder("INBOX")
        self.store.write_body("INBOX", 1, b"From: a@x.ca\r\n\r\nBonjour")
        self.assertEqual(
            self.store.read_body("INBOX", 1), b"From: a@x.ca\r\n\r\nBonjour"
        )

    def test_missing_body_is_none(self):
        self.assertIsNone(self.store.read_body("INBOX", 404))

    def test_has_body_flag_is_set(self):
        fid = self.store.upsert_folder("INBOX")
        self.store.upsert_messages(fid, [meta(1)])
        self.store.write_body("INBOX", 1, b"corps")
        self.assertTrue(self.store.list_messages(fid)[0].has_body)

    def test_folder_with_slash(self):
        self.store.upsert_folder("[Gmail]/Sent Mail")
        self.store.write_body("[Gmail]/Sent Mail", 1, b"corps")
        self.assertEqual(self.store.read_body("[Gmail]/Sent Mail", 1), b"corps")


class TestPurge(StoreCase):
    def test_purge_folder_drops_rows_and_files(self):
        fid = self.store.upsert_folder("INBOX")
        self.store.upsert_messages(fid, [meta(1)])
        self.store.write_body("INBOX", 1, b"corps")
        self.store.purge_folder("INBOX")
        self.assertEqual(self.store.list_messages(fid), [])
        self.assertIsNone(self.store.read_body("INBOX", 1))

    def test_purge_folder_resets_last_uid(self):
        self.store.upsert_folder("INBOX")
        self.store.set_folder_state("INBOX", last_uid=50)
        self.store.purge_folder("INBOX")
        self.assertEqual(self.store.folder_state("INBOX")["last_uid"], 0)

    def test_purge_all(self):
        fid = self.store.upsert_folder("INBOX")
        self.store.upsert_messages(fid, [meta(1)])
        self.store.purge_all()
        self.assertEqual(self.store.folders(), [])

    def test_size_bytes_grows(self):
        before = self.store.size_bytes()
        self.store.upsert_folder("INBOX")
        self.store.write_body("INBOX", 1, b"x" * 5000)
        self.assertGreater(self.store.size_bytes(), before)


class TestEncryptedStore(TestMessages):
    """Le même contrat, en chiffré : rien ne doit changer du point de vue de l'appelant."""

    mode = "encrypted"

    def test_subject_absent_from_db_file(self):
        self.store.upsert_messages(self.fid, [meta(1, subject="CONFIDENTIEL")])
        self.store.close()
        raw = (self.store.root / "cache.db").read_bytes()
        self.assertNotIn(b"CONFIDENTIEL", raw)
        self.store.open()

    def test_body_file_is_encrypted(self):
        self.store.write_body("INBOX", 1, b"TEXTE SECRET")
        path = next((self.store.root).rglob("*.eml*"))
        self.assertNotIn(b"TEXTE SECRET", path.read_bytes())

    def test_date_stays_queryable_in_clear(self):
        """Le tri doit rester du SQL : la date n'est pas scellée."""
        self.store.upsert_messages(self.fid, [meta(1, date=12345)])
        rows = self.store._conn.execute(
            "SELECT date FROM messages WHERE uid = 1"
        ).fetchall()
        self.assertEqual(rows[0][0], 12345)


class TestWrongKey(unittest.TestCase):
    def test_reopening_with_another_key_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            acc = account_from_preset("perso", "a@x.ca", "generic")
            first = Store(acc, mode="encrypted", key=new_key(), base=Path(tmp))
            first.open()
            fid = first.upsert_folder("INBOX")
            first.upsert_messages(fid, [meta(1, subject="secret")])
            first.close()

            second = Store(acc, mode="encrypted", key=new_key(), base=Path(tmp))
            second.open()
            with self.assertRaises(CryptoError):
                second.list_messages(fid)
            second.close()


class TestEphemeral(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "a@x.ca", "generic")

    def tearDown(self):
        self.tmp.cleanup()

    def test_cleanup_removes_everything(self):
        store = Store(
            self.account, mode="ephemeral", key=new_key(), base=Path(self.tmp.name)
        )
        store.open()
        root = store.root
        store.write_body("INBOX", 1, b"corps")
        self.assertTrue(root.exists())
        store.close()
        store.cleanup()
        self.assertFalse(root.exists())

    def test_sweep_removes_dead_pid_dirs(self):
        base = Path(self.tmp.name)
        dead = base / f"{EPHEMERAL_PREFIX}999999999"
        dead.mkdir()
        alive = base / f"{EPHEMERAL_PREFIX}{os.getpid()}"
        alive.mkdir()
        removed = sweep_orphan_ephemeral(base)
        self.assertEqual(removed, 1)
        self.assertFalse(dead.exists())
        self.assertTrue(alive.exists())

    def test_sweep_ignores_foreign_dirs(self):
        base = Path(self.tmp.name)
        (base / "autre-chose").mkdir()
        self.assertEqual(sweep_orphan_ephemeral(base), 0)
        self.assertTrue((base / "autre-chose").exists())


class TestCorruptDatabase(unittest.TestCase):
    """Un open() raté ne doit pas laisser l'objet porteur d'un handle cassé."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "a@x.ca", "generic")
        root = Path(self.tmp.name) / "perso"
        root.mkdir(parents=True)
        (root / "cache.db").write_bytes(b"ceci n'est pas une base sqlite" * 40)

    def tearDown(self):
        self.tmp.cleanup()

    def test_open_raises_store_error(self):
        store = Store(self.account, mode="clear", base=Path(self.tmp.name))
        with self.assertRaises(StoreError):
            store.open()

    def test_failed_open_does_not_publish_the_connection(self):
        """Sinon le open() suivant réussirait en silence sur une base sans schéma."""
        store = Store(self.account, mode="clear", base=Path(self.tmp.name))
        with self.assertRaises(StoreError):
            store.open()
        with self.assertRaises(StoreError):
            store.open()


class TestEphemeralIsolation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.a = account_from_preset("perso", "a@x.ca", "generic")
        self.b = account_from_preset("travail", "b@x.ca", "generic")

    def tearDown(self):
        self.tmp.cleanup()

    def _store(self, account):
        store = Store(account, mode="ephemeral", key=new_key(), base=self.base)
        store.open()
        return store

    def test_cleanup_spares_the_sibling_account(self):
        """Le dossier par PID est partagé : l'effacer tuerait le voisin."""
        first, second = self._store(self.a), self._store(self.b)
        first.write_body("INBOX", 1, b"corps a")
        second.write_body("INBOX", 1, b"corps b")
        first.cleanup()
        self.assertFalse(first.root.exists())
        self.assertTrue(second.root.exists())
        self.assertEqual(second.read_body("INBOX", 1), b"corps b")
        second.cleanup()

    def test_last_cleanup_removes_the_pid_directory(self):
        first, second = self._store(self.a), self._store(self.b)
        pid_dir = first.root.parent
        first.cleanup()
        self.assertTrue(pid_dir.exists())
        second.cleanup()
        self.assertFalse(pid_dir.exists())

    def test_pid_directory_is_0700(self):
        """/dev/shm est en 1777 : le dossier par PID ne doit rien laisser voir."""
        import stat as stat_module

        store = self._store(self.a)
        mode = stat_module.S_IMODE(os.stat(store.root.parent).st_mode)
        self.assertEqual(mode, 0o700)
        store.cleanup()

    def test_symlinked_pid_directory_is_refused(self):
        """Un tiers peut pré-créer le chemin : on refuse de le suivre."""
        target = self.base / "ailleurs"
        target.mkdir()
        (self.base / f"{EPHEMERAL_PREFIX}{os.getpid()}").symlink_to(target)
        store = Store(self.a, mode="ephemeral", key=new_key(), base=self.base)
        with self.assertRaises(StoreError):
            store.open()


class TestKeyPersistence(unittest.TestCase):
    """Le seul chemin du module qui écrit de la matière de clé sur disque."""

    class FakeVault:
        def __init__(self):
            self.data = {}

        def get(self, ref):
            return self.data.get(ref)

        def set(self, ref, value):
            self.data[ref] = value

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.account = account_from_preset("perso", "a@x.ca", "generic")
        self.vault = self.FakeVault()

    def tearDown(self):
        self.tmp.cleanup()

    def _store(self):
        store = Store(
            self.account, mode="encrypted", secrets=self.vault, base=self.base
        )
        store.open()
        return store

    def test_first_open_stores_a_key_under_the_cache_key_ref(self):
        self._store().close()
        self.assertIn(self.account.cache_key_ref(), self.vault.data)

    def test_stored_key_is_base64_of_32_bytes(self):
        import base64

        self._store().close()
        raw = base64.b64decode(self.vault.data[self.account.cache_key_ref()])
        self.assertEqual(len(raw), 32)

    def test_second_store_reuses_the_stored_key(self):
        first = self._store()
        fid = first.upsert_folder("INBOX")
        first.upsert_messages(fid, [meta(1, subject="Devis")])
        first.close()

        second = self._store()
        self.assertEqual(second.list_messages(fid)[0].subject, "Devis")
        second.close()

    def test_key_is_not_regenerated_on_reopen(self):
        self._store().close()
        stored = self.vault.data[self.account.cache_key_ref()]
        self._store().close()
        self.assertEqual(self.vault.data[self.account.cache_key_ref()], stored)

    def test_key_never_lands_in_the_cache_file(self):
        import base64

        store = self._store()
        fid = store.upsert_folder("INBOX")
        store.upsert_messages(fid, [meta(1)])
        root = store.root
        store.close()
        raw = base64.b64decode(self.vault.data[self.account.cache_key_ref()])
        blob = (root / "cache.db").read_bytes()
        self.assertNotIn(raw, blob)
        self.assertNotIn(
            base64.b64encode(raw), blob
        )


class TestThreadSafety(unittest.TestCase):
    """Le TUI synchronise dans un thread de travail pendant que l'écran lit.

    Sans `check_same_thread=False` ET le verrou, la toute première passe de
    synchronisation lèverait `sqlite3.ProgrammingError`.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "a@x.ca", "generic")
        self.store = Store(self.account, mode="clear", base=Path(self.tmp.name))
        self.store.open()
        self.fid = self.store.upsert_folder("INBOX")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_read_from_another_thread(self):
        import threading

        erreurs = []

        def worker():
            try:
                self.store.folders()
            except Exception as exc:
                erreurs.append(f"{type(exc).__name__}: {exc}")

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertEqual(erreurs, [])

    def test_write_from_another_thread(self):
        import threading

        erreurs = []

        def worker():
            try:
                self.store.upsert_messages(self.fid, [meta(1)])
            except Exception as exc:
                erreurs.append(f"{type(exc).__name__}: {exc}")

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertEqual(erreurs, [])
        self.assertEqual(len(self.store.list_messages(self.fid)), 1)

    def test_concurrent_writers_all_land(self):
        """Le verrou sérialise : aucun upsert ne doit se perdre."""
        import threading

        def worker(start):
            self.store.upsert_messages(
                self.fid, [meta(uid) for uid in range(start, start + 20)]
            )

        threads = [
            threading.Thread(target=worker, args=(base,))
            for base in (1, 101, 201, 301)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(self.store.list_messages(self.fid, limit=500)), 80)


class TestKeyRequired(unittest.TestCase):
    def test_encrypted_without_key_or_secrets_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            acc = account_from_preset("perso", "a@x.ca", "generic")
            store = Store(acc, mode="encrypted", base=Path(tmp))
            with self.assertRaises(StoreError):
                store.open()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Lancer les tests, vérifier qu'ils échouent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_store.py" -v
```

Attendu : `ModuleNotFoundError: No module named 'script.todo.mail.store'`.

- [ ] **Step 4: Implémenter `store.py`**

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le cache courriel local : une base SQLite et des fichiers .eml par compte.

Une racine par compte, jamais une base partagée : c'est ce qui permet à un
compte d'être éphémère pendant qu'un autre persiste, sans mélanger deux modes
de chiffrement dans les mêmes lignes.

Ce qui reste EN CLAIR dans la base — uid, dossier, date, drapeaux, taille —
est exactement ce dont le SQL a besoin pour trier et filtrer. Ce qui identifie
des personnes — expéditeur, destinataires, sujet, extrait, Message-ID — est
scellé. Le Message-ID a en plus un haché salé par la clé, pour qu'on puisse
recoller les fils de discussion sans le lire.
"""
from __future__ import annotations

import base64
import hashlib
import os
import functools
import shutil
import sqlite3
import stat
import threading
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from script.todo.mail.crypto import build_crypto, new_key

SCHEMA_VERSION = 1
EPHEMERAL_PREFIX = "erplibre-mail-"
VALID_MODES = ("clear", "encrypted", "ephemeral")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);
CREATE TABLE IF NOT EXISTS folders (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  display     TEXT,
  role        TEXT,
  uidvalidity INTEGER,
  uidnext     INTEGER,
  last_uid    INTEGER NOT NULL DEFAULT 0,
  total       INTEGER NOT NULL DEFAULT 0,
  unseen      INTEGER NOT NULL DEFAULT 0,
  synced_at   INTEGER
);
CREATE TABLE IF NOT EXISTS messages (
  id             INTEGER PRIMARY KEY,
  folder_id      INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
  uid            INTEGER NOT NULL,
  date           INTEGER,
  size           INTEGER,
  flags          TEXT,
  has_body       INTEGER NOT NULL DEFAULT 0,
  msgid_hash     TEXT,
  sealed_msgid   BLOB,
  sealed_from    BLOB,
  sealed_to      BLOB,
  sealed_subject BLOB,
  sealed_snippet BLOB,
  UNIQUE(folder_id, uid)
);
CREATE INDEX IF NOT EXISTS idx_msg_date ON messages(folder_id, date DESC);
"""


class StoreError(Exception):
    """Cache inutilisable : clé manquante, base corrompue, disque refusé."""


def _locked(method):
    """Sérialise l'accès à la connexion SQLite.

    `check_same_thread=False` lève l'interdiction de la stdlib, mais ne rend
    pas la connexion sûre pour autant : c'est CE verrou qui la rend sûre. Le
    TUI synchronise dans un thread de travail pendant que l'écran lit le cache
    depuis le thread principal — les deux se croisent vraiment, ce n'est pas
    une précaution théorique.
    """

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


@dataclass
class MessageMeta:
    uid: int
    date: int
    size: int
    flags: str
    msgid: str
    frm: str
    to: str
    subject: str
    snippet: str
    has_body: bool = False


def resolve_mode(account, prefs_get=None) -> str:
    """Le mode du compte, sinon le défaut général, sinon `clear`.

    Un défaut général illisible ne doit pas empêcher d'ouvrir le cache :
    on retombe sur le mode le plus permissif, jamais sur une erreur.
    """
    if account.cache_mode in VALID_MODES:
        return account.cache_mode
    if prefs_get is None:
        from script.todo import todo_prefs

        prefs_get = todo_prefs.get
    general = prefs_get("mail_cache_mode", "clear")
    return general if general in VALID_MODES else "clear"


def default_base() -> Path:
    return Path(os.path.expanduser("~/.erplibre/mail"))


def ephemeral_base() -> Path:
    """/dev/shm quand il est inscriptible, sinon le dossier temporaire."""
    shm = Path("/dev/shm")
    if shm.is_dir() and os.access(shm, os.W_OK):
        return shm
    import tempfile

    return Path(tempfile.gettempdir())


def cache_root(account, mode: str, base: Path | None = None) -> Path:
    if mode == "ephemeral":
        base = Path(base) if base else ephemeral_base()
        return base / f"{EPHEMERAL_PREFIX}{os.getpid()}" / account.name
    base = Path(base) if base else default_base()
    return base / account.name


# Noms qui, seuls, désigneraient autre chose que le dossier voulu.
DEGENERATE_DIRNAMES = {"": "_", ".": "%2E", "..": "%2E%2E"}


def folder_dirname(imap_name: str) -> str:
    """Un nom de dossier IMAP transformé en nom de dossier de fichiers.

    `quote` avec `safe=""` échappe tous les séparateurs, donc le résultat est
    toujours UN seul composant de chemin : « A/B » ne peut pas créer deux
    niveaux.

    Mais `quote` n'encode JAMAIS le point — la stdlib garde toujours
    « _.-~ » — et c'est voulu : beaucoup de serveurs IMAP séparent leur
    hiérarchie par des points, et « INBOX.Sent » doit rester lisible sur le
    disque. Le prix à payer est que « . » et « .. » traverseraient tels
    quels, puisque `racine / ".."` remonte d'un cran. Ces trois cas
    dégénérés sont donc les seuls réécrits.
    """
    quoted = urllib.parse.quote(imap_name, safe="")
    return DEGENERATE_DIRNAMES.get(quoted, quoted)


def _assert_private_dir(path: Path) -> None:
    """Refuse un dossier qu'on ne possède pas, ou qui est un lien symbolique."""
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise StoreError(f"{path} est un lien symbolique : cache refusé")
    if info.st_uid != os.getuid():
        raise StoreError(
            f"{path} appartient à un autre utilisateur : cache refusé"
        )


def sweep_orphan_ephemeral(base: Path | None = None) -> int:
    """Efface les caches éphémères dont le processus n'existe plus.

    `atexit` et les gestionnaires de signaux couvrent les sorties normales ;
    un SIGKILL, lui, laisse un résidu. Ce balayage au démarrage est le filet.
    """
    base = Path(base) if base else ephemeral_base()
    removed = 0
    if not base.is_dir():
        return 0
    for path in base.glob(f"{EPHEMERAL_PREFIX}*"):
        if not path.is_dir():
            continue
        raw_pid = path.name[len(EPHEMERAL_PREFIX) :]
        if not raw_pid.isdigit():
            continue
        pid = int(raw_pid)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        except PermissionError:
            # Le PID existe et appartient à quelqu'un d'autre : on n'y touche pas.
            continue
    return removed


class Store:
    """Le cache d'UN compte. À ouvrir, à fermer, éventuellement à effacer."""

    def __init__(
        self,
        account,
        *,
        mode: str | None = None,
        key: bytes | None = None,
        secrets=None,
        base: Path | None = None,
    ) -> None:
        self.account = account
        self.mode = mode or resolve_mode(account)
        self.root = cache_root(account, self.mode, base)
        self._key = key
        self._secrets = secrets
        self._conn: sqlite3.Connection | None = None
        self._crypto = None
        self._lock = threading.RLock()

    # -- Cycle de vie ---------------------------------------------------

    @_locked
    def open(self) -> None:
        if self._conn is not None:
            return
        self._crypto = build_crypto(self.mode, self._resolve_key())
        self._prepare_root()
        db_path = self.root / "cache.db"
        conn = None
        try:
            # `check_same_thread=False` parce que le TUI synchronise dans un
            # thread de travail : sans ça, la première passe lèverait
            # ProgrammingError. La sûreté vient du verrou, pas de ce drapeau.
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.commit()
        except sqlite3.DatabaseError as exc:
            if conn is not None:
                conn.close()
            raise StoreError(
                f"{db_path} est illisible ({exc}) — purgez le cache et resynchronisez"
            ) from exc
        # Publié SEULEMENT une fois le schéma en place. `sqlite3.connect` est
        # paresseux : une base corrompue n'échoue qu'à `executescript`, donc
        # affecter `self._conn` plus tôt laisserait un open() raté derrière lui
        # un handle sans schéma — et le open() suivant, voyant `_conn` non nul,
        # réussirait en silence sur une base inutilisable.
        self._conn = conn
        if db_path.exists():
            os.chmod(db_path, 0o600)

    @_locked
    def close(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.commit()
        except sqlite3.Error:
            # Fermer prime sur sauver : un commit refusé ne doit pas laisser la
            # connexion ouverte pour toujours.
            pass
        finally:
            self._conn.close()
            self._conn = None

    def cleanup(self) -> None:
        """Efface la racine du compte. Appelé à la sortie en mode éphémère.

        On n'efface QUE le dossier du compte : le dossier par PID est partagé
        avec les autres comptes éphémères du même processus, et l'effacer
        détruirait leurs caches vivants. Il ne part que s'il est vide.
        """
        self.close()
        if self.mode != "ephemeral":
            return
        shutil.rmtree(self.root, ignore_errors=True)
        parent = self.root.parent
        if parent.name.startswith(EPHEMERAL_PREFIX):
            try:
                parent.rmdir()
            except OSError:
                # Un autre compte éphémère l'occupe encore : c'est normal.
                pass

    def __enter__(self) -> "Store":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _prepare_root(self) -> None:
        """Crée la racine, en 0700 à chaque niveau qui nous appartient.

        `mkdir(parents=True)` crée les dossiers intermédiaires SANS appliquer
        le mode — c'est documenté dans la stdlib. En éphémère la racine vit
        sous `/dev/shm`, qui est en 1777 et partagé avec tous les utilisateurs
        locaux : un dossier par PID laissé à l'umask y rendrait les noms de
        comptes lisibles par n'importe qui, et un dossier pré-créé par un tiers
        à un chemin devinable lui permettrait de glisser un lien symbolique
        sous `write_body`.
        """
        parent = self.root.parent
        if self.mode == "ephemeral":
            parent.parent.mkdir(parents=True, exist_ok=True)
            parent.mkdir(mode=0o700, exist_ok=True)
            _assert_private_dir(parent)
        else:
            parent.mkdir(parents=True, exist_ok=True)
        os.chmod(parent, 0o700)
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    def _resolve_key(self) -> bytes | None:
        if self.mode == "clear":
            return None
        if self._key is not None:
            return self._key
        if self.mode == "ephemeral":
            # Tirée ici, gardée en RAM, jamais écrite : c'est tout l'intérêt.
            self._key = new_key()
            return self._key
        if self._secrets is None:
            raise StoreError(
                f"le mode {self.mode} exige une clé : aucun coffre fourni"
            )
        ref = self.account.cache_key_ref()
        stored = self._secrets.get(ref)
        if stored is None:
            self._key = new_key()
            self._secrets.set(ref, base64.b64encode(self._key).decode())
        else:
            self._key = base64.b64decode(stored)
        return self._key

    # -- Scellement -----------------------------------------------------

    def _seal(self, text: str) -> bytes:
        return self._crypto.seal((text or "").encode("utf-8"))

    def _open(self, blob) -> str:
        if blob is None:
            return ""
        return self._crypto.open(bytes(blob)).decode("utf-8", "replace")

    def _msgid_hash(self, msgid: str) -> str:
        salt = self._key or b"clear"
        return hashlib.sha256(salt + (msgid or "").encode("utf-8")).hexdigest()

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            raise StoreError("cache non ouvert : appelez open() d'abord")
        return self._conn

    # -- Dossiers -------------------------------------------------------

    @_locked
    def upsert_folder(
        self,
        name: str,
        display: str = "",
        role: str | None = None,
        uidvalidity: int | None = None,
        uidnext: int | None = None,
    ) -> int:
        db = self._db()
        db.execute(
            "INSERT INTO folders(name, display, role, uidvalidity, uidnext)"
            " VALUES(?,?,?,?,?)"
            " ON CONFLICT(name) DO UPDATE SET"
            "   display = COALESCE(excluded.display, folders.display),"
            "   role = COALESCE(excluded.role, folders.role),"
            "   uidvalidity = COALESCE(excluded.uidvalidity, folders.uidvalidity),"
            "   uidnext = COALESCE(excluded.uidnext, folders.uidnext)",
            (name, display or None, role, uidvalidity, uidnext),
        )
        db.commit()
        # `display` vaut NULL tant qu'aucun nom affichable n'est connu : c'est
        # ce qui rend le COALESCE vivant, donc ce qui permet à une resync qui
        # ne repasse que le nom IMAP de NE PAS écraser un libellé déjà décodé.
        # Les lecteurs retombent sur `name` (voir mailbox_refs, tâche 9).
        return db.execute(
            "SELECT id FROM folders WHERE name = ?", (name,)
        ).fetchone()[0]

    @_locked
    def folders(self) -> list[dict]:
        return [dict(r) for r in self._db().execute(
            "SELECT * FROM folders ORDER BY name"
        )]

    @_locked
    def folder_state(self, name: str) -> dict | None:
        row = self._db().execute(
            "SELECT * FROM folders WHERE name = ?", (name,)
        ).fetchone()
        return dict(row) if row else None

    @_locked
    def set_folder_state(self, name: str, **fields) -> None:
        allowed = {
            "last_uid", "total", "unseen", "uidvalidity", "uidnext",
            "synced_at", "role", "display",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise StoreError(f"champs de dossier inconnus : {sorted(unknown)}")
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        db = self._db()
        db.execute(
            f"UPDATE folders SET {sets} WHERE name = ?",
            (*fields.values(), name),
        )
        db.commit()

    @_locked
    def purge_folder(self, name: str) -> None:
        db = self._db()
        row = db.execute("SELECT id FROM folders WHERE name = ?", (name,)).fetchone()
        if row:
            db.execute("DELETE FROM messages WHERE folder_id = ?", (row[0],))
            db.execute(
                "UPDATE folders SET last_uid = 0, total = 0, unseen = 0"
                " WHERE id = ?",
                (row[0],),
            )
            db.commit()
        shutil.rmtree(self.root / folder_dirname(name), ignore_errors=True)

    # -- Messages -------------------------------------------------------

    @_locked
    def upsert_messages(self, folder_id: int, metas: list[MessageMeta]) -> int:
        db = self._db()
        rows = [
            (
                folder_id,
                m.uid,
                m.date,
                m.size,
                m.flags,
                self._msgid_hash(m.msgid),
                self._seal(m.msgid),
                self._seal(m.frm),
                self._seal(m.to),
                self._seal(m.subject),
                self._seal(m.snippet),
            )
            for m in metas
        ]
        db.executemany(
            "INSERT INTO messages(folder_id, uid, date, size, flags,"
            " msgid_hash, sealed_msgid, sealed_from, sealed_to,"
            " sealed_subject, sealed_snippet)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(folder_id, uid) DO UPDATE SET"
            "   date = excluded.date, size = excluded.size,"
            "   flags = excluded.flags, msgid_hash = excluded.msgid_hash,"
            "   sealed_msgid = excluded.sealed_msgid,"
            "   sealed_from = excluded.sealed_from,"
            "   sealed_to = excluded.sealed_to,"
            "   sealed_subject = excluded.sealed_subject,"
            "   sealed_snippet = excluded.sealed_snippet",
            rows,
        )
        db.commit()
        return len(rows)

    @_locked
    def update_flags(self, folder_id: int, uid: int, flags: str) -> None:
        db = self._db()
        db.execute(
            "UPDATE messages SET flags = ? WHERE folder_id = ? AND uid = ?",
            (flags, folder_id, uid),
        )
        db.commit()

    def _row_to_meta(self, row) -> MessageMeta:
        return MessageMeta(
            uid=row["uid"],
            date=row["date"],
            size=row["size"],
            flags=row["flags"] or "",
            msgid=self._open(row["sealed_msgid"]),
            frm=self._open(row["sealed_from"]),
            to=self._open(row["sealed_to"]),
            subject=self._open(row["sealed_subject"]),
            snippet=self._open(row["sealed_snippet"]),
            has_body=bool(row["has_body"]),
        )

    @_locked
    def list_messages(
        self, folder_id: int, limit: int = 500, offset: int = 0
    ) -> list[MessageMeta]:
        rows = self._db().execute(
            "SELECT * FROM messages WHERE folder_id = ?"
            " ORDER BY date DESC, uid DESC LIMIT ? OFFSET ?",
            (folder_id, limit, offset),
        ).fetchall()
        return [self._row_to_meta(r) for r in rows]

    @_locked
    def known_uids(self, folder_id: int, last_n: int = 500) -> list[int]:
        rows = self._db().execute(
            "SELECT uid FROM messages WHERE folder_id = ?"
            " ORDER BY uid DESC LIMIT ?",
            (folder_id, last_n),
        ).fetchall()
        return [r[0] for r in rows]

    # -- Corps ----------------------------------------------------------

    def _body_path(self, folder_name: str, uid: int) -> Path:
        suffix = ".eml" if self.mode == "clear" else ".eml.enc"
        return self.root / folder_dirname(folder_name) / f"{uid}{suffix}"

    @_locked
    def write_body(self, folder_name: str, uid: int, raw: bytes) -> None:
        path = self._body_path(folder_name, uid)
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        path.write_bytes(self._crypto.seal(raw))
        os.chmod(path, 0o600)
        db = self._db()
        db.execute(
            "UPDATE messages SET has_body = 1 WHERE uid = ? AND folder_id ="
            " (SELECT id FROM folders WHERE name = ?)",
            (uid, folder_name),
        )
        db.commit()

    @_locked
    def read_body(self, folder_name: str, uid: int) -> bytes | None:
        path = self._body_path(folder_name, uid)
        if not path.exists():
            return None
        return self._crypto.open(path.read_bytes())

    # -- Entretien ------------------------------------------------------

    @_locked
    def size_bytes(self) -> int:
        return sum(
            p.stat().st_size for p in self.root.rglob("*") if p.is_file()
        )

    @_locked
    def purge_all(self) -> None:
        db = self._db()
        db.execute("DELETE FROM messages")
        db.execute("DELETE FROM folders")
        db.commit()
        for child in self.root.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
```

- [ ] **Step 5: Lancer les tests, vérifier qu'ils passent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_store.py" -v
```

Attendu : `OK`, 65 tests — 58 méthodes, plus les 7 de `TestMessages` rejouées parce que `TestEncryptedStore` en hérite de `TestMessages`, ses cas comptent deux fois — c'est voulu : le contrat doit être identique dans les deux modes).

- [ ] **Step 6: Vérifier que les préférences n'ont rien cassé**

```bash
.venv.erplibre/bin/python -c "
from script.todo import todo_prefs
print(todo_prefs.DEFAULTS['mail_cache_mode'], todo_prefs.DEFAULTS['mail_refresh_sec'])
"
```

Attendu : `clear 300`.

- [ ] **Step 7: Formater et commiter**

```bash
make format
git add script/todo/mail/store.py test/test_mail_store.py script/todo/todo_prefs.py
git commit -m "[ADD] mail: per-account cache, clear or sealed, persistent or ephemeral"
```

---

### Task 5: Moteur de synchronisation, testé sans serveur

**Files:**
- Create: `script/todo/mail/imap_sync.py`
- Create: `test/test_mail_sync.py`
- Modify: `script/todo/mail/store.py` (deux méthodes de plus)

**Interfaces:**
- Consumes: `store.Store`, `store.MessageMeta` (tâche 4).
- Produces:
  - `@dataclass FolderInfo(name: str, display: str = "", role: str | None = None)`
  - `@dataclass SelectInfo(uidvalidity: int, uidnext: int, exists: int)`
  - `@dataclass HeaderInfo(uid: int, date: int, size: int, flags: str, msgid: str, frm: str, to: str, subject: str)`
  - `@dataclass SyncReport(folders: int = 0, new_messages: int = 0, purged: list = ..., errors: list = ...)`
  - `class ImapTransport(Protocol)` — `list_folders()`, `select(folder)`, `search_uids(since_uid)`, `fetch_headers(uids)`, `fetch_flags(uids)`, `fetch_body(uid)`, `store_flags(uid, add, remove)`, `append(folder, raw, flags)`, `logout()`
  - `class Syncer` : `__init__(self, store, transport)`, `sync(progress=None) -> SyncReport`, `fetch_body(folder_name, uid) -> bytes`
  - `Syncer.BATCH = 200`, `Syncer.FLAG_REFRESH = 500`
- Ajoutées à `Store` par cette tâche : `count_unseen(folder_id) -> int`, `set_snippet(folder_id, uid, text) -> None`.

- [ ] **Step 1: Ajouter les deux méthodes manquantes au `Store`**

Dans `script/todo/mail/store.py`, section `-- Messages --`, après `update_flags` :

```python
    @_locked
    def count_unseen(self, folder_id: int) -> int:
        """Les non-lus. `flags` est en clair, donc c'est du SQL, pas du déchiffrement."""
        return self._db().execute(
            "SELECT COUNT(*) FROM messages"
            " WHERE folder_id = ? AND flags NOT LIKE '%\\Seen%' ESCAPE '\\'",
            (folder_id,),
        ).fetchone()[0]

    @_locked
    def set_snippet(self, folder_id: int, uid: int, text: str) -> None:
        """L'extrait n'existe qu'une fois le corps téléchargé : ENVELOPE ne le donne pas."""
        db = self._db()
        db.execute(
            "UPDATE messages SET sealed_snippet = ?"
            " WHERE folder_id = ? AND uid = ?",
            (self._seal(text), folder_id, uid),
        )
        db.commit()
```

- [ ] **Step 2: Écrire les tests qui échouent**

`test/test_mail_sync.py` :

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.imap_sync import (
    FolderInfo,
    HeaderInfo,
    SelectInfo,
    Syncer,
)
from script.todo.mail.store import Store


class FakeImapTransport:
    """Un serveur IMAP en mémoire : assez pour exercer tout le moteur."""

    def __init__(self, folders=None):
        # {nom: {"uidvalidity": int, "messages": {uid: HeaderInfo},
        #        "bodies": {uid: bytes}}}
        self.folders = folders or {}
        self.selected = None
        self.appended = []
        self.stored_flags = []
        self.logged_out = False
        self.select_errors = set()

    # -- helpers de test ------------------------------------------------

    def add(self, folder, uid, subject="Sujet", flags="", body=b"corps"):
        f = self.folders.setdefault(
            folder, {"uidvalidity": 1, "messages": {}, "bodies": {}}
        )
        f["messages"][uid] = HeaderInfo(
            uid=uid,
            date=1000 + uid,
            size=len(body),
            flags=flags,
            msgid=f"<{uid}@x.ca>",
            frm="alice@x.ca",
            to="moi@x.ca",
            subject=subject,
        )
        f["bodies"][uid] = body

    # -- protocole ------------------------------------------------------

    def list_folders(self):
        return [FolderInfo(name=n) for n in sorted(self.folders)]

    def select(self, folder):
        if folder in self.select_errors:
            raise OSError(f"select refusé sur {folder}")
        self.selected = folder
        f = self.folders[folder]
        uids = list(f["messages"])
        return SelectInfo(
            uidvalidity=f["uidvalidity"],
            uidnext=(max(uids) + 1) if uids else 1,
            exists=len(uids),
        )

    def search_uids(self, since_uid):
        f = self.folders[self.selected]
        return sorted(u for u in f["messages"] if u >= since_uid)

    def fetch_headers(self, uids):
        f = self.folders[self.selected]
        return [f["messages"][u] for u in uids if u in f["messages"]]

    def fetch_flags(self, uids):
        f = self.folders[self.selected]
        return [(u, f["messages"][u].flags) for u in uids if u in f["messages"]]

    def fetch_body(self, uid):
        return self.folders[self.selected]["bodies"][uid]

    def store_flags(self, uid, add, remove):
        self.stored_flags.append((uid, tuple(add), tuple(remove)))

    def append(self, folder, raw, flags):
        self.appended.append((folder, raw, tuple(flags)))

    def logout(self):
        self.logged_out = True


class SyncCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "moi@x.ca", "generic")
        self.store = Store(self.account, mode="clear", base=Path(self.tmp.name))
        self.store.open()
        self.imap = FakeImapTransport()
        self.syncer = Syncer(self.store, self.imap)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def folder_id(self, name):
        return self.store.folder_state(name)["id"]


class TestFirstSync(SyncCase):
    def test_creates_folders(self):
        self.imap.add("INBOX", 1)
        self.imap.add("Sent", 1)
        report = self.syncer.sync()
        self.assertEqual(report.folders, 2)
        self.assertEqual({f["name"] for f in self.store.folders()}, {"INBOX", "Sent"})

    def test_stores_messages(self):
        self.imap.add("INBOX", 1, subject="Devis")
        self.imap.add("INBOX", 2, subject="Facture")
        report = self.syncer.sync()
        self.assertEqual(report.new_messages, 2)
        subjects = {m.subject for m in self.store.list_messages(self.folder_id("INBOX"))}
        self.assertEqual(subjects, {"Devis", "Facture"})

    def test_records_last_uid(self):
        self.imap.add("INBOX", 7)
        self.imap.add("INBOX", 9)
        self.syncer.sync()
        self.assertEqual(self.store.folder_state("INBOX")["last_uid"], 9)

    def test_records_uidvalidity(self):
        self.imap.add("INBOX", 1)
        self.syncer.sync()
        self.assertEqual(self.store.folder_state("INBOX")["uidvalidity"], 1)

    def test_counts_unseen(self):
        self.imap.add("INBOX", 1, flags="\\Seen")
        self.imap.add("INBOX", 2, flags="")
        self.syncer.sync()
        self.assertEqual(self.store.folder_state("INBOX")["unseen"], 1)

    def test_empty_folder_is_fine(self):
        self.imap.folders["INBOX"] = {"uidvalidity": 1, "messages": {}, "bodies": {}}
        report = self.syncer.sync()
        self.assertEqual(report.new_messages, 0)

    def test_no_body_downloaded_during_sync(self):
        self.imap.add("INBOX", 1)
        self.syncer.sync()
        self.assertFalse(self.store.list_messages(self.folder_id("INBOX"))[0].has_body)


class TestIncrementalSync(SyncCase):
    def test_second_pass_fetches_only_new(self):
        self.imap.add("INBOX", 1)
        self.syncer.sync()
        self.imap.add("INBOX", 2)
        report = self.syncer.sync()
        self.assertEqual(report.new_messages, 1)

    def test_nothing_new_reports_zero(self):
        self.imap.add("INBOX", 1)
        self.syncer.sync()
        self.assertEqual(self.syncer.sync().new_messages, 0)

    def test_flags_are_refreshed(self):
        self.imap.add("INBOX", 1, flags="")
        self.syncer.sync()
        self.imap.folders["INBOX"]["messages"][1].flags = "\\Seen"
        self.syncer.sync()
        self.assertEqual(
            self.store.list_messages(self.folder_id("INBOX"))[0].flags, "\\Seen"
        )


class TestUidValidity(SyncCase):
    def test_change_purges_and_resyncs(self):
        self.imap.add("INBOX", 1, subject="ancien")
        self.syncer.sync()
        # Le serveur a rebâti la boîte : mêmes UID, autres messages.
        self.imap.folders["INBOX"]["uidvalidity"] = 2
        self.imap.folders["INBOX"]["messages"][1].subject = "nouveau"
        report = self.syncer.sync()
        self.assertIn("INBOX", report.purged)
        got = self.store.list_messages(self.folder_id("INBOX"))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].subject, "nouveau")

    def test_same_uidvalidity_does_not_purge(self):
        self.imap.add("INBOX", 1)
        self.syncer.sync()
        self.assertEqual(self.syncer.sync().purged, [])


class TestBatching(SyncCase):
    def test_large_folder_is_fetched_in_batches(self):
        for uid in range(1, 451):
            self.imap.add("INBOX", uid)
        calls = []
        original = self.imap.fetch_headers

        def spy(uids):
            calls.append(len(uids))
            return original(uids)

        self.imap.fetch_headers = spy
        report = self.syncer.sync()
        self.assertEqual(report.new_messages, 450)
        self.assertEqual(calls, [200, 200, 50])


class TestErrors(SyncCase):
    def test_failing_folder_does_not_stop_the_others(self):
        self.imap.add("INBOX", 1)
        self.imap.add("Archives", 1)
        self.imap.select_errors.add("Archives")
        report = self.syncer.sync()
        self.assertEqual(report.new_messages, 1)
        self.assertEqual(len(report.errors), 1)
        self.assertIn("Archives", report.errors[0])


class TestProgress(SyncCase):
    def test_callback_receives_folder_and_counts(self):
        self.imap.add("INBOX", 1)
        self.imap.add("INBOX", 2)
        seen = []
        self.syncer.sync(progress=lambda name, done, total: seen.append((name, done, total)))
        self.assertEqual(seen[-1], ("INBOX", 2, 2))


class TestFetchBody(SyncCase):
    def test_downloads_and_caches(self):
        self.imap.add("INBOX", 1, body=b"From: a@x.ca\r\n\r\nBonjour Alice")
        self.syncer.sync()
        raw = self.syncer.fetch_body("INBOX", 1)
        self.assertIn(b"Bonjour Alice", raw)
        self.assertEqual(self.store.read_body("INBOX", 1), raw)

    def test_second_call_uses_the_cache(self):
        self.imap.add("INBOX", 1, body=b"corps")
        self.syncer.sync()
        self.syncer.fetch_body("INBOX", 1)
        self.imap.fetch_body = lambda uid: self.fail("le réseau a été rappelé")
        self.assertEqual(self.syncer.fetch_body("INBOX", 1), b"corps")

    def test_marks_has_body(self):
        self.imap.add("INBOX", 1)
        self.syncer.sync()
        self.syncer.fetch_body("INBOX", 1)
        self.assertTrue(self.store.list_messages(self.folder_id("INBOX"))[0].has_body)

    def test_snippet_survives_an_unknown_charset(self):
        """Un charset bidon ne doit pas faire tomber l'ouverture du message."""
        from script.todo.mail.imap_sync import snippet_from_raw

        raw = (
            b'Content-Type: text/plain; charset="bogus-charset-xyz"\r\n\r\n'
            b"Bonjour Alice"
        )
        self.assertIn("Bonjour", snippet_from_raw(raw))

    def test_fills_the_snippet(self):
        self.imap.add(
            "INBOX", 1, body=b"Subject: Devis\r\n\r\nBonjour, voici le devis."
        )
        self.syncer.sync()
        self.syncer.fetch_body("INBOX", 1)
        snippet = self.store.list_messages(self.folder_id("INBOX"))[0].snippet
        self.assertIn("Bonjour", snippet)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Lancer les tests, vérifier qu'ils échouent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_sync.py" -v
```

Attendu : `ModuleNotFoundError: No module named 'script.todo.mail.imap_sync'`.

- [ ] **Step 4: Implémenter `imap_sync.py`**

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le moteur de synchronisation, séparé de ce qui parle vraiment IMAP.

`Syncer` ne connaît qu'un PROTOCOLE (`ImapTransport`). C'est ce qui permet de
l'exercer entièrement contre un serveur en mémoire, sans réseau ni compte, et
c'est ce qui garde le décodage verbeux d'`imaplib` dans son propre fichier.

Une passe est incrémentale par construction : on demande les UID strictement
supérieurs au dernier connu. Le seul cas qui force une reprise à zéro est le
changement d'UIDVALIDITY — le serveur annonce alors que ses UID ne veulent
plus rien dire, et garder l'ancien cache produirait des messages faux.

Les corps ne descendent JAMAIS pendant une passe : une boîte de 20 000
messages doit se synchroniser en secondes, pas en gigaoctets.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

from script.todo.mail.store import MessageMeta

SNIPPET_LEN = 200


@dataclass
class FolderInfo:
    name: str
    display: str = ""
    role: str | None = None


@dataclass
class SelectInfo:
    uidvalidity: int
    uidnext: int
    exists: int


@dataclass
class HeaderInfo:
    uid: int
    date: int
    size: int
    flags: str
    msgid: str
    frm: str
    to: str
    subject: str


@dataclass
class SyncReport:
    folders: int = 0
    new_messages: int = 0
    purged: list = field(default_factory=list)
    errors: list = field(default_factory=list)


class ImapTransport(Protocol):
    """Ce dont le moteur a besoin. `imap_transport.ImaplibTransport` l'implémente."""

    def list_folders(self) -> list[FolderInfo]: ...

    def select(self, folder: str) -> SelectInfo: ...

    def search_uids(self, since_uid: int) -> list[int]: ...

    def fetch_headers(self, uids: list[int]) -> list[HeaderInfo]: ...

    def fetch_flags(self, uids: list[int]) -> list[tuple[int, str]]: ...

    def fetch_body(self, uid: int) -> bytes: ...

    def store_flags(self, uid: int, add: list[str], remove: list[str]) -> None: ...

    def append(self, folder: str, raw: bytes, flags: list[str]) -> None: ...

    def logout(self) -> None: ...


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def snippet_from_raw(raw: bytes, length: int = SNIPPET_LEN) -> str:
    """Les premiers mots du corps, pour la colonne d'aperçu de la liste."""
    import email

    try:
        msg = email.message_from_bytes(raw)
    except Exception:
        return ""
    part = msg
    if msg.is_multipart():
        part = next(
            (p for p in msg.walk() if p.get_content_type() == "text/plain"), None
        )
        if part is None:
            return ""
    try:
        payload = part.get_payload(decode=True) or b""
    except Exception:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        text = payload.decode(charset, "replace")
    except LookupError:
        # Un charset inconnu lève AVANT que `errors="replace"` ne serve : la
        # recherche du codec échoue d'abord. Sans ce repli, un seul message
        # mal étiqueté ferait tomber l'ouverture de la boîte.
        text = payload.decode("utf-8", "replace")
    return " ".join(text.split())[:length]


class Syncer:
    """Une passe de synchronisation, et le téléchargement d'un corps à la demande."""

    BATCH = 200
    FLAG_REFRESH = 500

    def __init__(self, store, transport: ImapTransport) -> None:
        self.store = store
        self.transport = transport

    def sync(self, progress=None) -> SyncReport:
        report = SyncReport()
        for folder in self.transport.list_folders():
            try:
                self._sync_folder(folder, report, progress)
            except Exception as exc:
                # Un dossier qui refuse ne doit pas priver l'utilisateur des autres.
                report.errors.append(f"{folder.name} : {exc}")
            report.folders += 1
        return report

    def _sync_folder(self, folder: FolderInfo, report: SyncReport, progress) -> None:
        fid = self.store.upsert_folder(folder.name, folder.display, folder.role)
        info = self.transport.select(folder.name)
        state = self.store.folder_state(folder.name) or {}

        known_validity = state.get("uidvalidity")
        if known_validity is not None and known_validity != info.uidvalidity:
            self.store.purge_folder(folder.name)
            report.purged.append(folder.name)
            state = self.store.folder_state(folder.name) or {}

        self.store.set_folder_state(
            folder.name, uidvalidity=info.uidvalidity, uidnext=info.uidnext
        )

        last_uid = state.get("last_uid") or 0
        uids = self.transport.search_uids(last_uid + 1)
        done = 0
        for batch in _chunks(uids, self.BATCH):
            headers = self.transport.fetch_headers(batch)
            self.store.upsert_messages(
                fid,
                [
                    MessageMeta(
                        uid=h.uid,
                        date=h.date,
                        size=h.size,
                        flags=h.flags,
                        msgid=h.msgid,
                        frm=h.frm,
                        to=h.to,
                        subject=h.subject,
                        snippet="",
                    )
                    for h in headers
                ],
            )
            report.new_messages += len(headers)
            done += len(batch)
            if progress:
                progress(folder.name, done, len(uids))
        if uids:
            self.store.set_folder_state(folder.name, last_uid=max(uids))

        # Les drapeaux des messages déjà connus changent sans que l'UID bouge :
        # un « lu » ailleurs ne serait jamais vu sans cette relecture.
        known = self.store.known_uids(fid, self.FLAG_REFRESH)
        if known:
            for uid, flags in self.transport.fetch_flags(known):
                self.store.update_flags(fid, uid, flags)

        self.store.set_folder_state(
            folder.name,
            total=info.exists,
            unseen=self.store.count_unseen(fid),
            synced_at=int(time.time()),
        )

    def fetch_body(self, folder_name: str, uid: int) -> bytes:
        """Le corps, du cache s'il y est, du serveur sinon."""
        cached = self.store.read_body(folder_name, uid)
        if cached is not None:
            return cached
        self.transport.select(folder_name)
        raw = self.transport.fetch_body(uid)
        self.store.write_body(folder_name, uid, raw)
        state = self.store.folder_state(folder_name)
        if state:
            self.store.set_snippet(state["id"], uid, snippet_from_raw(raw))
        return raw
```

- [ ] **Step 5: Lancer les tests, vérifier qu'ils passent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_sync.py" -v
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_store.py" -v
```

Attendu : `OK` pour les deux (les ajouts au `Store` ne doivent rien casser).

- [ ] **Step 6: Formater et commiter**

```bash
make format
git add script/todo/mail/imap_sync.py script/todo/mail/store.py test/test_mail_sync.py
git commit -m "[ADD] mail: incremental sync engine behind a transport protocol"
```

---

### Task 6: Le transport IMAP réel

**Files:**
- Create: `script/todo/mail/imap_transport.py`
- Create: `test/test_mail_imap_transport.py`

**Interfaces:**
- Consumes: `imap_sync.FolderInfo`, `SelectInfo`, `HeaderInfo` (tâche 5) ; `accounts.Account` (tâche 3).
- Produces:
  - `HEADER_FIELDS: str = "FROM TO SUBJECT DATE MESSAGE-ID"`
  - `decode_header_value(raw: str) -> str`
  - `decode_mailbox(name: str) -> str`
  - `parse_list_line(line: bytes) -> FolderInfo`
  - `parse_fetch_headers(data: list) -> list[HeaderInfo]`
  - `class ImapError(Exception)`
  - `class ImaplibTransport` : `__init__(self, client)`, `list_folders()`, `select(folder)`, `search_uids(since_uid)`, `fetch_headers(uids)`, `fetch_flags(uids)`, `fetch_body(uid)`, `store_flags(uid, add, remove)`, `append(folder, raw, flags)`, `logout()`
  - `connect(account, password) -> ImaplibTransport`

**Note de conception :** on n'analyse pas `ENVELOPE`. `BODY.PEEK[HEADER.FIELDS (…)]` renvoie des en-têtes RFC822 bruts que le module `email` de la stdlib décode déjà correctement, encodages compris. C'est moins de code, et surtout moins de code faux.

- [ ] **Step 1: Écrire les tests qui échouent**

`test/test_mail_imap_transport.py` :

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import unittest
from unittest.mock import MagicMock, patch

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.imap_transport import (
    ImapError,
    ImaplibTransport,
    connect,
    decode_header_value,
    decode_mailbox,
    parse_fetch_headers,
    parse_list_line,
)


class TestDecodeHeaderValue(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(decode_header_value("Bonjour"), "Bonjour")

    def test_encoded_word_base64(self):
        self.assertEqual(
            decode_header_value("=?UTF-8?B?RGV2aXMgcsOpdmlzw6k=?="), "Devis révisé"
        )

    def test_encoded_word_quoted_printable(self):
        self.assertEqual(
            decode_header_value("=?UTF-8?Q?Devis_r=C3=A9vis=C3=A9?="), "Devis révisé"
        )

    def test_mixed_parts(self):
        self.assertEqual(
            decode_header_value("Re: =?UTF-8?B?ZGV2aXM=?="), "Re: devis"
        )

    def test_none_is_empty(self):
        self.assertEqual(decode_header_value(None), "")

    def test_broken_encoding_does_not_raise(self):
        self.assertIsInstance(decode_header_value("=?UTF-8?B?!!!?="), str)


class TestDecodeMailbox(unittest.TestCase):
    def test_ascii_unchanged(self):
        self.assertEqual(decode_mailbox("INBOX"), "INBOX")

    def test_modified_utf7(self):
        self.assertEqual(decode_mailbox("&AMk-l&AOk-ments"), "Éléments")

    def test_ampersand_escape(self):
        self.assertEqual(decode_mailbox("A&-B"), "A&B")

    def test_broken_input_returns_original(self):
        self.assertEqual(decode_mailbox("&&&"), "&&&")


class TestParseListLine(unittest.TestCase):
    def test_plain_inbox(self):
        info = parse_list_line(b'(\\HasNoChildren) "/" "INBOX"')
        self.assertEqual(info.name, "INBOX")
        self.assertEqual(info.role, "inbox")

    def test_sent_role_from_special_use(self):
        info = parse_list_line(b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"')
        self.assertEqual(info.name, "[Gmail]/Sent Mail")
        self.assertEqual(info.role, "sent")

    def test_trash_role(self):
        self.assertEqual(
            parse_list_line(b'(\\Trash) "/" "Corbeille"').role, "trash"
        )

    def test_drafts_role(self):
        self.assertEqual(parse_list_line(b'(\\Drafts) "/" "Drafts"').role, "drafts")

    def test_junk_role(self):
        self.assertEqual(parse_list_line(b'(\\Junk) "/" "Spam"').role, "junk")

    def test_archive_role(self):
        self.assertEqual(
            parse_list_line(b'(\\Archive) "/" "Archive"').role, "archive"
        )

    def test_no_special_use_has_no_role(self):
        self.assertIsNone(parse_list_line(b'(\\HasNoChildren) "/" "Projets"').role)

    def test_unquoted_name(self):
        self.assertEqual(parse_list_line(b'(\\HasNoChildren) "/" Projets').name, "Projets")

    def test_display_is_decoded(self):
        info = parse_list_line(b'(\\HasNoChildren) "/" "&AMk-l&AOk-ments"')
        self.assertEqual(info.display, "Éléments")


HEADERS_1 = (
    b"1 (UID 101 RFC822.SIZE 420 FLAGS (\\Seen) BODY[HEADER.FIELDS "
    b"(FROM TO SUBJECT DATE MESSAGE-ID)] {160}",
    b"From: Alice <alice@x.ca>\r\n"
    b"To: moi@x.ca\r\n"
    b"Subject: =?UTF-8?B?RGV2aXMgcsOpdmlzw6k=?=\r\n"
    b"Date: Fri, 01 Aug 2026 10:41:00 +0000\r\n"
    b"Message-ID: <abc@x.ca>\r\n\r\n",
)
HEADERS_2 = (
    b"2 (UID 102 RFC822.SIZE 12 FLAGS () BODY[HEADER.FIELDS "
    b"(FROM TO SUBJECT DATE MESSAGE-ID)] {40}",
    b"From: bob@x.ca\r\nSubject: CR\r\n\r\n",
)


# Même message, mais le serveur place les attributs APRÈS le littéral.
# `imaplib` rend alors la fin de ligne dans une entrée séparée.
HEADERS_TRAILING = (
    b"3 (BODY[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)] {42}",
    b"From: carl@x.ca\r\nSubject: Facture\r\n\r\n",
)
TRAILING_ATTRS = b" UID 103 RFC822.SIZE 99 FLAGS (\\Answered))"


class TestParseFetchHeaders(unittest.TestCase):
    def test_single_message(self):
        got = parse_fetch_headers([HEADERS_1, b")"])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].uid, 101)

    def test_size_and_flags(self):
        got = parse_fetch_headers([HEADERS_1, b")"])[0]
        self.assertEqual(got.size, 420)
        self.assertEqual(got.flags, "\\Seen")

    def test_subject_is_decoded(self):
        self.assertEqual(
            parse_fetch_headers([HEADERS_1, b")"])[0].subject, "Devis révisé"
        )

    def test_from_and_to(self):
        got = parse_fetch_headers([HEADERS_1, b")"])[0]
        self.assertEqual(got.frm, "Alice <alice@x.ca>")
        self.assertEqual(got.to, "moi@x.ca")

    def test_msgid(self):
        self.assertEqual(parse_fetch_headers([HEADERS_1, b")"])[0].msgid, "<abc@x.ca>")

    def test_date_is_epoch(self):
        self.assertEqual(parse_fetch_headers([HEADERS_1, b")"])[0].date, 1785580860)

    def test_missing_date_is_zero(self):
        self.assertEqual(parse_fetch_headers([HEADERS_2, b")"])[0].date, 0)

    def test_missing_to_is_empty(self):
        self.assertEqual(parse_fetch_headers([HEADERS_2, b")"])[0].to, "")

    def test_several_messages(self):
        got = parse_fetch_headers([HEADERS_1, b")", HEADERS_2, b")"])
        self.assertEqual([m.uid for m in got], [101, 102])

    def test_non_tuple_entries_are_skipped(self):
        self.assertEqual(parse_fetch_headers([b")", None]), [])

    def test_attributes_after_the_literal_are_read(self):
        """RFC 3501 n'impose pas l'ordre : sinon le message disparaît."""
        got = parse_fetch_headers([HEADERS_TRAILING, TRAILING_ATTRS])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].uid, 103)

    def test_attributes_after_the_literal_keep_flags_and_size(self):
        got = parse_fetch_headers([HEADERS_TRAILING, TRAILING_ATTRS])[0]
        self.assertEqual(got.flags, "\\Answered")
        self.assertEqual(got.size, 99)
        self.assertEqual(got.subject, "Facture")

    def test_both_orders_in_one_response(self):
        got = parse_fetch_headers(
            [HEADERS_1, b")", HEADERS_TRAILING, TRAILING_ATTRS]
        )
        self.assertEqual([m.uid for m in got], [101, 103])


class TestTransport(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.transport = ImaplibTransport(self.client)

    def test_list_folders(self):
        self.client.list.return_value = (
            "OK",
            [b'(\\HasNoChildren) "/" "INBOX"', b'(\\Sent) "/" "Sent"'],
        )
        names = [f.name for f in self.transport.list_folders()]
        self.assertEqual(names, ["INBOX", "Sent"])

    def test_list_failure_raises(self):
        self.client.list.return_value = ("NO", [b"refuse"])
        with self.assertRaises(ImapError):
            self.transport.list_folders()

    def test_select_reads_uidvalidity_and_uidnext(self):
        self.client.select.return_value = ("OK", [b"42"])
        self.client.response.side_effect = lambda k: {
            "UIDVALIDITY": ("OK", [b"7"]),
            "UIDNEXT": ("OK", [b"103"]),
        }[k]
        info = self.transport.select("INBOX")
        self.assertEqual((info.uidvalidity, info.uidnext, info.exists), (7, 103, 42))

    def test_select_failure_raises(self):
        self.client.select.return_value = ("NO", [b"pas de boite"])
        with self.assertRaises(ImapError):
            self.transport.select("ABSENT")

    def test_search_uids(self):
        self.client.uid.return_value = ("OK", [b"101 102 103"])
        self.assertEqual(self.transport.search_uids(101), [101, 102, 103])

    def test_search_empty(self):
        self.client.uid.return_value = ("OK", [b""])
        self.assertEqual(self.transport.search_uids(1), [])

    def test_fetch_headers_empty_list_skips_network(self):
        self.assertEqual(self.transport.fetch_headers([]), [])
        self.client.uid.assert_not_called()

    def test_fetch_body(self):
        self.client.uid.return_value = ("OK", [(b"1 (UID 101 BODY[] {5}", b"corps"), b")"])
        self.assertEqual(self.transport.fetch_body(101), b"corps")

    def test_fetch_body_failure_raises(self):
        self.client.uid.return_value = ("NO", [b"refuse"])
        with self.assertRaises(ImapError):
            self.transport.fetch_body(101)

    def test_store_flags_add_and_remove(self):
        self.client.uid.return_value = ("OK", [b""])
        self.transport.store_flags(101, ["\\Seen"], ["\\Flagged"])
        calls = [c.args for c in self.client.uid.call_args_list]
        self.assertIn(("STORE", "101", "+FLAGS", "(\\Seen)"), calls)
        self.assertIn(("STORE", "101", "-FLAGS", "(\\Flagged)"), calls)

    def test_logout_is_forgiving(self):
        self.client.logout.side_effect = OSError("déjà fermé")
        self.transport.logout()  # ne doit pas lever


class TestFetchFlags(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.transport = ImaplibTransport(self.client)

    def test_empty_list_skips_the_network(self):
        self.assertEqual(self.transport.fetch_flags([]), [])
        self.client.uid.assert_not_called()

    def test_parses_bare_lines(self):
        self.client.uid.return_value = (
            "OK",
            [b"1 (UID 101 FLAGS (\\Seen))", b"2 (UID 102 FLAGS ())"],
        )
        self.assertEqual(
            self.transport.fetch_flags([101, 102]),
            [(101, "\\Seen"), (102, "")],
        )

    def test_skips_entries_without_a_uid(self):
        self.client.uid.return_value = (
            "OK",
            [b")", None, b"1 (UID 101 FLAGS (\\Seen))"],
        )
        self.assertEqual(self.transport.fetch_flags([101]), [(101, "\\Seen")])

    def test_failure_raises(self):
        self.client.uid.return_value = ("NO", [b"refuse"])
        with self.assertRaises(ImapError):
            self.transport.fetch_flags([101])


class TestAppend(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.transport = ImaplibTransport(self.client)

    def test_quotes_the_folder_and_joins_the_flags(self):
        self.client.append.return_value = ("OK", [b"fait"])
        self.transport.append("Sent Items", b"brut", ["\\Seen"])
        self.client.append.assert_called_once_with(
            '"Sent Items"', "(\\Seen)", None, b"brut"
        )

    def test_failure_raises(self):
        self.client.append.return_value = ("NO", [b"refuse"])
        with self.assertRaises(ImapError):
            self.transport.append("Sent", b"brut", [])


class TestConnect(unittest.TestCase):
    """`connect` est le code le plus sensible au protocole du fichier.

    Aucun de ces tests ne joint le réseau : `imaplib` est remplacé.
    """

    def _account(self, security):
        account = account_from_preset("perso", "moi@x.ca", "generic")
        account.imap.host = "imap.x.ca"
        account.imap.port = 993
        account.imap.security = security
        return account

    def test_ssl_branch(self):
        client = MagicMock()
        with patch("imaplib.IMAP4_SSL", return_value=client) as ctor:
            transport = connect(self._account("ssl"), "hunter2")
        ctor.assert_called_once_with("imap.x.ca", 993)
        client.login.assert_called_once_with("moi@x.ca", "hunter2")
        self.assertIsInstance(transport, ImaplibTransport)

    def test_starttls_branch_upgrades(self):
        client = MagicMock()
        with patch("imaplib.IMAP4", return_value=client):
            connect(self._account("starttls"), "hunter2")
        client.starttls.assert_called_once()

    def test_plain_branch_does_not_upgrade(self):
        client = MagicMock()
        with patch("imaplib.IMAP4", return_value=client):
            connect(self._account("none"), "hunter2")
        client.starttls.assert_not_called()

    def test_login_failure_becomes_an_imap_error(self):
        client = MagicMock()
        client.login.side_effect = OSError("530 refus")
        with patch("imaplib.IMAP4_SSL", return_value=client):
            with self.assertRaises(ImapError) as ctx:
                connect(self._account("ssl"), "mauvais")
        self.assertIn("530", str(ctx.exception))

    def test_connection_failure_becomes_an_imap_error(self):
        with patch("imaplib.IMAP4_SSL", side_effect=OSError("injoignable")):
            with self.assertRaises(ImapError):
                connect(self._account("ssl"), "hunter2")
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_imap_transport.py" -v
```

Attendu : `ModuleNotFoundError`.

- [ ] **Step 3: Implémenter `imap_transport.py`**

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La seule couche qui parle vraiment IMAP.

Choix qui explique tout le reste du fichier : on ne décode PAS `ENVELOPE`.
`BODY.PEEK[HEADER.FIELDS (...)]` rend des en-têtes RFC822 bruts, que le module
`email` de la stdlib sait déjà lire — encodages, mots encodés, dates comprises.
Analyser `ENVELOPE` à la main coûterait cent lignes de plus, toutes fausses
sur un cas limite ou l'autre.

`BODY.PEEK` et non `BODY` : lire un message dans le TUI ne doit pas le marquer
lu sur le serveur à l'insu de l'utilisateur.
"""
from __future__ import annotations

import email
import email.utils
import re
from email.header import decode_header
from email.parser import BytesHeaderParser

from script.todo.mail.imap_sync import FolderInfo, HeaderInfo, SelectInfo

HEADER_FIELDS = "FROM TO SUBJECT DATE MESSAGE-ID"

SPECIAL_USE = {
    "\\Sent": "sent",
    "\\Drafts": "drafts",
    "\\Trash": "trash",
    "\\Junk": "junk",
    "\\Archive": "archive",
    "\\All": "archive",
}

_UID_RE = re.compile(rb"UID\s+(\d+)")
_SIZE_RE = re.compile(rb"RFC822\.SIZE\s+(\d+)")
_FLAGS_RE = re.compile(rb"FLAGS\s+\(([^)]*)\)")
_LIST_RE = re.compile(rb'^\(([^)]*)\)\s+("[^"]*"|NIL)\s+(.*)$')


class ImapError(Exception):
    """Le serveur a refusé, ou a répondu quelque chose d'inattendu."""


def decode_header_value(raw: str | None) -> str:
    """Un en-tête RFC 2047 rendu en texte lisible, sans jamais lever."""
    if not raw:
        return ""
    try:
        parts = decode_header(raw)
    except Exception:
        return str(raw)
    out = []
    for value, charset in parts:
        if isinstance(value, bytes):
            out.append(value.decode(charset or "utf-8", "replace"))
        else:
            out.append(value)
    return "".join(out).strip()


def decode_mailbox(name: str) -> str:
    """Nom de boîte en UTF-7 modifié (RFC 3501) rendu lisible.

    Sur entrée invalide on rend le nom d'origine : un affichage imparfait vaut
    mieux qu'un dossier qu'on n'arrive plus à sélectionner.
    """
    if "&" not in name:
        return name
    try:
        out = []
        for chunk in name.split("&"):
            if not out:
                out.append(chunk)
                continue
            encoded, sep, rest = chunk.partition("-")
            if not sep:
                raise ValueError("séquence & non terminée")
            if encoded == "":
                out.append("&" + rest)
            else:
                pad = "=" * (-len(encoded) % 4)
                decoded = (encoded.replace(",", "/") + pad).encode("ascii")
                import base64

                out.append(base64.b64decode(decoded).decode("utf-16-be") + rest)
        return "".join(out)
    except Exception:
        return name


def parse_list_line(line: bytes) -> FolderInfo:
    """Une ligne de réponse LIST → nom, nom affichable, rôle."""
    match = _LIST_RE.match(line.strip())
    if not match:
        raw_name = line.decode("utf-8", "replace").strip().strip('"')
        return FolderInfo(name=raw_name, display=decode_mailbox(raw_name))
    flags = match.group(1).decode("ascii", "replace").split()
    name = match.group(3).decode("utf-8", "replace").strip().strip('"')
    role = next((SPECIAL_USE[f] for f in flags if f in SPECIAL_USE), None)
    if role is None and name.upper() == "INBOX":
        role = "inbox"
    return FolderInfo(name=name, display=decode_mailbox(name), role=role)


def parse_fetch_headers(data: list) -> list[HeaderInfo]:
    """Réponse FETCH d'en-têtes → une liste de `HeaderInfo`."""
    parser = BytesHeaderParser()
    out = []
    for index, item in enumerate(data):
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        prefix, raw_headers = item[0], item[1]
        # Les attributs peuvent SUIVRE le littéral au lieu de le précéder :
        # RFC 3501 n'impose aucun ordre, et `imaplib` rend alors la fin de la
        # ligne dans l'entrée suivante, hors du tuple. Ne lire que le préfixe
        # ferait disparaître le message SANS erreur — et comme le moteur
        # avance `last_uid` derrière, il ne serait jamais réessayé.
        trailer = b""
        if index + 1 < len(data) and isinstance(
            data[index + 1], (bytes, bytearray)
        ):
            trailer = bytes(data[index + 1])
        meta = bytes(prefix) + b" " + trailer
        uid_match = _UID_RE.search(meta)
        if not uid_match:
            continue
        size_match = _SIZE_RE.search(meta)
        flags_match = _FLAGS_RE.search(meta)
        msg = parser.parsebytes(raw_headers)
        date_raw = msg.get("Date")
        try:
            stamp = (
                int(email.utils.parsedate_to_datetime(date_raw).timestamp())
                if date_raw
                else 0
            )
        except (TypeError, ValueError):
            stamp = 0
        out.append(
            HeaderInfo(
                uid=int(uid_match.group(1)),
                date=stamp,
                size=int(size_match.group(1)) if size_match else 0,
                flags=(
                    flags_match.group(1).decode("ascii", "replace")
                    if flags_match
                    else ""
                ),
                msgid=(msg.get("Message-ID") or "").strip(),
                frm=decode_header_value(msg.get("From")),
                to=decode_header_value(msg.get("To")),
                subject=decode_header_value(msg.get("Subject")),
            )
        )
    return out


class ImaplibTransport:
    """`ImapTransport` réalisé sur `imaplib`. Le client est injecté : les tests
    passent un double, la production passe une connexion TLS."""

    def __init__(self, client) -> None:
        self.client = client

    @staticmethod
    def _ok(result, label: str):
        status, data = result
        if status != "OK":
            raise ImapError(f"{label} : le serveur a répondu {status} ({data!r})")
        return data

    def list_folders(self) -> list[FolderInfo]:
        data = self._ok(self.client.list(), "LIST")
        return [parse_list_line(line) for line in data if line]

    def select(self, folder: str) -> SelectInfo:
        data = self._ok(self.client.select(f'"{folder}"'), f"SELECT {folder}")
        exists = int(data[0]) if data and data[0] else 0
        return SelectInfo(
            uidvalidity=int(self._first(self.client.response("UIDVALIDITY")) or 0),
            uidnext=int(self._first(self.client.response("UIDNEXT")) or 0),
            exists=exists,
        )

    @staticmethod
    def _first(response) -> bytes | None:
        _, data = response
        return data[0] if data and data[0] else None

    def search_uids(self, since_uid: int) -> list[int]:
        data = self._ok(
            self.client.uid("SEARCH", None, f"UID {since_uid}:*"), "SEARCH"
        )
        raw = (data[0] or b"").split()
        # `UID n:*` rend toujours au moins un UID, même inférieur à n quand la
        # boîte est plus courte : on refiltre côté client.
        return [int(u) for u in raw if int(u) >= since_uid]

    def fetch_headers(self, uids: list[int]) -> list[HeaderInfo]:
        if not uids:
            return []
        spec = f"(UID FLAGS RFC822.SIZE BODY.PEEK[HEADER.FIELDS ({HEADER_FIELDS})])"
        data = self._ok(
            self.client.uid("FETCH", ",".join(str(u) for u in uids), spec),
            "FETCH HEADERS",
        )
        return parse_fetch_headers(data)

    def fetch_flags(self, uids: list[int]) -> list[tuple[int, str]]:
        if not uids:
            return []
        data = self._ok(
            self.client.uid("FETCH", ",".join(str(u) for u in uids), "(UID FLAGS)"),
            "FETCH FLAGS",
        )
        out = []
        for line in data:
            raw = line[0] if isinstance(line, tuple) else line
            if not isinstance(raw, (bytes, bytearray)):
                continue
            uid_match = _UID_RE.search(raw)
            flags_match = _FLAGS_RE.search(raw)
            if uid_match:
                out.append(
                    (
                        int(uid_match.group(1)),
                        flags_match.group(1).decode("ascii", "replace")
                        if flags_match
                        else "",
                    )
                )
        return out

    def fetch_body(self, uid: int) -> bytes:
        data = self._ok(
            self.client.uid("FETCH", str(uid), "(BODY.PEEK[])"), "FETCH BODY"
        )
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2:
                return item[1]
        raise ImapError(f"aucun corps rendu pour l'UID {uid}")

    def store_flags(self, uid: int, add: list[str], remove: list[str]) -> None:
        if add:
            self._ok(
                self.client.uid("STORE", str(uid), "+FLAGS", f"({' '.join(add)})"),
                "STORE +FLAGS",
            )
        if remove:
            self._ok(
                self.client.uid("STORE", str(uid), "-FLAGS", f"({' '.join(remove)})"),
                "STORE -FLAGS",
            )

    def append(self, folder: str, raw: bytes, flags: list[str]) -> None:
        self._ok(
            self.client.append(f'"{folder}"', f"({' '.join(flags)})", None, raw),
            f"APPEND {folder}",
        )

    def logout(self) -> None:
        """Fermer proprement est souhaitable, pas indispensable : on n'échoue
        jamais sur la sortie."""
        try:
            self.client.logout()
        except Exception:
            pass


def connect(account, password: str) -> ImaplibTransport:
    """Ouvre une connexion TLS et se connecte. Lève `ImapError` sur refus."""
    import imaplib

    conf = account.imap
    try:
        if conf.security == "ssl":
            client = imaplib.IMAP4_SSL(conf.host, conf.port)
        else:
            client = imaplib.IMAP4(conf.host, conf.port)
            if conf.security == "starttls":
                client.starttls()
        client.login(conf.user, password)
    except Exception as exc:
        # Frontière de conversion : `imaplib`, `ssl` et `socket` lèvent chacun
        # leur propre famille d'erreurs, et l'appelant n'a qu'un seul recours —
        # dire à l'utilisateur que la connexion a échoué. On les ramène donc
        # toutes à `ImapError`, en gardant le message d'origine.
        raise ImapError(f"connexion IMAP à {conf.host} refusée : {exc}") from exc
    return ImaplibTransport(client)
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_imap_transport.py" -v
```

Attendu : `OK`, 54 tests. L'époque `1785580860` a été calculée dans `.venv.erplibre` : la date de l'en-tête porte `+0000`, donc `timestamp()` ne dépend pas du fuseau de la machine.

- [ ] **Step 5: Formater et commiter**

```bash
make format
git add script/todo/mail/imap_transport.py test/test_mail_imap_transport.py
git commit -m "[ADD] mail: imaplib transport that parses headers, not ENVELOPE"
```

---

### Task 7: Composition MIME et envoi SMTP

**Files:**
- Create: `script/todo/mail/smtp_send.py`
- Create: `test/test_mail_send.py`

**Interfaces:**
- Consumes: `accounts.Account` (tâche 3).
- Produces:
  - `class SmtpError(Exception)`
  - `build_message(account, to, subject, body, *, cc=None, bcc=None, attachments=None, in_reply_to=None, references=None, date=None, msgid=None) -> EmailMessage`
  - `build_reply(account, original: EmailMessage, body, *, reply_all=False, date=None, msgid=None) -> EmailMessage`
  - `build_forward(account, original: EmailMessage, to, body, *, date=None, msgid=None) -> EmailMessage`
  - `recipients(msg) -> list[str]`
  - `class SmtpTransport(Protocol)` — `send_message(msg, from_addr: str, to_addrs: list[str]) -> None`, `quit() -> None`
  - `class SmtplibTransport`
  - `connect(account, password) -> SmtplibTransport`
  - `without_bcc(msg) -> EmailMessage` — copie sans le porte-Cci interne, à
    utiliser partout où le message quitte la machine (SMTP **et** dépôt IMAP
    dans Envoyés)
  - `send(account, msg, transport) -> list[str]` — rend la liste des destinataires servis

**Note :** `date` et `msgid` sont injectables uniquement pour que les tests soient déterministes. En production on ne les passe pas.

- [ ] **Step 1: Écrire les tests qui échouent**

`test/test_mail_send.py` :

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import email
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.smtp_send import (
    SmtpError,
    build_forward,
    build_message,
    build_reply,
    connect,
    recipients,
    send,
    without_bcc,
)

FIXED_DATE = "Fri, 01 Aug 2026 10:41:00 +0000"
FIXED_MSGID = "<fixe@erplibre>"


def account():
    return account_from_preset(
        "perso", "moi@x.ca", "generic", display_name="Mathieu Benoit"
    )


def original(subject="Devis", frm="Alice <alice@y.ca>", to="moi@x.ca", cc=""):
    raw = (
        f"From: {frm}\r\nTo: {to}\r\n"
        + (f"Cc: {cc}\r\n" if cc else "")
        + f"Subject: {subject}\r\n"
        f"Message-ID: <origine@y.ca>\r\n"
        f"Date: {FIXED_DATE}\r\n\r\nLe corps d'origine.\r\n"
    )
    return email.message_from_string(raw)


class FakeSmtp:
    def __init__(self, fail=False):
        self.sent = []
        self.quit_called = False
        self.fail = fail

    def send_message(self, msg, from_addr, to_addrs):
        if self.fail:
            raise OSError("550 destinataire refusé")
        self.sent.append((msg, from_addr, list(to_addrs)))

    def quit(self):
        self.quit_called = True


class TestBuildMessage(unittest.TestCase):
    def setUp(self):
        self.acc = account()

    def build(self, **kw):
        kw.setdefault("date", FIXED_DATE)
        kw.setdefault("msgid", FIXED_MSGID)
        return build_message(self.acc, "alice@y.ca", "Devis", "Bonjour", **kw)

    def test_from_uses_display_name(self):
        self.assertEqual(self.build()["From"], "Mathieu Benoit <moi@x.ca>")

    def test_from_without_display_name(self):
        acc = account_from_preset("perso", "moi@x.ca", "generic")
        msg = build_message(
            acc, "a@y.ca", "S", "B", date=FIXED_DATE, msgid=FIXED_MSGID
        )
        self.assertEqual(msg["From"], "moi@x.ca")

    def test_to_and_subject(self):
        msg = self.build()
        self.assertEqual(msg["To"], "alice@y.ca")
        self.assertEqual(msg["Subject"], "Devis")

    def test_body(self):
        self.assertIn("Bonjour", self.build().get_content())

    def test_accented_subject_survives(self):
        msg = build_message(
            self.acc, "a@y.ca", "Devis révisé", "B", date=FIXED_DATE, msgid=FIXED_MSGID
        )
        reparsed = email.message_from_bytes(msg.as_bytes())
        from email.header import decode_header

        # RFC 2047 découpe « Devis révisé » en DEUX morceaux : « Devis » reste
        # en clair, seul « révisé » est encodé. Ne lire que le premier
        # tronquerait le sujet et ferait échouer un test pourtant correct.
        parts = []
        for value, charset in decode_header(reparsed["Subject"]):
            if isinstance(value, bytes):
                value = value.decode(charset or "utf-8")
            parts.append(value)
        self.assertEqual("".join(parts), "Devis révisé")

    def test_multiple_recipients(self):
        msg = self.build(cc=["bob@y.ca", "carl@y.ca"])
        self.assertEqual(msg["Cc"], "bob@y.ca, carl@y.ca")

    def test_bcc_is_not_in_headers(self):
        """Un Cci qui part dans les en-têtes n'est plus un Cci."""
        msg = self.build(bcc=["secret@y.ca"])
        self.assertIsNone(msg["Bcc"])

    def test_bcc_is_still_a_recipient(self):
        msg = self.build(bcc=["secret@y.ca"])
        self.assertIn("secret@y.ca", recipients(msg))

    def test_message_id_present(self):
        self.assertEqual(self.build()["Message-ID"], FIXED_MSGID)

    def test_generated_message_id_when_absent(self):
        msg = build_message(self.acc, "a@y.ca", "S", "B", date=FIXED_DATE)
        self.assertTrue(msg["Message-ID"].startswith("<"))

    def test_empty_recipient_raises(self):
        with self.assertRaises(SmtpError):
            build_message(self.acc, "", "S", "B")


class TestAttachments(unittest.TestCase):
    def setUp(self):
        self.acc = account()
        self.tmp = tempfile.TemporaryDirectory()
        self.pdf = Path(self.tmp.name) / "devis.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 faux")

    def tearDown(self):
        self.tmp.cleanup()

    def test_message_becomes_multipart(self):
        msg = build_message(
            self.acc, "a@y.ca", "S", "B", attachments=[self.pdf],
            date=FIXED_DATE, msgid=FIXED_MSGID,
        )
        self.assertTrue(msg.is_multipart())

    def test_filename_is_kept(self):
        msg = build_message(
            self.acc, "a@y.ca", "S", "B", attachments=[self.pdf],
            date=FIXED_DATE, msgid=FIXED_MSGID,
        )
        names = [p.get_filename() for p in msg.iter_attachments()]
        self.assertEqual(names, ["devis.pdf"])

    def test_content_type_is_guessed(self):
        msg = build_message(
            self.acc, "a@y.ca", "S", "B", attachments=[self.pdf],
            date=FIXED_DATE, msgid=FIXED_MSGID,
        )
        part = next(msg.iter_attachments())
        self.assertEqual(part.get_content_type(), "application/pdf")

    def test_unknown_extension_falls_back_to_octet_stream(self):
        blob = Path(self.tmp.name) / "donnees.zzz"
        blob.write_bytes(b"\x00\x01")
        msg = build_message(
            self.acc, "a@y.ca", "S", "B", attachments=[blob],
            date=FIXED_DATE, msgid=FIXED_MSGID,
        )
        part = next(msg.iter_attachments())
        self.assertEqual(part.get_content_type(), "application/octet-stream")

    def test_missing_file_raises(self):
        with self.assertRaises(SmtpError):
            build_message(
                self.acc, "a@y.ca", "S", "B",
                attachments=[Path(self.tmp.name) / "absent.pdf"],
                date=FIXED_DATE, msgid=FIXED_MSGID,
            )

    def test_body_still_readable(self):
        msg = build_message(
            self.acc, "a@y.ca", "S", "Bonjour Alice", attachments=[self.pdf],
            date=FIXED_DATE, msgid=FIXED_MSGID,
        )
        self.assertIn("Bonjour Alice", msg.get_body(("plain",)).get_content())


class TestReply(unittest.TestCase):
    def setUp(self):
        self.acc = account()

    def reply(self, orig=None, **kw):
        kw.setdefault("date", FIXED_DATE)
        kw.setdefault("msgid", FIXED_MSGID)
        return build_reply(self.acc, orig or original(), "Ma réponse", **kw)

    def test_subject_gets_re_prefix(self):
        self.assertEqual(self.reply()["Subject"], "Re: Devis")

    def test_subject_not_prefixed_twice(self):
        self.assertEqual(self.reply(original(subject="Re: Devis"))["Subject"], "Re: Devis")

    def test_existing_re_case_insensitive(self):
        self.assertEqual(self.reply(original(subject="RE: Devis"))["Subject"], "RE: Devis")

    def test_recipient_is_the_sender(self):
        self.assertEqual(self.reply()["To"], "Alice <alice@y.ca>")

    def test_reply_to_header_wins(self):
        orig = original()
        orig["Reply-To"] = "equipe@y.ca"
        self.assertEqual(self.reply(orig)["To"], "equipe@y.ca")

    def test_in_reply_to(self):
        self.assertEqual(self.reply()["In-Reply-To"], "<origine@y.ca>")

    def test_references_starts_the_chain(self):
        self.assertEqual(self.reply()["References"], "<origine@y.ca>")

    def test_references_extends_the_chain(self):
        orig = original()
        orig["References"] = "<premier@y.ca> <second@y.ca>"
        self.assertEqual(
            self.reply(orig)["References"],
            "<premier@y.ca> <second@y.ca> <origine@y.ca>",
        )

    def test_reply_all_adds_the_others(self):
        orig = original(to="moi@x.ca, bob@y.ca", cc="carl@y.ca")
        msg = self.reply(orig, reply_all=True)
        joined = f"{msg['To']} {msg['Cc']}"
        self.assertIn("bob@y.ca", joined)
        self.assertIn("carl@y.ca", joined)

    def test_reply_all_drops_my_own_address(self):
        orig = original(to="moi@x.ca, bob@y.ca")
        msg = self.reply(orig, reply_all=True)
        self.assertNotIn("moi@x.ca", f"{msg['To']} {msg['Cc'] or ''}")

    def test_original_is_quoted(self):
        self.assertIn("> Le corps d'origine.", self.reply().get_content())


class TestForward(unittest.TestCase):
    def setUp(self):
        self.acc = account()

    def forward(self, **kw):
        kw.setdefault("date", FIXED_DATE)
        kw.setdefault("msgid", FIXED_MSGID)
        return build_forward(self.acc, original(), "bob@z.ca", "Pour info", **kw)

    def test_subject_gets_fwd_prefix(self):
        self.assertEqual(self.forward()["Subject"], "Fwd: Devis")

    def test_recipient(self):
        self.assertEqual(self.forward()["To"], "bob@z.ca")

    def test_original_attached_as_rfc822(self):
        types = [p.get_content_type() for p in self.forward().iter_attachments()]
        self.assertIn("message/rfc822", types)

    def test_no_in_reply_to(self):
        """Transférer n'est pas répondre : le fil ne doit pas se greffer."""
        self.assertIsNone(self.forward()["In-Reply-To"])


class TestRecipients(unittest.TestCase):
    def test_collects_to_cc_and_bcc(self):
        msg = build_message(
            account(), "a@y.ca", "S", "B", cc=["b@y.ca"], bcc=["c@y.ca"],
            date=FIXED_DATE, msgid=FIXED_MSGID,
        )
        self.assertEqual(sorted(recipients(msg)), ["a@y.ca", "b@y.ca", "c@y.ca"])

    def test_strips_display_names(self):
        msg = build_message(
            account(), "Alice <a@y.ca>", "S", "B", date=FIXED_DATE, msgid=FIXED_MSGID
        )
        self.assertEqual(recipients(msg), ["a@y.ca"])

    def test_deduplicates(self):
        msg = build_message(
            account(), "a@y.ca", "S", "B", cc=["a@y.ca"],
            date=FIXED_DATE, msgid=FIXED_MSGID,
        )
        self.assertEqual(recipients(msg), ["a@y.ca"])


class TestSend(unittest.TestCase):
    def setUp(self):
        self.acc = account()
        self.msg = build_message(
            self.acc, "a@y.ca", "S", "B", bcc=["c@y.ca"],
            date=FIXED_DATE, msgid=FIXED_MSGID,
        )

    def test_passes_envelope_from_and_recipients(self):
        smtp = FakeSmtp()
        served = send(self.acc, self.msg, smtp)
        _, from_addr, to_addrs = smtp.sent[0]
        self.assertEqual(from_addr, "moi@x.ca")
        self.assertEqual(sorted(to_addrs), ["a@y.ca", "c@y.ca"])
        self.assertEqual(sorted(served), ["a@y.ca", "c@y.ca"])

    def test_failure_is_wrapped(self):
        with self.assertRaises(SmtpError):
            send(self.acc, self.msg, FakeSmtp(fail=True))

    def test_failure_message_keeps_the_server_wording(self):
        with self.assertRaises(SmtpError) as ctx:
            send(self.acc, self.msg, FakeSmtp(fail=True))
        self.assertIn("550", str(ctx.exception))

    def test_no_recipient_raises_before_the_network(self):
        msg = build_message(
            self.acc, "a@y.ca", "S", "B", date=FIXED_DATE, msgid=FIXED_MSGID
        )
        del msg["To"]
        smtp = FakeSmtp()
        with self.assertRaises(SmtpError):
            send(self.acc, msg, smtp)
        self.assertEqual(smtp.sent, [])


class TestWithoutBcc(unittest.TestCase):
    """La copie qui part vers Envoyés emprunte IMAP, pas SMTP : elle doit
    être assainie elle aussi, sinon le Cci est lisible sur le serveur."""

    def setUp(self):
        self.msg = build_message(
            account(), "a@y.ca", "Devis", "Bonjour", bcc=["secret@y.ca"],
            date=FIXED_DATE, msgid=FIXED_MSGID,
        )

    def test_copy_has_no_internal_bcc_header(self):
        self.assertIsNone(without_bcc(self.msg)["X-ERPLibre-Bcc"])

    def test_bcc_address_is_absent_from_the_serialised_copy(self):
        self.assertNotIn(b"secret@y.ca", without_bcc(self.msg).as_bytes())

    def test_original_is_left_untouched(self):
        without_bcc(self.msg)
        self.assertIn("secret@y.ca", recipients(self.msg))

    def test_message_without_bcc_is_returned_as_is(self):
        plain = build_message(
            account(), "a@y.ca", "S", "B", date=FIXED_DATE, msgid=FIXED_MSGID
        )
        self.assertIs(without_bcc(plain), plain)

    def test_body_and_headers_survive(self):
        copy = without_bcc(self.msg)
        self.assertEqual(copy["Subject"], "Devis")
        self.assertIn("Bonjour", copy.get_content())


class TestConnect(unittest.TestCase):
    """`connect` choisit la branche SSL/STARTTLS et convertit les erreurs.

    Aucun de ces tests ne joint le réseau : `smtplib` est remplacé.
    """

    def _account(self, security):
        acc = account_from_preset("perso", "moi@x.ca", "generic")
        acc.smtp.host = "smtp.x.ca"
        acc.smtp.port = 465 if security == "ssl" else 587
        acc.smtp.security = security
        return acc

    def test_ssl_branch(self):
        client = MagicMock()
        with patch("smtplib.SMTP_SSL", return_value=client) as ctor:
            connect(self._account("ssl"), "hunter2")
        ctor.assert_called_once_with("smtp.x.ca", 465, timeout=30)
        client.login.assert_called_once_with("moi@x.ca", "hunter2")

    def test_starttls_branch_upgrades(self):
        client = MagicMock()
        with patch("smtplib.SMTP", return_value=client):
            connect(self._account("starttls"), "hunter2")
        client.starttls.assert_called_once()

    def test_plain_branch_does_not_upgrade(self):
        client = MagicMock()
        with patch("smtplib.SMTP", return_value=client):
            connect(self._account("none"), "hunter2")
        client.starttls.assert_not_called()

    def test_login_failure_becomes_an_smtp_error(self):
        client = MagicMock()
        client.login.side_effect = OSError("535 refus")
        with patch("smtplib.SMTP_SSL", return_value=client):
            with self.assertRaises(SmtpError) as ctx:
                connect(self._account("ssl"), "mauvais")
        self.assertIn("535", str(ctx.exception))

    def test_connection_failure_becomes_an_smtp_error(self):
        with patch("smtplib.SMTP_SSL", side_effect=OSError("injoignable")):
            with self.assertRaises(SmtpError):
                connect(self._account("ssl"), "hunter2")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_send.py" -v
```

Attendu : `ModuleNotFoundError`.

- [ ] **Step 3: Implémenter `smtp_send.py`**

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Construire un message et le remettre à un serveur SMTP.

`EmailMessage` fait le gros du travail : encodage des en-têtes accentués,
choix du transfert, structure multipart. On se contente de décider QUOI mettre
dedans — et surtout de ne pas mettre le Cci dans les en-têtes, où il cesserait
d'être caché tout en restant destinataire d'enveloppe.

`date` et `msgid` sont injectables pour que les tests soient déterministes ;
en production on laisse la stdlib les produire.
"""
from __future__ import annotations

import mimetypes
from email.message import EmailMessage
from email.utils import formatdate, getaddresses, make_msgid
from pathlib import Path
from typing import Protocol

MAX_QUOTE_LINES = 200


class SmtpError(Exception):
    """Message impossible à construire, ou serveur qui refuse."""


def _as_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _addresses(*header_values) -> list[str]:
    pairs = getaddresses([v for v in header_values if v])
    return [addr for _, addr in pairs if addr]


def build_message(
    account,
    to,
    subject: str,
    body: str,
    *,
    cc=None,
    bcc=None,
    attachments=None,
    in_reply_to: str | None = None,
    references: str | None = None,
    date: str | None = None,
    msgid: str | None = None,
) -> EmailMessage:
    to_list = _as_list(to)
    cc_list = _as_list(cc)
    bcc_list = _as_list(bcc)
    if not (to_list or cc_list or bcc_list):
        raise SmtpError("un message doit avoir au moins un destinataire")

    msg = EmailMessage()
    msg["From"] = account.from_header()
    if to_list:
        msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg["Subject"] = subject
    msg["Date"] = date or formatdate(localtime=True)
    msg["Message-ID"] = msgid or make_msgid(domain=account.email.split("@")[-1])
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    msg.set_content(body)

    # Le Cci ne va PAS dans les en-têtes : il ne vit que dans l'enveloppe
    # SMTP, que `recipients()` reconstitue.
    if bcc_list:
        msg["X-ERPLibre-Bcc"] = ", ".join(bcc_list)

    for path in attachments or []:
        _attach_file(msg, Path(path))
    return msg


def _attach_file(msg: EmailMessage, path: Path) -> None:
    if not path.is_file():
        raise SmtpError(f"pièce jointe introuvable : {path}")
    guessed, _ = mimetypes.guess_type(path.name)
    maintype, _, subtype = (guessed or "application/octet-stream").partition("/")
    msg.add_attachment(
        path.read_bytes(),
        maintype=maintype,
        subtype=subtype or "octet-stream",
        filename=path.name,
    )


def _plain_text(message) -> str:
    """Le texte d'un message, quel que soit son emballage."""
    if isinstance(message, EmailMessage):
        part = message.get_body(("plain",))
        if part is not None:
            return part.get_content()
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                try:
                    return payload.decode(charset, "replace")
                except LookupError:
                    # Un charset inconnu lève AVANT que `errors="replace"` ne
                    # serve : la recherche du codec échoue d'abord. Sans ce
                    # repli, un seul message mal étiqueté ferait tomber la
                    # réponse ou le transfert.
                    return payload.decode("utf-8", "replace")
        return ""
    payload = message.get_payload(decode=True)
    if payload is None:
        return str(message.get_payload())
    charset = message.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, "replace")
    except LookupError:
        return payload.decode("utf-8", "replace")


def _quote(text: str) -> str:
    lines = text.splitlines()[:MAX_QUOTE_LINES]
    return "\n".join(f"> {line}" for line in lines)


def build_reply(
    account,
    message,
    body: str,
    *,
    reply_all: bool = False,
    date: str | None = None,
    msgid: str | None = None,
) -> EmailMessage:
    subject = message.get("Subject", "")
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    to = [message.get("Reply-To") or message.get("From", "")]
    cc = []
    if reply_all:
        mine = account.email.lower()
        others = [
            addr
            for addr in _addresses(message.get("To"), message.get("Cc"))
            if addr.lower() != mine
        ]
        already = {a.lower() for a in _addresses(*to)}
        cc = [a for a in others if a.lower() not in already]

    parent_id = (message.get("Message-ID") or "").strip()
    references = " ".join(
        part for part in [(message.get("References") or "").strip(), parent_id] if part
    )

    return build_message(
        account,
        to,
        subject,
        f"{body}\n\n{_quote(_plain_text(message))}\n",
        cc=cc,
        in_reply_to=parent_id or None,
        references=references or None,
        date=date,
        msgid=msgid,
    )


def build_forward(
    account,
    message,
    to,
    body: str,
    *,
    date: str | None = None,
    msgid: str | None = None,
) -> EmailMessage:
    subject = message.get("Subject", "")
    if not subject.lower().startswith("fwd:"):
        subject = f"Fwd: {subject}"
    msg = build_message(account, to, subject, body, date=date, msgid=msgid)
    forwarded = message
    if not isinstance(forwarded, EmailMessage):
        import email

        forwarded = email.message_from_bytes(
            message.as_bytes(), _class=EmailMessage
        )
    # `add_attachment` dispatche vers `set_message_content` pour un `Message` :
    # cette variante n'a PAS de paramètre `maintype`, le passer lève TypeError.
    msg.add_attachment(forwarded, subtype="rfc822")
    return msg


def recipients(msg) -> list[str]:
    """Les destinataires d'enveloppe : To, Cc et le Cci gardé à part."""
    seen, out = set(), []
    for addr in _addresses(
        msg.get("To"), msg.get("Cc"), msg.get("X-ERPLibre-Bcc")
    ):
        low = addr.lower()
        if low not in seen:
            seen.add(low)
            out.append(addr)
    return out


class SmtpTransport(Protocol):
    def send_message(self, msg, from_addr: str, to_addrs: list[str]) -> None: ...

    def quit(self) -> None: ...


class SmtplibTransport:
    def __init__(self, client) -> None:
        self.client = client

    def send_message(self, msg, from_addr: str, to_addrs: list[str]) -> None:
        self.client.send_message(msg, from_addr=from_addr, to_addrs=to_addrs)

    def quit(self) -> None:
        try:
            self.client.quit()
        except Exception:
            pass


def connect(account, password: str) -> SmtplibTransport:
    import smtplib

    conf = account.smtp
    try:
        if conf.security == "ssl":
            client = smtplib.SMTP_SSL(conf.host, conf.port, timeout=30)
        else:
            client = smtplib.SMTP(conf.host, conf.port, timeout=30)
            if conf.security == "starttls":
                client.starttls()
        client.login(conf.user, password)
    except Exception as exc:
        raise SmtpError(f"connexion SMTP à {conf.host} refusée : {exc}") from exc
    return SmtplibTransport(client)


def send(account, msg, transport: SmtpTransport) -> list[str]:
    """Remet le message. Rend les destinataires servis, lève `SmtpError` sinon."""
    to_addrs = recipients(msg)
    if not to_addrs:
        raise SmtpError("aucun destinataire : rien n'a été envoyé")
    outgoing = without_bcc(msg)
    try:
        transport.send_message(outgoing, account.email, to_addrs)
    except Exception as exc:
        raise SmtpError(f"envoi refusé : {exc}") from exc
    return to_addrs


def without_bcc(msg):
    """Une copie sans le porte-Cci interne.

    PUBLIQUE à dessein : `send()` n'est pas le seul chemin par lequel le
    message quitte la machine. La copie déposée dans le dossier Envoyés part
    par IMAP, et si elle gardait `X-ERPLibre-Bcc` le Cci serait lisible sur le
    serveur — la même fuite, par une autre porte.
    """
    if msg.get("X-ERPLibre-Bcc") is None:
        return msg
    import copy

    clone = copy.deepcopy(msg)
    del clone["X-ERPLibre-Bcc"]
    return clone
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_send.py" -v
```

Attendu : `OK`, 50 tests.

- [ ] **Step 5: Formater et commiter**

```bash
make format
git add script/todo/mail/smtp_send.py test/test_mail_send.py
git commit -m "[ADD] mail: MIME building, replies, forwards and SMTP delivery"
```

---

### Task 8: Les fonctions pures de l'affichage

**Files:**
- Create: `script/todo/mail/tui_text.py`
- Create: `test/test_mail_tui_text.py`

**Interfaces:**
- Consumes: `store.MessageMeta` (tâche 4).
- Produces:
  - `@dataclass Attachment(filename: str, content_type: str, size: int, index: int)`
  - `html_to_text(html: str) -> str`
  - `extract_body(raw: bytes) -> tuple[str, list[Attachment]]`
  - `short_addr(value: str) -> str`
  - `truncate(text: str, width: int) -> str`
  - `format_date(epoch: int, now: int) -> str`
  - `format_size(size: int) -> str`
  - `is_unread(flags: str) -> bool`
  - `filter_messages(metas: list, query: str) -> list`

**Pourquoi un fichier à part :** ce sont les seules parties du TUI qui se testent vraiment. Les sortir de `tui.py` permet de les couvrir sans instancier une application Textual.

- [ ] **Step 1: Écrire les tests qui échouent**

`test/test_mail_tui_text.py` :

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import unittest

from script.todo.mail.store import MessageMeta
from script.todo.mail.tui_text import (
    extract_body,
    filter_messages,
    format_date,
    format_size,
    html_to_text,
    is_unread,
    short_addr,
    truncate,
)

# 2026-08-01 10:41:00 UTC
NOW = 1785580860


def meta(uid=1, subject="Devis", frm="Alice <alice@y.ca>", snippet="", flags=""):
    return MessageMeta(
        uid=uid, date=NOW, size=100, flags=flags, msgid=f"<{uid}@x.ca>",
        frm=frm, to="moi@x.ca", subject=subject, snippet=snippet,
    )


class TestHtmlToText(unittest.TestCase):
    def test_strips_tags(self):
        self.assertEqual(html_to_text("<p>Bonjour</p>"), "Bonjour")

    def test_decodes_entities(self):
        self.assertEqual(html_to_text("<p>caf&eacute; &amp; th&eacute;</p>"), "café & thé")

    def test_drops_script_and_style(self):
        out = html_to_text("<style>p{color:red}</style><script>alert(1)</script><p>Salut</p>")
        self.assertEqual(out, "Salut")

    def test_br_becomes_newline(self):
        self.assertEqual(html_to_text("a<br>b"), "a\nb")

    def test_block_tags_separate_lines(self):
        self.assertIn("\n", html_to_text("<div>a</div><div>b</div>"))

    def test_collapses_blank_runs(self):
        self.assertNotIn("\n\n\n", html_to_text("<p>a</p>\n\n\n\n\n<p>b</p>"))

    def test_empty_input(self):
        self.assertEqual(html_to_text(""), "")


class TestExtractBody(unittest.TestCase):
    def test_plain_text(self):
        text, atts = extract_body(b"Subject: S\r\n\r\nBonjour Alice")
        self.assertEqual(text.strip(), "Bonjour Alice")
        self.assertEqual(atts, [])

    def test_prefers_plain_over_html(self):
        raw = (
            b'Content-Type: multipart/alternative; boundary="B"\r\n\r\n'
            b"--B\r\nContent-Type: text/plain\r\n\r\nversion texte\r\n"
            b"--B\r\nContent-Type: text/html\r\n\r\n<p>version html</p>\r\n"
            b"--B--\r\n"
        )
        text, _ = extract_body(raw)
        self.assertIn("version texte", text)
        self.assertNotIn("html", text)

    def test_falls_back_to_html(self):
        raw = b"Content-Type: text/html\r\n\r\n<p>Bonjour <b>Alice</b></p>"
        text, _ = extract_body(raw)
        self.assertEqual(text.strip(), "Bonjour Alice")

    def test_lists_attachments(self):
        raw = (
            b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
            b"--B\r\nContent-Type: text/plain\r\n\r\ncorps\r\n"
            b"--B\r\nContent-Type: application/pdf\r\n"
            b'Content-Disposition: attachment; filename="devis.pdf"\r\n\r\n'
            b"%PDF\r\n--B--\r\n"
        )
        _, atts = extract_body(raw)
        self.assertEqual([a.filename for a in atts], ["devis.pdf"])
        self.assertEqual(atts[0].content_type, "application/pdf")

    def test_attachment_without_filename_gets_one(self):
        raw = (
            b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
            b"--B\r\nContent-Type: text/plain\r\n\r\ncorps\r\n"
            b"--B\r\nContent-Type: application/pdf\r\n"
            b"Content-Disposition: attachment\r\n\r\n%PDF\r\n--B--\r\n"
        )
        _, atts = extract_body(raw)
        self.assertTrue(atts[0].filename)

    def test_broken_message_does_not_raise(self):
        text, atts = extract_body(b"\x00\x01\x02 pas un courriel")
        self.assertIsInstance(text, str)
        self.assertIsInstance(atts, list)

    def test_unknown_charset_does_not_raise(self):
        """Un charset bidon doit dégrader l'affichage, pas tuer le TUI."""
        raw = b'Content-Type: text/plain; charset="bogus-xyz"\r\n\r\nBonjour'
        text, _ = extract_body(raw)
        self.assertIn("Bonjour", text)

    def test_decodes_charset(self):
        raw = (
            b"Content-Type: text/plain; charset=iso-8859-1\r\n"
            b"Content-Transfer-Encoding: 8bit\r\n\r\nCaf\xe9"
        )
        text, _ = extract_body(raw)
        self.assertIn("Café", text)


class TestShortAddr(unittest.TestCase):
    def test_display_name_wins(self):
        self.assertEqual(short_addr("Alice Tremblay <a@y.ca>"), "Alice Tremblay")

    def test_bare_address(self):
        self.assertEqual(short_addr("a@y.ca"), "a@y.ca")

    def test_quoted_display_name(self):
        self.assertEqual(short_addr('"Tremblay, Alice" <a@y.ca>'), "Tremblay, Alice")

    def test_empty(self):
        self.assertEqual(short_addr(""), "")

    def test_first_of_several(self):
        self.assertEqual(short_addr("a@y.ca, b@y.ca"), "a@y.ca")


class TestTruncate(unittest.TestCase):
    def test_short_text_untouched(self):
        self.assertEqual(truncate("abc", 10), "abc")

    def test_long_text_gets_ellipsis(self):
        self.assertEqual(truncate("abcdefghij", 5), "abcd…")

    def test_result_never_exceeds_width(self):
        self.assertEqual(len(truncate("abcdefghij", 5)), 5)

    def test_width_of_one(self):
        self.assertEqual(truncate("abcdef", 1), "…")

    def test_zero_width(self):
        self.assertEqual(truncate("abc", 0), "")


class TestFormatDate(unittest.TestCase):
    def test_today_shows_time(self):
        self.assertRegex(format_date(NOW, NOW), r"^\d{2}:\d{2}$")

    def test_this_year_shows_day_and_month(self):
        self.assertRegex(format_date(NOW - 90 * 86400, NOW), r"^\d{2}-\d{2}$")

    def test_older_shows_the_year(self):
        self.assertRegex(format_date(NOW - 800 * 86400, NOW), r"^\d{4}-\d{2}-\d{2}$")

    def test_zero_is_blank(self):
        self.assertEqual(format_date(0, NOW), "")

    def test_absurd_epoch_is_blank_and_does_not_raise(self):
        """Le contrat du module : une date d'en-tête aberrante ne lève jamais."""
        for hostile in (10**18, 2**63, -(10**18)):
            self.assertEqual(format_date(hostile, NOW), "")


class TestFormatSize(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(format_size(512), "512 o")

    def test_kilobytes(self):
        self.assertEqual(format_size(2048), "2.0 ko")

    def test_megabytes(self):
        self.assertEqual(format_size(5 * 1024 * 1024), "5.0 Mo")

    def test_zero(self):
        self.assertEqual(format_size(0), "0 o")


class TestIsUnread(unittest.TestCase):
    def test_no_flags_is_unread(self):
        self.assertTrue(is_unread(""))

    def test_seen_is_read(self):
        self.assertFalse(is_unread("\\Seen"))

    def test_seen_among_others(self):
        self.assertFalse(is_unread("\\Answered \\Seen"))

    def test_none_is_unread(self):
        self.assertTrue(is_unread(None))


class TestFilterMessages(unittest.TestCase):
    def setUp(self):
        self.metas = [
            meta(1, subject="Devis révisé", frm="Alice <a@y.ca>"),
            meta(2, subject="CR réunion", frm="Bob <b@y.ca>", snippet="ordre du jour"),
        ]

    def test_empty_query_returns_all(self):
        self.assertEqual(len(filter_messages(self.metas, "")), 2)

    def test_matches_subject(self):
        self.assertEqual([m.uid for m in filter_messages(self.metas, "devis")], [1])

    def test_is_case_insensitive(self):
        self.assertEqual([m.uid for m in filter_messages(self.metas, "DEVIS")], [1])

    def test_matches_sender(self):
        self.assertEqual([m.uid for m in filter_messages(self.metas, "bob")], [2])

    def test_matches_snippet(self):
        self.assertEqual([m.uid for m in filter_messages(self.metas, "ordre")], [2])

    def test_accent_insensitive(self):
        self.assertEqual([m.uid for m in filter_messages(self.metas, "revise")], [1])

    def test_no_match(self):
        self.assertEqual(filter_messages(self.metas, "zzz"), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_tui_text.py" -v
```

Attendu : `ModuleNotFoundError`.

- [ ] **Step 3: Implémenter `tui_text.py`**

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Tout ce que le TUI calcule avant d'afficher.

Ces fonctions sont volontairement hors de `tui.py` : elles n'ont besoin
d'aucun widget, donc elles se testent en une ligne. Le fichier de l'application
n'a plus qu'à composer des cadres et à appeler ces fonctions.

Un courriel arrive rarement dans la forme qu'on espère : corps vide, HTML seul,
charset menteur, pièce jointe sans nom. Aucune de ces fonctions ne lève ; au
pire elles rendent une chaîne vide. Un message illisible doit s'afficher mal,
pas faire tomber la boîte de réception.
"""
from __future__ import annotations

import datetime
import email
import email.policy
import html as html_module
import re
import unicodedata
from dataclasses import dataclass

_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL
)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_BLOCK_RE = re.compile(
    r"</(p|div|tr|li|h[1-6]|table|blockquote)>", re.IGNORECASE
)
_TAG_RE = re.compile(r"<[^>]+>")
_BLANKS_RE = re.compile(r"\n{3,}")


@dataclass
class Attachment:
    filename: str
    content_type: str
    size: int
    index: int


def html_to_text(html: str) -> str:
    """Du HTML rendu lisible, sans dépendance externe.

    Ce n'est pas un moteur de rendu : on veut lire un courriel, pas afficher
    une page. Scripts et styles disparaissent, les blocs deviennent des sauts
    de ligne, le reste est du texte.
    """
    if not html:
        return ""
    text = _SCRIPT_STYLE_RE.sub("", html)
    text = _BR_RE.sub("\n", text)
    text = _BLOCK_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = html_module.unescape(text)
    lines = [line.strip() for line in text.splitlines()]
    return _BLANKS_RE.sub("\n\n", "\n".join(lines)).strip()


def _decode_part(part) -> str:
    try:
        payload = part.get_payload(decode=True)
    except Exception:
        return ""
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, "replace")
    except LookupError:
        # Même piège que dans `imap_sync.snippet_from_raw` : un charset
        # inconnu lève à la recherche du codec, donc AVANT que
        # `errors="replace"` n'ait la moindre chance de servir.
        return payload.decode("utf-8", "replace")


def extract_body(raw: bytes) -> tuple[str, list[Attachment]]:
    """Le texte affichable d'un message, et la liste de ses pièces jointes."""
    try:
        msg = email.message_from_bytes(raw, policy=email.policy.default)
    except Exception:
        return raw.decode("utf-8", "replace"), []

    plain, html, attachments = "", "", []
    index = 0
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_maintype() == "multipart":
            continue
        disposition = (part.get_content_disposition() or "").lower()
        ctype = part.get_content_type()
        if disposition == "attachment" or (
            disposition == "inline" and not ctype.startswith("text/")
        ):
            try:
                payload = part.get_payload(decode=True) or b""
            except Exception:
                payload = b""
            attachments.append(
                Attachment(
                    filename=part.get_filename() or f"piece-jointe-{index + 1}",
                    content_type=ctype,
                    size=len(payload),
                    index=index,
                )
            )
            index += 1
            continue
        if ctype == "text/plain" and not plain:
            plain = _decode_part(part)
        elif ctype == "text/html" and not html:
            html = _decode_part(part)

    if plain:
        return plain, attachments
    if html:
        return html_to_text(html), attachments
    return "", attachments


def short_addr(value: str) -> str:
    """« Alice Tremblay <a@y.ca> » → « Alice Tremblay ». Sinon l'adresse."""
    if not value:
        return ""
    from email.utils import getaddresses

    pairs = getaddresses([value])
    if not pairs:
        return value.strip()
    name, addr = pairs[0]
    return (name or addr).strip()


def truncate(text: str, width: int) -> str:
    """Coupé à `width` caractères au plus, ellipse comprise."""
    text = text or ""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def format_date(epoch: int, now: int) -> str:
    """Aujourd'hui → l'heure. Cette année → jour-mois. Avant → la date pleine."""
    if not epoch:
        return ""
    try:
        stamp = datetime.datetime.fromtimestamp(epoch)
        today = datetime.datetime.fromtimestamp(now)
    except (OSError, OverflowError, ValueError):
        # `fromtimestamp` lève hors de la plage représentable — OSError ou
        # OverflowError selon l'ampleur. Une date aberrante vient d'un en-tête,
        # donc d'une source non fiable : elle doit s'afficher vide, pas faire
        # tomber la liste des messages.
        return ""
    if stamp.date() == today.date():
        return stamp.strftime("%H:%M")
    if stamp.year == today.year:
        return stamp.strftime("%m-%d")
    return stamp.strftime("%Y-%m-%d")


def format_size(size: int) -> str:
    size = size or 0
    if size < 1024:
        return f"{size} o"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} ko"
    return f"{size / (1024 * 1024):.1f} Mo"


def is_unread(flags: str | None) -> bool:
    return "\\seen" not in (flags or "").lower()


def _fold(text: str) -> str:
    """Sans accents ni casse : « revise » doit trouver « révisé »."""
    stripped = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in stripped if not unicodedata.combining(c)).lower()


def filter_messages(metas: list, query: str) -> list:
    """Filtre incrémental sur ce que le cache contient déjà.

    Volontairement local : la recherche côté serveur est une fonction de la
    phase 3, celle-ci doit répondre à chaque frappe sans réseau.
    """
    if not query:
        return list(metas)
    needle = _fold(query)
    return [
        m
        for m in metas
        if needle in _fold(f"{m.subject} {m.frm} {m.to} {m.snippet}")
    ]
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_tui_text.py" -v
```

Attendu : `OK`, 44 tests.

- [ ] **Step 5: Formater et commiter**

```bash
make format
git add script/todo/mail/tui_text.py test/test_mail_tui_text.py
git commit -m "[ADD] mail: the display logic that can be tested without a screen"
```

---

### Task 9: L'application Textual — trois volets et lecture plein écran

**Files:**
- Create: `script/todo/mail/tui.py`
- Create: `test/test_mail_tui.py`

**Interfaces:**
- Consumes: `accounts.load`, `accounts.Account` (tâche 3) ; `store.Store`, `store.resolve_mode`, `store.sweep_orphan_ephemeral` (tâche 4) ; `imap_sync.Syncer` (tâche 5) ; `imap_transport.connect` (tâche 6) ; `tui_text.*` (tâche 8) ; `secrets.SecretStore` (tâche 2).
- Produces:
  - `@dataclass MailboxRef(account_name: str, folder_name: str, display: str, unseen: int)`
  - `class Session` — un compte ouvert : `account`, `store`, `syncer`, `online: bool`, `error: str`
    - `open_sessions(accounts, secrets, base=None, connect_fn=None) -> list[Session]`
    - `Session.close()`, `Session.sync(progress=None) -> SyncReport`
  - `mailbox_refs(sessions) -> list[MailboxRef]`
  - `run_tui(run_app: bool = True, sessions=None) -> None`

**Rappel de contrainte :** `textual` s'importe **dans** `run_tui`, jamais au niveau module. `test_mail_tui.py` doit pouvoir importer `tui.py` sans Textual installé.

- [ ] **Step 1: Écrire les tests qui échouent**

`test/test_mail_tui.py` :

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.tui import (
    MailboxRef,
    Session,
    mailbox_refs,
    open_sessions,
)


class FailingConnect:
    def __init__(self, message="serveur injoignable"):
        self.message = message

    def __call__(self, account, password):
        raise OSError(self.message)


class FakeTransport:
    def list_folders(self):
        return []

    def logout(self):
        pass


class FakeSecrets:
    def __init__(self, password="hunter2"):
        self.password = password

    def get(self, ref):
        return self.password

    def set(self, ref, value):
        self.password = value


class SessionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.accounts = [
            account_from_preset("perso", "moi@x.ca", "generic"),
            account_from_preset("travail", "moi@y.ca", "generic"),
        ]
        # Épinglé : sans ça, resolve_mode lirait les préférences réelles de la
        # machine et le test dépendrait de ~/.erplibre.
        for account in self.accounts:
            account.cache_mode = "clear"

    def tearDown(self):
        self.tmp.cleanup()


class TestOpenSessions(SessionCase):
    def test_one_session_per_account(self):
        sessions = open_sessions(
            self.accounts, FakeSecrets(), base=self.base,
            connect_fn=lambda a, p: FakeTransport(),
        )
        self.assertEqual([s.account.name for s in sessions], ["perso", "travail"])
        for s in sessions:
            s.close()

    def test_disabled_account_is_skipped(self):
        self.accounts[1].enabled = False
        sessions = open_sessions(
            self.accounts, FakeSecrets(), base=self.base,
            connect_fn=lambda a, p: FakeTransport(),
        )
        self.assertEqual([s.account.name for s in sessions], ["perso"])
        for s in sessions:
            s.close()

    def test_cache_opens_even_when_the_network_fails(self):
        """Réseau coupé : la boîte doit rester consultable."""
        sessions = open_sessions(
            self.accounts, FakeSecrets(), base=self.base,
            connect_fn=FailingConnect(),
        )
        self.assertTrue(all(not s.online for s in sessions))
        self.assertTrue(all(s.store is not None for s in sessions))
        for s in sessions:
            s.close()

    def test_network_error_is_kept_for_display(self):
        sessions = open_sessions(
            self.accounts, FakeSecrets(), base=self.base,
            connect_fn=FailingConnect("530 refus"),
        )
        self.assertIn("530", sessions[0].error)
        for s in sessions:
            s.close()

    def test_missing_password_marks_offline(self):
        class NoSecret:
            def get(self, ref):
                return None

        sessions = open_sessions(
            self.accounts, NoSecret(), base=self.base,
            connect_fn=lambda a, p: FakeTransport(),
        )
        self.assertFalse(sessions[0].online)
        for s in sessions:
            s.close()

    def test_online_when_everything_works(self):
        sessions = open_sessions(
            self.accounts, FakeSecrets(), base=self.base,
            connect_fn=lambda a, p: FakeTransport(),
        )
        self.assertTrue(all(s.online for s in sessions))
        for s in sessions:
            s.close()


class TestMailboxRefs(SessionCase):
    def setUp(self):
        super().setUp()
        self.sessions = open_sessions(
            self.accounts, FakeSecrets(), base=self.base,
            connect_fn=lambda a, p: FakeTransport(),
        )

    def tearDown(self):
        for s in self.sessions:
            s.close()
        super().tearDown()

    def test_empty_when_no_folder(self):
        self.assertEqual(mailbox_refs(self.sessions), [])

    def test_lists_folders_of_every_account(self):
        self.sessions[0].store.upsert_folder("INBOX", "INBOX", "inbox")
        self.sessions[1].store.upsert_folder("INBOX", "INBOX", "inbox")
        refs = mailbox_refs(self.sessions)
        self.assertEqual(
            [(r.account_name, r.folder_name) for r in refs],
            [("perso", "INBOX"), ("travail", "INBOX")],
        )

    def test_inbox_comes_first(self):
        store = self.sessions[0].store
        store.upsert_folder("Archives", "Archives", None)
        store.upsert_folder("INBOX", "INBOX", "inbox")
        names = [r.folder_name for r in mailbox_refs(self.sessions)]
        self.assertEqual(names[0], "INBOX")

    def test_carries_unseen_count(self):
        store = self.sessions[0].store
        store.upsert_folder("INBOX", "INBOX", "inbox")
        store.set_folder_state("INBOX", unseen=4)
        self.assertEqual(mailbox_refs(self.sessions)[0].unseen, 4)

    def test_display_falls_back_to_name(self):
        self.sessions[0].store.upsert_folder("Projets")
        self.assertEqual(mailbox_refs(self.sessions)[0].display, "Projets")


class TestBrokenCache(SessionCase):
    """Un cache illisible sur UN compte ne doit pas couler les autres."""

    def _corrupt(self, name):
        root = self.base / name
        root.mkdir(parents=True, exist_ok=True)
        (root / "cache.db").write_bytes(b"pas une base sqlite" * 50)

    def _open(self):
        return open_sessions(
            self.accounts,
            FakeSecrets(),
            base=self.base,
            connect_fn=lambda a, p: FakeTransport(),
        )

    def test_the_other_accounts_still_open(self):
        self._corrupt("perso")
        sessions = self._open()
        self.assertEqual(
            [s.account.name for s in sessions], ["perso", "travail"]
        )
        self.assertIsNone(sessions[0].store)
        self.assertIsNotNone(sessions[1].store)
        for session in sessions:
            session.close()

    def test_the_broken_account_keeps_its_error(self):
        self._corrupt("perso")
        sessions = self._open()
        self.assertIn("cache.db", sessions[0].error)
        for session in sessions:
            session.close()

    def test_the_broken_account_is_offline(self):
        self._corrupt("perso")
        sessions = self._open()
        self.assertFalse(sessions[0].online)
        for session in sessions:
            session.close()

    def test_mailbox_refs_skips_it_without_raising(self):
        self._corrupt("perso")
        sessions = self._open()
        sessions[1].store.upsert_folder("INBOX", "INBOX", "inbox")
        refs = mailbox_refs(sessions)
        self.assertEqual([r.account_name for r in refs], ["travail"])
        for session in sessions:
            session.close()

    def test_closing_a_broken_session_does_not_raise(self):
        self._corrupt("perso")
        sessions = self._open()
        for session in sessions:
            session.close()


class TestImportsWithoutTextual(unittest.TestCase):
    def test_module_imports_without_textual(self):
        """Le module doit rester utilisable là où Textual n'est pas installé."""
        import script.todo.mail.tui as tui

        self.assertTrue(hasattr(tui, "run_tui"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_tui.py" -v
```

Attendu : `ModuleNotFoundError: No module named 'script.todo.mail.tui'`.

- [ ] **Step 3: Implémenter la partie testable de `tui.py`**

Créer `script/todo/mail/tui.py` avec, pour l'instant, tout sauf l'application :

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le client courriel à l'écran : trois volets, et la lecture en plein écran.

Textual s'importe DANS `run_tui`, jamais au niveau module — c'est le motif du
reste de `script/todo/`. Conséquence utile : la moitié basse de ce fichier
(sessions, dossiers) se teste sans écran et sans dépendance.

Une session = un compte ouvert. Elle survit à une panne réseau : le cache
s'ouvre d'abord, la connexion est tentée ensuite, et son échec ne fait que
poser un drapeau `online = False`. Une boîte hors ligne reste lisible.
"""
from __future__ import annotations

from dataclasses import dataclass

from script.todo.mail.imap_sync import Syncer
from script.todo.mail.store import Store, sweep_orphan_ephemeral

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


ROLE_ORDER = {"inbox": 0, "drafts": 1, "sent": 2, "archive": 3, "junk": 4, "trash": 5}


@dataclass
class MailboxRef:
    account_name: str
    folder_name: str
    display: str
    unseen: int


class Session:
    """Un compte ouvert : son cache, et son lien réseau s'il tient."""

    def __init__(self, account, store: Store, syncer: Syncer | None, error: str = ""):
        self.account = account
        self.store = store
        self.syncer = syncer
        self.error = error

    @property
    def online(self) -> bool:
        return self.syncer is not None

    def sync(self, progress=None):
        if self.syncer is None:
            return None
        return self.syncer.sync(progress=progress)

    def close(self) -> None:
        if self.syncer is not None:
            try:
                self.syncer.transport.logout()
            except Exception:
                pass
        if self.store is not None:
            if self.store.mode == "ephemeral":
                self.store.cleanup()
            else:
                self.store.close()


def open_sessions(accounts, secrets, base=None, connect_fn=None) -> list[Session]:
    """Ouvre le cache de chaque compte actif, puis tente le réseau.

    L'ordre compte : un mot de passe absent ou un serveur muet ne doit pas
    priver l'utilisateur de ce qu'il a déjà téléchargé.
    """
    if connect_fn is None:
        from script.todo.mail.imap_transport import connect as connect_fn

    sweep_orphan_ephemeral()
    sessions = []
    for account in accounts:
        if not account.enabled:
            continue
        store = Store(account, secrets=secrets, base=base)
        store.open()
        syncer, error = None, ""
        try:
            password = secrets.get(account.secret_ref)
            if not password:
                raise ValueError(t("mail_no_password_stored"))
            syncer = Syncer(store, connect_fn(account, password))
        except Exception as exc:
            error = str(exc)
        sessions.append(Session(account, store, syncer, error))
    return sessions


def mailbox_refs(sessions: list[Session]) -> list[MailboxRef]:
    """Les dossiers de tous les comptes, boîte de réception en tête."""
    refs = []
    for session in sessions:
        if session.store is None:
            # Compte dont le cache n'a pas pu s'ouvrir : il apparaît dans
            # l'arbre avec son erreur, mais il n'a aucun dossier à lister.
            continue
        folders = sorted(
            session.store.folders(),
            key=lambda f: (ROLE_ORDER.get(f["role"], 99), f["name"].lower()),
        )
        for folder in folders:
            refs.append(
                MailboxRef(
                    account_name=session.account.name,
                    folder_name=folder["name"],
                    display=folder["display"] or folder["name"],
                    unseen=folder["unseen"] or 0,
                )
            )
    return refs
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_tui.py" -v
```

Attendu : `OK`, 20 tests. `test_module_imports_without_textual` doit passer — s'il échoue, c'est qu'un `import textual` a fuité au niveau module.

- [ ] **Step 5: Ajouter l'application Textual**

À la fin de `script/todo/mail/tui.py` :

```python
def run_tui(run_app: bool = True, sessions=None) -> None:
    """Ouvre le client. `run_app=False` construit l'application sans la lancer,
    ce qui permet de vérifier qu'elle se compose sans écran."""
    try:
        from textual.app import App, ComposeResult
        from textual.binding import Binding
        from textual.containers import Horizontal, Vertical
        from textual.widgets import (
            DataTable,
            Footer,
            Header,
            Input,
            Static,
            Tree,
        )
    except ImportError:
        print(t("mail_install_textual"))
        return

    from script.todo.mail import tui_text
    from script.todo import todo_prefs

    class MailApp(App):
        CSS = """
        #panes { height: 1fr; }
        #folders { width: 28; border-right: solid $panel; }
        #list { width: 2fr; }
        #preview { width: 3fr; border-left: solid $panel; padding: 0 1; }
        #status { height: 1; background: $panel; }
        #search { display: none; }
        #search.visible { display: block; }
        .fullscreen #folders, .fullscreen #list { display: none; }
        """

        BINDINGS = [
            Binding("q", "quit", "Quitter"),
            Binding("r", "sync_current", "Sync"),
            Binding("R", "sync_all", "Sync tout"),
            Binding("enter", "toggle_fullscreen", "Plein écran"),
            Binding("escape", "leave_fullscreen", "Retour", show=False),
            Binding("slash", "focus_search", "Rechercher"),
            Binding("s", "mark_seen", "Lu"),
            Binding("u", "mark_unseen", "Non lu"),
        ]

        def __init__(self, sessions):
            super().__init__()
            self.sessions = sessions
            self.refs: list[MailboxRef] = []
            self.current_ref: MailboxRef | None = None
            self.metas = []
            self.query = ""

        # -- composition ------------------------------------------------

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Horizontal(id="panes"):
                yield Tree(t("mail_accounts"), id="folders")
                with Vertical():
                    yield Input(placeholder=t("mail_search"), id="search")
                    yield DataTable(id="list", cursor_type="row")
                yield Static("", id="preview")
            yield Static("", id="status")
            yield Footer()

        def on_mount(self) -> None:
            table = self.query_one("#list", DataTable)
            table.add_columns(" ", t("mail_from"), t("mail_subject"), t("mail_date"))
            self.reload_folders()
            self.run_worker(self.sync_all_worker, thread=True)
            interval = todo_prefs.get("mail_refresh_sec", 300)
            if interval:
                # Minuterie posée à l'ouverture, retirée avec l'écran : aucune
                # synchronisation ne tourne quand le TUI n'est pas là.
                self.set_interval(
                    interval, lambda: self.run_worker(self.sync_all_worker, thread=True)
                )

        # -- données ----------------------------------------------------

        def reload_folders(self) -> None:
            self.refs = mailbox_refs(self.sessions)
            tree = self.query_one("#folders", Tree)
            tree.clear()
            by_account: dict[str, list[MailboxRef]] = {}
            for ref in self.refs:
                by_account.setdefault(ref.account_name, []).append(ref)
            for session in self.sessions:
                mark = "" if session.online else " ⚠"
                node = tree.root.add(f"{session.account.name}{mark}", expand=True)
                for ref in by_account.get(session.account.name, []):
                    label = ref.display
                    if ref.unseen:
                        label = f"{label}  {ref.unseen}"
                    node.add_leaf(label, data=ref)
            tree.root.expand()
            if self.current_ref is None and self.refs:
                self.select_ref(self.refs[0])

        def session_for(self, name: str) -> Session | None:
            return next(
                (s for s in self.sessions if s.account.name == name), None
            )

        def select_ref(self, ref: MailboxRef) -> None:
            self.current_ref = ref
            session = self.session_for(ref.account_name)
            state = session.store.folder_state(ref.folder_name)
            self.metas = (
                session.store.list_messages(state["id"]) if state else []
            )
            self.refresh_list()

        def refresh_list(self) -> None:
            import time

            table = self.query_one("#list", DataTable)
            table.clear()
            now = int(time.time())
            for meta in tui_text.filter_messages(self.metas, self.query):
                table.add_row(
                    "●" if tui_text.is_unread(meta.flags) else " ",
                    tui_text.truncate(tui_text.short_addr(meta.frm), 22),
                    tui_text.truncate(meta.subject or t("mail_no_subject"), 48),
                    tui_text.format_date(meta.date, now),
                    key=str(meta.uid),
                )

        def current_meta(self):
            table = self.query_one("#list", DataTable)
            if table.cursor_row is None or not self.metas:
                return None
            shown = tui_text.filter_messages(self.metas, self.query)
            if table.cursor_row >= len(shown):
                return None
            return shown[table.cursor_row]

        # -- événements -------------------------------------------------

        def on_tree_node_selected(self, event) -> None:
            if isinstance(getattr(event.node, "data", None), MailboxRef):
                self.select_ref(event.node.data)

        def on_data_table_row_highlighted(self, event) -> None:
            self.show_preview()

        def on_input_changed(self, event) -> None:
            if event.input.id == "search":
                self.query = event.value
                self.refresh_list()

        def show_preview(self) -> None:
            meta = self.current_meta()
            preview = self.query_one("#preview", Static)
            if meta is None or self.current_ref is None:
                preview.update("")
                return
            session = self.session_for(self.current_ref.account_name)
            header = (
                f"[b]{t('mail_from')}[/b] {meta.frm}\n"
                f"[b]{t('mail_to')}[/b] {meta.to}\n"
                f"[b]{t('mail_subject')}[/b] {meta.subject}\n"
                f"{tui_text.format_size(meta.size)}\n\n"
            )
            if not session.online and not meta.has_body:
                preview.update(header + t("mail_body_needs_network"))
                return
            try:
                raw = session.syncer.fetch_body(
                    self.current_ref.folder_name, meta.uid
                ) if session.online else session.store.read_body(
                    self.current_ref.folder_name, meta.uid
                )
            except Exception as exc:
                preview.update(header + f"{t('mail_body_error')} {exc}")
                return
            body, attachments = tui_text.extract_body(raw or b"")
            if attachments:
                listing = "\n".join(
                    f"  📎 {a.filename}  {tui_text.format_size(a.size)}"
                    for a in attachments
                )
                header += f"{t('mail_attachments')}\n{listing}\n\n"
            preview.update(header + body)

        # -- actions ----------------------------------------------------

        def action_toggle_fullscreen(self) -> None:
            self.query_one("#panes").toggle_class("fullscreen")

        def action_leave_fullscreen(self) -> None:
            self.query_one("#panes").remove_class("fullscreen")

        def action_focus_search(self) -> None:
            field = self.query_one("#search", Input)
            field.add_class("visible")
            field.focus()

        def action_mark_seen(self) -> None:
            self._set_flag("\\Seen", add=True)

        def action_mark_unseen(self) -> None:
            self._set_flag("\\Seen", add=False)

        def _set_flag(self, flag: str, add: bool) -> None:
            meta = self.current_meta()
            if meta is None or self.current_ref is None:
                return
            session = self.session_for(self.current_ref.account_name)
            state = session.store.folder_state(self.current_ref.folder_name)
            flags = set(meta.flags.split()) if meta.flags else set()
            flags.add(flag) if add else flags.discard(flag)
            session.store.update_flags(state["id"], meta.uid, " ".join(sorted(flags)))
            if session.online:
                try:
                    session.syncer.transport.select(self.current_ref.folder_name)
                    session.syncer.transport.store_flags(
                        meta.uid, [flag] if add else [], [] if add else [flag]
                    )
                except Exception as exc:
                    self.set_status(f"{t('mail_flag_error')} {exc}")
            self.select_ref(self.current_ref)

        def action_sync_current(self) -> None:
            self.run_worker(self.sync_current_worker, thread=True)

        def action_sync_all(self) -> None:
            self.run_worker(self.sync_all_worker, thread=True)

        def set_status(self, text: str) -> None:
            self.call_from_thread(
                self.query_one("#status", Static).update, text
            ) if self._thread_id_differs() else self.query_one(
                "#status", Static
            ).update(text)

        def _thread_id_differs(self) -> bool:
            import threading

            return threading.current_thread() is not threading.main_thread()

        def sync_current_worker(self) -> None:
            if self.current_ref is None:
                return
            self._sync([self.session_for(self.current_ref.account_name)])

        def sync_all_worker(self) -> None:
            self._sync(self.sessions)

        def _sync(self, sessions) -> None:
            for session in sessions:
                if session is None or not session.online:
                    continue
                self.set_status(f"{t('mail_syncing')} {session.account.name}…")
                try:
                    report = session.sync()
                except Exception as exc:
                    self.set_status(f"{session.account.name} : {exc}")
                    continue
                message = (
                    f"{session.account.name} : {report.new_messages}"
                    f" {t('mail_new_messages')}"
                )
                if report.errors:
                    message += f" — {len(report.errors)} {t('mail_errors')}"
                self.set_status(message)
            if self._thread_id_differs():
                self.call_from_thread(self.reload_folders)
            else:
                self.reload_folders()

        def on_unmount(self) -> None:
            for session in self.sessions:
                session.close()

    app = MailApp(sessions or [])
    if run_app:
        app.run()
```

- [ ] **Step 6: Enregistrer une pièce jointe sur disque**

Le spec demande que les pièces jointes soient non seulement listées, mais
enregistrables. Ajouter la fonction, avant `run_tui` :

```python
def save_attachment(raw: bytes, index: int, directory) -> "pathlib.Path":
    """Écrit la pièce jointe `index` du message dans `directory`.

    Le nom vient du message, donc d'une source non fiable : on n'en garde que
    le nom de base, et on refuse de sortir du dossier demandé.
    """
    import email
    import email.policy
    import pathlib

    from script.todo.mail.tui_text import extract_body

    _, attachments = extract_body(raw)
    match = next((a for a in attachments if a.index == index), None)
    if match is None:
        raise ValueError(t("mail_attachment_not_found"))

    message = email.message_from_bytes(raw, policy=email.policy.default)
    parts = [
        part
        for part in (message.walk() if message.is_multipart() else [message])
        if part.get_content_maintype() != "multipart"
        and (part.get_content_disposition() or "").lower()
        in ("attachment", "inline")
    ]
    payload = parts[index].get_payload(decode=True) or b""

    directory = pathlib.Path(directory).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / pathlib.Path(match.filename).name
    target.write_bytes(payload)
    return target
```

et l'action correspondante dans `MailApp` :

```python
        def action_save_attachment(self) -> None:
            meta = self.current_meta()
            if meta is None or self.current_ref is None:
                return
            session = self.session_for(self.current_ref.account_name)
            raw = session.store.read_body(self.current_ref.folder_name, meta.uid)
            if raw is None:
                self.set_status(t("mail_body_needs_network"))
                return
            _, attachments = tui_text.extract_body(raw)
            if not attachments:
                self.set_status(t("mail_no_attachment"))
                return
            try:
                target = save_attachment(raw, 0, "~/Téléchargements")
            except Exception as exc:
                self.set_status(f"{t('mail_save_failed')} {exc}")
                return
            self.set_status(f"{t('mail_saved_to')} {target}")
```

avec le raccourci, dans `MailApp.BINDINGS` :

```python
            Binding("w", "save_attachment", "Enregistrer PJ"),
```

Ajouter les tests correspondants à `test/test_mail_tui.py` :

```python
class TestSaveAttachment(unittest.TestCase):
    RAW = (
        b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
        b"--B\r\nContent-Type: text/plain\r\n\r\ncorps\r\n"
        b"--B\r\nContent-Type: application/pdf\r\n"
        b'Content-Disposition: attachment; filename="devis.pdf"\r\n\r\n'
        b"%PDF\r\n--B--\r\n"
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_the_file(self):
        from script.todo.mail.tui import save_attachment

        target = save_attachment(self.RAW, 0, self.tmp.name)
        self.assertTrue(target.exists())
        self.assertEqual(target.name, "devis.pdf")

    def test_unknown_index_raises(self):
        from script.todo.mail.tui import save_attachment

        with self.assertRaises(ValueError):
            save_attachment(self.RAW, 7, self.tmp.name)

    def test_filename_cannot_escape_the_directory(self):
        """Le nom vient du message : il ne doit jamais écrire ailleurs."""
        from script.todo.mail.tui import save_attachment

        hostile = self.RAW.replace(b'"devis.pdf"', b'"../../evade.pdf"')
        target = save_attachment(hostile, 0, self.tmp.name)
        self.assertEqual(target.parent, Path(self.tmp.name))
```

- [ ] **Step 7: Vérifier que l'application se compose**

```bash
.venv.erplibre/bin/python -c "
from script.todo.mail.tui import run_tui
run_tui(run_app=False, sessions=[])
print('composition OK')
"
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_tui.py" -v
```

Attendu : `composition OK`, puis `OK`.

- [ ] **Step 8: Formater et commiter**

```bash
make format
git add script/todo/mail/tui.py test/test_mail_tui.py
git commit -m "[ADD] mail: three-pane Textual client with offline-tolerant sessions"
```

---

### Task 10: Écrire un message — formulaire et sortie vers `$EDITOR`

**Files:**
- Modify: `script/todo/mail/tui.py`
- Create: `test/test_mail_compose.py`

**Interfaces:**
- Consumes: `smtp_send.build_message`, `build_reply`, `build_forward`, `send`, `connect` (tâche 7) ; `tui.Session` (tâche 9).
- Produces:
  - `edit_in_external_editor(text: str, editor: str | None = None, runner=None) -> str`
  - `parse_recipients(raw: str) -> list[str]`
  - `deliver(session, msg, send_fn=None) -> str` — rend le message de statut à afficher
  - `class ComposeScreen` (interne à `run_tui`)

- [ ] **Step 1: Écrire les tests qui échouent**

`test/test_mail_compose.py` :

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.smtp_send import SmtpError, build_message
from script.todo.mail.store import Store
from script.todo.mail.tui import (
    Session,
    deliver,
    edit_in_external_editor,
    parse_recipients,
)


class TestParseRecipients(unittest.TestCase):
    def test_single(self):
        self.assertEqual(parse_recipients("a@y.ca"), ["a@y.ca"])

    def test_comma_separated(self):
        self.assertEqual(parse_recipients("a@y.ca, b@y.ca"), ["a@y.ca", "b@y.ca"])

    def test_semicolon_also_works(self):
        self.assertEqual(parse_recipients("a@y.ca; b@y.ca"), ["a@y.ca", "b@y.ca"])

    def test_keeps_display_names(self):
        self.assertEqual(
            parse_recipients("Alice <a@y.ca>, b@y.ca"), ["Alice <a@y.ca>", "b@y.ca"]
        )

    def test_drops_empty_fragments(self):
        self.assertEqual(parse_recipients("a@y.ca,,  ,b@y.ca"), ["a@y.ca", "b@y.ca"])

    def test_empty_string(self):
        self.assertEqual(parse_recipients(""), [])


class TestExternalEditor(unittest.TestCase):
    def test_returns_what_the_editor_wrote(self):
        def runner(cmd):
            path = Path(cmd[-1])
            path.write_text("écrit dans vim")
            return 0

        self.assertEqual(
            edit_in_external_editor("départ", editor="vim", runner=runner),
            "écrit dans vim",
        )

    def test_seeds_the_file_with_the_current_text(self):
        seen = {}

        def runner(cmd):
            seen["contenu"] = Path(cmd[-1]).read_text()
            return 0

        edit_in_external_editor("brouillon", editor="vim", runner=runner)
        self.assertEqual(seen["contenu"], "brouillon")

    def test_non_zero_exit_keeps_the_original(self):
        def runner(cmd):
            Path(cmd[-1]).write_text("ignoré")
            return 1

        self.assertEqual(
            edit_in_external_editor("départ", editor="vim", runner=runner), "départ"
        )

    def test_missing_editor_keeps_the_original(self):
        def runner(cmd):
            raise FileNotFoundError("pas d'éditeur")

        self.assertEqual(
            edit_in_external_editor("départ", editor="absent", runner=runner), "départ"
        )

    def test_temp_file_is_removed(self):
        seen = {}

        def runner(cmd):
            seen["chemin"] = Path(cmd[-1])
            return 0

        edit_in_external_editor("x", editor="vim", runner=runner)
        self.assertFalse(seen["chemin"].exists())


class DeliverCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "moi@x.ca", "generic")
        self.store = Store(self.account, mode="clear", base=Path(self.tmp.name))
        self.store.open()
        self.msg = build_message(self.account, "a@y.ca", "Devis", "Bonjour")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def session(self, online=True, transport=None):
        class FakeSyncer:
            def __init__(self, transport):
                self.transport = transport

        syncer = FakeSyncer(transport) if online else None
        return Session(self.account, self.store, syncer)


class TestDeliver(DeliverCase):
    def test_sends_and_reports(self):
        sent = []
        status = deliver(
            self.session(), self.msg, send_fn=lambda acc, m, tr: sent.append(m) or ["a@y.ca"]
        )
        self.assertEqual(len(sent), 1)
        self.assertIn("a@y.ca", status)

    def test_appends_to_the_sent_folder(self):
        class FakeTransport:
            def __init__(self):
                self.appended = []

            def append(self, folder, raw, flags):
                self.appended.append((folder, flags))

        transport = FakeTransport()
        deliver(
            self.session(transport=transport),
            self.msg,
            send_fn=lambda acc, m, tr: ["a@y.ca"],
        )
        self.assertEqual(transport.appended[0][0], self.account.sent_folder)
        self.assertIn("\\Seen", transport.appended[0][1])

    def test_append_failure_does_not_lose_the_send(self):
        """Le message est parti : un APPEND raté ne doit pas se lire comme un échec."""
        class BrokenTransport:
            def append(self, folder, raw, flags):
                raise OSError("dossier Envoyés introuvable")

        status = deliver(
            self.session(transport=BrokenTransport()),
            self.msg,
            send_fn=lambda acc, m, tr: ["a@y.ca"],
        )
        self.assertIn("a@y.ca", status)

    def test_offline_session_refuses(self):
        with self.assertRaises(SmtpError):
            deliver(self.session(online=False), self.msg)

    def test_send_failure_is_propagated(self):
        def boom(acc, m, tr):
            raise SmtpError("550 refus")

        with self.assertRaises(SmtpError):
            deliver(self.session(), self.msg, send_fn=boom)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_compose.py" -v
```

Attendu : `ImportError: cannot import name 'deliver'`.

- [ ] **Step 3: Ajouter les fonctions testables à `tui.py`**

Avant `run_tui`, dans `script/todo/mail/tui.py` :

```python
def parse_recipients(raw: str) -> list[str]:
    """« a@y.ca; Alice <b@y.ca> » → deux entrées. Virgule ou point-virgule."""
    if not raw:
        return []
    parts = raw.replace(";", ",").split(",")
    return [p.strip() for p in parts if p.strip()]


def edit_in_external_editor(
    text: str, editor: str | None = None, runner=None
) -> str:
    """Ouvre `$EDITOR` sur le corps et rend ce qui en revient.

    Si l'éditeur manque ou sort en erreur, on garde le texte de départ : perdre
    un brouillon parce que `vim` n'est pas installé serait inacceptable.
    """
    import os
    import subprocess
    import tempfile

    editor = editor or os.environ.get("EDITOR") or "nano"
    runner = runner or (lambda cmd: subprocess.call(cmd))
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".txt", delete=False, encoding="utf-8"
    )
    path = handle.name
    try:
        handle.write(text or "")
        handle.close()
        try:
            code = runner([editor, path])
        except Exception:
            return text
        if code != 0:
            return text
        with open(path, encoding="utf-8") as opened:
            return opened.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def deliver(session, msg, send_fn=None, connect_fn=None) -> str:
    """Envoie, puis dépose une copie dans Envoyés. Rend le texte de statut.

    L'ordre n'est pas négociable : l'APPEND vient APRÈS l'envoi, et son échec
    n'annule rien. Le message est déjà parti ; le signaler comme un échec
    pousserait l'utilisateur à l'envoyer deux fois.
    """
    from script.todo.mail.smtp_send import SmtpError, without_bcc
    from script.todo.mail.smtp_send import connect as smtp_connect
    from script.todo.mail.smtp_send import send as smtp_send_fn

    if not session.online:
        raise SmtpError(t("mail_offline_cannot_send"))

    send_fn = send_fn or smtp_send_fn
    transport = None
    if send_fn is smtp_send_fn:
        from script.todo.mail.secrets import SecretStore  # noqa: F401

        connect_fn = connect_fn or smtp_connect
        transport = connect_fn(session.account, session.password)
    try:
        served = send_fn(session.account, msg, transport)
    finally:
        if transport is not None:
            transport.quit()

    status = f"{t('mail_sent_to')} {', '.join(served)}"
    try:
        # `without_bcc` et pas `msg` : la copie déposée dans Envoyés part sur
        # le serveur IMAP, et garder le porte-Cci interne y rendrait le Cci
        # lisible — la même fuite que dans l'enveloppe SMTP, par une autre porte.
        session.syncer.transport.append(
            session.account.sent_folder, without_bcc(msg).as_bytes(), ["\\Seen"]
        )
    except Exception as exc:
        status += f" — {t('mail_sent_not_filed')} ({exc})"
    return status
```

`deliver` a besoin du mot de passe SMTP du compte. Le porter sur la session,
explicitement, plutôt que d'aller le rechercher dans le coffre à chaque envoi.

Dans `Session.__init__` (tâche 9), ajouter le paramètre :

```python
    def __init__(self, account, store: Store, syncer: Syncer | None,
                 error: str = "", password: str = ""):
        self.account = account
        self.store = store
        self.syncer = syncer
        self.error = error
        self.password = password
```

et, dans `open_sessions`, remplacer le corps de la boucle par :

```python
        store = Store(account, secrets=secrets, base=base)
        try:
            store.open()
        except Exception as exc:
            # Un cache corrompu, une clé introuvable ou un disque plein ne
            # doivent pas empêcher les AUTRES comptes de s'ouvrir. On garde la
            # session, sans cache, avec son erreur affichable — c'est le même
            # principe que pour une panne réseau, appliqué au disque.
            sessions.append(Session(account, None, None, str(exc), ""))
            continue
        syncer, error, password = None, "", ""
        try:
            password = secrets.get(account.secret_ref) or ""
            if not password:
                raise ValueError(t("mail_no_password_stored"))
            syncer = Syncer(store, connect_fn(account, password))
        except Exception as exc:
            error = str(exc)
        sessions.append(Session(account, store, syncer, error, password))
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_compose.py" -v
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_tui.py" -v
```

Attendu : `OK` pour les deux.

- [ ] **Step 5: Ajouter l'écran de composition**

Dans `run_tui`, après la définition de `MailApp`, ajouter l'écran et ses raccourcis. Le formulaire porte les en-têtes en `Input`, le corps en `TextArea`, et `e` sort vers `$EDITOR` :

```python
    from textual.screen import ModalScreen
    from textual.widgets import Button, TextArea

    class ComposeScreen(ModalScreen):
        BINDINGS = [
            Binding("ctrl+s", "send", "Envoyer"),
            Binding("e", "external_editor", "Éditeur"),
            Binding("escape", "cancel", "Annuler"),
        ]

        def __init__(self, session, msg_defaults=None):
            super().__init__()
            self.session = session
            self.defaults = msg_defaults or {}

        def compose(self):
            with Vertical(id="compose"):
                yield Static(
                    f"{t('mail_from')} {self.session.account.from_header()}"
                )
                yield Input(
                    value=self.defaults.get("to", ""),
                    placeholder=t("mail_to"),
                    id="to",
                )
                yield Input(
                    value=self.defaults.get("cc", ""),
                    placeholder=t("mail_cc"),
                    id="cc",
                )
                yield Input(
                    value=self.defaults.get("subject", ""),
                    placeholder=t("mail_subject"),
                    id="subject",
                )
                yield Input(placeholder=t("mail_attachments_paths"), id="files")
                yield TextArea(self.defaults.get("body", ""), id="body")
                yield Static("", id="compose_status")
                yield Button(t("mail_send"), id="send")

        def action_external_editor(self) -> None:
            area = self.query_one("#body", TextArea)
            area.text = edit_in_external_editor(area.text)

        def action_cancel(self) -> None:
            self.dismiss(None)

        def on_button_pressed(self, event) -> None:
            if event.button.id == "send":
                self.action_send()

        def action_send(self) -> None:
            from script.todo.mail.smtp_send import build_message

            status = self.query_one("#compose_status", Static)
            try:
                paths = [
                    p for p in parse_recipients(self.query_one("#files", Input).value)
                ]
                msg = build_message(
                    self.session.account,
                    parse_recipients(self.query_one("#to", Input).value),
                    self.query_one("#subject", Input).value,
                    self.query_one("#body", TextArea).text,
                    cc=parse_recipients(self.query_one("#cc", Input).value),
                    attachments=paths,
                    in_reply_to=self.defaults.get("in_reply_to"),
                    references=self.defaults.get("references"),
                )
                forwarded = self.defaults.get("forward_of")
                if forwarded is not None:
                    # `subtype=` seul : pour un `Message`, `add_attachment`
                    # dispatche vers `set_message_content`, qui n'a pas de
                    # paramètre `maintype` (vérifié à la tâche 7).
                    msg.add_attachment(forwarded, subtype="rfc822")
                self.dismiss(deliver(self.session, msg))
            except Exception as exc:
                # On ne ferme PAS l'écran : le brouillon reste à l'écran, avec
                # l'erreur exacte du serveur, prêt à être corrigé et renvoyé.
                status.update(f"[b red]{exc}[/]")
```

Puis, dans `MailApp`, les actions qui l'ouvrent :

```python
        def action_compose(self) -> None:
            session = self._session_or_first()
            if session:
                self.push_screen(ComposeScreen(session), self._after_compose)

        def action_reply(self) -> None:
            self._open_reply(reply_all=False)

        def action_reply_all(self) -> None:
            self._open_reply(reply_all=True)

        def action_forward(self) -> None:
            self._open_with_original(forward=True)

        def _session_or_first(self):
            if self.current_ref:
                return self.session_for(self.current_ref.account_name)
            return self.sessions[0] if self.sessions else None

        def _original_message(self):
            meta = self.current_meta()
            if meta is None or self.current_ref is None:
                return None, None
            session = self.session_for(self.current_ref.account_name)
            raw = session.store.read_body(self.current_ref.folder_name, meta.uid)
            if raw is None and session.online:
                raw = session.syncer.fetch_body(
                    self.current_ref.folder_name, meta.uid
                )
            if raw is None:
                return session, None
            import email
            import email.policy

            return session, email.message_from_bytes(
                raw, policy=email.policy.default
            )

        def _open_reply(self, reply_all: bool) -> None:
            from script.todo.mail.smtp_send import build_reply

            session, original = self._original_message()
            if session is None or original is None:
                self.set_status(t("mail_nothing_to_reply_to"))
                return
            draft = build_reply(session.account, original, "", reply_all=reply_all)
            self.push_screen(
                ComposeScreen(
                    session,
                    {
                        "to": draft["To"] or "",
                        "cc": draft["Cc"] or "",
                        "subject": subject,
                        "body": draft.get_content(),
                        "in_reply_to": draft["In-Reply-To"],
                        "references": draft["References"],
                    },
                ),
                self._after_compose,
            )

        def _open_with_original(self, forward: bool) -> None:
            session, original = self._original_message()
            if session is None or original is None:
                self.set_status(t("mail_nothing_to_forward"))
                return
            # `build_forward` exige un destinataire réel (il construit le
            # message final, prêt à partir) : lui en passer un vide — le
            # temps de ne connaître QUE le sujet, avant que l'utilisateur
            # n'ait rempli le formulaire — lève `SmtpError`. Le préfixe
            # « Fwd: » est donc calculé ici, sans passer par `build_message`.
            subject = original.get("Subject", "") or ""
            if not subject.lower().startswith("fwd:"):
                subject = f"Fwd: {subject}"
            self.push_screen(
                ComposeScreen(
                    session,
                    {
                        "subject": subject,
                        "body": "",
                        # Le message d'origine voyage à part : `action_send`
                        # reconstruit le courriel depuis le formulaire, donc
                        # sans ça le transfert partirait VIDE, avec le seul
                        # objet « Fwd: ».
                        "forward_of": original,
                    },
                ),
                self._after_compose,
            )

        def _after_compose(self, status) -> None:
            if status:
                self.set_status(status)
```

et les raccourcis, à ajouter à `MailApp.BINDINGS` :

```python
            Binding("c", "compose", "Écrire"),
            Binding("a", "reply", "Répondre"),
            Binding("A", "reply_all", "Répondre à tous"),
            Binding("f", "forward", "Transférer"),
```

- [ ] **Step 6: Vérifier que tout se compose encore**

```bash
.venv.erplibre/bin/python -c "
from script.todo.mail.tui import run_tui
run_tui(run_app=False, sessions=[])
print('composition OK')
"
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_*.py" 2>&1 | tail -3
```

Attendu : `composition OK` puis `OK`.

- [ ] **Step 7: Formater et commiter**

```bash
make format
git add script/todo/mail/tui.py test/test_mail_compose.py
git commit -m "[ADD] mail: compose form, external editor and delivery to Sent"
```

---

### Task 11: Le menu, et « Question » qui devient « Assistant »

**Files:**
- Create: `script/todo/mail/menu.py`
- Modify: `script/todo/todo_i18n.py`
- Modify: `script/todo/todo.py` (menu principal et `execute_prompt_ia`)
- Create: `test/test_mail_menu.py`

**Interfaces:**
- Consumes: tout le paquet `mail`.
- Produces :
  - `prompt_execute_mail(todo) -> None`
  - `prompt_mail_accounts(todo) -> None`
  - `prompt_mail_cache(todo) -> None`
  - `secret_store_for(todo) -> SecretStore`
  - `cache_summary(accounts, base=None) -> list[dict]` — nom, mode, taille
- Modifiées dans `todo.py` : `prompt_assistant()` (nouveau), `_assistant_question()` (l'ancien corps d'`execute_prompt_ia`, inchangé).

- [ ] **Step 1: Ajouter les clés i18n**

Dans `script/todo/todo_i18n.py`, remplacer l'entrée `"Question"` (ligne 38) par :

```python
    "Assistant": {
        "fr": "🤖 Assistant",
        "en": "🤖 Assistant",
    },
```

Puis ajouter, à la fin du dictionnaire `TRANSLATIONS`, ce bloc :

```python
    # Courriel
    "mail_menu": {
        "fr": "Courriel - Lire et envoyer du courriel",
        "en": "Mail - Read and send email",
    },
    "mail_ai_question": {
        "fr": "Question IA - Poser une question à un modèle",
        "en": "AI question - Ask a model a question",
    },
    "mail_open_tui": {
        "fr": "Ouvrir le client courriel (TUI)",
        "en": "Open the mail client (TUI)",
    },
    "mail_accounts_menu": {"fr": "Comptes", "en": "Accounts"},
    "mail_sync_now": {"fr": "Synchroniser maintenant", "en": "Synchronise now"},
    "mail_cache_menu": {"fr": "Cache", "en": "Cache"},
    "mail_account_list": {"fr": "Lister les comptes", "en": "List accounts"},
    "mail_account_add": {"fr": "Ajouter un compte", "en": "Add an account"},
    "mail_account_delete": {"fr": "Supprimer un compte", "en": "Delete an account"},
    "mail_account_template": {
        "fr": "Générer un modèle accounts.json",
        "en": "Generate an accounts.json template",
    },
    "mail_account_test": {
        "fr": "Tester la connexion d'un compte",
        "en": "Test an account connection",
    },
    "mail_cache_default_mode": {
        "fr": "Mode de cache par défaut",
        "en": "Default cache mode",
    },
    "mail_cache_account_mode": {
        "fr": "Mode de cache d'un compte",
        "en": "Cache mode of one account",
    },
    "mail_cache_size_purge": {
        "fr": "Taille du cache et purge",
        "en": "Cache size and purge",
    },
    "mail_no_account": {
        "fr": "Aucun compte configuré. Ajoutez-en un d'abord.",
        "en": "No account configured. Add one first.",
    },
    "mail_ask_name": {"fr": "Nom court du compte : ", "en": "Short account name: "},
    "mail_ask_email": {"fr": "Adresse courriel : ", "en": "Email address: "},
    "mail_ask_display_name": {
        "fr": "Nom affiché (facultatif) : ",
        "en": "Display name (optional): ",
    },
    "mail_ask_preset": {"fr": "Fournisseur : ", "en": "Provider: "},
    "mail_ask_password": {"fr": "Mot de passe : ", "en": "Password: "},
    "mail_ask_imap_host": {"fr": "Serveur IMAP : ", "en": "IMAP server: "},
    "mail_ask_smtp_host": {"fr": "Serveur SMTP : ", "en": "SMTP server: "},
    "mail_ask_account": {"fr": "Quel compte ? ", "en": "Which account? "},
    "mail_ask_mode": {
        "fr": "Mode (clear / encrypted / ephemeral) : ",
        "en": "Mode (clear / encrypted / ephemeral): ",
    },
    "mail_app_password_note": {
        "fr": "Ce fournisseur exige un mot de passe d'application.",
        "en": "This provider requires an app password.",
    },
    "mail_account_saved": {"fr": "Compte enregistré.", "en": "Account saved."},
    "mail_account_deleted": {"fr": "Compte supprimé.", "en": "Account deleted."},
    "mail_connection_ok": {"fr": "Connexion réussie.", "en": "Connection succeeded."},
    "mail_connection_failed": {"fr": "Connexion échouée :", "en": "Connection failed:"},
    "mail_template_written": {"fr": "Modèle écrit dans", "en": "Template written to"},
    "mail_purge_confirm": {
        "fr": "Effacer tout le cache de ce compte ? (o/N) ",
        "en": "Erase this account's whole cache? (y/N) ",
    },
    "mail_purged": {"fr": "Cache effacé.", "en": "Cache erased."},
    "mail_no_vault": {
        "fr": "Aucun coffre disponible : installez pykeepass ou déverrouillez un trousseau système.",
        "en": "No vault available: install pykeepass or unlock a system keyring.",
    },
    "mail_no_password_stored": {
        "fr": "Aucun mot de passe enregistré pour ce compte.",
        "en": "No password stored for this account.",
    },
    "mail_install_textual": {
        "fr": "Installez textual pour le client courriel (pip).",
        "en": "Install textual for the mail client (pip).",
    },
    "mail_accounts": {"fr": "Comptes", "en": "Accounts"},
    "mail_search": {"fr": "Rechercher…", "en": "Search…"},
    "mail_from": {"fr": "De :", "en": "From:"},
    "mail_to": {"fr": "À :", "en": "To:"},
    "mail_cc": {"fr": "Cc :", "en": "Cc:"},
    "mail_subject": {"fr": "Objet :", "en": "Subject:"},
    "mail_date": {"fr": "Date", "en": "Date"},
    "mail_send": {"fr": "Envoyer", "en": "Send"},
    "mail_attachments": {"fr": "Pièces jointes :", "en": "Attachments:"},
    "mail_attachments_paths": {
        "fr": "Pièces jointes (chemins séparés par des virgules)",
        "en": "Attachments (comma-separated paths)",
    },
    "mail_no_subject": {"fr": "(sans objet)", "en": "(no subject)"},
    "mail_body_needs_network": {
        "fr": "Corps non téléchargé — connexion requise.",
        "en": "Body not downloaded — connection required.",
    },
    "mail_body_error": {
        "fr": "Lecture du corps impossible :",
        "en": "Cannot read the body:",
    },
    "mail_flag_error": {
        "fr": "Drapeau non transmis au serveur :",
        "en": "Flag not sent to the server:",
    },
    "mail_syncing": {"fr": "Synchronisation de", "en": "Synchronising"},
    "mail_new_messages": {"fr": "nouveaux messages", "en": "new messages"},
    "mail_errors": {"fr": "erreurs", "en": "errors"},
    "mail_offline_cannot_send": {
        "fr": "Compte hors ligne : envoi impossible.",
        "en": "Account offline: cannot send.",
    },
    "mail_sent_to": {"fr": "Envoyé à", "en": "Sent to"},
    "mail_sent_not_filed": {
        "fr": "envoyé, mais pas classé dans Envoyés",
        "en": "sent, but not filed in Sent",
    },
    "mail_nothing_to_reply_to": {
        "fr": "Aucun message sélectionné.",
        "en": "No message selected.",
    },
    "mail_nothing_to_forward": {
        "fr": "Aucun message à transférer.",
        "en": "No message to forward.",
    },
    "mail_attachment_not_found": {
        "fr": "Pièce jointe introuvable.",
        "en": "Attachment not found.",
    },
    "mail_no_attachment": {
        "fr": "Ce message n'a pas de pièce jointe.",
        "en": "This message has no attachment.",
    },
    "mail_save_failed": {
        "fr": "Enregistrement impossible :",
        "en": "Cannot save:",
    },
    "mail_saved_to": {"fr": "Enregistré dans", "en": "Saved to"},
```

- [ ] **Step 2: Vérifier la complétude des traductions**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_todo_i18n.py" -v 2>&1 | grep -E "test_all_entries_have_fr_and_en|test_no_empty_translations"
```

Attendu : les deux en `ok`. Les trois échecs de `TestT` restent, ils sont dans la baseline.

- [ ] **Step 3: Écrire les tests du menu**

`test/test_mail_menu.py` :

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.menu import cache_summary
from script.todo.mail.store import Store


class TestCacheSummary(unittest.TestCase):
    # Sans injection, `resolve_mode` retombe sur les VRAIES préférences de la
    # machine, et `todo_prefs` crée `~/.erplibre` au passage.
    CLEAR = staticmethod(lambda k, d=None: "clear")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.accounts = [
            account_from_preset("perso", "a@x.ca", "generic"),
            account_from_preset("travail", "b@x.ca", "generic"),
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_row_per_account(self):
        rows = cache_summary(
            self.accounts, base=self.base, prefs_get=self.CLEAR
        )
        self.assertEqual([r["name"] for r in rows], ["perso", "travail"])

    def test_reports_the_effective_mode(self):
        self.accounts[0].cache_mode = "encrypted"
        rows = cache_summary(
            self.accounts, base=self.base, prefs_get=lambda k, d=None: "clear"
        )
        self.assertEqual(rows[0]["mode"], "encrypted")
        self.assertEqual(rows[1]["mode"], "clear")

    def test_size_is_zero_before_any_sync(self):
        rows = cache_summary(self.accounts, base=self.base, prefs_get=self.CLEAR)
        self.assertEqual(rows[0]["size"], 0)

    def test_size_grows_with_the_cache(self):
        store = Store(self.accounts[0], mode="clear", base=self.base)
        store.open()
        store.upsert_folder("INBOX")
        store.write_body("INBOX", 1, b"x" * 4096)
        store.close()
        rows = cache_summary(self.accounts, base=self.base, prefs_get=self.CLEAR)
        self.assertGreater(rows[0]["size"], 4000)

    def test_missing_cache_does_not_raise(self):
        rows = cache_summary(
            self.accounts, base=self.base / "inexistant", prefs_get=self.CLEAR
        )
        self.assertEqual(len(rows), 2)


class TestAddAccountRollsBack(unittest.TestCase):
    """Une sauvegarde ratée ne doit pas laisser le mot de passe dans le coffre."""

    def test_failed_save_removes_the_orphan_secret(self):
        from unittest.mock import MagicMock, patch

        import script.todo.mail.menu as menu

        vault = MagicMock()
        vault.available_backends.return_value = ["kdbx"]
        with patch.object(
            menu, "secret_store_for", return_value=vault
        ), patch.object(
            menu.mail_accounts, "save", side_effect=OSError("disque plein")
        ), patch.object(
            menu, "_load_accounts", return_value=[]
        ), patch(
            "builtins.input",
            side_effect=["perso", "moi@x.ca", "", "4", "imap.x.ca", "smtp.x.ca"],
        ), patch(
            "getpass.getpass", return_value="hunter2"
        ):
            menu._add_account(MagicMock())

        vault.set.assert_called_once()
        vault.delete.assert_called_once_with("kdbx:ERPLibre/Mail/perso")

    def test_failed_save_does_not_crash_the_menu(self):
        from unittest.mock import MagicMock, patch

        import script.todo.mail.menu as menu

        vault = MagicMock()
        vault.available_backends.return_value = ["kdbx"]
        with patch.object(
            menu, "secret_store_for", return_value=vault
        ), patch.object(
            menu.mail_accounts, "save", side_effect=OSError("disque plein")
        ), patch.object(
            menu, "_load_accounts", return_value=[]
        ), patch(
            "builtins.input",
            side_effect=["perso", "moi@x.ca", "", "4", "imap.x.ca", "smtp.x.ca"],
        ), patch(
            "getpass.getpass", return_value="hunter2"
        ):
            menu._add_account(MagicMock())  # ne doit pas lever


class TestMailKeysAreTranslated(unittest.TestCase):
    """Le seul filet contre une clé oubliée.

    `t()` rend la clé elle-même quand elle est absente : rien n'échoue, et
    l'interface affiche « mail_body_error » en toutes lettres à l'utilisateur.
    Aucun autre test ne peut attraper ça.
    """

    def test_every_key_used_in_the_mail_package_is_declared(self):
        import re
        from pathlib import Path

        import script.todo.mail as mail_pkg
        from script.todo.todo_i18n import TRANSLATIONS

        pattern = re.compile(r"""(?<![A-Za-z_])t\((["'])(mail_[a-z_]+)\1\)""")
        used = set()
        for path in Path(mail_pkg.__file__).parent.glob("*.py"):
            used |= {m.group(2) for m in pattern.finditer(path.read_text())}
        self.assertTrue(used, "aucune clé trouvée : le motif ne correspond plus")
        missing = sorted(used - set(TRANSLATIONS))
        self.assertEqual(
            missing, [], f"clés utilisées mais non traduites : {missing}"
        )


class TestTodoWiring(unittest.TestCase):
    def test_todo_exposes_prompt_assistant(self):
        from script.todo.todo import TODO

        self.assertTrue(hasattr(TODO, "prompt_assistant"))

    def test_todo_keeps_the_ai_question(self):
        from script.todo.todo import TODO

        self.assertTrue(hasattr(TODO, "_assistant_question"))

    def test_assistant_key_is_translated(self):
        from script.todo.todo_i18n import TRANSLATIONS

        self.assertIn("Assistant", TRANSLATIONS)
        self.assertNotIn("Question", TRANSLATIONS)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils échouent**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_menu.py" -v
```

Attendu : `ModuleNotFoundError: No module named 'script.todo.mail.menu'`.

- [ ] **Step 5: Implémenter `menu.py`**

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les entrées de menu du client courriel.

Ce module est le SEUL point de contact entre le paquet `mail` et le CLI :
`todo.py` importe `prompt_execute_mail` et rien d'autre. Le sens de la
dépendance est volontaire — `mail` ne doit jamais importer `todo`.
"""
from __future__ import annotations

import getpass

import click

from script.todo import todo_prefs
from script.todo.mail import accounts as mail_accounts
from script.todo.mail.accounts import PRESETS, AccountError
from script.todo.mail.secrets import SecretError, SecretStore
from script.todo.mail.store import Store, resolve_mode
from script.todo.todo_i18n import t

CACHE_MODES = ("clear", "encrypted", "ephemeral")


def secret_store_for(todo) -> SecretStore:
    """Le coffre du CLI : son kdbx s'il en a un, sinon le trousseau système."""
    manager = getattr(todo, "kdbx_manager", None)
    return SecretStore(kdbx_manager=manager, use_keyring=True)


def cache_summary(accounts, base=None, prefs_get=None) -> list[dict]:
    """Nom, mode effectif et taille sur disque, pour l'écran de cache."""
    rows = []
    for account in accounts:
        mode = resolve_mode(account, prefs_get)
        size = 0
        try:
            root = Store(account, mode=mode, base=base).root
            if root.is_dir():
                size = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
        except Exception:
            size = 0
        rows.append({"name": account.name, "mode": mode, "size": size})
    return rows


def _load_accounts():
    try:
        return mail_accounts.load()
    except AccountError as exc:
        print(exc)
        return []


def prompt_execute_mail(todo) -> None:
    while True:
        help_info = f"""{todo._menu_header()}
[1] {t("mail_open_tui")}
[2] {t("mail_accounts_menu")}
[3] {t("mail_sync_now")}
[4] {t("mail_cache_menu")}
[0] {t("Back")}"""
        status = click.prompt(help_info)
        print()
        if status == "0":
            return
        if status == "1":
            _open_tui(todo)
        elif status == "2":
            prompt_mail_accounts(todo)
        elif status == "3":
            _sync_now(todo)
        elif status == "4":
            prompt_mail_cache(todo)
        else:
            print(t("Command not found !"))


def _open_tui(todo) -> None:
    from script.todo.mail.tui import open_sessions, run_tui

    accounts = _load_accounts()
    if not accounts:
        print(t("mail_no_account"))
        return
    sessions = open_sessions(accounts, secret_store_for(todo))
    try:
        run_tui(sessions=sessions)
    finally:
        for session in sessions:
            session.close()


def _sync_now(todo) -> None:
    from script.todo.mail.tui import open_sessions

    accounts = _load_accounts()
    if not accounts:
        print(t("mail_no_account"))
        return
    sessions = open_sessions(accounts, secret_store_for(todo))
    try:
        for session in sessions:
            if not session.online:
                print(f"{session.account.name} : {session.error}")
                continue
            report = session.sync()
            print(
                f"{session.account.name} : {report.new_messages}"
                f" {t('mail_new_messages')}"
            )
            for error in report.errors:
                print(f"  {error}")
    finally:
        for session in sessions:
            session.close()


def prompt_mail_accounts(todo) -> None:
    while True:
        help_info = f"""{todo._menu_header()}
[1] {t("mail_account_list")}
[2] {t("mail_account_add")}
[3] {t("mail_account_delete")}
[4] {t("mail_account_template")}
[5] {t("mail_account_test")}
[0] {t("Back")}"""
        status = click.prompt(help_info)
        print()
        if status == "0":
            return
        if status == "1":
            _list_accounts()
        elif status == "2":
            _add_account(todo)
        elif status == "3":
            _delete_account(todo)
        elif status == "4":
            _write_template()
        elif status == "5":
            _test_account(todo)
        else:
            print(t("Command not found !"))


def _list_accounts() -> None:
    accounts = _load_accounts()
    if not accounts:
        print(t("mail_no_account"))
        return
    for account in accounts:
        mark = "" if account.enabled else " (désactivé)"
        print(
            f"  {account.name}{mark} — {account.email}"
            f" — {account.imap.host} / {account.smtp.host}"
        )


def _add_account(todo) -> None:
    store = secret_store_for(todo)
    if not store.available_backends():
        print(t("mail_no_vault"))
        return

    name = input(t("mail_ask_name")).strip()
    email_addr = input(t("mail_ask_email")).strip()
    display = input(t("mail_ask_display_name")).strip()

    keys = list(PRESETS)
    for index, key in enumerate(keys, start=1):
        print(f"  [{index}] {PRESETS[key]['label']}")
    choice = input(t("mail_ask_preset")).strip()
    try:
        preset_key = keys[int(choice) - 1]
    except (ValueError, IndexError):
        preset_key = "generic"

    vault = "kdbx" if "kdbx" in store.available_backends() else "keyring"
    try:
        account = mail_accounts.account_from_preset(
            name, email_addr, preset_key, display_name=display, vault=vault
        )
    except AccountError as exc:
        print(exc)
        return

    if preset_key == "generic":
        account.imap.host = input(t("mail_ask_imap_host")).strip()
        account.smtp.host = input(t("mail_ask_smtp_host")).strip()
    if PRESETS[preset_key]["app_password"]:
        print(t("mail_app_password_note"))
        print(f"  {PRESETS[preset_key]['note']}")

    password = getpass.getpass(t("mail_ask_password"))
    try:
        store.set(account.secret_ref, password)
    except SecretError as exc:
        print(exc)
        return

    existing = [a for a in _load_accounts() if a.name != account.name]
    try:
        mail_accounts.save(existing + [account])
    except (AccountError, OSError) as exc:
        # Le mot de passe est déjà dans le coffre. L'y laisser sous une
        # référence qu'aucune configuration ne désigne en ferait un déchet
        # invisible — et une exception qui remonte ici tuerait le menu.
        try:
            store.delete(account.secret_ref)
        except SecretError:
            pass
        print(exc)
        return
    print(t("mail_account_saved"))


def _pick_account(prompt_key="mail_ask_account"):
    accounts = _load_accounts()
    if not accounts:
        print(t("mail_no_account"))
        return None, []
    for index, account in enumerate(accounts, start=1):
        print(f"  [{index}] {account.name}")
    choice = input(t(prompt_key)).strip()
    try:
        return accounts[int(choice) - 1], accounts
    except (ValueError, IndexError):
        return None, accounts


def _delete_account(todo) -> None:
    account, accounts = _pick_account()
    if account is None:
        return
    try:
        secret_store_for(todo).delete(account.secret_ref)
    except SecretError:
        # Le secret peut avoir déjà disparu : ce n'est pas une raison de
        # garder le compte dans la configuration.
        pass
    mail_accounts.save([a for a in accounts if a.name != account.name])
    print(t("mail_account_deleted"))


def _write_template() -> None:
    try:
        path = mail_accounts.write_template()
    except AccountError as exc:
        print(exc)
        return
    print(f"{t('mail_template_written')} {path}")


def _test_account(todo) -> None:
    from script.todo.mail.imap_transport import connect

    account, _ = _pick_account()
    if account is None:
        return
    password = secret_store_for(todo).get(account.secret_ref)
    if not password:
        print(t("mail_no_password_stored"))
        return
    try:
        transport = connect(account, password)
        folders = transport.list_folders()
        transport.logout()
    except Exception as exc:
        print(f"{t('mail_connection_failed')} {exc}")
        return
    print(f"{t('mail_connection_ok')} {len(folders)}")


def prompt_mail_cache(todo) -> None:
    while True:
        current = todo_prefs.get("mail_cache_mode", "clear")
        help_info = f"""{todo._menu_header()}
[1] {t("mail_cache_default_mode")} ({current})
[2] {t("mail_cache_account_mode")}
[3] {t("mail_cache_size_purge")}
[0] {t("Back")}"""
        status = click.prompt(help_info)
        print()
        if status == "0":
            return
        if status == "1":
            mode = input(t("mail_ask_mode")).strip()
            if mode in CACHE_MODES:
                todo_prefs.set("mail_cache_mode", mode)
            else:
                print(t("Command not found !"))
        elif status == "2":
            account, accounts = _pick_account()
            if account is None:
                continue
            mode = input(t("mail_ask_mode")).strip()
            account.cache_mode = mode if mode in CACHE_MODES else None
            mail_accounts.save(accounts)
        elif status == "3":
            _cache_size_and_purge()
        else:
            print(t("Command not found !"))


def _cache_size_and_purge() -> None:
    accounts = _load_accounts()
    if not accounts:
        print(t("mail_no_account"))
        return
    for row in cache_summary(accounts):
        print(f"  {row['name']} — {row['mode']} — {row['size'] // 1024} ko")
    account, _ = _pick_account()
    if account is None:
        return
    if input(t("mail_purge_confirm")).strip().lower() not in ("o", "y"):
        return
    store = Store(account)
    store.open()
    store.purge_all()
    store.close()
    print(t("mail_purged"))
```

- [ ] **Step 6: Ressaisir un mot de passe refusé**

Le spec impose qu'un mot de passe rejeté déclenche une ressaisie, et que le
coffre soit mis à jour seulement après un essai réussi. Ajouter à `menu.py` :

```python
def retry_password(todo, account, attempts: int = 3, connect_fn=None) -> bool:
    """Redemande le mot de passe jusqu'à ce qu'il passe. Vrai si le coffre a
    été mis à jour.

    L'écriture n'a lieu QU'APRÈS une connexion réussie : remplacer un mot de
    passe valide par une faute de frappe serait pire que l'échec initial.
    """
    if connect_fn is None:
        from script.todo.mail.imap_transport import connect as connect_fn

    store = secret_store_for(todo)
    for _ in range(attempts):
        password = getpass.getpass(t("mail_ask_password"))
        if not password:
            return False
        try:
            transport = connect_fn(account, password)
        except Exception as exc:
            print(f"{t('mail_connection_failed')} {exc}")
            continue
        transport.logout()
        store.set(account.secret_ref, password)
        print(t("mail_connection_ok"))
        return True
    return False
```

et l'appeler depuis `_test_account`, en remplaçant le bloc `except` :

```python
    except Exception as exc:
        print(f"{t('mail_connection_failed')} {exc}")
        retry_password(todo, account)
        return
```

Tests à ajouter à `test/test_mail_menu.py` :

```python
class TestRetryPassword(unittest.TestCase):
    def setUp(self):
        self.account = account_from_preset("perso", "a@x.ca", "generic")
        self.vault = {}

    def _todo(self):
        from unittest.mock import MagicMock

        return MagicMock()

    def test_updates_the_vault_after_a_good_password(self):
        from unittest.mock import patch

        from script.todo.mail.menu import retry_password

        class OkTransport:
            def logout(self):
                pass

        with patch("getpass.getpass", return_value="bon"), patch(
            "script.todo.mail.menu.secret_store_for"
        ) as store:
            store.return_value.set.side_effect = self.vault.__setitem__
            ok = retry_password(
                self._todo(), self.account, connect_fn=lambda a, p: OkTransport()
            )
        self.assertTrue(ok)
        self.assertEqual(self.vault[self.account.secret_ref], "bon")

    def test_does_not_touch_the_vault_when_every_try_fails(self):
        from unittest.mock import patch

        from script.todo.mail.menu import retry_password

        def refuse(account, password):
            raise OSError("530 refus")

        with patch("getpass.getpass", return_value="faux"), patch(
            "script.todo.mail.menu.secret_store_for"
        ) as store:
            store.return_value.set.side_effect = self.vault.__setitem__
            ok = retry_password(
                self._todo(), self.account, attempts=2, connect_fn=refuse
            )
        self.assertFalse(ok)
        self.assertEqual(self.vault, {})

    def test_empty_input_gives_up(self):
        from unittest.mock import patch

        from script.todo.mail.menu import retry_password

        with patch("getpass.getpass", return_value=""):
            self.assertFalse(
                retry_password(self._todo(), self.account, connect_fn=lambda a, p: None)
            )
```

- [ ] **Step 7: Brancher le menu dans `todo.py`**

Dans `script/todo/todo.py`, remplacer `[3] {t("Question")}` du menu principal par :

```python
[3] {t("Assistant")}
```

Renommer `execute_prompt_ia` en `_assistant_question` (le corps ne change pas), puis ajouter juste avant :

```python
    def prompt_assistant(self):
        """Ce qui s'adresse à l'humain : poser une question, lire son courriel."""
        from script.todo.mail.menu import prompt_execute_mail

        while True:
            help_info = f"""{self._menu_header()}
[1] {t("mail_ai_question")}
[2] {t("mail_menu")}
[0] {t("Back")}"""
            status = click.prompt(help_info)
            print()
            if status == "0":
                return
            if status == "1":
                self._assistant_question()
            elif status == "2":
                prompt_execute_mail(self)
            else:
                print(t("Command not found !"))
```

Enfin, dans `run()`, remplacer l'appel de la branche `status == "3"` :

```python
            elif status == "3":
                self.prompt_assistant()
```

- [ ] **Step 8: Lancer les tests**

```bash
.venv.erplibre/bin/python -m unittest discover -s test -p "test_mail_menu.py" -v
.venv.erplibre/bin/python -m unittest discover -s test 2>&1 | grep -E "^(OK|FAILED|Ran )"
```

Attendu : `test_mail_menu.py` en `OK`, et la suite complète avec **exactement les 6 échecs de la baseline** — aucun de plus.

- [ ] **Step 9: Vérifier le menu à la main**

```bash
printf '3\n0\n0\n' | .venv.erplibre/bin/python script/todo/todo.py 2>&1 | grep -i "assistant\|courriel\|mail" | head
```

Attendu : le sous-menu Assistant s'affiche avec ses deux entrées.

- [ ] **Step 10: Formater et commiter**

```bash
make format
git add script/todo/mail/menu.py script/todo/todo.py script/todo/todo_i18n.py \
        test/test_mail_menu.py
git commit -m "[ADD] mail: menu entries, and Question becomes Assistant"
```

---

### Task 12: Documentation bilingue

**Files:**
- Create: `doc/EMAIL.base.md`
- Modify: `doc/TODO.base.md`
- Modify: `script/todo/README.base.md`

**Interfaces:** aucune — c'est de la prose.

**Rappel :** on n'édite JAMAIS `EMAIL.md` ni `EMAIL.fr.md` : ils sont produits par `make doc_markdown` à partir du `.base.md`. La skill `erplibre-doc-i18n` donne les marqueurs et l'en-tête obligatoires — la charger avant d'écrire.

- [ ] **Step 1: Charger la skill de documentation**

Invoquer la skill `erplibre-doc-i18n` et suivre son format d'en-tête et ses marqueurs de langue. Ne pas deviner la syntaxe mmg.

- [ ] **Step 2: Écrire `doc/EMAIL.base.md`**

Le document couvre, dans cet ordre :

1. **À quoi ça sert** — un client courriel dans le CLI TODO, plusieurs comptes, un cache local.
2. **Prérequis** — `cryptography`, `keyring`, `textual`, `pykeepass` ; pour Gmail, Outlook et iCloud, un **mot de passe d'application** est obligatoire, avec le lien vers la page de chaque fournisseur, et la mention que OAuth arrive en phase 2.
3. **Ajouter un compte** — le chemin de menu `Assistant > Courriel > Comptes > Ajouter`, ce que chaque question attend, et où va le mot de passe (kdbx d'abord, trousseau système ensuite).
4. **Les trois modes de cache** — le tableau `clear` / `encrypted` / `ephemeral`, ce que chacun laisse sur le disque, comment choisir le défaut général et comment le surcharger par compte.
5. **Le TUI** — la disposition en trois volets, et le tableau complet des touches : `↑ ↓ Tab`, `Entrée` (plein écran), `Échap`, `r`, `Shift+R`, `c`, `a`, `A`, `f`, `s`, `u`, `w` (enregistrer une pièce jointe), `/`, `q`.
6. **Écrire un message** — le formulaire, la touche `e` vers `$EDITOR`, les pièces jointes, `Ctrl+S` pour envoyer.
7. **Synchronisation** — au lancement, à la touche, et le rafraîchissement automatique toutes les `mail_refresh_sec` secondes **tant que le TUI est ouvert**.
8. **Où sont les fichiers** — `~/.erplibre/mail/accounts.json`, `~/.erplibre/mail/<compte>/cache.db`, les `.eml`, et `/dev/shm` pour l'éphémère.
9. **Dépannage** — mot de passe refusé, `keyring` qui écrirait en clair, `textual` absent, `UIDVALIDITY` changé, cache corrompu.
10. **Limites de la phase 1** — pas d'OAuth, pas de statistiques, pas de recherche serveur, pas de file d'attente hors ligne. Renvoyer vers le spec pour les phases suivantes.

- [ ] **Step 3: Ajouter le lien dans `doc/TODO.base.md`**

Une ligne dans la table des matières ou la liste des outils, pointant vers `EMAIL.md`.

- [ ] **Step 4: Mentionner le module dans `script/todo/README.base.md`**

Une ligne décrivant le paquet `mail/` parmi les autres modules du dossier.

- [ ] **Step 5: Générer la documentation**

```bash
make doc_markdown
git status --short doc/
```

Attendu : `doc/EMAIL.md` et `doc/EMAIL.fr.md` apparaissent, produits et non écrits à la main.

- [ ] **Step 6: Commiter**

```bash
git add doc/EMAIL.base.md doc/EMAIL.md doc/EMAIL.fr.md \
        doc/TODO.base.md doc/TODO.md doc/TODO.fr.md \
        script/todo/README.base.md script/todo/README.md script/todo/README.fr.md
git commit -m "[ADD] doc: how to set up and use the mail client"
```

---

## Vérification finale de la phase 1

- [ ] **Suite complète**

```bash
.venv.erplibre/bin/python -m unittest discover -s test 2>&1 | grep -E "^(OK|FAILED|Ran )"
```

Attendu : les 6 échecs de la baseline, et **rien d'autre**. Si un septième apparaît, il vient de ce travail.

- [ ] **Les sept critères du spec**

Reprendre un par un les critères de succès de `docs/superpowers/specs/2026-08-02-email-tui-design.md` et les exercer contre un vrai compte :

1. configurer un compte Gmail avec mot de passe d'application, sans éditer un fichier ;
2. ouvrir le TUI, lire un message en aperçu puis en plein écran ;
3. répondre, et retrouver la copie dans Envoyés ;
4. basculer le compte en `encrypted`, puis vérifier que le sujet n'apparaît plus en clair :
   ```bash
   grep -r "un sujet connu" ~/.erplibre/mail/<compte>/ && echo "FUITE" || echo "scellé"
   ```
5. lancer un compte en `ephemeral`, quitter, et vérifier qu'il ne reste rien :
   ```bash
   ls -d /dev/shm/erplibre-mail-* 2>/dev/null && echo "RESIDU" || echo "propre"
   ```
6. couper le réseau, rouvrir le TUI, et relire le cache ;
7. `make doc_markdown` génère la documentation bilingue sans diff inattendu.
