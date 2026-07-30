# Base image specification

Target host: **small VM** — 2 vCPU, 8 GB RAM, EBS storage (recommend ≥60 GB gp3),
single persistent instance. One candidate at a time (admin concurrent); workspace runs
as containers and is reset between candidates; the host stays thin.

## Landscape survey → what to preinstall

Criteria: what AI/ML candidates actually reach for in interviews (2025–26 usage
surveys, PyPI download rank, our problem tracks), constrained to CPU-only 8 GB.

### Tier 1 — core, always installed

| Package | Why | Approx. size |
|---|---|---|
| python 3.12 | baseline | — |
| numpy, pandas, scipy | universal | ~200 MB |
| scikit-learn | the classical-ML lingua franca | ~120 MB |
| matplotlib, seaborn | plotting | ~120 MB |
| statsmodels | stats/inference questions | ~50 MB |
| xgboost, lightgbm | dominant on tabular problems (our `ml` track) | ~150 MB |
| pyarrow, duckdb | parquet + fast SQL-on-files; SQL questions without a DB server | ~150 MB |
| jupyterlab, ipykernel, ipywidgets | notebook environment | ~250 MB |
| torch (CPU wheel) | de-facto standard DL framework | ~750 MB |
| nltk, spaCy (+ `en_core_web_sm`) | classical NLP | ~200 MB |
| openai, anthropic, litellm (client) | LLM SDKs — all pointed at our proxy | ~30 MB |
| google-adk | agent development kit (`llm`/agent problems) | ~50 MB |
| httpx, requests, pydantic, tqdm, python-dotenv | utility layer | ~30 MB |
| pytest, ruff | let candidates test/lint like real work | ~30 MB |

Non-Python: git, tmux, ripgrep, sqlite3, curl/jq, make, gcc (for pip builds).

### Tier 2 — optional layers

| Package | Why optional |
|---|---|
| tensorflow-cpu (+ keras) | ~600 MB; minority framework now — install only if a problem requires it |
| transformers, sentence-transformers | common for `llm` track, but model weights blow the RAM/disk budget fast; enable per problem with a pinned small model pre-cached |
| shap | explanations stretch tasks |
| faiss-cpu / chromadb | RAG problems |
| langchain-core / langgraph | only if a problem is explicitly about these frameworks |
| polars | offered if a candidate asks; not assumed |

### Deliberately excluded

- **GPU anything** — no GPU on the host.
- **conda** — pip + venv in a container is lighter and reproducible; conda adds ~3 GB.
- Local LLM runtimes (ollama etc.) — 8 GB can't serve a useful model *and* leave
  headroom; LLM ability comes from the proxy instead.

## Image layout

```
environments/
├── Dockerfile.workspace     # tier-1 stack + code-server + jupyterlab
├── compose.yaml             # workspace + (optional) local litellm for dev
└── layers/                  # tier-2 optional pip layers
```

- Base: `python:3.12-slim-bookworm` (Debian). Host OS: RHEL8-family (Rocky/Alma 8,
  for broad enterprise compatibility); the host only runs the container
  runtime + platform services.
- **code-server** (VS Code OSS server, MIT) with Python + Jupyter extensions
  pre-installed; candidate reaches it and JupyterLab through the portal over HTTPS.
- Estimated image size: ~2.5–3 GB compressed pull, well within 60 GB EBS.

## RAM budget check (worst realistic case, everything co-resident)

| | GB |
|---|---|
| OS + container runtime + audit agent | 0.8 |
| Portal + admin console + proxy | 0.5 |
| code-server + extensions | 0.7 |
| JupyterLab server | 0.3 |
| Kernel with 400k-row pandas workload + xgboost/torch training | 2–4 |
| **Headroom** | **≥1.5** |

Problems declare `expected_peak_ram_gb`; CI runs each reference solution in a
memory-capped container to enforce it.

## Version pinning

All versions pinned in `environments/requirements.lock` (generated with `uv pip
compile`); image rebuilt and problems re-verified on a monthly cadence, not ad hoc.
