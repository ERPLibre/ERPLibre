
# Open LLMs — the survey, and when it expires

This guide describes the open-weight models that can be run on a machine you
own, and the engines that serve them. It is the long form of what
`TODO › Assistant › AI › Open models` shows on one screen.

Its tables are not typed here: they are **generated** from
`script/todo/assistant/panorama.py`, which is the authority. A table copied by
hand drifts away from the data it claims to render, and documentation is where
that drift is least visible — nobody re-reads a table of numbers to check that
it is still true.

## 1. What this is, and when it expires

**This survey was taken on 2026-09-13.** That date is `DATE_RELEVE` in the
module, and it is the first thing to read, before any number below it.

A catalogue of models rots in weeks, not in years. The proof is in the survey
itself: `DeepSeek-V4.1-Flash`, which takes rank 1 of the independent coding
leaderboard quoted in section 6, was published **three days before** the survey
was taken. Three days earlier, the top of this guide would have named a
different model.

That is why the menu **shows the survey's age instead of hiding it**. The entry
carries the number of days, then a verdict:

| Age of the survey | What the menu says |
|---|---|
| 0 to 45 days | ✅ survey is fresh |
| 46 to 120 days | ⚠️ survey should be re-read |
| past 120 days | ⛔ survey is stale — check before trusting it |

The two thresholds are `AGE_TIEDE` and `AGE_FROID`, and they are short on
purpose: six weeks sometimes separate two generations of the same model.

**If you are reading this past those thresholds, trust the upstream sources
over these tables.** The publisher's own repository — its `config.json`, its
file sizes, its licence file — is the thing that is still true. A model card
says what a model is today; this guide says what it was on the day it was
surveyed. Where the two disagree, the guide is the one that is wrong.

Two more warnings belong here rather than further down.

**No official RAM or VRAM figure is published for any of these models**,
neither by the model cards nor by the project sites. Every hardware value in
this guide is *derived*: from verified file sizes, from the models' own
declared dimensions, and from a "quantization size plus one to two gigabytes of
margin" rule stated by a community quantizer. They are estimates, never vendor
specifications, and this guide says so each time it matters.

**The search-engine layer of the web is actively misleading on this subject.**
One widely-reproduced round-up consulted during the survey gives one model a
1 M context where its own configuration says 262 144, calls another one
"Modified MIT" where the publishing platform's tag says `license:other`,
invents a model that does not exist, and quotes a 4-bit size off by a hundred
gigabytes. Treat that kind of overview as a lead to verify, never as data.

## 2. How to read the tables

Three ideas make the rest of this guide usable. Each of them is arithmetic, and
each of them contradicts something that people say about models.

### 2.1 The KV cache, and why it is the most useful column

Serving a model costs the weights **plus** a cache that grows with the
conversation. Nobody advertises it, and past a certain context length it is
larger than the model itself.

For a model with ordinary grouped-query attention, the cache costs, per token:

```text
2 (K and V)
  × the number of FULL-ATTENTION layers
  × kv_heads
  × head_dim
  × 2 bytes (fp16 or bf16)
```

Two traps live in that formula.

**Only full-attention layers count.** A hybrid model whose other layers are
linear-attention or state-space layers caches nothing in them. Multiplying by
the total layer count is the single most common way of being wrong here — for
one model in the table it would inflate the figure by a factor of eleven.

**A latent-attention (MLA) model does not have the factor of two.** Its cache
is one compressed latent vector per layer, plus the rotary dimensions, so:

```text
layers × (kv_lora_rank + qk_rope_head_dim) × 2 bytes
```

Applying the ordinary formula to an MLA model is wrong twice over: it doubles
the latent and it ignores the RoPE dimensions that must also be cached.

What that buys you, concretely: Apertus-8B costs 2 × 32 × 8 × 128 × 2 =
131 072 bytes, exactly **128 KiB per token**, so its native 65 536-token window
is **8 GiB of cache on top of the weights**. One MoE in the table costs
48.4 KiB per token in its latent form; another, with thirty-two kv heads,
costs **576 KiB per token** — twenty-four times more — and at a million tokens
that is 549.3 GiB of cache, more than twice what two large machines hold
together.

**At a million tokens the cache is usually bigger than the weights.** The
clearest case in the table is a 4-billion-parameter model: 7.5 GiB of weights
against 30.5 GiB of cache. The cache is four times the model.

### 2.2 Active parameters, not total, decide decode speed

Decoding one token means reading the parameters it activates out of memory.
The ceiling is therefore an arithmetic one:

```text
tokens per second ≤ memory bandwidth ÷ bytes read per token
```

On a machine with 273 GB/s of memory bandwidth, a **dense** 70-billion model
quantized to 4 bits reads about 40 GB per token, which caps it at 6.8 tokens
per second, and 4 to 5 in practice. A **sparse** mixture-of-experts of 229 G
total with only 10 G active reads a small fraction of itself, and its ceiling
is around 58 tokens per second — an order of magnitude apart, with the sparse
model being the *bigger* one on disk.

So: **filter on active parameters, never on the total, and never on "it
fits"**. The table's `Parameters` column gives both whenever they differ, and
the active figure is the one that predicts latency.

The ceilings in this guide are theoretical. One measurement anchors them: a
120-billion MoE with 5.1 G active was measured at **60.57 tokens per second**
decoding and 1 956 tokens per second in prefill, which is **61 % of its own
theoretical ceiling** of 99.4. Every throughput estimate here is the ceiling
scaled into that band, and is therefore derived — not a published figure.

### 2.3 Context length is not a function of model size

This is the idea that surprises people, and the table makes it visible.

A **4 G dense model** documents 1 010 000 tokens. A **70 G dense model** stops
at 65 536. The small one wins because only **8 of its 32 layers** are
full-attention, so its cache grows four times more slowly; the large one pays
all 80 of its layers on every token. Another model in the table keeps only
**6 attention layers out of 52** and has the cheapest cache on record — 6 KiB
per token, 5.7 GiB for a million tokens.

What actually sets a context length is (a) the positional encoding — the RoPE
base, YaRN or NTK interpolation, layers without positional encoding at all —
and (b) the attention layout, which decides whether the cache grows with the
tokens. Neither of them reads the parameter count.

### 2.4 The convention of the context column

The `Context` column carries no words, in either language, because the table is
generated once for both. A context described as "native" or "recommended"
would print in French to an English reader. The convention is therefore
made of symbols:

| What is printed | What it means |
|---|---|
| `65 536` | the native length, bare |
| `262 144 → 1,01 M YaRN` | native, then what an extrapolation reaches |
| `1 048 576 ⚑ 300 K` | the flag marks what the publisher actually recommends |
| `262 144 (config)` | only the configuration file asserts it |

The distinction is not cosmetic, and two facts justify it.

**An extrapolated context degrades well before its limit.** An independent
long-context benchmark evaluating 26 models across eight spans from 8 K to 1 M
measures a mean relative decline of **24.3 %** between the 8K-128K span and the
8K-1M span. The best model loses 8.5 %, the worst 60.5 %, and seven models out
of 26 change rank when the span widens — with confidence intervals of 1 to 2
points against gaps of 5 to 16, that is not noise.

**A publisher has already withdrawn, in writing, a one-million claim its own
configuration contradicted.** On one model family, a member of staff wrote word
for word: "sorry for the confusion on 1M context, we will fix documentation."
The configuration says 262 144, the README says 128 K in plus 128 K out, the
technical report says 1 M, and the limit observed on the publisher's own hosted
API is 131 072 tokens with full recall to 128 K and degradation beyond. When a
`(config)` marker appears in the column, this is the class of situation it
warns about.

One last consequence, worth stating plainly: **a million tokens is a capacity,
not a working window**. The same benchmark shows that dropping its entire 1 M
span saves 54.5 % of the token budget while preserving a Spearman correlation
of 0.997 against the full ranking. Secondary sources put the useful production
window between 200 and 400 K, and effective capacity is commonly cited at 60 to
70 % of the announced window.

## 3. The engines

An engine is the program that loads the weights and serves them over an HTTP
API. Five are described here; two more are named at the end of the section
because the survey could **not** describe them.

| Name | Licence | Port | API | Formats | Platforms | Apertus minimum |
|---|---|---|---|---|---|---|
| Ollama | MIT | 11434 | /v1 + /api | GGUF | Linux, macOS, Windows | 0.12.6 |
| llama.cpp | MIT | 8080 | /v1 + /health | GGUF, NVFP4, MXFP4 | CPU, CUDA, Vulkan, Metal, SYCL, ROCm | b6671 |
| mlx-lm (MLX) | MIT | 8080 | /v1 + /health | safetensors MLX INT2-INT6 | Apple Silicon | 0.27.1 |
| LocalAI | MIT | 8080 | /v1 + /api + /readyz | GGUF + safetensors (via backends) | Linux x86_64, ARM64 | — |
| vLLM | Apache-2.0 | 8000 | /v1 + /health + /version | safetensors bf16, FP8, NVFP4, int4 | Linux + CUDA, CPU avx512 | 0.10.2 |

**The `Formats` column is the decisive one.** It says which weight
repositories are usable at all, and it rules out a model far more often than
available memory does. An engine that eats only GGUF cannot load the official
safetensors; an engine that eats only safetensors cannot load a community GGUF.

### Why there is a minimum version at all: the xIELU activation

Apertus does not use the activation function everything else uses. It uses
**xIELU**, and that single fact dates support for it in every engine. An engine
released before xIELU landed in its sources does not become slow or approximate
on Apertus — it **cannot** run it. It either refuses the file with
`unknown model architecture: apertus`, or loads it and emits noise.

Below the minimum, **the download succeeds and only inference fails**. Check
the version before spending five gigabytes of traffic, not after.

The `Apertus minimum` column applies to the Apertus family only. For any other
model in section 4, the floor is whatever version added that architecture, and
the survey does not record it.

### Ollama

Installs from the distribution package where one exists, and from the official
binary otherwise; there is no source package in the two largest Debian-family
distributions, so it is an archive or a third-party repository there. It
registers its own service.

**GGUF only** — which now includes GGUF in MXFP4 and NVFP4, but never FP8 or
NVFP4 safetensors. MLX safetensors only go through a custom build, outside the
public one.

**Minimum 0.12.6**, of 15 October 2025, and that number was established **by a
source diff, not by release notes**: the 0.12.5 tag contains no occurrence of
"apertus" or "xielu", 0.12.6 contains two and three, and it is the vendored
llama.cpp refresh that brings the activation. No release note between 0.12.3
and 0.34.0 mentions Apertus at all — searching the changelog tells you nothing.

*Strengths.* The shortest path: one command, and the `hf.co/<repository>:<quant>`
bridge opens every community GGUF with no catalogue to maintain. It is also the
only engine in this list that **announces its capabilities** — `POST /api/show`
reports tools, vision and context length — and the only one that exposes
downloading over HTTP (`POST /api/pull`), so it can be driven without a shell.

*Weaknesses and traps.* **`ollama pull apertus` returns 404.** Apertus is not
in the official library; the request to add it has been open since 2 September
2025 and two more issues are open beside it. Apertus's own guide points at a
community repository and warns, in as many words, that the team cannot support
community builds directly — and that repository's chat template is announced as
"intentionally basic", so it is not at parity with the official Jinja template
for tools and multilingual work. There is **no sharing of a model between
machines**: the two upstream issues are still open, and third-party wrappers
replicate whole models only. One last trap: its GGUF blobs for MoE models are
not readable by upstream llama.cpp — experts are packed in groups of four —
which has no effect on Apertus, a dense model, but bites when the two engines
share one store.

### llama.cpp

Installs from its upstream script — 225 lines of POSIX shell — which puts the
binary under your own account and a copy in `~/.local/bin`, **without root**,
provided that directory is on your `PATH`. Packages exist in one rolling
distribution and in the development and recent releases of the Debian family.

**GGUF only**, but that now covers `NVFP4` and `MXFP4` alongside `Q2_K`…`Q8_0`
and `BF16`. No FP8 or NVFP4 safetensors.

**Minimum build `b6671`**, of 2 October 2025: `b6670`, from the same day, does
not have it, and the publishing team recommends `b6686` or newer. Below it the
message is `error loading model architecture: unknown model architecture:
apertus`.

*Strengths.* It is the only engine here that installs without administrative
rights. The binary is unified — `llama serve`, `llama cli`, `llama bench` — and
`--jinja` is now on by default, so the chat template embedded in the GGUF
applies by itself, which is exactly the trap Apertus sets. It is also the
safest 4-bit path for a 70 G model: one `Q4_K_M` file of 43.7 GB, where `Q6_K`
at 57.9 GB arrives in pieces to reassemble.

*Weaknesses and traps.* **There is no prebuilt binary for Linux on ARM with
CUDA.** A current release offers an ARM64 CPU build, an ARM64 Vulkan build and
a Windows ARM64 CUDA build, and nothing else: on an ARM machine with an NVIDIA
GPU, you compile. **A distribution package is frequently older than the
minimum** — one release of a widely used distribution still ships `b5882`,
which predates Apertus support, and the failure arrives *after* five gigabytes
have been downloaded; another distribution's stable release has no package at
all. **xIELU is not on every backend from the minimum build**: CPU and CUDA got
it on 2 October 2025, but WebGPU on 5 December 2025, Vulkan on 21 December
2025, Metal on 14 April 2026 and the Intel path on 15 July 2026 — an Intel
target therefore needs far more than `b6671`; check the build, not the
calendar. Its **back-to-back networking is plain TCP, with no RDMA, and gets
slower as machines are added**: 20.4, then 17.2, then 15.2 tokens per second at
one, two and four nodes on a large model. And **the converter moved**: the
Apertus model class now lives in `conversion/llama.py`, no longer in
`convert_hf_to_gguf.py`, which has become a 312-line shell — a grep in the
wrong file concludes wrongly that the model is unsupported.

On recent NVIDIA silicon, building with `-DGGML_NATIVE=ON` and a `native` CUDA
architecture fails, and the project's own build file says so; pass the
architecture explicitly with a CUDA 13.x compiler. Finally, two version series
coexist upstream — the `bNNNNN` builds and a parallel semantic version — and
the survey does not establish the correspondence between them.

### mlx-lm (MLX)

Installs with `pip install mlx-lm`, or from a pinned git commit.

**MLX-quantized safetensors only** — INT2, INT3, INT4, INT6 — produced by
`mlx_lm.convert`. This matters for Apertus more than anywhere else: the
publisher officially ships MLX INT3/INT4/INT6 for the whole Mini family, at
2.2 / 2.6 / 3.4 GB for the 4 B, 1.0 / 1.1 / 1.3 GB for the 1.5 B and
0.3 / 0.3 / 0.4 GB for the 0.5 B.

**Minimum mlx-lm 0.27.1**, of 4 September 2025 — Apertus ran here *one day
after* its public release, because xIELU was already in the model file.

*Strengths.* It is Apple's own framework, and the only one that truly reaches
the GPU on that platform. Eleven tool-call parsers ship with it and are chosen
automatically, with no flag to pass. **Tensor parallelism is the default
sharing mode** — the one that actually speeds up decoding, unlike pipeline
parallelism — over a Thunderbolt 5 RDMA transport with an announced latency
under 50 µs. Measured on a 16 GB laptop of that platform: Apertus 1.0 8B at
21.5 tokens per second for a 4.7 GB peak, and Apertus v1.1 4B at 32.1 tokens
per second for 2.9 GB.

*Weaknesses and traps.* **Its own documentation states that the server "is not
recommended for production as it only implements basic security checks"**, and
`--allowed-origins` defaults to `*`: never bind it to a public address without
a proxy in front. **The last published tag is older than the features you
want** — the tool parsers and the recent architectures are only on the main
branch — so you install from git and pin a commit. Tensor parallelism is
**per model**: it requires a `shard()` method in the model file, and the fix
for uneven sharding is not merged, so a number of machines that does not divide
the dimensions silently falls back to pipeline, with no speed gain. And there
is **no MLX build of Apertus 70B** from the community organisation: the only
one in existence is a third-party fine-tune of 39.7 GB, not the publisher's
original — otherwise you convert it yourself, which is straightforward since
xIELU is in place.

MLX now has a CUDA backend on Linux, but the entire served and measured path of
this survey remains the Apple one.

### LocalAI

Installs from a script that puts the binary in a system directory with `sudo`
or under your own account, or from a container image. Note that the script
**no longer writes a systemd unit**: you produce it yourself.

**GGUF through its llama.cpp backend**, and safetensors in bf16, FP8 and NVFP4
when it delegates to its vLLM or SGLang backends, which returned in 4.3.0 for
ARM64 machines on CUDA 13 wheels.

**No minimum version is published for Apertus**, which is why that cell of the
table is a dash. Support is inherited from the llama.cpp it embeds, and the
survey does not pin that embedded version — so llama.cpp's `b6671` does not
transpose mechanically into a LocalAI number.

*Strengths.* One core that speaks both the OpenAI and the Anthropic API shapes,
and that can put either llama.cpp or a real vLLM behind itself depending on
what the model needs. It downloads by URI — `huggingface://`, `hf://`,
`hf.co/`, `oci://`, `ollama://`, `github://`, `http(s)://`, `file` — so any
community GGUF is reachable without a catalogue. And `GET /healthz` and
`GET /readyz` separate "started" from "ready", which **no other engine in this
list distinguishes**.

*Weaknesses and traps.* **Its gallery contains zero Apertus entries**: the
index is 2.5 MB and 1 566 entries, and it yields no match for "apertus" and
none for "swiss". `local-ai run apertus` therefore fails, and the
`huggingface://` form is mandatory, not a preference. Worse for a step-by-step
installer: **its backends download themselves at the first inference**, meaning
a multi-gigabyte container image — a slow and fallible step that must be
counted on its own and not folded into "start the server". One identification
trap: it re-emits the whole of Ollama's native API and literally answers
"Ollama is running" on `/`, so in a probe ladder it must be tested **before**
Ollama; what separates them is `GET /readyz`, where Ollama returns 404.

### vLLM

Installs from a Python wheel or a container image.

**safetensors**: bf16/fp16, FP8 W8A8, NVFP4 compressed-tensors, int4 w4a16,
MXFP4, and an FP8 KV cache. No GGUF in practice for these models.

**Minimum 0.10.2**, of 13 September 2025, from the pull request that added
"Apertus and XIELU" — day-zero support, shipped before the model was public.
The `apertus` tool-call parser is upstream too, with its template and its
tests.

*Strengths.* It is the **only engine in this list that consumes the publisher's
official weights directly**. Every other path depends on a community quantizer,
because the Apertus organisation publishes no GGUF at all. And batching
recovers everything a single stream loses: 20.5 tokens per second at one stream
against 368 at thirty-two on an 8 B in FP8, and 5.79 against 695 aggregated
tokens per second from 1 to 256 streams on a 49 B in NVFP4.

*Weaknesses and traps.* **It announces no capability whatsoever**: a client can
read neither the tools, nor vision support, nor the context length — you assume
or you try. In bf16 the 8 B weighs 16.1 GB and does not fit a 16 GB card:
24 GB is the real floor, otherwise you want an FP8 build at 9.1 GB, which is
itself only fast from compute capability 8.9 upward. **The CPU path is
unusable for a beginner**: `avx512f` is required for the full feature set, an
`LD_PRELOAD` has to be found by hand, and the torch tree weighs several
gigabytes — and a virtual machine with the default CPU model does not even
expose `avx512` to the guest, so test the processor flags before offering vLLM
on a target without a GPU.

> ⚠️ **The optional fused xIELU CUDA kernel is not to be installed.** It lives
> in a repository with **no licence at all** — no `LICENSE` file, the hosting
> platform reports `license: None`, and there is no package on the index. A
> free-software project cannot ship it. The pure-PyTorch fallback is automatic
> and correct; it costs speed and nothing else.

Two more facts about this engine. **Apertus v1.5 is not upstream**: the model
registry knows only the v1 class, the model pull request is open and not
merged, and the claim to the contrary that circulates in research summaries is
false — what is upstream is the *tool parser*, not the model. And on the ARM64
wheel, one quantization extension carries cubins for one compute capability
only; both of the load-time guards pass anyway, so the failure arrives late, at
kernel launch. A compressed-tensors NVFP4 checkpoint without a transform scheme
escapes that hole, its matrix kernels coming from a library that does carry the
right target.

### The two engines this survey could NOT describe

They are **named rather than tabulated with empty cells**. A row whose four
columns out of eleven say "not surveyed" clutters without informing, and a menu
that offers an engine it cannot describe promises more than it holds.

**llamafile.** What is established: it is the path the official Apertus
documentation presents for an ordinary machine, it has its own guide page, it
listens on port 8080, it serves `/completions` described as "OpenAI-compatible
format", and it needs neither Python nor CUDA — a prebuilt executable is all
there is. **What is missing: the licence, any version number, the weight format
it consumes, and a minimum version for Apertus.** Four fields out of eleven.
No precise behaviour can be promised, and the machine cannot be probed other
than by calling `/completions`.

**SGLang.** What is established: it has an official Apertus guide page — which
llama.cpp does not — batching takes it from 20.5 to 368 tokens per second on an
8 B in FP8, speculative decoding is one flag away, and it **refused to serve an
NVFP4 build in two different versions**, which matters because NVFP4 is
precisely the format recent hardware is bought for. **What is missing: the
licence, the default port, the minimum version for Apertus, and its own
installation path.** Three fields out of eleven are empty, and the module
records a port of `0` to mean "not filled in" rather than inventing a number to
fill the cell.

Both need a clean verification before they appear as a menu choice.

## 4. The open models

Twenty-four entries. The order answers the question a reader asks, not a
ranking: Apertus first, because it is this repository's subject; then what
**runs** on a modest machine, from the smallest up; then what **does not fit**,
from the least oversized to the most, so that the wall is visible instead of
being guessed at.

| Name | Publisher | Parameters | Context | Licence | Weights | KV cache/token |
|---|---|---|---|---|---|---|
| Apertus-8B-Instruct-2509 | Swiss AI Initiative (EPFL / ETH / CSCS) | 8,05 G dense | 65 536 | Apache-2.0 + USAGE_POLICY | bf16 16,1 Go · FP8 9,1 Go · NVFP4 6,1 Go | 128,0 Kio (2·32·8·128·2) |
| Apertus-70B-Instruct-2509 | Swiss AI Initiative (EPFL / ETH / CSCS) | 70,6 G dense | 65 536 | Apache-2.0 + USAGE_POLICY | 4 bits 39,9 Go · FP8 72,8 Go · bf16 141,2 Go | 320,0 Kio (2·80·8·128·2) |
| Apertus v1.1 Mini (0.5B, 1.5B, 4B) | Swiss AI Initiative (EPFL / ETH / CSCS) | 0,5 / 1,5 / 4 G dense | 4 096 (x3) | Apache-2.0 + USAGE_POLICY | 4B 7,7 Go · 1.5B 3,0 Go · 0.5B 1,1 Go | 96,0 / 32,0 / 20,0 Kio (4B / 1,5B / 0,5B) |
| Apertus-v1.5-8B | Swiss AI Initiative (EPFL / ETH / CSCS) | 8,90 G dense (multimodal) | 262 144 | Apache-2.0 (gated) | bf16 18,4 Go · FP8 11,4 Go · NVFP4 9,0 Go | 128,0 Kio (2·32·8·128·2) |
| Apertus-v1.5-70B | Swiss AI Initiative (EPFL / ETH / CSCS) | 72,0 G dense (multimodal) | 262 144 | Apache-2.0 (gated) | W4A16 43,0 Go · FP8 76,2 Go · bf16 144,6 Go | 320,0 Kio (2·80·8·128·2) |
| Qwen3.5-4B | Alibaba (Qwen) | 4 G dense | 262 144 → 1,01 M YaRN | Apache-2.0 | bf16 8,1 Go (7,5 Gio) | 32,0 Kio (2·8·4·128·2) |
| Qwen3.8-27B | Alibaba (Qwen) | 27,8 G dense | 262 144 | Apache-2.0 | Q4 17,6 Go · Q8 29,0 Go · bf16 55,6 Go | 256,0 Kio (2·64·4·256·2) calc. |
| Nemotron 3 Nano 30B-A3B | NVIDIA | 31,6 G · act. 3,6 G (MoE) | 262 144 (config) | NVIDIA Open Model License | FP8 31,6 Go · bf16 63,2 Go | 6,0 Kio (2·6·2·128·2) |
| Qwen3.6-35B-A3B | Alibaba (Qwen) | 35 G · act. 3 G (MoE) | 262 144 → 1,01 M YaRN | Apache-2.0 | FP8 35,0 Go · bf16 70,0 Go | 20,0 Kio (2·10·2·128·2) |
| Qwen3.5-35B-A3B | Alibaba (Qwen) | 35 G · act. 3 G (MoE) | 262 144 → 1,01 M YaRN | Apache-2.0 | FP8 35,0 Go · bf16 70,0 Go | 20,0 Kio (2·10·2·128·2) |
| gpt-oss-120b | OpenAI | 116,8 G · act. 5,1 G (MoE) | 131 072 | Apache-2.0 | 63,0 Go (MXFP4) | 72,0 Kio (2·36·8·128·2) |
| Mistral-Small-4-119B-2603 | Mistral AI | 119 G · act. 6,5 G (MoE) | 1 048 576 (config) ⚑ 200 K | Apache-2.0 | NVFP4 70,8 Go · IQ4_XS 58,1 Go | 576,0 Kio (2·36·32·128·2) |
| Devstral 2 123B Instruct 2512 | Mistral AI | 123 G dense (Small 2 : 24 G dense) | 262 144 | license:other (Mistral (custom)) | Q4_K_M 74,9 Go · Small 2 en Q4 ~14 Go | — |
| Nemotron 3 Super 120B-A12B | NVIDIA | 120,6 G · act. 12,7 G (MoE) | 262 144 (config) | NVIDIA Open Model License | NVFP4 80,3 Go · FP8 128,4 Go | 8,0 Kio (2·8·2·128·2) |
| Qwen3.8-Flash-Next | Alibaba (Qwen) | 125 G · act. 6 G (MoE) · 180 G | 262 144 → 1 M YaRN | qwen-community-1.0 | IQ4_XS 93,7 Go · NVFP4 132,7 Go | 24,0 Kio (2·12·2·128·2) |
| Kimi-Linear-48B-A3B-Instruct | Moonshot AI | 48 G · act. ~3 G (MoE) | — | MIT | bf16 98,3 Go | — |
| MiniMax-M2.7 | MiniMax | 228,7 G · act. 10 G (MoE) | 204 800 | Modified MIT | IQ4_XS 108,4 Go · NVFP4 139,9 Go | 248,0 Kio (2·62·8·128·2) |
| DeepSeek-V4-Flash-0731 | DeepSeek | 304,2 G · act. ~13 G (MoE) | 65 536 → 1 M YaRN | MIT | IQ3_XXS 104,2 Go · NVFP4 175,6 Go | 48,4 Kio (MLA 43·576·2) |
| GLM-5.3-Flash | Z.ai / Zhipu (zai-org) | 321,3 G · act. 18 G (MoE) | 1 048 576 ⚑ 300 K | MIT | IQ3_XXS 120,4 Go · NVFP4 204,4 Go | 50,6 Kio (MLA 45·576·2, inf.) |
| MiniMax-M3 | MiniMax | ~428 G · act. ~23 G (MoE) | 1 048 576 | minimax-community | IQ3_XXS 194,9 Go · IQ4_XS 207,6 Go | 120,0 Kio (2·60·4·128·2) |
| GLM-5.3 | Z.ai / Zhipu (zai-org) | ~744 G · act. — | 1 048 576 (config) | license:other « glm-5.3 » | IQ3_XXS 281,7 Go · IQ4_XS 365,3 Go · FP8 755 Go | — (cf. GLM-5.2 : 87,8 Kio) |
| DeepSeek-V4.1-Flash | DeepSeek | 763,2 G | 1 048 576 (config) | MIT | FP8 510,3 Go · ~380 Go en 4 bits | — |
| Kimi K2.7-Code | Moonshot AI | 1 000 G · act. 32 G (MoE) | 262 144 | Modified MIT | 595,2 Go (INT4) | 68,6 Kio (MLA 61·576·2) |
| Kimi K3 | Moonshot AI | 2 800 G · act. 104 G (MoE) | 1 048 576 | Kimi K3 License (Modified MIT +) | 1 560,9 Go en MXFP4 (119) | 27,0 Kio (MLA 24/93) |

### 4.1 The Apertus family

Five entries, one publisher, and a clean split between what runs today and what
does not.

**Apertus-8B-Instruct-2509 is the one to pin for this repository.** It is
8 053 338 176 parameters, dense, 32 layers, 65 536 tokens of context,
Apache-2.0 and not gated. It is the only Apertus that is genuinely comfortable:
15.0 GiB in bf16, its full window on one machine, and **all four engines serve
it unpatched**. In bf16 it does not fit a 16 GB card — 16.1 GB of weights alone
— so the realistic floor is a 24 GB card, or the FP8 build at 9.1 GB, which is
only fast from compute capability 8.9. Its chat template is the trap: unusual
special tokens plus a mandatory developer block, and when it is misapplied the
raw control tokens leak into the visible answers.

Its licence deserves one careful sentence. It is Apache-2.0, but a usage policy
ships beside the licence file, carrying an indemnification obligation and a
recommendation to re-download a fingerprint filter twice a year. "Apache-2.0,
nothing else to read" would be wrong.

**Apertus-70B-Instruct-2509 is a different kind of machine.** Same family, 80
layers, same 65 536-token window, 320 KiB of KV per token — so its full window
costs 20 GiB of cache on top of the weights. A 4-bit quantization fits one
machine with room to spare at 39.9 GB, but being dense it rereads all of it per
token: a 6.8 tokens per second ceiling, 4 to 5 in practice. In bf16 it fits no
single 128 GB machine at all — 131.5 GiB of weights against a usable budget of
about 115 GiB — and fails even at zero context; two machines carry it
comfortably at about 75.8 GiB per node.

Three warnings about its builds, and all three are about community
quantizations. **No quantization of any Apertus is official** — the publisher
ships no FP8 and no quantized checkpoint for either size — so everything usable
on recent hardware is community-made and not validated by the publishing
institutions. One widely-downloaded "dynamic 4-bit" build **weighs 114.4 GB and
not 40**: its dynamic scheme left 52.5 G of parameters in bf16 against only
18.6 GB of 4-bit payload, and the name misleads. And two repositories from the
same author, one labelled NVFP4 and one NVFP4A16, are **the same model to the
byte** at 42.80 GB each: do not download both.

**The Apertus v1.1 Mini family — 0.5 B, 1.5 B, 4 B — is the small-machine
answer, and its context is the wall.** All three declare **4 096 tokens**, and
nothing in their configuration scales that: the 4 B and the 1.5 B use a default
rotary type with no scaling at all. For a coding assistant, 4 096 tokens is
fatal. What you get in exchange is that the whole family, six repositories of
full weights, is resident together in 21.8 GiB, the cache is a non-issue at
96 / 32 / 20 KiB per token, and the ceilings are 35.7, 90 and beyond 150 tokens
per second going down the sizes.

Their quantizations carry a platform trap: **nine of the ten official ones are
MLX builds**, hence Apple-only and useless on an ARM machine with an NVIDIA
GPU; the tenth, the only NVFP4, covers the 1.5-billion model alone. And the
largest Mini has **no NVFP4 build at all**, official or community.

One curiosity that looks like a packaging error and is not: the 0.5 B base
repository (0.9 GB) is *smaller* than its instruction-tuned sibling (1.1 GB).
The instructed one declares tied word embeddings in its configuration but ships
an untied output head, and the 131 072 × 1024 table is the 0.3 GB of
difference. For every other pair in the family, base and instructed are
identical to the byte.

**Apertus v1.5, in both sizes, is gated and unserved.** Two things stop it.

First, **the repositories are gated**. Approval is automatic on a click, but an
account is required, along with accepting the acceptable-use and privacy
policies and filling in a company field and an institutional email address. An
anonymous fetch of the configuration returns "Access to model … is restricted"
— which is a 401 that nobody expects on a remote machine part-way through an
install. Ungated mirrors exist, and they bypass the policy the official
repository requires.

Second, **no upstream engine loads it**. Its architecture class is registered
only in a pinned fork of one engine, at one commit, alongside a pinned fork of
the transformers library; the upstream pull request has been open since 31 July
2026 and its predecessor was closed without merging; llama.cpp has neither a
converter for it nor a multimodal projector, across all 92 files of its
conversion package; and the corresponding Ollama issue is open. The
quantizations unlock nothing on the software side: they are still the same
architecture and still go through the same fork.

And **every v1.5 GGUF you will find is an amputation, not a conversion**: both
the vision and the audio towers are *removed* from the weight map — not
converted, removed — and the input vocabulary is truncated from 266 752 back to
131 072. A `-text-` in the file name is the only warning you get.

What v1.5 would buy, if it were servable: 262 144 tokens instead of 65 536, a
full slot at 49.1 GiB for the 8 B, and Apertus's only multimodal path. For the
70 B, a single community build reaches the full 262 144 on one machine — 40 GiB
of weights plus 40 GiB of fp8 cache, with about 14 GiB to spare — and the irony
worth seeing before committing is that this build sits on the *least* supported
software path of all. Also note that one of its NVFP4 builds is not uniform:
its own configuration declares a mixed-precision scheme, NVFP4 on the
feed-forward projections and FP8 on attention, which is why it weighs 51.5 GB
instead of about 43.

Finally, on the v1.5 side, **there is no technical report**. It was promised
"in the coming weeks" at the 24 July 2026 release and does not exist. There is
no quality figure for v1.5 anywhere.

### 4.2 What runs on a modest machine

"Modest" here means three tiers, and the honest way to read them is by the
memory you actually have, not by the parameter count.

**A laptop or a small server — under 24 GB.** The Apertus Minis, the Apertus 8B
in a 4-bit GGUF, and one dense 4 G model that is in this catalogue for what it
proves rather than for what it does. That model documents 1 010 000 tokens at
four billion parameters under Apache-2.0 — the same window as a model four
hundred times its size — because only 8 of its 32 layers are full-attention.
The inversion to look at is that its 7.5 GiB of weights carry 30.5 GiB of cache
at a million tokens, and being dense it tops out near 34 tokens per second,
with no coding benchmark published. Keep it for the demonstration.

Also in this tier, the small sibling of a code-specialized family: about 14 GB
in 4-bit for roughly 12 to 14 tokens per second at 68.0 % on a self-reported
patch benchmark, under Apache-2.0. That is a defensible fallback when you want
a small dedicated coding model and a clean licence.

**A single large machine — roughly 117 GiB usable.** This is where the
catalogue becomes interesting, and where the active-parameter rule does all the
work.

The most comfortable fit is a 119 G mixture-of-experts with only 6.5 G active:
65.9 GiB on one machine, about 45 GiB genuinely free after overhead,
Apache-2.0, a ceiling near 70 tokens per second. It is also the canonical
warning of this guide: its configuration declares 1 048 576 tokens and its card
quietly recommends 200 K, and **its cache is the most expensive in the whole
catalogue** at 576 KiB per token — twenty-four times another model in the same
table. Those 45 free gigabytes buy about 82 K tokens in a bf16 cache, 164 K in
fp8. Budget 64 K to 100 K of real context and check `kv_heads × head_dim ×
layers` before believing any announced length.

The fastest thing actually verified on this class of hardware is a 116.8 G MoE
with 5.1 G active, shipped natively in MXFP4 at 63 GB: 1 956 tokens per second
in prefill, 60.57 decoding, Apache-2.0, and **the only model in the catalogue
whose announced window fits with room to spare** — its entire 131 072 tokens
cost 9.0 GiB, 68 GiB all told. Its weakness is that same window: 131 072 tokens
is half of what an agent working across a repository asks for, and its
publisher has released nothing open since 4 August 2025. Superseded as a main
agent, excellent as fast local completion and as a tool caller.

Two hybrid models make long context nearly free in memory. One keeps 6 attention
layers out of 52 and costs 6 KiB per token — 5.7 GiB for a million tokens,
64.6 GiB all told in bf16 and 32.3 GiB in FP8, the cheapest cache on record.
The other keeps 10 full-attention layers out of 40 and gives the best
speed-to-context trade-off on one machine: 42.1 GiB in FP8 for a million
tokens, with a ceiling around 91 tokens per second. Both come with a caveat:
the first has a deployed limit observed at 131 072 tokens with degradation
beyond 128 K and **no coding score anywhere**, and the second's million is a
YaRN extrapolation whose larger sibling loses fourteen points on a long-context
benchmark between a 128 K span and a 1 M one.

The only model in the catalogue that holds **a million tokens on one machine**
is a 125 G / 6 G-active hybrid: 87.3 GiB of weights plus 11.4 GiB of fp8 cache.
A bf16 cache brings the total to 110.2 GiB, too tight once activations and
graphs are counted, so switch the cache to fp8. Its two costs are a house
licence to read before any commercial deployment — it is explicitly *not*
Apache-2.0, unlike its dense siblings — and the fact that no independent figure
exists for it: only its dense 27 G sibling is on the independent leaderboard.

That dense 27 G sibling is worth its own sentence, because it teaches the rule.
It punches far above its size — 0.730 on an independent terminal benchmark,
within a point of a model seven times bigger — and every one of its
quantizations fits easily. And it is **disqualified on throughput anyway**: its
near-twin was measured at 12.63 tokens per second on one node, below
comfortable interactive speed, because dense means all 27.8 G are read for
every token. Its best use is as a quality reviewer in bf16 while a fast sparse
model does the bulk of the work.

One 48 G research model on linear attention fits comfortably at 98.3 GB with
about 3 G active and a ceiling near 90 tokens per second. It has no coding
benchmark at all and its native context was not recorded. Keep it for what it
demonstrates: linear attention degrades *gracefully*, gaining ranks as the
evaluated span widens.

**Two machines — about 251 GB.** Two models earn this tier. One is a 304 G /
13 G-active MoE under MIT with a compact latent cache, and it is **the best
documented entry in the whole catalogue**: an independent score that agrees
with its own card, plus a throughput measurement on exactly this class of
hardware — 52.87 tokens per second decoding across two directly linked
machines. Its costs are honest: it needs two machines in NVFP4, its
time-to-first-token at 131 K was measured at 89.36 s, and its million tokens is
a factor-16 YaRN stretch of a base trained at 64 K, so aim at 128 to 256 K as a
working window.

The other is a 321 G / 18 G-active multimodal MoE, also MIT, carrying the best
independent coding score of everything that fits. Eighteen billion active
parameters cost about 30 % of throughput against the previous one for 1.6 more
points — the other model wins on speed per point. Its 3-bit build would fit one
machine, but see section 6 before taking that road.

A third, at ~428 G with ~23 G active, *barely* fits two machines and is **not
recommended**: it decodes about twice as slowly as a smaller sibling for no
gain on the terminal benchmark, and its striking 0.805-against-0.660 split
between two benchmarks suggests tuning for patch-style evaluation rather than
long terminal agency.

**Two models here are superseded and the table says so.** One 35 G MoE is
kept only because the published context arithmetic was done on it; its newer
generation has identical geometry and equal or better quality, so there is no
reason to deploy the older one fresh. And one 123 G *dense* coding model is
superseded by the sparse 119 G model above, which folds three previous families
into one checkpoint. That dense model is the perfect illustration of the rule:
it fits on one machine at 74.9 GB in 4-bit, and it is disqualified anyway at a
3.6 tokens per second ceiling and about 2.5 in practice. **"It fits" is not a
criterion.**

### 4.3 What does not fit at all

Four entries, and they are in the table on purpose: the wall should be visible,
not guessed at. All four are strong, all four are open, and none of them will
run on two machines.

The strongest open coding model there is needs **365.3 GB in its 4-bit build**
against a 251 GB ceiling for two machines, and even its 3-bit build at 281.7 GB
still overflows. Note also that its licence **left MIT** at this generation for
a house licence, where the previous versions and its own smaller sibling stayed
MIT — if licence purity matters, pin the older version or take the sibling.

The model at rank 1 of the independent coding leaderboard, published three days
before the survey, is **MIT-licensed and you still cannot run it**: about
380 GB even in 4 bits. Its family's runnable branch is the two-machine model of
section 4.2.

A code-specialized trillion-parameter model at 595.2 GB is 2.37 times over the
two-machine ceiling, needs five machines for the weights alone, and is
**already in native INT4** — going lower would need about two bits per
parameter, well under usability, with no official checkpoint at that level. Its
licence is a near-MIT with a single display obligation above very large usage
thresholds and, notably, no internal-use restriction at all. And a high-speed
variant quoted for its speed **has no published weights**, so those numbers are
not reproducible when self-hosting.

Finally, a 2 800 G model with 104 G active weighs 1 560.9 GB across 119 files —
6.21 times two machines, thirteen machines for the weights alone. Even if you
had them, about 57 GB would be read per decoded token, which is 4.8 tokens per
second at 273 GB/s; its own publisher serves it at 37.4 tokens per second. It
is nonetheless the best demonstration in the catalogue of the cache rule: only
24 of its 93 layers keep a growing cache, so a million tokens costs about 29 GB
of KV for 2 800 billion parameters — the *cache* would fit on your desk.

One integration trap from that model is worth knowing even if you never run it,
because it applies to any model of its kind: it always returns a separate
reasoning field that **must be passed back verbatim** in the following turns,
tool calls included. An agent that passes back only the visible content loses
the thread silently — no error, and therefore no diagnosis.

### Two cross-cutting warnings about identity

**Pin the repository identifier and the revision, not the name.** One publisher
ships five distinct models whose names differ by a date or a suffix, and the
word "Flash" designates a small distilled model at one vendor and a 300 G+
mixture-of-experts at two others. A configuration pinned by name will one day
resolve to something else.

**Do not trust a leaderboard's "open weights" column.** The one used for this
survey is wrong in at least two places: it marks as closed a model that is
publicly downloadable at 755 GB, and it marks two others as closed although
their publisher ships both. Check that status on the weight repository itself.

## 5. Resources — what a class of machine actually holds

### 5.1 Nameplate memory is not usable memory

The number on the box is not the number a model gets.

**On a unified-memory Linux machine, a 128 GB nameplate reports about
117 GiB**, and the survey budgets **115 GiB** once activations, the accelerator
context, fragmentation and the prefill buffer are counted. The difference is
not academic: one model's FP8 build measures **116.1 GiB against 117 usable**,
which leaves not one gigabyte for any of those four, and it must be treated as
**not fitting** even though the arithmetic says it does by a hair.

**On macOS, the system reserves about a quarter of the unified memory.** A
256 GB machine offers roughly 192 GB to a model until `sudo sysctl
iogpu.wired_limit_mb=237568` raises it to about 232 GB. One more constraint on
that platform: its matrix accelerators cover FP16 and INT8 but **not BF16** —
convert to 4-bit or 8-bit, never to bf16.

**On a discrete GPU, the card is the budget and there is no borrowing.** The
Apertus 8B in bf16 is 16.1 GB of weights alone, so it does not fit a 16 GB
card; 24 GB is the real floor, or an FP8 build at 9.1 GB.

### 5.2 What each class holds

| Machine | Usable budget | What it holds |
|---|---|---|
| Laptop, 16 GB unified | ~12 GB | the Apertus Minis, and the Apertus 8B in 4-bit — measured at 21.5 tok/s for a 4.7 GB peak, and 32.1 tok/s for 2.9 GB on the 4 B |
| GPU card, 16 GB | 16 GB | an 8 B in FP8 (9.1 GB), not in bf16 |
| GPU card, 24 GB | 24 GB | an 8 B in bf16, the real floor for full-precision serving |
| One unified machine, 128 GB | ~115-117 GiB | a 63 GB MXFP4 MoE with 50 GiB free; a 70.8 GB NVFP4 MoE with ~45 GiB free; a 93.7 GB build with a million tokens of fp8 cache; a 4-bit 70 B with its full window |
| Two linked machines | ~251 GB | a 175.6 GB NVFP4 MoE; a 4-bit build of a 321 G model; and nothing at 365 GB or above |

Every figure in that table is derived from verified file sizes plus the
measured overheads above. **None of it is a vendor specification.**

### 5.3 Linking two machines aggregates capacity, not bandwidth

This is the part that disappoints people.

Two machines hold twice the weights. They do **not** decode twice as fast, and
under some engines they decode *more slowly*.

What is measured: one MoE decodes at **52.87 tokens per second across two
directly linked machines**, which is about 73 % of what carrying the
single-machine estimate over would predict. The interconnect between them moves
about 10.2 GB/s, and how a large mixture-of-experts with expert parallelism
scales across it is **not measured** at all.

What is measured on the other side: llama.cpp's back-to-back transport is plain
TCP with no RDMA, and it **gets slower as nodes are added** — 20.4, then 17.2,
then 15.2 tokens per second at one, two and four nodes. The opposite was also
observed, 1.8 rising to 12.5 tokens per second going from one ARM box to two —
but there the single node was out of memory, so the second machine was buying
capacity, not speed.

**Nothing in the survey settles the case that actually decides**: the model
fits on one machine, and you add a second. Until someone measures that, treat a
second machine as capacity.

On Apple hardware the sharing story is better in kind: tensor parallelism —
the mode that genuinely speeds decoding, unlike pipeline parallelism — is the
default over a Thunderbolt 5 RDMA transport with an announced latency under
50 µs. It is still per-model, and it silently falls back to pipeline when the
machine count does not divide the model's dimensions.

### 5.4 Disk, and the margin

Disk is the easy half, and the rule is the one a community quantizer states:
**the size of the quantization, plus one to two gigabytes of margin.** A
download writes intermediate files and an engine writes a service file.

One conversion case is much worse than that rule, and the menu warns before
starting: converting a 70 B to a 4-bit Apple build downloads the
full-precision weights first, so it asks for about 175 GB of free space to
produce 41 GB.

### 5.5 Before concluding that a model is slow

The one measurement that anchors every throughput estimate in this guide — 61 %
of the theoretical ceiling — was taken with a specific kernel, driver and CUDA
version. Without the right kernel option, the same model's **load time goes
from 22 s to 104 s**. Before concluding that a model is slow on your machine,
check that the kernel, the driver and the toolkit match the ones the published
measurements used.

## 6. Strengths and weaknesses, honestly

### 6.1 A benchmark score is inseparable from its harness

This is the single most important caveat about every coding number in this
guide, and it is not a hedge.

**One publisher measured a 3.6-point spread for one unchanged model across two
harnesses** — 79.7 against 76.1 — and published both. That spread is as large
as the gap that separates the top open models from each other. Nothing about
the model changed; the scaffolding around it did.

The harnesses in play are not comparable either. One publisher measures inside
a specific coding agent at maximum reasoning effort, with six-hour timeouts,
averaged over three runs. Another measures in an unpublished "minimal mode"
harness of its own. A third reports the better of two harnesses. A fourth ran
its own house harness while quoting competitors measured in someone else's —
and a secondary source reports that model three points lower in an independent
harness than its card claims.

**No card figure will be reproduced with different scaffolding.** When this
guide writes "independent", it means a third party ran the model; when it
writes "self-reported", it means the publisher did. The module's `codage` field
carries that word for every model that has one.

### 6.2 SWE-bench Verified no longer discriminates

It is saturated at 0.950, and the major laboratories have stopped reporting it.
The open models cluster between **0.772 and 0.806** — five of them in a
handkerchief. A benchmark on which everything scores the same has stopped
carrying information.

The terminal-agency benchmark spreads those same models from **0.25 to 0.91**.
If you must choose on one number, choose on that one — and then read section
6.1 again, because that number has a harness too.

### 6.3 Sub-4-bit quality loss is unmeasured, exactly where it matters

Two of the strongest models here fit on **one** machine if you take them below
four bits: a 2-bit build at 90.9 GB, and a 3-bit build at 120.4 GB. Both are
tempting, and **no published benchmark replays either model at that level**.

The reason to be careful is the *shape* of the degradation rather than its
size. Agentic degradation is vicious and invisible: the JSON of tool calls
deforms, long plans lose their coherence — while perplexity barely moves. The
usual quick check will tell you nothing is wrong.

Prefer a 4-bit build on two machines to a 2- or 3-bit build on one, unless you
are prepared to measure the difference yourself.

### 6.4 Apertus is a sovereign multilingual model, not a coding model

This has to be said plainly, with its numbers.

The only coding table that exists for Apertus, for any version, is Table 18 of
its technical report (arXiv:2509.14233), and it is **self-reported**:

| Model | HumanEval Pass@10 | MBPP Pass@1 |
|---|---|---|
| **Apertus-8B** | **67.0** | **36.2** |
| **Apertus-70B** | **73.0** | **47.0** |
| Qwen3-32B | 97.0 | 73.6 |
| Llama-3.3-70B-Instruct | 95.8 | 75.6 |
| Qwen2.5-72B-Instruct | 95.4 | 74.6 |
| gemma-3-27b-it | 89.3 | 72.8 |
| SmolLM3-3B | 89.7 | 52.8 |

Read the last row. **A 3-billion-parameter model beats the 70-billion Apertus
on HumanEval.** The gap to a 32 B coding model is 24 points. And the metric
flatters Apertus twice over: Pass@10 is roughly ten times more forgiving than
the Pass@1 that the models it is compared against report elsewhere.

There is **no SWE-bench, no Terminal-Bench, no LiveCodeBench, and no agentic or
tool-use result for any version of Apertus**, anywhere.

What Apertus has instead is what put it in this repository: Apache-2.0 weights
that download without an account, **open training data**, a published training
recipe with its intermediate checkpoints, coverage of **1 811 languages**, 17 T
pre-training tokens for the family, and compliance work of the kind European
regulation asks for. It is a sovereign, auditable, multilingual model. Take it
for that. For a coding agent, take something else and say so out loud.

### 6.5 This is not a ranking

Two models three points apart on a benchmark are **tied**, because the
scaffolding that calls them weighs as much as what separates them. The columns
of these tables exist to **rule out** what will not fit on a machine, not to
crown a winner.

## 7. What this survey does not know

This section is the guide's honesty, and it is not to be softened. Everything
below is a hole that was found and left open rather than filled with a guess.

### 7.1 About the engines

- **SGLang is the widest hole.** The survey gives neither its licence, nor its
  default port, nor its minimum version for Apertus, nor its own installation
  path. It establishes only three things about it: an official guide page
  exists, batching takes it from 20.5 to 368 tokens per second on an 8 B in
  FP8, and two versions failed to serve an NVFP4 build.
- **llamafile is documented by a single line**, the one in the official guide:
  port 8080, `/completions` described as "OpenAI-compatible", neither Python
  nor CUDA required. Licence, version number, weight format consumed and
  minimum for Apertus are all absent.
- **No minimum LocalAI version for Apertus is published.** It depends on the
  llama.cpp it embeds, and the survey does not pin that engine — so
  llama.cpp's `b6671` does not transpose mechanically into a LocalAI number.
- **mlx-lm's own licence is not recorded.** MIT is established for MLX, the
  compute framework; the serving project is a different repository.
- **llama.cpp's current version appears as two different numbers** on two
  consecutive days of the survey. Two version series coexist upstream — the
  `bNNNNN` builds and a parallel semantic version — and the survey gives no
  correspondence between them.
- **What llama.cpp does when you add a machine is not settled**, and the two
  measurements do not contradict each other: on four Apple machines over
  Thunderbolt the throughput goes *down* (20.4, 17.2, 15.2 tokens per second
  from one to four nodes) because the transport is plain TCP, but on two ARM
  boxes it goes *up*, from 1.8 to 12.5 — and there the single node was out of
  memory. Nothing establishes the deciding case: the model fits on one machine,
  and a second is added.
- **No engine supports Apertus v1.5 today.** The vLLM model pull request is
  open, llama.cpp has no converter, the Ollama issue is open, and the official
  path goes through a pinned fork of the transformers library. The only v1.5
  GGUFs in circulation are amputations, and a `-text-` in the file name is the
  only warning.
- **No report of Apertus on recent NVIDIA silicon exists.** Every throughput
  figure of that hardware class comes from other models served by these
  engines, used as a proxy: how the xIELU activation behaves on that compute
  capability is measured nowhere.
- **No official RAM or VRAM figure is published**, by any model card or project
  site. Every hardware value is derived from verified file sizes plus a
  community quantizer's "quantization size plus one to two gigabytes" rule.
- **The gap in one vLLM ARM64 extension was measured statically**, by cubin
  coverage; the runtime failure was not reproduced. And the inspection tool
  cannot settle it: a family cubin and a specific cubin display the same target
  name, so auditing a wheel and concluding "no support, therefore broken" is a
  false negative.
- **Which engine reports download progress is not documented.** The survey
  establishes only that Ollama exposes a pull over HTTP and that LocalAI's
  backends download themselves at first inference; it describes the output of
  none of them. Verify before promising a progress bar in a menu.
- **One distributed runner stays out of the catalogue for lack of fields.** It
  is established as Apache-2.0, built on MLX, with tensor and pipeline
  parallelism — but also as stalled, with its last substantial commit on
  22 June 2026 and weeks at a time with none, and as running on CPU only under
  Linux, hence unable to use an NVIDIA GPU. Neither its default port nor
  Apertus support is recorded.

### 7.2 About the models and their figures

- **The KV cache of one model is inferred**, and it is the only figure in the
  catalogue that does not trace back to a published layer count: its 45 layers
  were read as latent attention. Its documented mix of sparse and linear
  attention could not be verified layer by layer.
- **One model's KV per token was calculated here**, from the verified geometry
  of its configuration, because the source did not cost that model.
- **One model's total parameter count exists in two versions**, 304.2 G from
  the weight index and 284 G from a competitor's comparison table. Both
  circulate; the index figure was kept.
- **One model's weights exist in two costings**, and the practical conclusion
  changes between them: its FP8 build goes from "just at the limit" to "does
  not fit". The byte sums were kept over the earlier parameter-based estimates.
- **One model's weights were widely misreported.** The figure of 1 560.9 GB is
  a byte sum over 119 files; two earlier estimates circulated, and a number
  repeated across several blogs is in fact the size of a *different* model.
  Hardware sizing done on that number would be off by a factor of 2.6.
- **The decimal sizes of four models are arithmetic conversions** from binary
  units: the source gave only the binary figures for them.
- **No coding score is published at all** for seven of the twenty-four entries,
  including the whole Apertus family beyond its Table 18. For one of them the
  card's figures exist but are rendered as **images** and could not be
  extracted.
- **Apertus's only coding figures are self-reported**, and the metric is about
  ten times more forgiving than the one the models it is compared against
  report.
- **Apertus v1.5 has no technical report.** It was promised "in the coming
  weeks" at the 24 July 2026 release and does not exist. There is no quality
  figure for v1.5 anywhere.
- **Whether the pinned forks needed by Apertus v1.5 build on ARM64 with CUDA 13
  is unknown.** That is the single question that decides its feasibility, and
  it is not settled.
- **The behaviour of xIELU on recent NVIDIA compute capability is unverified**,
  and it conditions the entire Apertus column.
- **The native context of one model was not recorded** on its sheet, and the
  active parameter count of another is not stated on its card.
- **One model's widely-repeated "Modified MIT" qualification could not be
  confirmed**: the publishing platform's tag says `license:other`.
- **Proprietary models were deliberately excluded** from this survey, which
  covers open weights only.

### 7.3 About context length and benchmarks

- **An announced context length is often an extrapolation, not a trained
  property.** Three models in the table are native at 262 144 and reach a
  million only through YaRN; one is a factor-16 stretch of a base trained at
  65 536. The extension is applied by the engine at inference, is not free in
  quality, and must be enabled explicitly — the model will not do it by itself.
- **Among the open models examined, only four declare a context of a million or
  more with no YaRN entry at all.**
- **A one-million claim was retracted in writing** by a publisher, on a family
  whose configuration says 262 144, whose README says 128 K in plus 128 K out,
  whose technical report says 1 M, and whose hosted API was observed to stop at
  131 072 with degradation past 128 K.
- **Quality collapses before the announced number.** An independent
  long-context benchmark of 26 models over eight spans measures a mean relative
  decline of 24.3 % between the 8K-128K span and the 8K-1M span; best case
  8.5 %, worst case 60.5 %. Seven models out of 26 change rank, with confidence
  intervals of 1 to 2 points against gaps of 5 to 16.
- **That same benchmark truncates from the middle** when a model's window is
  shorter than the span being evaluated, so a poor score at the 1 M span may
  reflect a short window rather than real degradation. Read those scores
  alongside each model's declared context.
- **A million tokens is a capacity, not a working window.** Dropping the 1 M
  span entirely saves 54.5 % of the token budget while preserving a Spearman
  correlation of 0.997 against the full ranking, with a maximum rank shift of
  one. Secondary sources put the useful production window at 200 to 400 K, and
  effective capacity is commonly cited at 60 to 70 % of the announced window.
- **Card scores are inseparable from their harness**, and the gap between two
  harnesses can exceed the gap between two models — one publisher's own
  3.6-point spread for an unchanged model is the proof.
- **Sub-4-bit quality loss is measured for none of these models**, including
  the two builds that would change the answer by fitting on one machine.
- **Do not choose on SWE-bench Verified in 2026**: it is saturated at 0.950,
  the major laboratories have stopped reporting it, and the open models cluster
  between 0.772 and 0.806.
- **A leaderboard's "open weights" column is wrong in at least two places.**
  Verify that status on the weight repository, never on a leaderboard's
  checkbox.
- **The search-engine layer of the web is actively misleading on this
  subject**, as section 1 describes. Treat a round-up article as a lead to
  verify, never as data.
