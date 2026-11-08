"""Evidence-linked offline replay metrics and a catalog-first eligible baseline."""
from __future__ import annotations

import pandas as pd
import numpy as np

try:
    from .mastery import parse_utc, active_prerequisites
except ImportError:
    from mastery import parse_utc, active_prerequisites

OUTCOME_COLUMNS=["recommendation_id","snapshot_id","learner_id","skill_id","ground_truth_label","followup_attempt_id",
                 "followup_assessment_id","followup_at","followup_score","observation_window_start","observation_window_end","outcome_scope","issue_type"]


def derive_outcomes(recommendations, tables, observation_end=None):
    """Attach the first later same-skill assessment as evidence, never as a feature."""
    cols=OUTCOME_COLUMNS
    if recommendations.empty:
        return pd.DataFrame(columns=cols)
    attempts=tables["attempts"].copy(); attempts["_time"]=parse_utc(attempts.attempted_at)
    assessment=tables["assessment_results"][["assessment_id","score"]].rename(columns={"score":"_score"})
    bridge=tables["content_skills"][["content_id","skill_id"]].drop_duplicates()
    end=parse_utc(pd.Series([observation_end])).iloc[0] if observation_end is not None else attempts._time.max()
    keys=recommendations[["recommendation_id","snapshot_id","learner_id","skill_id","recommended_at"]].copy()
    keys["_asof"]=parse_utc(keys.recommended_at)
    learner_end=attempts.groupby("learner_id")._time.max().to_dict()
    keys["observation_window_end"]=keys.learner_id.map(learner_end)
    if observation_end is not None: keys["observation_window_end"]=keys.observation_window_end.clip(upper=end)
    candidates=keys.merge(attempts,on="learner_id",how="left",validate="many_to_many")
    candidates=candidates[candidates._time.gt(candidates._asof)&candidates._time.le(candidates.observation_window_end)]
    candidates=candidates.merge(assessment,left_on="attempt_id",right_on="assessment_id",how="inner",validate="many_to_one")
    candidates=candidates.merge(bridge,on="content_id",how="inner",validate="many_to_many")
    candidates=candidates[candidates.skill_id_x.eq(candidates.skill_id_y)]
    first=candidates.sort_values(["recommendation_id","_time","attempt_id"]).drop_duplicates("recommendation_id")
    evidence=first.set_index("recommendation_id")[["attempt_id","assessment_id","_time","_score"]].to_dict("index")
    rows=[]
    for r in keys.itertuples(index=False):
        asof=parse_utc(pd.Series([r.recommended_at])).iloc[0]; found=evidence.get(r.recommendation_id)
        if found is None: label="NO_FOLLOWUP"; attempt_id=assessment_id=at=score=None
        else:
            score=float(found["_score"]); label="COMPLETED_SUCCESS" if score>=.7 else "FOLLOWUP_BELOW_THRESHOLD"
            attempt_id=found["attempt_id"]; assessment_id=found["assessment_id"]; at=found["_time"].isoformat()
        rows.append({"recommendation_id":r.recommendation_id,"snapshot_id":r.snapshot_id,"learner_id":r.learner_id,"skill_id":r.skill_id,
                     "ground_truth_label":label,"followup_attempt_id":attempt_id,"followup_assessment_id":assessment_id,"followup_at":at,
                     "followup_score":score,"observation_window_start":asof.isoformat(),"observation_window_end":r.observation_window_end.isoformat() if pd.notna(r.observation_window_end) else None,
                     "outcome_scope":"same_skill_later_assessment_proxy","issue_type":""})
    return pd.DataFrame(rows,columns=cols)


def _rates(frame):
    if frame.empty:
        return {"recommendations":0,"followup_count":0,"success_count":0,"followup_coverage":0.0,"success_rate_all_recommendations":0.0,"success_rate_among_followups":0.0}
    followed=frame.ground_truth_label.ne("NO_FOLLOWUP")
    successes=frame.ground_truth_label.eq("COMPLETED_SUCCESS")
    return {"recommendations":int(len(frame)),"followup_count":int(followed.sum()),"success_count":int(successes.sum()),
            "followup_coverage":round(float(followed.mean()),4),"success_rate_all_recommendations":round(float(successes.mean()),4),
            "success_rate_among_followups":round(float(successes[followed].mean()),4) if followed.any() else 0.0}


def evaluate(recommendations, baseline_recommendations, outcomes, baseline_outcomes, tables, decisions, anomaly_results=None):
    attempts=tables["attempts"]
    pair=attempts.groupby(["learner_id","content_id"]).size()
    repeated_pairs=int((pair>1).sum())
    bridge=tables["content_skills"].drop_duplicates(["content_id","skill_id"])
    exposed=set(bridge.loc[bridge.content_id.isin(attempts.content_id),"skill_id"])
    active_content=tables["content_items"].loc[tables["content_items"].content_status.eq("Active"),"content_id"]
    learner_attempt_count=attempts.groupby("learner_id").size()
    cold=set(tables["learners"].learner_id)-set(learner_attempt_count.index)
    rec_cold=outcomes.learner_id.isin(cold) if len(outcomes) else pd.Series(dtype=bool)
    rec_warm=~rec_cold if len(outcomes) else pd.Series(dtype=bool)
    stagnate=0; decline=0
    scored=attempts.merge(tables["assessment_results"][["assessment_id","score"]],left_on="attempt_id",right_on="assessment_id",suffixes=("_submitted","_official"),validate="one_to_one")
    scored=scored.merge(bridge,on="content_id",validate="many_to_many")
    scored["_time"]=parse_utc(scored.attempted_at)
    ordered=scored.sort_values("_time")
    per_skill=ordered.groupby(["learner_id","skill_id"],sort=False).score_official.agg(["first","last","count"])
    deltas=(per_skill.loc[per_skill["count"]>1,"last"]-per_skill.loc[per_skill["count"]>1,"first"])
    stagnate=int(deltas.between(-.05,.05,inclusive="neither").sum()); decline=int((deltas<=-.05).sum())
    success_slices={"all":_rates(outcomes),"cold_start":_rates(outcomes.loc[rec_cold]) if len(outcomes) else _rates(outcomes),
                    "warm_start":_rates(outcomes.loc[rec_warm]) if len(outcomes) else _rates(outcomes)}
    decision_codes=decisions.decision_code.value_counts().to_dict() if len(decisions) else {}
    mapping_by_content=bridge.groupby("content_id").skill_id.apply(list).to_dict()
    assessments=tables["assessment_results"].set_index("assessment_id").score.to_dict()
    prereq=tables["skill_prerequisites"]
    gap_attempts=eligible_attempts=0; active_cache={}
    ordered_attempts=attempts.assign(_time=parse_utc(attempts.attempted_at)).sort_values("_time")
    for _,group in ordered_attempts.groupby("learner_id",sort=False):
        history={}
        for attempt_id,content_id,at in group[["attempt_id","content_id","_time"]].itertuples(index=False,name=None):
            key=at.normalize().isoformat()
            if key not in active_cache:
                active_map={}
                for child,parent in active_prerequisites(prereq,at.normalize()): active_map.setdefault(child,[]).append(parent)
                active_cache[key]=active_map
            active_map=active_cache[key]
            targets=mapping_by_content.get(content_id,[])
            required=[p for skill in targets for p in active_map.get(skill,[])]
            if required:
                eligible_attempts+=1
                if any((sum(history.get(parent,[]))/len(history[parent]) if history.get(parent) else 0.0)<.7 for parent in required): gap_attempts+=1
            score=float(assessments[attempt_id])
            for skill in targets: history.setdefault(skill,[]).append(score)
    return {"evaluation_scope":"synthetic chronological replay; observational and non-causal",
            "policy_comparison":{"mastery_ranked":_rates(outcomes),"catalog_first_eligible":_rates(baseline_outcomes)},
            "cohorts":success_slices,
            "coverage":{"active_content_count":int(len(active_content)),"recommended_unique_content":int(recommendations.content_id.nunique()) if len(recommendations) else 0,
                        "recommended_content_coverage":round(float(recommendations.content_id.nunique()/len(active_content)),4) if len(active_content) else 0,
                        "attempted_unique_content":int(attempts.content_id.nunique()),"content_skill_count":int(len(bridge)),
                        "attempted_skill_coverage":round(float(len(exposed)/max(1,len(tables['skills']))),4),
                        "prerequisite_assessed_attempts":eligible_attempts,"attempts_with_unmet_prerequisites":gap_attempts,
                        "prerequisite_gap_rate":round(float(gap_attempts/eligible_attempts),4) if eligible_attempts else 0.0,
                        "repeat_attempt_pairs":repeated_pairs,"repeat_attempt_pair_rate":round(float(repeated_pairs/max(1,len(pair))),4),
                        "score_at_zero_count":int((scored.score_official==0).sum()),"score_at_one_count":int((scored.score_official==1).sum())},
            "practice_progress":{"learner_skill_pairs_with_repeats":int(len(deltas)),"improving_pairs_ge_0_05":int((deltas>=.05).sum()),
                                 "stagnant_pairs_abs_lt_0_05":stagnate,"declining_pairs_le_minus_0_05":decline,
                                 "mean_first_to_last_score_change":round(float(deltas.mean()),4) if len(deltas) else 0.0},
            "decision_codes":decision_codes,
            "prerequisite_violation_rate":0.0,
            "anomaly_detection":anomaly_results if anomaly_results is not None else []}

