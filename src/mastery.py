"""Time-bounded, evidence-linked mastery calculations."""
from __future__ import annotations

import pandas as pd

MASTERY_TOLERANCE = 0.00005
RULE_VERSION = "mastery-2.1"


def parse_utc(values):
    """Parse mixed ISO timestamp forms as UTC; malformed input becomes NaT."""
    return pd.to_datetime(values, format="mixed", utc=True, errors="coerce")


def compute_mastery(tables, learner_id, as_of):
    """Return per-skill means and source IDs for one learner at an explicit cutoff.

    AssessmentResult.score is authoritative. A score is attributed once to each
    distinct ContentSkill mapping of its content. Bridge expansion therefore
    changes skill coverage but never multiplies the event count for a skill.
    """
    cutoff = pd.to_datetime(as_of, format="mixed", utc=True, errors="coerce")
    if pd.isna(cutoff):
        raise ValueError(f"invalid as_of timestamp: {as_of!r}")
    expanded=expand_evidence(tables)
    return summarize_evidence(expanded.loc[expanded.learner_id.eq(learner_id)],cutoff)


def expand_evidence(tables):
    """Join official assessment events to the true N:M skill bridge once."""
    attempts=tables["attempts"].copy()
    attempts["_time"]=parse_utc(attempts.attempted_at)
    scores = tables["assessment_results"][["assessment_id", "score"]]
    bridge = tables["content_skills"][["content_id", "skill_id"]].drop_duplicates()
    evidence = attempts.merge(scores, left_on="attempt_id", right_on="assessment_id", how="inner", validate="one_to_one", suffixes=("_attempt", "_assessment"))
    evidence = evidence.merge(bridge, on="content_id", how="inner", validate="many_to_many")
    return evidence.loc[evidence._time.notna()]


def summarize_evidence(evidence, as_of):
    """Aggregate expanded evidence at one UTC cutoff, retaining exact source IDs."""
    cutoff=pd.to_datetime(as_of,format="mixed",utc=True,errors="coerce")
    if pd.isna(cutoff): return {}
    evidence=evidence.loc[evidence._time.le(cutoff),["_time","attempt_id","assessment_id","skill_id","score_assessment"]]
    if evidence.empty: return {}
    evidence=evidence.sort_values(["_time","attempt_id","skill_id"],kind="mergesort")
    accum={}
    for at,attempt_id,assessment_id,skill,score in evidence.itertuples(index=False,name=None):
        row=accum.setdefault(skill,{"sum":0.0,"count":0,"attempt_ids":[],"assessment_ids":[]})
        row["sum"]+=float(score); row["count"]+=1
        row["attempt_ids"].append(str(attempt_id)); row["assessment_ids"].append(str(assessment_id))
    result={skill:{"mastery":row["sum"]/row["count"],"attempt_ids":row["attempt_ids"],
                   "assessment_ids":row["assessment_ids"],"cutoff_at":cutoff.isoformat()}
            for skill,row in accum.items()}
    return result


def active_prerequisites(prerequisites, as_of):
    """Return direct prerequisite edges active on [effective_from, effective_to)."""
    cutoff = pd.to_datetime(as_of, format="mixed", utc=True, errors="coerce")
    if pd.isna(cutoff):
        return []
    start = parse_utc(prerequisites.effective_from)
    end = parse_utc(prerequisites.effective_to.replace("", pd.NA))
    active = start.le(cutoff) & (end.isna() | end.gt(cutoff))
    return list(zip(prerequisites.loc[active, "skill_id"], prerequisites.loc[active, "prerequisite_skill_id"]))
