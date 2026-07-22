# Contributing a problem

Planning-stage guide. Dataset production is handled separately — this
guide defines the contract a problem must meet so authoring stays smooth later.

## Ground rules

1. **Copy the template.** `cp -r _template <track>-<slug>-<nnn>` (tracks and ID scheme
   in `README.md`). Every file in the template exists for a reason; fill or
   consciously empty each one.
2. **The manifest is the interface.** `problem.yaml` is what the platform reads —
   candidate-visible paths, resource limits, environment needs, LLM requirement.
   If your problem needs something the manifest can't express, raise it as a schema
   change first; don't work around it.
3. **Visibility is a hard contract.** Anything not under `candidate_paths` never
   reaches a candidate. Statement (`problem.md`), starter code, and the data
   dictionary are candidate-facing; rubric, solution, and generators are not. Write
   each file for its audience. Candidate-facing files carry **zero meta content**:
   no interviewer annotations ("candidate-facing", grading notes) and no platform
   mechanics (submit/snapshot instructions — the portal covers those). Candidates
   read under time pressure: keep statements minimal, one example per concept.
4. **No problem without a rubric.** `rubric.md` must ship with the problem: scoring
   grid, planted pitfalls with the signal they carry, expected trajectory, follow-up
   questions. A problem the rubric can't score doesn't get registered.
5. **Fit the box.** One candidate on 2 vCPU / 8 GB with ~5 GB workload headroom.
   Declare `expected_peak_ram_gb` honestly; stay within the stated `duration_minutes`.
6. **Datasets (deferred).** Follow the template's shape — a seeded, committed
   generator whose *output* (never the generator) ships to candidates; generated files
   are gitignored. Detailed dataset standards will be defined separately; don't block
   problem design on them.

## Quality bar

- **Layered difficulty:** a core task most qualified candidates finish, plus clearly
  marked stretch parts that separate levels.
- **Judgment over recall:** prefer "choose and defend" tasks over "implement from
  memory".
- **Realistic mess, documented:** every planted defect appears in the rubric's
  pitfall table. Undocumented traps are bugs, not features.
- **Domain color is skin-deep**: keep domain color in the *statement*, not the
  *skill*, so a problem generalizes to another AI/ML domain by reskinning.

## Review checklist (PR)

- [ ] Manifest complete and consistent with the files present
- [ ] Statement readable standalone by a candidate (no interviewer context leaked)
- [ ] Rubric: grid + pitfalls + trajectory + follow-ups
- [ ] Reference solution at "strong" rubric level (or an explicit TODO with owner)
- [ ] Dogfooded end-to-end within the stated time box
- [ ] One reviewer solved it cold
- [ ] Registry entry added with `status: draft`
