# Rubric — ml-eval-concepts-001

**Interviewer-only. Do not mount into the candidate workspace.**

Short conceptual screen (~10–15 min). The letters are a prompt for a conversation:
ask "why" on each answer, and weight the explanation over the selection. Q2 has two
correct options; partial selections are recorded and are themselves signal.

## Answer key

| Q  | Answer | One-line why |
|----|--------|--------------|
| Q1 | **B** | 99% of records are negative, so the all-negative model is right 99% of the time. |
| Q2 | **B, C** | PR-AUC and precision/recall at the real alert budget reflect performance on the rare class; A is dominated by the majority class, D ignores the positives entirely. |
| Q3 | **B** | The column is a proxy for the label (leakage): excellent offline scores, useless in production where it is empty at prediction time. |
| Q4 | **C** | A time-ordered split mirrors deployment; random and stratified splits let the model see the future and hide the drift. |
| Q5 | **C** | The constraint is a fixed review capacity, so the threshold is "top 200 per day" and the metric is precision at that cutoff. |

## Talking points

**Q1 (B).** The point is that accuracy says nothing under heavy imbalance. A strong
candidate volunteers that the baseline to beat is 99%, not 50%.

**Q2 (B, C).** Probe: what does PR-AUC summarise that ROC-AUC hides when positives are
rare? Why is precision at a fixed alert count the metric the reviewers actually feel?
Selecting only one of B or C is acceptable if the explanation is right; selecting A
without caveats is the concern.

**Q3 (B).** Leakage. Ask how they would detect it before training (a feature that is
missing for unreviewed records, a single feature with implausible importance, a
suspiciously perfect validation score). Ask what "available at prediction time" means.

**Q4 (C).** Drift. Ask what they would monitor after deployment and how they would
know when to retrain. A candidate who argues for a stratified split should be asked
what happens when the positive rate keeps rising.

**Q5 (C).** The operating point is a business constraint, not a statistical one. Ask
how they would present the trade-off (precision at 100, 200, 400 alerts) and what they
would do if the reviewers' capacity changed.

## Guidance

- Solid: B / B+C / B / C / C with explanations that name imbalance, leakage, drift
  and the capacity constraint in their own words.
- Concerning: defends accuracy for Q2, or says the leaked column is "just a strong
  feature" in Q3.
