<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [common] -->

# Generative AI / LLM Policy

<!-- [en] -->

ERPLibre adopts the [OCA Generative AI / LLM
Policy](https://github.com/dixmit/oca.github/blob/ai_policy/AI_POLICY.md).
The text below is a summary; the OCA document is the reference.

<!-- [fr] -->

ERPLibre adopte la [politique IA générative / LLM de
l'OCA](https://github.com/dixmit/oca.github/blob/ai_policy/AI_POLICY.md).
Le texte ci-dessous en est un résumé ; le document de l'OCA fait foi.

<!-- [en] -->

## The short version

- Using AI tools to help you is fine.
- Handing over responsibility to them is not.
- Every contribution comes from a human who understands it and answers for
  it, however it was produced.
- Any AI involvement means an `Assisted-by:` trailer. It is binary: either
  there was AI involvement or there was not, with no threshold to judge.
- AI tools never go in `Co-authored-by:`.
- Unsupervised agentic tools are not permitted.
- If you cannot explain and defend every line, do not submit it.
- During review, engage with the feedback. Regenerating and resubmitting is
  not an answer, and neither is "the AI wrote it".
- Do not post AI-generated review comments or summaries you have not
  fact-checked yourself.

<!-- [fr] -->

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

<!-- [en] -->

## Declaring AI use

Add one `Assisted-by:` line per model, in the same shape as
`Co-authored-by:`, with no blank line between them:

<!-- [fr] -->

## Déclarer l'usage de l'IA

Ajoutez une ligne `Assisted-by:` par modèle, sur le même modèle que
`Co-authored-by:`, sans ligne vide entre elles :

<!-- [common] -->

```text
Assisted-by: Claude Opus 4.6
Assisted-by: GitHub Copilot:gpt-5
```

<!-- [en] -->

The trailer says nothing about the quality of the work. It applies to every
level of use, from a piece of advice to fully autonomous coding.

`Co-authored-by:` must not name an AI tool: authorship of a work by a machine
is legally undefined. Disclosure is expected and welcome; it does not reduce
the contributor's responsibility one bit.

## Size and pace

Reviewer burden is roughly *quantity × rate*. A patch under 30 lines in a
single file is the reference point. A contribution over 500 lines needs prior
agreement with a maintainer. Contribute at a pace and size a volunteer can
actually absorb.

## Scope

This policy covers contributions to ERPLibre. Anything ERPLibre sends
upstream to the OCA is governed directly by the OCA document, including its
metrics framework and its consequences.

<!-- [fr] -->

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

<!-- [en] -->

## Credits

Adapted from the OCA policy, itself based on the policy of the *attrs*
project. The OCA document was led by Stuart J Mackintosh, with significant
contribution from Enric Tobella Alomar, and reviewed by the OCA Governance
Working Group.

<!-- [fr] -->

## Crédits

Adapté de la politique de l'OCA, elle-même fondée sur celle du projet
*attrs*. Le document de l'OCA a été mené par Stuart J Mackintosh, avec une
contribution notable d'Enric Tobella Alomar, et revu par le Governance
Working Group de l'OCA.
