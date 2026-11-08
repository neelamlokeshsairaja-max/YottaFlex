"""Explainable prerequisite-aware, difficulty-matched recommendation policy."""
from __future__ import annotations

import json
import heapq
import pandas as pd

try:
    from .mastery import expand_evidence, summarize_evidence, active_prerequisites, RULE_VERSION
except ImportError:
    from mastery import expand_evidence, summarize_evidence, active_prerequisites, RULE_VERSION

REC_COLUMNS=["recommendation_id","snapshot_id","learner_id","content_id","skill_id","mapped_skill_ids",
             "recommended_at","rank","reason_code","mastery_at_recommendation","difficulty_target",
             "difficulty_selected","difficulty_fallback","evidence_attempt_ids","evidence_assessment_ids",
             "explanation_json","status"]
PATH_COLUMNS=["learning_path_id","snapshot_id","learner_id","sequence_no","recommendation_id","content_id","created_at","status"]
DECISION_COLUMNS=["snapshot_id","learner_id","decision_at","decision_code","eligible_skill_count","candidate_content_count","reason_detail"]
EVENT_COLUMNS=["event_id","snapshot_id","entity_type","entity_id","event_at","old_state","new_state","reason_code","evidence_json"]


def _ts(value):
    return pd.to_datetime(value,format="mixed",utc=True,errors="coerce")


def recommend(tables, snapshot_id="snapshot"):
    """Return recommendations, ranked path steps, decisions and immutable events."""
    learners=tables["learners"]; skills=tables["skills"]; content=tables["content_items"]
    attempts=tables["attempts"].copy(); attempts["_time"]=_ts(attempts.attempted_at)
    groups={k:v.sort_values(["_time","attempt_number","attempt_id"]) for k,v in attempts.groupby("learner_id",sort=False)}
    expanded_evidence=expand_evidence(tables)
    evidence_groups={k:v for k,v in expanded_evidence.groupby("learner_id",sort=False)}
    mappings=tables["content_skills"][["content_id","skill_id"]].drop_duplicates()
    skills_by_content=mappings.groupby("content_id").skill_id.apply(lambda s:sorted(set(s))).to_dict()
    skill_sets_by_content={cid:frozenset(mapped) for cid,mapped in skills_by_content.items()}
    items_by_skill=mappings.groupby("skill_id").content_id.apply(lambda s:sorted(set(s))).to_dict()
    prereq=tables["skill_prerequisites"]
    skill_meta=skills.set_index("skill_id").to_dict("index")
    course_active=tables["courses"].set_index("course_id").course_status.eq("Active").to_dict()
    content_meta=content.set_index("content_id").to_dict("index")
    active_contents={cid for cid,m in content_meta.items() if m["content_status"]=="Active" and course_active.get(m["course_id"],False)}
    all_skill_ids=skills.skill_id.tolist()
    active_edge_cache={}
    level_rank={"Beginner":0,"Intermediate":1,"Advanced":2}
    recs=[]; baseline_recs=[]; path=[]; decisions=[]; events=[]; rid=0
    for learner in learners.itertuples(index=False):
        learner_id=learner.learner_id
        if learner.learner_status!="Active":
            decisions.append({"snapshot_id":snapshot_id,"learner_id":learner_id,"decision_at":"","decision_code":"INACTIVE_LEARNER","eligible_skill_count":0,"candidate_content_count":0,"reason_detail":"Learner lifecycle state is not Active."})
            events.append({"event_id":f"EVT-DEC-{int(learner_id[-6:]):06d}","snapshot_id":snapshot_id,"entity_type":"LearnerDecision","entity_id":learner_id,
                           "event_at":"","old_state":"","new_state":"INACTIVE_LEARNER","reason_code":"INACTIVE_LEARNER","evidence_json":"{}"})
            continue
        history=groups.get(learner_id,attempts.iloc[0:0])
        history_count=int(len(history)*.6)
        if len(history)>0: history_count=max(1,history_count)
        known=history.iloc[:history_count]
        as_of=known.iloc[-1]._time if len(known) else pd.Timestamp("2026-01-01",tz="UTC")
        as_of_text=as_of.isoformat()
        estimates=summarize_evidence(evidence_groups.get(learner_id,expanded_evidence.iloc[0:0]),as_of)
        mastery={sk:v["mastery"] for sk,v in estimates.items()}
        edge_key=as_of.normalize().value
        if edge_key not in active_edge_cache:
            active_edge_cache[edge_key]=active_prerequisites(prereq,as_of)
        active_edges=active_edge_cache[edge_key]
        req_map={}
        for child,parent in active_edges: req_map.setdefault(child,[]).append(parent)
        unmet=[]; eligible_skills=[]
        for sk in all_skill_ids:
            level=mastery.get(sk,0.0)
            if level>=.8: continue
            parents=req_map.get(sk,[])
            if any(mastery.get(parent,0.0)<.7 for parent in parents):
                unmet.append(sk); continue
            eligible_skills.append(sk)
        eligible_set=set(eligible_skills)
        candidates=[]
        considered=set()
        for sk in sorted(eligible_skills,key=lambda x:(mastery.get(x,0.0),x)):
            for cid in items_by_skill.get(sk,[]):
                if cid in considered or cid not in active_contents: continue
                mapped=skills_by_content.get(cid,[])
                # A multi-skill item is eligible only if every covered skill is eligible.
                if not mapped or not skill_sets_by_content[cid].issubset(eligible_set): continue
                considered.add(cid)
                focus=min(mapped,key=lambda x:(mastery.get(x,0.0),x))
                target="Beginner" if mastery.get(focus,0)<.5 else ("Intermediate" if mastery.get(focus,0)<.7 else "Advanced")
                selected=content_meta[cid]["difficulty_level"]
                fallback=selected!=target
                candidates.append((mastery.get(focus,0.0),focus,cid,mapped,target,selected,fallback))
        candidate_key=lambda x:(x[0],x[1],x[2])
        if not candidates:
            all_mastered=all(mastery.get(sk,0.0)>=.8 for sk in skills.skill_id)
            if all_mastered: code="ALL_TARGETS_MASTERED"
            elif not eligible_skills and unmet: code="PREREQUISITE_BLOCKED"
            else: code="NO_ELIGIBLE_CONTENT"
            detail={"unmet_prerequisite_skill_ids":sorted(unmet),"inactive_or_unmapped_content_count":len(content)-len(active_contents)}
            decisions.append({"snapshot_id":snapshot_id,"learner_id":learner_id,"decision_at":as_of_text,"decision_code":code,"eligible_skill_count":len(eligible_skills),"candidate_content_count":0,"reason_detail":json.dumps(detail,sort_keys=True)})
            events.append({"event_id":f"EVT-DEC-{int(learner_id[-6:]):06d}","snapshot_id":snapshot_id,"entity_type":"LearnerDecision","entity_id":learner_id,
                           "event_at":as_of_text,"old_state":"","new_state":code,"reason_code":code,"evidence_json":json.dumps(detail,sort_keys=True)})
            continue
        base=min(candidates,key=lambda x:(x[2],x[1]))
        bm,bs,bc,bmapped,btarget,bselected,bfallback=base
        bev=estimates.get(bs,{"mastery":0.0,"attempt_ids":[],"assessment_ids":[]})
        baseline_recs.append({"recommendation_id":f"BASE-{int(learner_id[-6:]):06d}","snapshot_id":snapshot_id,"learner_id":learner_id,
                              "content_id":bc,"skill_id":bs,"mapped_skill_ids":json.dumps(bmapped),"recommended_at":as_of_text,"rank":1,
                              "reason_code":"BASELINE_CATALOG_FIRST","mastery_at_recommendation":round(bm,8),"difficulty_target":btarget,
                              "difficulty_selected":bselected,"difficulty_fallback":bfallback,"evidence_attempt_ids":json.dumps(bev["attempt_ids"]),
                              "evidence_assessment_ids":json.dumps(bev["assessment_ids"]),"explanation_json":json.dumps({"policy":"catalog_first_eligible","covered_skill_ids":bmapped,
                                  "history_cutoff_at":as_of_text,"source_attempt_ids":bev["attempt_ids"],"source_assessment_ids":bev["assessment_ids"]},sort_keys=True),"status":"Recommended"})
        path_id=f"PATH-2026-{int(learner_id[-6:]):06d}"
        for rank,candidate in enumerate(heapq.nsmallest(3,candidates,key=candidate_key),1):
            mastery_value,focus,cid,mapped,target,selected,fallback=candidate
            reason="COLD_START_FOUNDATION" if not len(known) else ("MASTERY_REINFORCEMENT" if mastery_value>=.7 else "PREREQUISITES_MET_LOW_MASTERY")
            if fallback: reason += "_DIFFICULTY_FALLBACK"
            focus_ev=estimates.get(focus,{"mastery":0.0,"attempt_ids":[],"assessment_ids":[],"cutoff_at":as_of_text})
            evidence={"rule_version":RULE_VERSION,"direct_parent_policy":"all active direct parents require mastery >= 0.70",
                      "mastery_threshold":.8,"prerequisite_threshold":.7,"focus_skill_id":focus,
                      "covered_skill_ids":mapped,"mastery_by_covered_skill":{s:round(mastery.get(s,0.0),8) for s in mapped},
                      "prerequisites_by_covered_skill":{s:{p:round(mastery.get(p,0.0),8) for p in req_map.get(s,[])} for s in mapped},
                      "difficulty_target":target,"difficulty_selected":selected,"difficulty_fallback":fallback,
                      "history_cutoff_at":as_of_text,"source_attempt_ids":focus_ev["attempt_ids"],
                      "source_assessment_ids":focus_ev["assessment_ids"]}
            rid+=1; rec_id=f"REC-{rid:09d}"
            rec={"recommendation_id":rec_id,"snapshot_id":snapshot_id,"learner_id":learner_id,"content_id":cid,"skill_id":focus,
                 "mapped_skill_ids":json.dumps(mapped),"recommended_at":as_of_text,"rank":rank,"reason_code":reason,
                 "mastery_at_recommendation":round(mastery_value,8),"difficulty_target":target,"difficulty_selected":selected,
                 "difficulty_fallback":fallback,"evidence_attempt_ids":json.dumps(focus_ev["attempt_ids"]),
                 "evidence_assessment_ids":json.dumps(focus_ev["assessment_ids"]),"explanation_json":json.dumps(evidence,sort_keys=True),"status":"Recommended"}
            recs.append(rec)
            path.append({"learning_path_id":path_id,"snapshot_id":snapshot_id,"learner_id":learner_id,"sequence_no":rank,
                         "recommendation_id":rec_id,"content_id":cid,"created_at":as_of_text,"status":"Active"})
            events.append({"event_id":f"EVT-PATH-{int(learner_id[-6:]):06d}-{rank:02d}","snapshot_id":snapshot_id,"entity_type":"LearningPath",
                           "entity_id":path_id,"event_at":as_of_text,"old_state":"","new_state":"Active","reason_code":"PATH_CREATED",
                           "evidence_json":json.dumps({"recommendation_id":rec_id,"sequence_no":rank,"content_id":cid},sort_keys=True)})
            events.append({"event_id":f"EVT-REC-{rid:09d}","snapshot_id":snapshot_id,"entity_type":"Recommendation","entity_id":rec_id,
                           "event_at":as_of_text,"old_state":"","new_state":"Recommended","reason_code":reason,
                           "evidence_json":json.dumps(evidence,sort_keys=True)})
        decisions.append({"snapshot_id":snapshot_id,"learner_id":learner_id,"decision_at":as_of_text,"decision_code":"RECOMMENDATIONS_CREATED",
                          "eligible_skill_count":len(eligible_skills),"candidate_content_count":len(candidates),"reason_detail":""})
        events.append({"event_id":f"EVT-DEC-{int(learner_id[-6:]):06d}","snapshot_id":snapshot_id,"entity_type":"LearnerDecision","entity_id":learner_id,
                       "event_at":as_of_text,"old_state":"","new_state":"RECOMMENDATIONS_CREATED","reason_code":"RECOMMENDATIONS_CREATED","evidence_json":"{}"})
    return (pd.DataFrame(recs,columns=REC_COLUMNS),pd.DataFrame(path,columns=PATH_COLUMNS),
            pd.DataFrame(baseline_recs,columns=REC_COLUMNS),
            pd.DataFrame(decisions,columns=DECISION_COLUMNS),pd.DataFrame(events,columns=EVENT_COLUMNS))
