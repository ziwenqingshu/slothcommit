# Benchmarks (real numbers, one machine)

All numbers were measured on **2026-10-20** in a cloud sandbox:
2 vCPU ARM Neoverse-V2 (no GPU), 7.8 GB RAM, `gemma-3-1b-it` from
[unsloth/gemma-3-1b-it-GGUF](https://huggingface.co/unsloth/gemma-3-1b-it-GGUF).
Your laptop will differ: these are a floor, not a promise.

## Raw model speed (`llama-bench`, 2 threads)

| Runtime | Quant | Prompt (pp512) | Generation (tg64) |
|---|---|---|---|
| llama.cpp b11756 official `ubuntu-arm64` build | Q4_K_M | 53.9 tok/s | 31.6 tok/s |
| llama.cpp b11756 official `ubuntu-arm64` build | **Q4_0** | **182.1 tok/s** | **56.8 tok/s** |
| llama-cpp-python 0.3.36 prebuilt CPU wheel | Q4_K_M | ~25 tok/s | ~15 tok/s |
| llama-cpp-python 0.3.36 prebuilt CPU wheel | Q4_0 | ~26 tok/s | ~16 tok/s |

Q4_0 is ~3.4x faster at reading prompts here because llama.cpp repacks it
for ARM's int8 matrix instructions. Since a commit message is mostly *reading*
(a diff) and very little *writing* (one line), that's why Q4_0 is the default.

## End-to-end `sloth` timings (llama-server backend, Q4_0)

| Task | Time |
|---|---|
| `sloth commit`, 8 real commits on the demo repo (diffs of 1-25 lines) | 2.2 s - 4.8 s, mean 3.4 s |
| new-file commits of 200-300 lines (diff condensed, subject only) | 6.5 s - 8.1 s |
| first request after starting the server (cold, few-shot prefix not cached) | 8.2 s |
| same small diff, warm server | 1.1 s |
| `sloth week` (6-7 commits, English or Chinese) | 3.0 s - 4.7 s |
| llama-server resident memory (`-c 4096 -np 1`) | ~1.6 GB |

## The in-process backend is the slow fallback

The same staged diff (2 files, +13/-2) through `--backend llamacpp`
(llama-cpp-python wheel, Q4_0, grammar-constrained JSON): **67.9 s**,
versus 4.8 s through llama-server. The prebuilt wheel isn't compiled with the
CPU's int8 matmul extensions, and the Python-side grammar sampler adds overhead.
Use `llama-server` or Ollama if you can; keep the in-process backend for
"I refuse to run a daemon".

## Not measured

* The Ollama backend is implemented and unit-tested against Ollama's
  documented `/api/chat` structured-output API, but I could not download the
  Ollama binary inside the sandbox, so it has no live timing here.
* Gemma 3 4B (Q4_0) read prompts at ~40 tok/s here and got OOM-killed while
  the 1B server was also loaded, so it is not benchmarked end-to-end.
