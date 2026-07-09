# Rubric — Anomalous transaction detection (ml-txn-anomaly-001)

*(Interviewer-only.)*

## Planted pitfalls

| Pitfall | Where | Signal if caught | Signal if missed |
|---|---|---|---|
| `review_outcome` leaks the label (post-review field) | column | Understands label provenance / leakage; strong hire signal | Model will look perfect (AUC ≈ 1.0); disqualifying for senior if unquestioned |
| ~1.5% exact duplicate rows | whole file | Routine data hygiene | Minor; inflates metrics slightly |
| `amount` is native currency; must normalize via `currency` | amount/currency | Reads the data dictionary, thinks in units | Large-amount signal becomes noisy |
| Labels only for reviewed rows (`is_anomalous` NaN ≈ 91% of rows) | label | Grasps selective labeling / sample bias; discusses it even if they can't fix it in 90 min | Treats NaN as 0 → silently trains on biased negatives |
| Positive rate drifts up in final month | time dimension | Motivates time-based split, monitoring | Random split overstates performance |

## Scoring grid

| Dimension | 1 — weak | 2 — adequate | 3 — strong | 4 — exceptional |
|---|---|---|---|---|
| Data handling | Loads and models immediately | Finds dupes or currency issue | Finds leakage + selective labels | All pitfalls + quantifies their impact |
| Methodology | Random split, accuracy | Stratified split, AUC | Time split, PR-AUC or precision@200/day, threshold tied to alert budget | Also addresses label bias (e.g. evaluates on reviewed subset with caveats) |
| Modeling | Default classifier, no imbalance handling | Class weights or resampling | Sensible features (per-customer aggregates, USD normalization), calibrated choice | Compares approaches, explains why the winner wins |
| Communication | Code only | Some narration | Clear summary of decisions and limitations | Frames results in reviewer-workflow terms (queue quality, drift monitoring) |
| Stretch: explanations | — | Global feature importance | Per-alert attributions (e.g. SHAP) with caveats | Ties explanations to reviewer actionability |

## Expected trajectory

- **First 15 min:** EDA; should surface label NaNs and `review_outcome` distribution.
- **Midpoint:** feature prep done, first model trained, evaluation framing chosen.
- **End:** evaluation against alert budget + written summary. Stretch is genuinely optional.

## Follow-up questions

1. *Your model's precision at 200 alerts/day is X. How would you convince the
   transaction review team to trust it over the rule system?* — look for backtesting
   against historical confirmed anomalies, shadow-mode deployment, reviewer feedback loop.
2. *The labels come only from reviewed transactions. What does that do to your
   model, and what would you do about it?* — selective labels / PU-learning awareness;
   at minimum, honest uncertainty.
3. *Six months from now precision drops. What's your debugging order?* — drift in
   inputs vs labels vs upstream pipeline; monitoring design.
