# Data dictionary

All IDs are immutable text keys. Timestamps use ISO-8601 with UTC offsets. Scores and mastery are unitless values from 0 to 1. Empty `effective_to` means the relationship remains current.

| Entity / file | Primary key | Fields and validation | Relationships |
|---|---|---|---|
| Learner / `master/learners.csv` | `learner_id` (`LRN-######`) | `learner_name` required text; `experience_level` Beginner/Intermediate/Advanced; `learner_status` Active | 1:N Attempt, Recommendation, LearningPath |
| Course / `master/courses.csv` | `course_id` (`CRS-######`) | `course_name` required text; `course_status` Active | 1:N ContentItem |
| Skill / `master/skills.csv` | `skill_id` (`SKL-######`) | `skill_name` required text; `difficulty_level` Beginner/Intermediate/Advanced | N:M ContentItem through ContentSkill; recursive N:M prerequisite relation |
| SkillPrerequisite / `master/skill_prerequisites.csv` | `prerequisite_id` (`PRQ-######`) | `skill_id`, `prerequisite_skill_id` required Skill FKs and must differ; `effective_from` required date; `effective_to` optional date >= start | Each row links one dependent skill to one prerequisite; each Skill may have many |
| ContentItem / `master/content_items.csv` | `content_id` (`CNT-######`) | `course_id` required Course FK; title required; type Video/PDF/Quiz/Exercise/Project; difficulty Beginner/Intermediate/Advanced; duration positive minutes; status Active | N:1 Course; N:M Skill through ContentSkill |
| ContentSkill / `master/content_skills.csv` | `content_skill_id` (`CSM-######`) | Content and Skill FKs required; each pair unique | Bridge table, N:M |
| Attempt / `transactions/attempts.csv` | `attempt_id` (`ATT-<learner-id>-######`) | Learner and Content FKs; `attempted_at` required ISO timestamp; score [0,1]; positive per-learner attempt number, unique with learner | N:1 Learner, N:1 Content; 1:1 AssessmentResult in generated data |
| AssessmentResult / `transactions/assessment_results.csv` | `assessment_id` (same ID as originating Attempt) | Attempt FK; score [0,1]; assessment type ActivityScore | Attempt 1:1 AssessmentResult |
| LearningPath / `outputs/learning_paths.csv` | Composite (`learning_path_id`, `sequence_no`) | path format `PATH-2026-######`; positive sequence; status Active; recommendation FK | Learner 1:N paths; path 1:N ordered recommendations |
| Recommendation / `outputs/recommendations.csv` | `recommendation_id` (`REC-#########`) | Learner, content, skill FKs; ISO recommendation timestamp; positive rank; reason code; mastery [0,1]; status Recommended | Learner 1:N; Content 1:N; LearningPath references each recommendation |
| Recommendation outcome / `ground_truth/recommendation_outcomes.csv` | `recommendation_id` (Recommendation FK) | `ground_truth_label`: COMPLETED_SUCCESS when a subsequent attempt on its skill scores >=0.70; FOLLOWUP_BELOW_THRESHOLD for a lower later score; NO_FOLLOWUP when no later attempt is observed; `issue_type` empty for baseline outcomes | Recommendation 1:0..1 observed outcome |

## Outcome and anomaly labels

`recommendation_outcomes.csv` uses the later event history and labels observed success only when a subsequent matching activity score is at least 0.70. `anomaly_cases.csv` contains expected labels for five deliberately invalid scenarios and is not an input feature table. Baseline tables contain no injected invalid rows.

`anomaly_examples.csv` provides one concrete malformed JSON payload per anomaly, with `case_id`, `issue_type`, `entity_id`, `payload_json`, and `ground_truth_label`. These fixtures are test/evaluation examples and must stay outside baseline recommendation features.

## Validation expectations

Primary keys and bridge pairs are unique; all foreign keys resolve; score ranges and allowed enums are valid; IDs match their documented pattern; timestamps are ISO-8601; and event order is nondecreasing per learner. Prerequisites must be satisfied before recommendation (mastery >= 0.70). Mastery must exclude attempts after recommendation time.
