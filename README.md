# Learning activity recommender

This is a deterministic synthetic-data project. No learner information is sourced from real people.

## Run

From the project root, activate the existing environment and run:

```powershell
.\.venv\Scripts\Activate.ps1
python src\pipeline.py
```

For a fresh environment, install the two dependencies first with `python -m pip install -r requirements.txt`.

The starter run creates 100 learners, 20 skills, 50 activities and 760 attempts (five cold-start learners have no attempts). For the requested full volume (10,000 learners, 500 skills, 2,000 activities and 500,000 attempts), run:

```powershell
python src\pipeline.py --full
```

Use `--seed 20261022` to pin the random seed. The full run may take a few minutes and create sizable CSV files.

## What the pipeline does

1. Creates parent/master tables, then dependent attempt and assessment events.
2. Estimates mastery as the mean score for each learner and skill, using only attempts at or before the recommendation timestamp.
3. Recommends active content for skills below 0.80 mastery only when every direct prerequisite is at least 0.70. It uses a 60/40 chronological per-learner history/holdout split; cold-start learners receive foundation skills first. Activity difficulty is selected to match estimated mastery.
4. Writes reason codes, ranked learning paths, outcomes, validation metrics, and SHA-256 row/checksum manifest.
5. Keeps labeled exception definitions and concrete negative fixtures in `data/ground_truth/`; they do not contaminate baseline input data.

## Output layout

- `data/master/`: learners, courses, skills, prerequisite graph, content and content-skill bridge.
- `data/transactions/`: attempts and assessment results.
- `data/outputs/`: recommendations, learning paths, validation summary and source manifest.
- `data/ground_truth/`: recommendation outcomes, anomaly definitions and concrete malformed fixtures, isolated from baseline inputs.

## Key rules and limitations

- Score scale is 0.0–1.0. Mastery is a transparent arithmetic mean, not a psychometric model.
- Prerequisite edges form a simple directed chain. Content has one mapped skill in the starter synthetic dataset.
- Recommendations are generated at the timestamp marking the end of each learner's first 60% of attempts. A later attempt on the recommended skill is labeled `COMPLETED_SUCCESS` at score >= 0.70 or `FOLLOWUP_BELOW_THRESHOLD` below that; no later attempt is `NO_FOLLOWUP`, not proof of failure. The report includes follow-up coverage and success rates.
- `anomaly_cases.csv` documents exception rules; `anomaly_examples.csv` carries one concrete fixture per scenario. Both are separate from generated baseline records.
- For a stronger model evaluation, split by timestamp before model tuning. Do not randomly split attempts because that leaks future learner behavior into training.

## Data dictionary summary

See `DATA_DICTIONARY.md` for fields, constraints and relationship cardinalities. See `sql/schema.sql/schema.sql` for a relational schema sketch.
