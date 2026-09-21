
# Forge — Forgejo et Gitea

Quatre modules, un partage : **ce qui décide n'affiche rien, et ce qui
affiche ne décide rien.** C'est ce partage qui rend un verdict vérifiable
sans forge, et qui permet au même code de servir un menu, un script et une
épreuve.

## Le secret n'est pas dans le profil

Un profil de forge porte son URL de base, son compte propriétaire et sa
posture TLS — en JSON lisible. **Le jeton d'API vit dans le coffre
KeePassXC.** Un profil peut donc être lu, montré, comparé et versionné chez
un client sans jamais donner de quoi écrire dans la forge.

## Dire POURQUOI, et non « ça a échoué »

L'API rend un verdict nommé, d'un vocabulaire clos : `ok`, `no-token`,
`bad-token`, `localnetwork-refused`, `not-found`, `already-exists`,
`tls-untrusted`, `unreachable`, `refused`.

Deux d'entre eux existent parce que la réponse naïve envoie au mauvais
endroit :

- **`localnetwork-refused`** — Forgejo refuse de miroiter un dépôt dont
  l'adresse résout dans une plage privée. En manquer la formulation fait
  conclure à un mauvais jeton, et l'on va en réémettre un qui allait bien.
- **`tls-untrusted`** — le certificat auto-signé d'une forge de laboratoire
  est le cas courant, et il se corrige en approuvant l'autorité, pas en
  changeant de jeton.

La taille de page est demandée **explicitement** : un client qui se fie au
défaut du serveur s'arrête au bout d'une page sans le dire.

## Le miroir : montrer l'écart avant de créer quoi que ce soit

`mirror.plan(declared, present)` reçoit deux listes de noms et rend un plan.
Il **n'appelle rien**. C'est ce qui rend le rapprochement de deux cents noms
vérifiable sans forge, et ce qui permet de MONTRER le plan avant qu'un seul
dépôt soit créé.

## L'adresse décide de qui peut lire le jeton

Un jeton d'API voyage dans un en-tête. Contrôler l'URL de base d'une forge
n'est donc pas cosmétique : cela décide de qui reçoit le jeton. Ce contrôle
vit ici, à côté de la forge, et non dans le module de formats partagés.

```bash
# Le plan d'un miroir, sans joindre aucune forge :
python3 -c "from script.forge import mirror; \
  p = mirror.plan(['a', 'b'], ['a']); print(p)"
```