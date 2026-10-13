# Subject models used in Pivot Benchmark runs

Zerava's own GGUF quantizations, built by Dhiraj Sah (September 2026). Every published result
names one of these files; anyone repeating a result needs the same file or an identical build.
Fields marked TODO are to be filled by Dhiraj from the build log; the files are not in git
(4-9 GB each). Plan: publish the four files on Hugging Face under the ZeravaTech organisation
with this table as the model card.

| File | Size | Source model (Hugging Face id, revision) | Quantization | Tool and version | Built |
|---|---|---|---|---|---|
| zerava-llama-3.1-8b-instruct-Q4_K_M.gguf | 4.6 GB | meta-llama/Llama-3.1-8B-Instruct, revision TODO | Q4_K_M | llama.cpp convert_hf_to_gguf.py + llama-quantize, version/commit TODO | 2026-09-22 |
| zerava-mistral-7b-instruct-v0.3-Q4_K_M.gguf | 4.1 GB | mistralai/Mistral-7B-Instruct-v0.3, revision TODO | Q4_K_M | same, TODO | 2026-09-22 |
| zerava-gemma-3-12b-it-Q4_K_M.gguf | TODO | google/gemma-3-12b-it, revision TODO | Q4_K_M | same, TODO | 2026-09-22 |
| zerava-qwen2.5-14b-instruct-Q4_K_M.gguf | 8.4 GB | Qwen/Qwen2.5-14B-Instruct, revision TODO | Q4_K_M | same, TODO | 2026-09-22 |

Serving in the runs: llama-cpp-python server, --n_gpu_layers -1, --n_ctx 8192, chat template from the
GGUF metadata; subject max_tokens 300, temperature 0.7 (see config.yaml). The sha256 of each file should
be added here once computed on the machine: `sha256sum ~/models/zerava-*.gguf`.
