

# Generative AI / LLM Policy


ERPLibre adopts the [OCA Generative AI / LLM
Policy](https://github.com/dixmit/oca.github/blob/ai_policy/AI_POLICY.md).
The text below is a summary; the OCA document is the reference.


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


## Declaring AI use

Add one `Assisted-by:` line per model, in the same shape as
`Co-authored-by:`, with no blank line between them:


```text
Assisted-by: Claude Opus 4.6
Assisted-by: GitHub Copilot:gpt-5
```


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


## Credits

Adapted from the OCA policy, itself based on the policy of the *attrs*
project. The OCA document was led by Stuart J Mackintosh, with significant
contribution from Enric Tobella Alomar, and reviewed by the OCA Governance
Working Group.
