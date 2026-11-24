#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Images et client RFB du test long des bureaux (qemu_desktops.py).

Trois choses, sans dépendance hors de la bibliothèque standard :

* écrire et relire une PNG RGB 8 bits, la seule forme que ce module produit ;
* convertir une capture XWD (celle que « xwd -root » fait d'un Xvfb) en PNG ;
* parler RFB juste assez pour capturer un écran : la console QEMU (sécurité
  None) et les serveurs du bureau (VeNCrypt, sous-type X509Plain ou
  TLSPlain, compte et mot de passe vérifiés par PAM).

L'image se juge au NOMBRE DE TEINTES, pas à la taille du fichier. Une barre
i3 de 20 pixels sur fond noir pèse quelques kilo-octets pour des centaines de
teintes lissées par l'anticrénelage ; un écran noir ou la seule boîte de
connexion d'xrdp en compte de 1 à 8 et pèse parfois davantage. La taille
classe mal les deux cas, les teintes les séparent.

  qemu_desktops_image.py shot HOTE PORT SORTIE.png [--user U --pwfile F]
  qemu_desktops_image.py stat FICHIER.png
  qemu_desktops_image.py xwd ENTREE.xwd SORTIE.png

Le mot de passe se lit dans un fichier, jamais sur la ligne de commande : elle
est visible de tous les comptes de l'hôte.
"""

import argparse
import socket
import ssl
import struct
import sys
import time
import zlib

# Plafond du décompte des teintes : au-delà, l'écran est un bureau rendu, et
# continuer à remplir l'ensemble ne coûte que de la mémoire.
TEINTES_MAX = 5000

# Un pixel dont aucune composante ne dépasse ce seuil compte comme noir : la
# compression des encodeurs RDP laisse un bruit de quelques unités sur un
# écran éteint.
SEUIL_NOIR = 24

# Sous-types VeNCrypt acceptés, dans l'ordre de préférence : X509Plain (le
# serveur présente un certificat), puis TLSPlain (TLS anonyme). Les deux
# portent le compte et le mot de passe dans le tunnel ; le certificat n'est
# pas vérifié, la VM l'ayant généré elle-même.
VENCRYPT_PLAIN = (262, 259)


# --------------------------------------------------------------------------
# PNG
# --------------------------------------------------------------------------


def _bloc(type_, donnees):
    corps = type_ + donnees
    return (
        struct.pack(">I", len(donnees))
        + corps
        + struct.pack(">I", zlib.crc32(corps) & 0xFFFFFFFF)
    )


def png_octets(largeur, hauteur, rgb):
    """Une PNG RGB 8 bits non entrelacée, filtre 0 sur chaque ligne.

    `rgb` : largeur × hauteur × 3 octets, ligne par ligne. Lève ValueError si
    la longueur ne correspond pas aux dimensions."""
    pas = 3 * largeur
    if len(rgb) != pas * hauteur:
        raise ValueError(
            f"{len(rgb)} octets pour {largeur}x{hauteur} pixels RGB"
        )
    brut = bytearray()
    for y in range(hauteur):
        brut.append(0)
        brut += rgb[y * pas : (y + 1) * pas]
    return (
        b"\x89PNG\r\n\x1a\n"
        + _bloc(
            b"IHDR",
            struct.pack(">IIBBBBB", largeur, hauteur, 8, 2, 0, 0, 0),
        )
        + _bloc(b"IDAT", zlib.compress(bytes(brut), 6))
        + _bloc(b"IEND", b"")
    )


def png_ecrire(chemin, largeur, hauteur, rgb):
    with open(chemin, "wb") as fh:
        fh.write(png_octets(largeur, hauteur, rgb))


def png_lire(donnees):
    """(largeur, hauteur, rgb) d'une PNG écrite par png_octets.

    Ne lit QUE cette forme — RGB 8 bits, filtre 0 — et lève ValueError sur
    toute autre : un décodeur partiel qui lirait de travers rendrait un
    décompte de teintes faux sans le dire."""
    if donnees[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("signature PNG absente")
    i, idat, largeur, hauteur = 8, b"", 0, 0
    while i + 8 <= len(donnees):
        n, type_ = struct.unpack(">I4s", donnees[i : i + 8])
        corps = donnees[i + 8 : i + 8 + n]
        if type_ == b"IHDR":
            largeur, hauteur, prof, couleur = struct.unpack(
                ">IIBB", corps[:10]
            )
            if (prof, couleur) != (8, 2):
                raise ValueError("PNG non RGB 8 bits")
        elif type_ == b"IDAT":
            idat += corps
        i += 12 + n
    brut = zlib.decompress(idat)
    pas = 3 * largeur
    rgb = bytearray()
    for y in range(hauteur):
        ligne = brut[y * (pas + 1) : (y + 1) * (pas + 1)]
        if ligne[0] != 0:
            raise ValueError(f"filtre PNG {ligne[0]} non pris en charge")
        rgb += ligne[1:]
    return largeur, hauteur, bytes(rgb)


def teintes(largeur, hauteur, rgb, plafond=TEINTES_MAX):
    """(teintes distinctes plafonnées à `plafond`, % de pixels non noirs)."""
    total = largeur * hauteur
    if not total:
        return 0, 0.0
    vues, non_noirs = set(), 0
    for o in range(0, 3 * total, 3):
        px = rgb[o : o + 3]
        if max(px) > SEUIL_NOIR:
            non_noirs += 1
        if len(vues) < plafond:
            vues.add(bytes(px))
    return len(vues), 100.0 * non_noirs / total


def stat_png(chemin):
    """« colours=N nonblack=P » d'une PNG de ce module : la forme qu'écrit
    le résultat d'une VM et que lit le verdict."""
    with open(chemin, "rb") as fh:
        n, pct = teintes(*png_lire(fh.read()))
    return f"colours={n} nonblack={pct:.2f}"


# --------------------------------------------------------------------------
# XWD
# --------------------------------------------------------------------------


def xwd_vers_rgb(donnees):
    """(largeur, hauteur, rgb) d'une capture XWD ZPixmap 32 bits par pixel.

    C'est la forme que « xwd -root » produit d'un Xvfb en profondeur 24 :
    chaque pixel tient sur quatre octets B, G, R, X dans l'ordre de poids
    faible d'abord. Tout autre format lève ValueError plutôt que de rendre
    une image aux couleurs permutées."""
    if len(donnees) < 100:
        raise ValueError("en-tête XWD tronqué")
    h = struct.unpack(">25I", donnees[:100])
    taille_entete, format_ = h[0], h[2]
    largeur, hauteur, ordre = h[4], h[5], h[7]
    bpp, pas, ncouleurs = h[11], h[12], h[19]
    if format_ != 2 or bpp != 32 or ordre != 0:
        raise ValueError(
            f"XWD non pris en charge (format={format_} bpp={bpp}"
            f" ordre={ordre})"
        )
    debut = taille_entete + ncouleurs * 12
    if len(donnees) < debut + pas * hauteur:
        raise ValueError("pixels XWD tronqués")
    rgb = bytearray()
    for y in range(hauteur):
        ligne = donnees[debut + y * pas : debut + y * pas + 4 * largeur]
        for x in range(0, 4 * largeur, 4):
            rgb += bytes((ligne[x + 2], ligne[x + 1], ligne[x]))
    return largeur, hauteur, bytes(rgb)


def xwd_vers_png(entree, sortie):
    with open(entree, "rb") as fh:
        largeur, hauteur, rgb = xwd_vers_rgb(fh.read())
    png_ecrire(sortie, largeur, hauteur, rgb)
    return largeur, hauteur


# --------------------------------------------------------------------------
# RFB
# --------------------------------------------------------------------------


class RefusAuthentification(Exception):
    """Le serveur a refusé le compte ou le mot de passe."""


def _lire(sock, n):
    lu = b""
    while len(lu) < n:
        morceau = sock.recv(n - len(lu))
        if not morceau:
            raise EOFError(f"connexion fermée après {len(lu)}/{n} octets")
        lu += morceau
    return lu


def choisir_securite(types, utilisateur):
    """Type de sécurité RFB à demander parmi `types` offerts.

    Sans compte : None (1), celle de la console QEMU. Avec un compte :
    VeNCrypt (19) et rien d'autre. Un serveur de bureau qui offrirait None
    ou la seule authentification VNC à huit caractères n'est pas celui que
    le guide de connexion annonce : la capture échoue au lieu de s'y
    rabattre. Lève ValueError quand rien ne convient."""
    if utilisateur:
        if 19 in types:
            return 19
    elif 1 in types:
        return 1
    raise ValueError(f"aucune sécurité utilisable parmi {list(types)}")


def choisir_sous_type(sous_types):
    for st in VENCRYPT_PLAIN:
        if st in sous_types:
            return st
    raise ValueError(f"ni X509Plain ni TLSPlain parmi {list(sous_types)}")


def _vencrypt(sock, utilisateur, mot_de_passe):
    _lire(sock, 2)
    sock.sendall(b"\x00\x02")
    if _lire(sock, 1)[0] != 0:
        raise ValueError("version VeNCrypt 0.2 refusée")
    k = _lire(sock, 1)[0]
    sous_types = struct.unpack(f">{k}I", _lire(sock, 4 * k))
    sock.sendall(struct.pack(">I", choisir_sous_type(sous_types)))
    if _lire(sock, 1)[0] != 1:
        raise ValueError("sous-type VeNCrypt refusé")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    sock = ctx.wrap_socket(sock)
    u, p = utilisateur.encode(), mot_de_passe.encode()
    sock.sendall(struct.pack(">II", len(u), len(p)) + u + p)
    return sock


def poignee(hote, port, utilisateur=None, mot_de_passe=None, delai=20):
    """Connexion RFB 3.8 authentifiée. Rend (socket, largeur, hauteur).

    Lève RefusAuthentification sur un refus du compte, ValueError sur une
    sécurité inutilisable, OSError sur une connexion impossible."""
    sock = socket.create_connection((hote, port), timeout=delai)
    _lire(sock, 12)
    sock.sendall(b"RFB 003.008\n")
    n = _lire(sock, 1)[0]
    if n == 0:
        ln = struct.unpack(">I", _lire(sock, 4))[0]
        raise ValueError(f"refusé d'emblée : {_lire(sock, ln)!r}")
    securite = choisir_securite(list(_lire(sock, n)), utilisateur)
    sock.sendall(bytes([securite]))
    if securite == 19:
        sock = _vencrypt(sock, utilisateur, mot_de_passe or "")
    if struct.unpack(">I", _lire(sock, 4))[0] != 0:
        try:
            ln = struct.unpack(">I", _lire(sock, 4))[0]
            raison = _lire(sock, ln)
        except (OSError, EOFError, struct.error):
            raison = b""
        raise RefusAuthentification(raison.decode(errors="replace"))
    sock.sendall(b"\x01")  # session partagée
    largeur, hauteur = struct.unpack(">HH", _lire(sock, 4))
    _lire(sock, 16)
    _lire(sock, struct.unpack(">I", _lire(sock, 4))[0])
    # 32 bits par pixel, profondeur 24, petit-boutiste, rouge 16 vert 8
    # bleu 0 : la forme que _rectangles recopie sans conversion.
    sock.sendall(
        struct.pack(
            ">BxxxBBBBHHHBBBxxx", 0, 32, 24, 0, 1, 255, 255, 255, 16, 8, 0
        )
    )
    sock.sendall(struct.pack(">BxHi", 2, 1, 0))  # encodage brut seul
    return sock, largeur, hauteur


def touche(sock, symbole):
    sock.sendall(struct.pack(">BBxxI", 4, 1, symbole))
    sock.sendall(struct.pack(">BBxxI", 4, 0, symbole))
    time.sleep(0.05)


def _message_annexe(sock, type_):
    """Consomme un message serveur autre qu'une mise à jour d'image."""
    if type_ == 2:  # cloche
        return
    if type_ == 1:  # table de couleurs
        _lire(sock, 1)
        _premiere, n = struct.unpack(">HH", _lire(sock, 4))
        _lire(sock, 6 * n)
        return
    if type_ == 3:  # presse-papiers
        _lire(sock, 3)
        _lire(sock, struct.unpack(">I", _lire(sock, 4))[0])
        return
    raise ValueError(f"message RFB {type_} inattendu")


def saisir(sock, largeur, hauteur):
    """(largeur, hauteur, rgb) de l'écran entier, en encodage brut.

    Un changement de taille annoncé (pseudo-encodage -223) relance la
    demande pour la nouvelle surface."""
    sock.sendall(struct.pack(">BBHHHH", 3, 0, 0, 0, largeur, hauteur))
    image = bytearray(largeur * hauteur * 4)
    recu = 0
    while recu < largeur * hauteur:
        type_ = _lire(sock, 1)[0]
        if type_ != 0:
            _message_annexe(sock, type_)
            continue
        _lire(sock, 1)
        for _ in range(struct.unpack(">H", _lire(sock, 2))[0]):
            x, y, rl, rh, enc = struct.unpack(">HHHHi", _lire(sock, 12))
            if enc == -223:
                largeur, hauteur = rl, rh
                image = bytearray(largeur * hauteur * 4)
                recu = 0
                sock.sendall(
                    struct.pack(">BBHHHH", 3, 0, 0, 0, largeur, hauteur)
                )
                continue
            if enc != 0:
                raise ValueError(f"encodage RFB {enc} inattendu")
            donnees = _lire(sock, rl * rh * 4)
            for ligne in range(rh):
                o = ((y + ligne) * largeur + x) * 4
                image[o : o + rl * 4] = donnees[
                    ligne * rl * 4 : (ligne + 1) * rl * 4
                ]
            recu += rl * rh
    rgb = bytearray()
    for o in range(0, len(image), 4):
        rgb += bytes((image[o + 2], image[o + 1], image[o]))
    return largeur, hauteur, bytes(rgb)


def capture_rfb(
    hote, port, sortie, utilisateur=None, mot_de_passe=None, reveil=False
):
    """Capture l'écran d'un serveur RFB dans `sortie`. Rend une ligne d'état.

    « saved L H » en cas de succès, « AUTH-FAIL raison » sur un refus du
    compte, « ERROR raison » sinon : la forme que le résultat d'une VM
    enregistre. `reveil` envoie une touche Maj avant la capture : un écran
    mis en veille ne produit sinon aucune image nouvelle."""
    try:
        sock, largeur, hauteur = poignee(hote, port, utilisateur, mot_de_passe)
    except RefusAuthentification as err:
        return f"AUTH-FAIL {err}".strip()
    except (OSError, EOFError, ValueError, struct.error) as err:
        return f"ERROR {err}"
    try:
        if reveil:
            touche(sock, 0xFFE1)
            time.sleep(1)
        largeur, hauteur, rgb = saisir(sock, largeur, hauteur)
    except (OSError, EOFError, ValueError, struct.error) as err:
        return f"ERROR {err}"
    finally:
        sock.close()
    png_ecrire(sortie, largeur, hauteur, rgb)
    return f"saved {largeur} {hauteur}"


def main(argv=None):
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sous = parseur.add_subparsers(dest="cmd", required=True)
    p = sous.add_parser("shot")
    p.add_argument("hote")
    p.add_argument("port", type=int)
    p.add_argument("sortie")
    p.add_argument("--user")
    p.add_argument("--pwfile")
    p.add_argument("--wake", action="store_true")
    sous.add_parser("stat").add_argument("png")
    x = sous.add_parser("xwd")
    x.add_argument("entree")
    x.add_argument("sortie")
    args = parseur.parse_args(argv)
    if args.cmd == "stat":
        print(stat_png(args.png))
        return 0
    if args.cmd == "xwd":
        print("%d %d" % xwd_vers_png(args.entree, args.sortie))
        return 0
    mdp = None
    if args.pwfile:
        with open(args.pwfile, encoding="utf-8") as fh:
            mdp = fh.read().strip()
    etat = capture_rfb(
        args.hote, args.port, args.sortie, args.user, mdp, args.wake
    )
    print(etat)
    return 0 if etat.startswith("saved") else 3


if __name__ == "__main__":
    sys.exit(main())
