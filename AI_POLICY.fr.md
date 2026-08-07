

# Generative AI / LLM Policy


ERPLibre adopte la [politique IA générative / LLM de
l'OCA](https://github.com/dixmit/oca.github/blob/ai_policy/AI_POLICY.md).
Le texte ci-dessous en est un résumé ; le document de l'OCA fait foi.


## En bref

- Se faire aider par des outils d'IA ne pose pas de problème.
- Leur abandonner la responsabilité, si.
- Toute contribution vient d'un humain qui la comprend et en répond, quelle
  qu'ait été sa fabrication.
- Tout recours à l'IA se déclare par un trailer `Assisted-by:`. C'est
  binaire : il y a eu IA ou non, sans seuil à apprécier.
- Un outil d'IA ne figure jamais dans `Co-authored-by:`.
- Les outils agentiques non supervisés sont interdits.
- Si vous ne savez pas expliquer et défendre chaque ligne, ne soumettez pas.
- En revue, répondez au fond. Régénérer et resoumettre n'est pas une réponse,
  « c'est l'IA qui l'a écrit » non plus.
- Ne publiez pas de commentaires ni de résumés générés par IA sans les avoir
  vérifiés vous-même.


## Déclarer l'usage de l'IA

Ajoutez une ligne `Assisted-by:` par modèle, sur le même modèle que
`Co-authored-by:`, sans ligne vide entre elles :


```text
Assisted-by: Claude Opus 4.6
Assisted-by: GitHub Copilot:gpt-5
```


Le trailer ne dit rien de la qualité du travail. Il vaut pour tout niveau
d'usage, du simple conseil au codage entièrement autonome.

`Co-authored-by:` ne doit pas nommer un outil d'IA : la paternité d'une œuvre
par une machine est juridiquement indéfinie. La déclaration est attendue et
bienvenue ; elle ne diminue en rien la responsabilité du contributeur.

## Taille et rythme

La charge du relecteur vaut à peu près *quantité × fréquence*. Le repère est
un correctif de moins de 30 lignes dans un seul fichier. Au-delà de 500
lignes, l'accord préalable d'un mainteneur est nécessaire. Contribuez à un
rythme et dans un volume qu'un bénévole peut absorber.

## Portée

Cette politique couvre les contributions à ERPLibre. Ce qu'ERPLibre remonte
à l'OCA relève directement du document de l'OCA, cadre de métriques et
sanctions compris.


## Crédits

Adapté de la politique de l'OCA, elle-même fondée sur celle du projet
*attrs*. Le document de l'OCA a été mené par Stuart J Mackintosh, avec une
contribution notable d'Enric Tobella Alomar, et revu par le Governance
Working Group de l'OCA.