# YottaFlex Learning Recommender

A deterministic, explainable synthetic learning-path workflow. All generated records are synthetic; the offline outcome replay is observational and does not establish causal learning benefit.

## Quick start

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python src\pipeline.py --seed 20261022
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python src/pipeline.py --seed 20261022
```

Add `--full` for 10,000 learners, 500 skills, 2,000 content items, and exactly 500,000 attempts. Add `--output-dir PATH` to choose the snapshot root (default: `data/runs`). Every run is staged, validated, then published as an immutable snapshot directory; the prior successful snapshot is preserved. `data/runs/current_run.json` points to the current snapshot. CSV, JSON Lines, a populated SQLite database, the manifest, execution record, and evaluation outputs are written with each snapshot.

Run focused checks with `python -m unittest discover -s tests -v`. Compare reproducibility by running `python tools/check_reproducibility.py --scale starter` or `--scale full`; the command makes two isolated runs and records row-count and SHA-256 equality in `docs/reproducibility_report.md`.

## Workflow

```text
master data + prerequisite DAG
              ↓ validation
attempts + official assessment events
              ↓ chronological 60/40 split
as-of mastery + effective prerequisite rules
              ↓ eligible content across all mapped skills
recommendations + path decisions + evidence events
              ↓ later same-skill holdout assessments
outcomes + policy comparison + anomaly checks
              ↓ staged validation and export
versioned CSV / JSONL / SQLite snapshot
```

`src/generator.py` creates master and event tables. `src/mastery.py` computes means from authoritative `AssessmentResult.score` at a learner and UTC cutoff. A score is attributed once to every distinct skill mapped to its content; the bridge expansion does not duplicate attempts within any single skill. `src/recommender.py` applies the decision rules. `src/validation.py` returns structured record-level issues and executes the five negative cases. `src/evaluation.py` computes evidence-linked outcomes and compares the ranking policy with a catalog-first policy over the same eligible content and holdout. `src/exports.py` writes LF CSVs, JSONL, the SQLite seed database, and portable hashes. `src/pipeline.py` coordinates the staged run.

## Rules and interpretation

- Mastery is the arithmetic mean of official assessment scores for a learner-skill, using only events at or before the recommendation timestamp. The stored estimate and exact contributing attempt and assessment IDs are independently reconciled.
- Active prerequisite intervals use `[effective_from, effective_to)`. Eligibility requires **all active direct parents** to have mastery of at least 0.70. Target skills below 0.80 are eligible. Cycles and self-edges fail validation.
- Learners are recommended activities mapped to skills in their assigned track. A multi-skill activity is eligible only when every mapped skill is in that track and otherwise eligible. The lowest-mastery covered skill is the recommendation focus; the explanation records all covered skills and their prerequisite evidence.
- Content difficulty follows the focus skill’s mastery band. If no exact difficulty exists among eligible items, the nearest available level is selected and the fallback is recorded in the reason code and explanation.
- Cold-start learners receive foundation activities. Inactive learners, prerequisite blocks, mastered targets, and empty catalogs produce explicit learner-decision codes and schema-correct empty recommendation tables.
- Generated learners follow varied prerequisite-respecting tracks, use multiple formats and difficulty levels, and include repeated content practice. Scores combine learner ability, item difficulty, practice count, and bounded seeded noise.
- Outcome labels identify the first later assessment on the recommendation’s focus skill: `COMPLETED_SUCCESS` at score >= 0.70, `FOLLOWUP_BELOW_THRESHOLD` below it, or `NO_FOLLOWUP`. The outcome row includes the actual attempt and assessment IDs, score, timestamp, and learner-specific observation window. Same-skill follow-up is a proxy; it does not prove the recommended content itself was completed. No-follow-up is unknown, not failure.
- Evaluation reports follow-up coverage and rates by cold/warm cohort, a catalog-first baseline, repeat practice and progress, score boundaries, skill/content coverage, prerequisite-gap exposure, and anomaly detection. Rates are synthetic replay metrics, not accuracy or causal impact.
- Anomaly examples and expected labels live under `ground_truth`; they are never recommendation features. The pipeline injects one fault at a time into isolated copies and checks the production validator.

## Outputs

Each `data/runs/<run-id>/` snapshot contains:

- `master/`: learners, courses, skills, effective-dated prerequisite edges, content, and the ContentSkill bridge.
- `transactions/`: attempts and official assessment results.
- `outputs/`: ranked and baseline recommendations, learning paths, learner decisions, domain events, validation summary, and source manifest.
- `ground_truth/`: evidence-linked outcomes, anomaly cases, and detection results.
- `learning_recommender.sqlite`: populated relational seed with foreign-key and score reconciliation checks.
- Matching `.jsonl` exports beside each CSV export.

The structured field specification is in [DATA_DICTIONARY.md](DATA_DICTIONARY.md). The relational DDL is [sql/schema.sql](sql/schema.sql). Runtime `STARTED`/`FAILED`/`COMPLETE` records are stored under `data/runs/executions/` separately from deterministic dataset checksums.

## Known limits

The generator is a controlled synthetic replay, not an adaptive production service. The curriculum graph has five branching domains; thresholds are documented fixed rules. Prerequisite eligibility uses direct parents rather than full transitive closure, as explicitly selected for this project. Outputs are snapshots; production ingestion, user privacy controls, instructor overrides, and real-world validation require separate design and authorized data.
