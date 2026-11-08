# Data dictionary and validation contract

CSV and JSONL are UTF-8 with LF line endings. IDs are immutable within a `snapshot_id`; ISO timestamps include UTC offset. Score/mastery units are probabilities on `[0,1]`. Nullable values are called out as optional; blank CSV values represent null. Effective intervals are start-inclusive/end-exclusive.

## Core entities

| Entity / field | Type; required; allowed values / unit | Key and validation |
|---|---|---|
| **Learner** — `learner_id` | string, required | PK, `LRN-######` |
| `learner_name` | string, required | nonempty |
| `track_id` | string, required | `TRK-##`; generated track |
| `experience_level` | enum, required | Beginner / Intermediate / Advanced |
| `learner_status` | enum, required | Active / Inactive; only Active learners receive recommendations |
| **Course** — `course_id` | string, required | PK, `CRS-######` |
| `course_name` | string, required | nonempty |
| `course_status` | enum, required | Active / Inactive; recommendation content must belong to Active course |
| **Skill** — `skill_id` | string, required | PK, `SKL-######` |
| `skill_name` | string, required | nonempty, unique in generated data |
| `domain` | enum/string, required | Python / Analytics / Databases / Statistics / AI |
| `difficulty_level` | enum, required | Beginner / Intermediate / Advanced |
| **SkillPrerequisite** — `prerequisite_id` | string, required | PK, `PRQ-######` |
| `skill_id` | string, required | FK to Skill; dependent skill |
| `prerequisite_skill_id` | string, required | FK to Skill; must differ from `skill_id`; graph must be acyclic |
| `effective_from` | ISO date, required | edge starts at this UTC date, inclusive |
| `effective_to` | ISO date, optional | if present, strictly later than start; edge expires at this UTC date, exclusive |
| **ContentItem** — `content_id` | string, required | PK, `CNT-######` |
| `course_id` | string, required | FK to Course |
| `content_title` | string, required | nonempty |
| `content_type` | enum, required | Video / PDF / Quiz / Exercise / Project |
| `difficulty_level` | enum, required | Beginner / Intermediate / Advanced |
| `duration_minutes` | integer, required | positive minutes |
| `content_status` | enum, required | Active / Inactive |
| **ContentSkill** — `content_skill_id` | string, required | PK, `CSM-######` |
| `content_id` | string, required | FK to ContentItem |
| `skill_id` | string, required | FK to Skill; unique with `content_id`; every content item must map to at least one skill |
| **Attempt** — `attempt_id` | string, required | PK, `ATT-LRN-######-######` |
| `learner_id` | string, required | FK to Learner |
| `content_id` | string, required | FK to ContentItem |
| `attempted_at` | ISO timestamp, required | UTC-normalized; chronological by increasing `attempt_number` |
| `score` | decimal, required | `[0,1]`; submitted score reconciles to official assessment score |
| `attempt_number` | integer, required | positive, unique within learner |
| `attempt_kind` | enum, required | INITIAL for first learner-content event; RETAKE for later event on that content |
| **AssessmentResult** — `assessment_id` | string, required | PK and FK to Attempt; intentionally shares `attempt_id`, giving a 1:1 relationship in generated data |
| `score` | decimal, required | `[0,1]`; authoritative score used for mastery and evaluation |
| `assessment_type` | enum, required | ActivityScore |

## Decisions, paths, events, and outcomes

| Entity / field | Type; required; allowed values / unit | Key and validation |
|---|---|---|
| **Recommendation** — `recommendation_id` | string, required | PK within snapshot, `REC-#########` |
| `snapshot_id` | string, required | immutable source/rule snapshot namespace |
| `learner_id` | string, required | FK to active Learner |
| `content_id` | string, required | FK to active ContentItem whose Course is Active |
| `skill_id` | string, required | focus Skill, mapped by the selected ContentSkill bridge |
| `mapped_skill_ids` | JSON array string, required | all distinct skills covered by selected content; must equal the current bridge |
| `recommended_at` | ISO timestamp, required | decision cutoff in UTC |
| `rank` | integer, required | positive; rank order within learner path |
| `reason_code` | enum/string, required | COLD_START_FOUNDATION / PREREQUISITES_MET_LOW_MASTERY / MASTERY_REINFORCEMENT / corresponding `_DIFFICULTY_FALLBACK` suffix / BASELINE_CATALOG_FIRST |
| `mastery_at_recommendation` | decimal, required | `[0,1]`; reconciles to official score history at `recommended_at`, tolerance 0.00005 |
| `difficulty_target` | enum, required | mastery band: <0.50 Beginner; <0.70 Intermediate; otherwise Advanced |
| `difficulty_selected` | enum, required | selected ContentItem difficulty |
| `difficulty_fallback` | boolean, required | true exactly when selected level differs from target |
| `evidence_attempt_ids` | JSON string array, required | source attempts for focus skill at or before cutoff |
| `evidence_assessment_ids` | JSON string array, required | corresponding official score IDs |
| `explanation_json` | JSON object string, required | rule version, direct-parent policy, target/mastery thresholds, covered-skill mastery and prerequisites, difficulty choice, cutoff, and source IDs |
| `status` | enum, required | Recommended |
| **LearningPath** — `learning_path_id` | string, required | `PATH-2026-######`; one per learner per snapshot |
| `snapshot_id` | string, required | must match the referenced recommendation snapshot |
| `learner_id` | string, required | FK to Learner; must match recommendation owner |
| `sequence_no` | integer, required | positive, contiguous from 1; composite PK with path ID; equals recommendation rank |
| `recommendation_id` | string, required | FK to Recommendation |
| `content_id` | string, required | FK to ContentItem; must match recommendation content; no repeated content within one path |
| `created_at` | ISO timestamp, required | path decision time |
| `status` | enum, required | Active / Completed / Blocked / Archived |
| **LearnerDecision** — (`snapshot_id`, `learner_id`) | composite PK, required | exactly one explicit decision per learner per snapshot |
| `decision_at` | ISO timestamp, optional | null only where no history/decision time exists |
| `decision_code` | enum, required | INACTIVE_LEARNER / ALL_TARGETS_MASTERED / PREREQUISITE_BLOCKED / NO_ELIGIBLE_CONTENT / RECOMMENDATIONS_CREATED |
| `eligible_skill_count` | integer, required | zero or greater |
| `candidate_content_count` | integer, required | zero or greater |
| `reason_detail` | JSON/string, required | trace of blocked prerequisites or empty-candidate explanation |
| **DomainEvent** — `event_id` | string, required | PK; stable within snapshot |
| `snapshot_id` | string, required | event namespace |
| `entity_type`, `entity_id` | strings, required | entity and source identifier |
| `event_at` | ISO timestamp, optional | absent only for a learner with no decision history |
| `old_state`, `new_state` | strings, required | explicit lifecycle transition; initial old state is empty |
| `reason_code` | string, required | reason for transition |
| `evidence_json` | JSON object string, required | source evidence and decision details |
| **RecommendationOutcome** — `recommendation_id` | string, required | PK and FK to Recommendation; at most one evaluation label |
| `snapshot_id`, `learner_id`, `skill_id` | strings, required | source decision namespace and FKs |
| `ground_truth_label` | enum, required | COMPLETED_SUCCESS / FOLLOWUP_BELOW_THRESHOLD / NO_FOLLOWUP |
| `followup_attempt_id` | string, optional | FK to the actual later Attempt; null for NO_FOLLOWUP |
| `followup_assessment_id` | string, optional | FK to official score; null for NO_FOLLOWUP |
| `followup_at` | ISO timestamp, optional | actual follow-up event time |
| `followup_score` | decimal, optional | `[0,1]`, official assessment score |
| `observation_window_start`, `observation_window_end` | ISO timestamps, optional end | learner-specific holdout interval |
| `outcome_scope` | enum, required | `same_skill_later_assessment_proxy`; this does not assert the selected item itself was completed |
| `issue_type` | string, required | empty for baseline outcome rows |

## Cardinality, joins, and validation behavior

- Course 1:N ContentItem; Learner 1:N Attempt, Recommendation, LearningPath; Attempt 1:1 AssessmentResult in the generated dataset; Recommendation 1:0..1 RecommendationOutcome.
- ContentItem N:M Skill through unique ContentSkill rows. Skill prerequisites form an effective-dated self-relation. A bridge-expanded attempt contributes the same official score once to each mapped skill’s mastery; event and outcome denominators remain based on distinct Attempt/Recommendation IDs.
- Validation returns structured rows with entity, primary key, field, issue type, expected value, and observed value. It checks required nulls separately from FK membership, enums, ID patterns, event chronology, bridge cardinality, assessment score reconciliation, graph cycles/roots, effective intervals, as-of mastery/evidence, mapped-skill eligibility, lifecycle state, path ownership/sequence/loops, and decision/event keys.
- `ground_truth/anomaly_cases.csv` and `anomaly_results.csv` define and report the five injected exception classes. Fixture payloads and expected labels are not model features.
