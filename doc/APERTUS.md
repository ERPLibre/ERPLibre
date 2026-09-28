
# Apertus — the open LLM, on your own machine

Apertus is a large language model that ERPLibre can install for you, here or
on a server you own, and then talk to from the TODO CLI. The whole path is one
menu entry: `TODO › Assistant › AI › Apertus`.

This guide says what the model is, which variant and which engine to pick,
what it costs in disk and memory, how the menu installs it, and — just as
important — what is **not** official about that path.

## 1. What Apertus is

Apertus comes from the **Swiss AI Initiative**, a joint effort of **EPFL**,
**ETH Zurich** and the **CSCS** (the Swiss National Supercomputing Centre, in
Lugano). It was trained on **Alps**, the CSCS supercomputer. Its licence is
**Apache-2.0**.

| | |
|---|---|
| Official site | `https://apertus-ai.org/` |
| Documentation | `https://apertus-ai.org/docs/` |
| Weights | `https://huggingface.co/swiss-ai` |

"Open" here is meant in its strong sense, and it is the reason this model is
in ERPLibre rather than another one. Three things are published, not one:

- the **weights**, downloadable without an account and redistributable;
- the **training data** — which corpora, in what proportion, with what
  filtering;
- the **full training recipe** — the hyper-parameters, the schedule, the
  intermediate checkpoints, the code.

Most models called "open" publish only the first. Publishing the three is what
makes a result reproducible instead of merely usable.

**One reservation, and the guide states it rather than hide it.** Beside its
`LICENSE.txt`, Apertus ships a `USAGE_POLICY.md`, which carries an
indemnification obligation towards ETH Zurich and EPFL. The model stays free
and redistributable under Apache-2.0 — but "Apache-2.0, nothing else to read"
would be wrong. Read the policy before deploying the model in front of third
parties.

## 2. Why it fits ERPLibre

ERPLibre is AGPL-3.0+ and requires free software of everything it ships. A
model under a "community licence" with a user-count cap, a field-of-use
restriction or a revocation clause would not pass that bar; Apache-2.0 does.
The four engines the menu can install are free too — three MIT, one
Apache-2.0.

**No vendor lock-in.** The model is a file. Nothing expires, nothing phones
home, no key is rotated out from under you, and no price list changes. An
installation that works today works the same in five years, offline.

**It runs on your own machine.** Local, or a server you administer. That is
what makes the CLI's assistant usable on real work: an ERP question carries
the data it is about — a customer name, an amount, a database name. Sent to a
hosted model, that data leaves. Served by an engine listening on `127.0.0.1`,
it never leaves the machine that already holds it.

This is the same reasoning that runs through the rest of the assistant: the
repository's rule is that an address, a host name or a database name never
becomes prompt text. A local model removes the question instead of guarding
it.

## 3. Choosing a model

Two families are offered, and one number separates them.

**Apertus 8B Instruct** (`swiss-ai/Apertus-8B-Instruct-2509`) is the full
model: 8 billion parameters, **65536 tokens of context**, Apache-2.0, no
account needed to download.

**Apertus Mini** is **Apertus v1.1**, published by the same team
(arXiv **2605.29128**). It is obtained by *pre-training distillation* from the
8B teacher: a 90 % KL-divergence / 10 % cross-entropy mix over **1.7 T
permissively-licensed tokens**, about ten times shorter than a full
pre-training run — 2.4 × 10²² FLOPs for the whole family, roughly 12 % of what
the 8B cost. It is a real, official model, not a community shrink.

> ⚠️ **The price of distillation is the context: 4096 tokens, against 65536
> for the 8B.** This is the single most important line of this section. A Mini
> will not read a long file, a long diff or a long conversation — it will
> forget the beginning. If you hit that wall, it is not a bug and no setting
> raises it.

| Model | Parameters | Context | GGUF size | Repository |
|---|---|---|---|---|
| Apertus 8B Instruct, `Q4_K_M` | 8 B | **65536** | 5.06 GB | `swiss-ai/Apertus-8B-Instruct-2509` |
| Apertus 8B Instruct, `Q8_0` | 8 B | **65536** | 8.57 GB | `swiss-ai/Apertus-8B-Instruct-2509` |
| Apertus Mini 1.5B Instruct | 1.5 B | **4096** | ≈ 1.2 GB | `swiss-ai/Apertus-v1.1-1.5B-Instruct` |
| Apertus Mini 0.5B Instruct | 0.5 B | **4096** | ≈ 0.5 GB | `swiss-ai/Apertus-v1.1-0.5B-Instruct` |

A **4 B** Mini also exists upstream (`swiss-ai/Apertus-v1.1-4B-Instruct`, same
4096 tokens), but no GGUF build of it was found, so the menu does not offer
it.

Official quantizations are published for **MLX** (INT3/INT4/INT6, Apple
Silicon) and for **vLLM** (NVFP4A16). There is **no official GGUF** — see
section 8.

**Which one to take.** Take the **8B in `Q4_K_M`** unless you have a reason
not to: it is the default, and the context is what makes an assistant useful
on real files. Take a **Mini** when the machine cannot hold the 8B, when you
want an answer in a second on a CPU, or when the questions are short and
self-contained. Take the **8B in `Q8_0`** only if you have memory to spare and
want the last bit of quality.

> ⚠️ **The 0.5 B Mini does not answer factual questions correctly.**
> Measured on a working install: it writes correct French, follows an
> instruction and leaks no special token — so the engine and the chat template
> are fine — and it still answers `2` to *two plus two* and names Geneva as the
> capital of Switzerland. Knowledge is what half a billion parameters cannot
> hold. Use it to exercise an install or to check that a server answers; use
> the 8B to get an answer you rely on.

**Do not aim at Apertus v1.5.** `swiss-ai/Apertus-v1.5-8B` is a *different
architecture*, it is gated on its download page (an account and a token are
required, so a remote machine fails with a 401 nobody expected), it is absent
from the upstream transformers library, from the vLLM registry and from the
llama.cpp converter, and its card demands a pinned fork of transformers. None
of the four engines serves it. The menu targets v1 and v1.1 only.

## 4. Choosing an engine

An engine is the program that loads the weights and serves them over an
OpenAI-compatible HTTP API. Four are offered, all free software:

| Engine | Licence | Default port | Minimum version | Who it suits |
|---|---|---|---|---|
| **Ollama** | MIT | 11434 | **0.12.6** | anyone starting out — one install command, a systemd service, and the only engine that reports real download progress |
| **llama.cpp** | MIT | 8080 | build **b6671** | a machine where you have no root, or where you want to pick the quantization yourself |
| **LocalAI** | MIT | 8080 | **4.0.0** | a host that already serves several models through one gateway |
| **vLLM** | Apache-2.0 | 8000 | **0.10.2** | a GPU machine serving several users at once |

The default is **Ollama**, and it is the right answer for a first install.

### Why a minimum version: the xIELU activation

Apertus does not use the activation function everything else uses. It uses
**xIELU**, and that single fact dates support for it everywhere. An engine
released before xIELU landed in its sources does not become slow or
approximate on Apertus — it **cannot** run it. It either refuses the file with
`unknown model architecture: apertus`, or loads it and produces gibberish.

That is why the menu **checks the engine version before downloading anything**
— step 5 of 9, ahead of the multi-gigabyte step 7. Learning about a version
number should not cost 5 GB of traffic.

Where xIELU landed:

- **llama.cpp** — build `b6671` (CPU and CUDA in the same change).
- **Ollama** — `0.12.6`. **No release note mentions it**; searching the
  changelog for "xielu" finds nothing, and only a diff of the vendored sources
  shows it. If the version check fails on an Ollama that looks recent, that is
  why.
- **vLLM** — `0.10.2`, which shipped before the model was public.
- **LocalAI** — inherits support from the llama.cpp it embeds; `4.0.0` is the
  floor the menu uses.

Other ggml back ends got xIELU later than CPU and CUDA: Vulkan, then Metal,
then SYCL/Intel. An Intel Arc target therefore needs much more than `b6671` —
check the build, not the calendar.

### What each engine costs you in practice

- **Ollama** installs itself from the distribution package where one exists,
  and from its upstream script otherwise; it registers its own service. It is
  the only one of the four whose pull emits a machine-readable progress
  stream, which is why the install screen can show a real percentage for it
  and only a step counter for the others.
- **llama.cpp** is installed from its upstream installer under your own
  account, without root. Distribution packages are frequently older than
  `b6671` — one current distribution still ships `b5882` — and you would only
  find out after downloading the weights.
- **LocalAI** needs the `huggingface://` URI form, because its gallery has no
  Apertus entry at all. Its **first** call also downloads a multi-gigabyte OCI
  back end image; that is a step of its own, not a fold of "start the server".
- **vLLM** is a GPU engine in practice. Its CPU wheel requires the `avx512f`
  instruction set and an `LD_PRELOAD`, and a virtual machine with a default
  CPU model often does not expose `avx512`. In bf16 the weights are 16.11 GB,
  which makes 24 GB of VRAM the real floor; a 16 GB card wants the
  `RedHatAI/Apertus-8B-Instruct-2509-FP8-dynamic` build instead (9.13 GB,
  Apache-2.0).

> ⚠️ **The fused xIELU CUDA kernel is deliberately not installed.** vLLM
> suggests installing it from a source repository that carries **no LICENSE
> file at all**, which an AGPL-3.0+ project cannot ship. The pure-PyTorch
> fallback is automatic and correct; it costs speed, nothing else.

## 5. Hardware — what it really takes

**No official VRAM or RAM figure is published for Apertus.** Everything below
is *derived*: from the sizes of the published files, and from the model's own
declared dimensions. Treat them as floors, not as certified requirements.

### Disk

The GGUF file sizes are the ones in section 3: **5.06 GB** for the 8B in
`Q4_K_M`, **8.57 GB** in `Q8_0`, about **1.2 GB** and **0.5 GB** for the two
Minis. The installer checks free space before downloading, and asks for the
model's size **plus a 2 GiB margin** — a download writes intermediate files,
and an engine writes a service file.

### Memory: the weights, plus the KV cache

The weights are the easy half: roughly the file size, once loaded.

The other half is the **KV cache**, which grows with the context and which no
one advertises. For the **8B**, it is exactly **128 KiB per token**:

```text
2 tensors (K and V)
  × 32 layers
  × 8 key/value heads
  × 128 head dimension
  × 2 bytes (fp16)
  = 131072 bytes = 128 KiB per token
```

Multiply that by the model's native context and the number stops being
academic:

| Context | KV cache for the 8B |
|---|---|
| 4096 tokens | 512 MiB |
| **8192 tokens** (the cap the menu applies) | **1 GiB** |
| **65536 tokens** (the model's native maximum) | **8 GiB** |

Accepting the native context therefore reserves **8 GiB on top of the
weights** — about 13 GB in total for a 5.06 GB `Q4_K_M`. That is how a machine
with plenty of room for the file still gets its engine killed the moment the
first question arrives.

**This is why the menu starts every engine with a capped context — 8192
tokens.** A model whose native context is already shorter keeps its own: a
Mini at 4096 tokens is served at 4096. If you need the full 65536, raise the
cap knowingly and budget the 8 GiB.

Reasonable derived floors, for the 8B in `Q4_K_M` at the 8192-token cap:
about **7 GB** of RAM (or VRAM) to serve it, and about **7.2 GB** of free disk
to install it. The Minis are an order of magnitude cheaper on both counts, and
that — not speed — is the reason to pick one on a small machine.

## 6. Installing through the menu

The whole installation is `TODO › Assistant › AI › Apertus`. The screen:

```text
🇨🇭 Apertus — the open LLM of the Swiss Confederation.
📍 TODO › Assistant › AI › Apertus
Command:

── 📖 Understand ──
[1] 📖 Guide — what Apertus is, and how to use it

── 🎯 Prepare ──
[2] 🎯 Target — the machine to install on  (here)
[3] ⚙️ Engine — how to serve the model  (Ollama)
[4] 🧠 Model — full 8B, or distilled Mini  (8B-Instruct-2509, Q4_K_M)

── 📦 Install ──
[5] 📦 Install  (never run)
[6] 🩺 Check and keep the server

── 💬 Use ──
[7] 💬 Chat with the model
[8] 🧹 Uninstall
[0] 🔙 Back
```

**[2] Target.** Three ways to designate a machine: here, a QEMU virtual
machine of this host, or a host from your `~/.ssh/config`. A remote target is
reached with `BatchMode` — the connection must already work without typing a
password, or the menu would appear frozen while `ssh` waits for one.

**[3] Engine** and **[4] Model** are the two choices of sections 3 and 4. Both
suffixes show the current value in parentheses, so the screen always says what
would be installed.

**[5] Install** prints a **full plan first**, then asks **once**:

```text
Target  : SSH server "<alias>"
Engine  : Ollama (MIT)
Model   : Apertus-8B-Instruct-2509, Q4_K_M — 5.06 GB
Space   : 7.2 GB needed, 41 GB free
Context : 8192 tokens (native 65536 capped — 8 GiB of KV cache otherwise)

Will execute:
  1. atteindre  ...
  ...
  9. repondre   ...

Run these 9 steps? (y/N)
```

The nine steps, in this order:

| # | Step | What it does |
|---|---|---|
| 1 | `atteindre` | is the target reachable at all |
| 2 | `sudo` | does `sudo` work without an interactive password |
| 3 | `place` | is there room for the model plus the 2 GiB margin |
| 4 | `paquet` | install the engine (skipped if its binary is already there) |
| 5 | `version` | **is the engine new enough for xIELU** |
| 6 | `service` | put the engine to listen |
| 7 | `tirer` | download the weights — the long one |
| 8 | `ecouter` | does the API answer on `/v1/models` |
| 9 | `repondre` | a real completion comes back |

The order is deliberate: **step 5 comes before step 7**. An engine that is too
old is caught before the gigabytes, not after.

Each step carries a completion test, so a second run skips what is already
done. An engine already installed does not get reinstalled; weights already
pulled do not get pulled again.

**If a step fails**, the run stops there, prints the step, its exit code and
the tail of its output, and records the progress. Coming back into **[5]**
then opens the resume screen instead of starting over:

```text
📍 TODO › Assistant › AI › Apertus › Resume

  ✅ 1 atteindre      ✅ 2 sudo        ✅ 3 place
  ✅ 4 paquet         ⛔ 5 version     ⬜ 6 service
  ⬜ 7 tirer          ⬜ 8 ecouter     ⬜ 9 repondre

  4/9 steps, 3 min 12 s elapsed, 2 attempts.

[1] ▶️ Resume at step 5
[2] 🔄 Start over
[3] 📜 See the full last output
[0] 🔙 Back
```

That progress lives in `~/.erplibre/apertus_install.json`, **outside the
repository** — one entry per target machine. It is written there and not in
the tree on purpose: a progress record names its machine, and everything in
the tree follows the repository upstream. Starting over resets that target's
progress while keeping the failure history, so the screen can still show what
went wrong last time.

**[6] Check and keep the server** probes the engine and, if it answers, offers
to keep it as the assistant's server — after which `Assistant › LLM` talks to
it like any other.

**[8] Uninstall** removes the weights and stops the service; it does **not**
remove the engine, which may well be serving other models. Because it is
irreversible, it asks you to **retype the target's name in full** — a "yes" is
given by reflex, retyping makes you look at which machine you are emptying.

You can pick how progress is displayed with the `apertus_progress` preference:
`ask`, `tui` or `cli`. Both renderings describe the same state; the TUI simply
draws it.

## 7. Using it

### From the menu

`[7] Chat with the model` opens the conversation, and the answer arrives token
by token rather than in one block at the end. The usual commands of the CLI's
conversation apply — `/save` to keep a transcript, `/ctx` to see where the
context stands, `/new` to start a fresh thread.

The history lives in memory and nowhere else. It dies with the menu, and
`/save` is the only way to keep a trace.

### From your own code

Every engine serves the same OpenAI-compatible API, so anything that speaks to
a hosted model speaks to this one by changing the base URL. With Ollama on the
default port:

```bash
curl -fsS http://127.0.0.1:11434/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "hf.co/unsloth/Apertus-8B-Instruct-2509-GGUF:Q4_K_M",
    "messages": [{"role": "user", "content": "Explain an Odoo manifest."}]
  }'
```

Two things change from one engine to another, and only two: the **port** (see
the table in section 4) and the string to put in `"model"`. Ollama wants the
`hf.co/<repository>:<quantization>` bridge form, LocalAI wants a
`huggingface://` URI, llama.cpp wants the GGUF file, and vLLM wants the
upstream repository name. `GET /v1/models` on the running engine always tells
you which string it accepts.

No API key is required on a local engine. If a client library demands one, any
non-empty string does.

## 8. What is NOT official

This is the honest core of the guide. The model is official; **the path this
menu takes to run it is partly not**, and you should know exactly where the
seam is.

**There is no official GGUF. At all.** The `swiss-ai` organisation publishes
two dozen repositories and not one `.gguf` file. Official quantizations exist
only for MLX and for vLLM. Every path through Ollama, llama.cpp or LocalAI
therefore depends on a **community quantizer**. The menu only offers
repositories that declare their licence — an `apache-2.0` field that is filled
in, rather than left empty — because licence hygiene is not optional in an
AGPL-3.0+ project. Apertus's own documentation points at community builds and
says, in as many words, that the team cannot support them directly.

**`ollama pull apertus` does not work.** Apertus is not in Ollama's official
library; the request to add it has been open for a long time. The bare name
404s. The menu uses the HuggingFace bridge form
`hf.co/<repository>:<quantization>` instead, which is why the model string
looks longer than the ones in Ollama's documentation.

**The LocalAI gallery contains zero Apertus entries.** Its `index.yaml` holds
more than fifteen hundred models and not one of them matches. `local-ai run
apertus` fails; the `huggingface://` URI is mandatory, not a preference.

**`apertus.click` is not the Apertus project.** It is an unaffiliated
marketing landing page. It serves no model, no API and no download, and it is
not operated by EPFL, ETH Zurich or the CSCS. This guide deliberately does not
link it. The real site is **`apertus-ai.org`**, and the weights are under
`huggingface.co/swiss-ai`. If a search engine sends you to the other one, you
are in the wrong place.

What this adds up to: the **weights** and the **licence** are official and
verifiable; the **GGUF conversion**, the **Ollama reference** and the
**LocalAI URI** are community plumbing that the menu picks for you and that
you are free to replace.

## 9. Troubleshooting

### `unknown model architecture: apertus`

The engine is **too old**. It does not know the xIELU activation, and no
option, no flag and no re-download will change that. Check the version against
the table in section 4 and upgrade the engine:

```bash
ollama --version          # needs 0.12.6 or newer
llama-server --version    # needs build b6671 or newer
local-ai --version        # needs 4.0.0 or newer
```

On llama.cpp in particular, a distribution package is often the culprit: some
current distributions still ship a build older than `b6671`. Install from the
upstream installer instead, which puts a recent binary under your own account.

The menu catches this at step 5, before any download. Seeing the message means
the engine was installed or upgraded outside the menu.

### Special tokens leak into the replies

Answers that contain `<|assistant_start|>`, `<|user_start|>`,
`<|system_start|>` or similar markers mean the **chat template is not being
applied**. Apertus uses an unusual template, with a mandatory developer block;
when the engine falls back to a generic template, the model's own control
tokens end up in the visible text.

The fix is on the engine side, not the model's: make sure it applies the
template shipped with the weights — for llama.cpp, that is the `--jinja`
switch, which the menu passes. A raw completion endpoint bypasses the template
by design; use the chat endpoint (`/v1/chat/completions`).

### The engine is killed (out of memory)

Almost always the **context**. The 8B declares 65536 tokens, and the KV cache
for that is 8 GiB on top of the weights (section 5). A machine with room for
the file gets killed at the first question.

Cap the context. The menu serves at 8192 tokens for exactly this reason; if
you are launching an engine by hand, pass the equivalent option —
`--ctx-size` for llama.cpp, `--max-model-len` for vLLM, `num_ctx` for Ollama —
and keep it at 8192 unless you have measured that you can afford more.

A second suspect, if the context is already capped: a quantization that is too
large for the machine. `Q8_0` is 8.57 GB against 5.06 GB for `Q4_K_M`, for a
difference in quality most uses will not notice.

### The install seems frozen on a remote target

A remote step runs under `BatchMode`, where a password prompt waits invisibly.
If a host needs an interactive `sudo` password, step 2 says so and stops
there. If the freeze happens earlier, the SSH connection itself is asking for
something: make `ssh <target> true` work without typing anything, then come
back.

### A download that says nothing for minutes

Normal. Pulling several gigabytes can stay silent for a long while; only
Ollama exposes a real progress stream, and the other three can only be shown
as a step counter and an elapsed time. The screen marks a long silence rather
than inventing a progress bar.
