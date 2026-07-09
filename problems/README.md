# Problems

Curated technical interview problems. Each problem is a self-contained directory that
the platform can package into a candidate workspace.

## Directory contract

```
problems/
├── registry.yaml           # index of all problems + visibility defaults
├── _template/              # copy this to start a new problem
└── <problem-id>/           # e.g. ml-txn-anomaly-001
    ├── problem.yaml        # manifest (metadata, resources, visibility)
    ├── problem.md          # candidate-facing statement            [CANDIDATE]
    ├── starter/            # starter code/notebooks given as-is    [CANDIDATE]
    ├── data/
    │   ├── generate.py     # synthetic dataset generator (seeded)  [interviewer]
    │   └── README.md       # data dictionary                       [CANDIDATE]
    ├── rubric.md           # scoring guide, follow-up questions    [interviewer]
    └── solution/           # reference solution(s)                 [interviewer]
```

**Visibility is enforced by the provisioner, not convention:** only `problem.md`,
`starter/`, `data/README.md`, and the *generated output* of `data/generate.py` are
copied into a candidate workspace. `rubric.md`, `solution/`, and `generate.py` itself
never leave this repo.

## Problem IDs

`<track>-<slug>-<nnn>`, tracks:

| Track | Prefix | Focus |
|---|---|---|
| Data science | `ds` | wrangling, EDA, metrics, statistics |
| Classical ML | `ml` | tabular modeling, evaluation, imbalance, features |
| LLM application | `llm` | RAG, agents, prompt/tool design against the proxy |
| ML engineering | `mle` | debugging pipelines, performance, productionization |

## Dataset rules

- **Synthetic only.** No real customer/production data, ever. Datasets are produced by
  a committed, seeded `data/generate.py` so they are reproducible and diffable.
- Materialized size ≤100 MB (fits the 8 GB instance budget). Declare expected peak RAM
  in `problem.yaml`.
- Generated data files are **not committed** (see `.gitignore`); CI regenerates them.
- Public datasets: commit a download script + checksum, not the data.

## Writing a good problem

- **Layered difficulty**: a core task most candidates finish, plus stretch parts that
  separate levels. The rubric maps parts to signals.
- **Realistic mess**: data should contain the kinds of defects the job actually has
  (dupes, mixed types, leakage traps) — deliberately and documented in the rubric.
- **Judgment over recall**: prefer "choose and defend an evaluation metric" over
  "implement X from memory".
- **Rubric first-class**: every problem ships `rubric.md` with a scoring grid,
  expected pitfalls, and interviewer follow-up questions. A problem without a rubric
  doesn't get registered.
- **Time-boxed**: state expected duration in the manifest; verify by dogfooding.

## Adding a problem

1. `cp -r _template <track>-<slug>-<nnn>` and fill in every file.
2. Run `python data/generate.py` and sanity-check output + data dictionary.
3. Dogfood it end-to-end within the stated time box.
4. Add an entry to `registry.yaml` (problems default to `hidden` until an admin
   enables them).
5. PR review must include one person solving it cold.
