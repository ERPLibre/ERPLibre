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
        self.assertTrue(
            AesGcmCrypto(self.key).seal(b"x").startswith(SEALED_MAGIC)
        )

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
        self.assertIsInstance(
            build_crypto("encrypted", new_key()), AesGcmCrypto
        )

    def test_ephemeral_mode(self):
        self.assertIsInstance(
            build_crypto("ephemeral", new_key()), AesGcmCrypto
        )

    def test_encrypted_without_key_raises(self):
        with self.assertRaises(CryptoError):
            build_crypto("encrypted", None)

    def test_unknown_mode_raises(self):
        with self.assertRaises(CryptoError):
            build_crypto("magique", None)


if __name__ == "__main__":
    unittest.main()
