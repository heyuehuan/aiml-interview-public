# Anomalous transaction detection

## Context

Our transaction review team reviews transactions flagged as potentially anomalous.
Reviewers can review at most **200 transactions per day**; today's rule-based system
floods them with low-quality alerts. You have six months of historical transactions,
a subset of which were reviewed and labeled.

## Data

In `~/workspace/data/`:

- `transactions.csv` — six months of transactions with labels where available.

Full data dictionary in `data/README.md`.

## Deliverables

- A notebook or script with your analysis, model, and evaluation.
- A short (~half page) written summary: approach, key decisions, what you'd do next.

## Ground rules

- Any preinstalled library is fair game.
- Explain your reasoning as you go — intermediate work is part of the assessment.

## Tasks

### Q1 — Core: score transactions and use the alert budget

Build a model that scores transactions by anomaly likelihood, and propose how to use it
under the 200-alerts/day budget. Justify your evaluation methodology.

### Q2 — Stretch: explain the alerts (if time permits)

Reviewers want to know *why* a transaction was flagged. Show how you'd surface
per-alert explanations.
