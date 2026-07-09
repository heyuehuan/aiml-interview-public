# Environments

The candidate workspace definition: what the interviewee actually sees and uses.

## Contents

- `Dockerfile.workspace` — python 3.12 + tier-1 ML stack + code-server + JupyterLab
  (package list: `../infra/images/base-image-spec.md`).
- `compose.yaml` — run the exact candidate environment locally:
  `docker compose up` → code-server on :8443, JupyterLab on :8888. Used for problem
  authoring and dogfooding.
- `layers/` — optional tier-2 package layers enabled per problem
  (`problem.yaml: environment.extra_pip`).
- `requirements.lock` — pinned versions (uv pip compile), rebuilt monthly.

## Workspace layout as the candidate sees it

```
~/workspace/
├── PROBLEM.md          # from problems/<id>/problem.md
├── data/               # generated dataset + data dictionary
├── starter/            # if the problem provides it
└── (their work)
```

The provisioner copies **only** `candidate_paths` from the problem directory —
solutions and rubrics stay out by construction.
