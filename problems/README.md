# Problems

Curated technical interview problems. Each problem is a self-contained directory that
the platform can package into a candidate workspace.

## Directory contract

```
problems/
├── _template/              # copy this to start a new problem
└── <problem-id>/           # e.g. ml-txn-anomaly-001
    ├── problem.yaml        # manifest — id/title/status/summary/candidate_paths/
    │                       #   data.generator; the manifests ARE the problem index
    │                       #
    ├── problem.md          # candidate-facing statement            [CANDIDATE]
    ├── starter/            # starter code/notebooks given as-is    [CANDIDATE]
    └── data/
        ├── generate.py     # synthetic dataset generator (seeded)  [interviewer]
        └── README.md       # data dictionary                       [CANDIDATE]
```

**Statements only — no scoring material.** Rubrics, answer keys and reference solutions
are deliberately not kept in this repo. Published next to the problem they bias everyone
who reads them: the candidate who finds the repo, and the interviewer who scores against
someone else's grid instead of the work in front of them. Keep assessment notes wherever
your hiring record lives.

**Visibility is enforced by the provisioner, not convention:** only `problem.md`,
`starter/`, `data/README.md`, and the *generated output* of `data/generate.py` are
copied into a candidate workspace. `generate.py` itself never leaves this repo, and the
packager still refuses `rubric.md`, `solution/`, and answer-key-shaped files by name — so
interviewer material added to a problem later cannot reach a workspace by accident.

## Problem IDs

`<track>-<slug>-<nnn>`, tracks:

| Track | Prefix | Focus |
|---|---|---|
| Data science | `ds` | wrangling, EDA, metrics, statistics |
| Classical ML | `ml` | tabular modeling, evaluation, imbalance, features |
| LLM application | `llm` | RAG, agents, prompt/tool design against the proxy |
| ML engineering | `mle` | debugging pipelines, performance, productionization |
| General coding | `gen` | algorithms / data-structure thinking on realistic data |

## Dataset rules

Dataset production is **handled separately** — the shape below is the
contract problems design against; detailed standards come later.

- **Synthetic only.** No real customer/production data, ever. Datasets are produced by
  a committed, seeded `data/generate.py` so they are reproducible and diffable.
- Materialized size ≤100 MB (fits the 8 GB instance budget). Declare expected peak RAM
  in `problem.yaml`.
- Generated data files are **not committed** (see `.gitignore`).
- Public datasets: commit a download script + checksum, not the data.

## Writing a good problem

- **Layered difficulty**: a core task most candidates finish, plus stretch parts that
  separate levels.
- **Realistic mess**: data should contain the kinds of defects the job actually has
  (dupes, mixed types, leakage traps) — planted deliberately, never by accident.
- **Judgment over recall**: prefer "choose and defend an evaluation metric" over
  "implement X from memory".
- **Statement carries its own weight**: a candidate should be able to start from
  `problem.md` alone, with no interviewer commentary to fill in gaps.
- **Time-boxed**: state expected duration in the manifest; verify by dogfooding.

## Adding a problem

See [`CONTRIBUTING.md`](CONTRIBUTING.md) — contract, quality bar, and PR checklist.
