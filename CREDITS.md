# Credits

SlothCommit is new code written in October 2026 for the DEV Hacktoberfest
Open-Source AI Challenge (Week 3: "Slow and Steady"). No code was copied from
other projects, but it stands entirely on the shoulders of these:

| Project | What SlothCommit uses it for | License |
|---|---|---|
| [Gemma 3](https://ai.google.dev/gemma) by Google DeepMind (`gemma-3-1b-it`) | the model that writes every message | [Gemma Terms of Use](https://ai.google.dev/gemma/terms) (open weights) |
| [unsloth/gemma-3-1b-it-GGUF](https://huggingface.co/unsloth/gemma-3-1b-it-GGUF) | ungated GGUF conversion of Gemma 3 1B (default download) | follows Gemma terms |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | `llama-server` backend, GBNF grammar-constrained JSON | MIT |
| [llama-cpp-python](https://github.com/abetlen/llama-cpp-python) | in-process backend | MIT |
| [Ollama](https://github.com/ollama/ollama) | optional backend (`gemma3:1b`) | MIT |
| [Conventional Commits](https://www.conventionalcommits.org/) | the commit message format | CC BY 3.0 |
| [asciinema](https://asciinema.org/) + [agg](https://github.com/asciinema/agg) | recording `docs/demo.gif` | GPL-3.0 / Apache-2.0 |

Prior art that does the same job with cloud models: [aicommits](https://github.com/Nutlope/aicommits),
[opencommit](https://github.com/di-sukharev/opencommit). SlothCommit's twist is that it is
designed around a 1B model on a CPU: few-shot prompting, schema-constrained output,
and doing everything deterministic (commit type for docs/test/CI-only changes,
changelog grouping, stats) in plain Python instead of asking the model.
