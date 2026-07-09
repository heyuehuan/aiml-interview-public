# Reference solution — ml-txn-anomaly-001

*(Interviewer-only.)*

## Approach sketch (target: rubric level 3–4)

1. **Hygiene:** drop exact duplicates; convert `amount` to USD via `currency`.
2. **Leakage:** drop `review_outcome` after demonstrating it's post-hoc
   (`confirmed_anomaly` ⇔ label ≈ 1). Keep the demonstration in the notebook.
3. **Labels:** restrict training to reviewed rows (`is_anomalous` notna);
   explicitly note the selective-labeling bias.
4. **Split:** train on months 1–5, evaluate on month 6 (drift makes this matter).
5. **Features:** USD amount (+ large-amount indicator), channel, elevated-category
   flag, cross-border flag, hour-of-day, per-customer 30-day aggregates (count, sum, max).
6. **Model:** gradient boosting (xgboost/lightgbm) with class weights; logistic
   regression as baseline.
7. **Evaluation:** precision/recall at k = 200·(days in eval window) alerts;
   PR-AUC secondary. Compare against a rule baseline (e.g. flag all off-hours
   p2p transfers) to frame the win.
8. **Stretch:** SHAP values per alert, mapped to reviewer-readable reasons.

## Acceptable alternatives

- Isolation-forest / semi-supervised angle using unlabeled rows — fine if the
  candidate justifies it and still evaluates on labeled data.
- Threshold-free ranking framing (queue ordering) instead of hard threshold.
