# Model evaluation concepts

## Context

A team trains a binary classifier to flag records for human review. Positives are
rare, the data arrives in time order, and reviewers can look at a fixed number of
flagged records per day.

Unless a question says otherwise, assume a standard supervised setup. Some questions
have more than one correct option; select every option you believe is correct.

---

## Q1. A dataset has 1% positives. A model predicts "negative" for every record. What is its accuracy?

- **A.** About 50%, because there are two classes.
- **B.** About 99%.
- **C.** 0%, because it never finds a positive.
- **D.** Undefined, because accuracy needs at least one predicted positive.

## Q2. With 1% positives, which of these are informative ways to evaluate the model? Select all that apply.

- **A.** Accuracy at the default 0.5 threshold.
- **B.** Area under the precision-recall curve.
- **C.** Precision and recall at the number of alerts the reviewers can actually handle.
- **D.** Log-loss computed on the negative class only.

## Q3. A column is filled in *after* a record has been reviewed (for example, the review outcome). It is used as a training feature. What is the most likely result?

- **A.** The model underfits, because the column is mostly empty.
- **B.** Near-perfect offline metrics that do not hold up once the model runs on new,
  unreviewed records.
- **C.** No effect — tree-based models are not affected by such columns.
- **D.** Training fails with an error.

## Q4. The positive rate rises over the last month of the data. Which validation split best estimates how the model will do next month?

- **A.** A uniformly random train/validation split.
- **B.** A stratified random split that preserves the positive rate.
- **C.** Train on the earlier period, validate on the later period.
- **D.** Leave-one-out cross-validation.

## Q5. Reviewers can handle 200 flagged records per day. How should the operating threshold be chosen?

- **A.** Use the default probability threshold of 0.5.
- **B.** Pick the threshold that maximises accuracy on the validation set.
- **C.** Rank records by score each day, flag the top 200, and report precision (and
  recall) at that cutoff.
- **D.** Pick the threshold where precision equals recall.
