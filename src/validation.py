"""Structured source, decision, graph and lifecycle validation."""
from __future__ import annotations

import json
import re
from collections import defaultdict

import pandas as pd

try:
    from .mastery import expand_evidence, summarize_evidence, parse_utc, active_prerequisites, MASTERY_TOLERANCE
except ImportError:
    from mastery import expand_evidence, summarize_evidence, parse_utc, active_prerequisites, MASTERY_TOLERANCE

REQUIRED={
 "learners":["learner_id","learner_name","track_id","experience_level","learner_status"],
 "courses":["course_id","course_name","course_status"],
 "skills":["skill_id","skill_name","track_id","domain","difficulty_level"],
 "skill_prerequisites":["prerequisite_id","skill_id","prerequisite_skill_id","effective_from"],
 "content_items":["content_id","course_id","content_title","content_type","difficulty_level","duration_minutes","content_status"],
 "content_skills":["content_skill_id","content_id","skill_id"],
 "attempts":["attempt_id","learner_id","content_id","attempted_at","score","attempt_number","attempt_kind"],
 "assessment_results":["assessment_id","score","assessment_type"]}
PKEY={"learners":"learner_id","courses":"course_id","skills":"skill_id","skill_prerequisites":"prerequisite_id","content_items":"content_id","content_skills":"content_skill_id","attempts":"attempt_id","assessment_results":"assessment_id"}
ID_PATTERNS={"learner_id":r"LRN-\d{6}","course_id":r"CRS-\d{6}","skill_id":r"SKL-\d{6}","prerequisite_id":r"PRQ-\d{6}","content_id":r"CNT-\d{6}","content_skill_id":r"CSM-\d{6}","attempt_id":r"ATT-LRN-\d{6}-\d{6}"}
ENUMS={("learners","experience_level"): {"Beginner","Intermediate","Advanced"},("learners","learner_status"): {"Active","Inactive"},
       ("courses","course_status"): {"Active","Inactive"},("skills","difficulty_level"): {"Beginner","Intermediate","Advanced"},
       ("content_items","content_type"): {"Video","PDF","Quiz","Exercise","Project"},
       ("content_items","difficulty_level"): {"Beginner","Intermediate","Advanced"},("content_items","content_status"): {"Active","Inactive"},
       ("attempts","attempt_kind"): {"INITIAL","RETAKE"},("assessment_results","assessment_type"): {"ActivityScore"}}


def _issue(entity, key, field, code, expected=None, observed=None):
    def clean(value):
        if value is None: return None
        if hasattr(value,"item"):
            try: value=value.item()
            except (ValueError,TypeError): pass
        if hasattr(value,"isoformat") and not isinstance(value,str):
            try: return value.isoformat()
            except (ValueError,TypeError): pass
        try:
            missing=pd.isna(value)
            if not hasattr(missing,"__len__") and bool(missing): return None
        except (TypeError,ValueError): pass
        return value if isinstance(value,(str,int,float,bool,list,dict)) else str(value)
    return {"entity":entity,"primary_key":clean(key),"field":field,"issue_type":code,
            "expected":clean(expected),"observed":clean(observed)}


def _graph_cycles(skills, prerequisites):
    graph=defaultdict(list)
    for r in prerequisites.itertuples(index=False):
        if pd.notna(r.skill_id) and pd.notna(r.prerequisite_skill_id): graph[str(r.prerequisite_skill_id)].append(str(r.skill_id))
    state={}; cyclic=set()
    def visit(node,stack):
        state[node]=1; stack.append(node)
        for nxt in graph[node]:
            if state.get(nxt,0)==0: visit(nxt,stack)
            elif state.get(nxt)==1:
                cyclic.update(stack[stack.index(nxt):])
        stack.pop(); state[node]=2
    for node in skills:
        if state.get(node,0)==0: visit(node,[])
    return sorted(cyclic)


def validate(tables, recommendations=None, paths=None, decisions=None, events=None, snapshot_id=None):
    issues=[]
    # Required columns and non-null checks precede every join, including empty frames.
    for name,required in REQUIRED.items():
        frame=tables.get(name)
        if frame is None:
            issues.append(_issue(name,None,"*","MISSING_ENTITY",required,None)); continue
        missing=set(required)-set(frame.columns)
        if missing:
            issues.append(_issue(name,None,"*","MISSING_COLUMNS",sorted(missing),list(frame.columns)))
            continue
        for col in required:
            nulls=frame[col].isna() | frame[col].astype("string").str.strip().eq("")
            for idx in frame.index[nulls][:100]:
                key=frame.loc[idx,PKEY[name]] if PKEY[name] in frame.columns else idx
                issues.append(_issue(name,key,col,"REQUIRED_VALUE_MISSING","non-null",None))
        key=PKEY[name]
        if frame[key].duplicated().any():
            for val in frame.loc[frame[key].duplicated(keep=False),key].astype(str).unique()[:100]: issues.append(_issue(name,val,key,"DUPLICATE_PRIMARY_KEY","unique",val))
        if key in ID_PATTERNS:
            bad=~frame[key].astype("string").str.fullmatch(ID_PATTERNS[key],na=False)
            for idx in frame.index[bad][:100]: issues.append(_issue(name,frame.loc[idx,key],key,"INVALID_ID_FORMAT",ID_PATTERNS[key],frame.loc[idx,key]))
        for (entity,col),allowed in ENUMS.items():
            if entity==name and col in frame:
                bad=~frame[col].isin(allowed)
                for idx in frame.index[bad][:100]: issues.append(_issue(name,frame.loc[idx,key],col,"INVALID_ENUM",sorted(allowed),frame.loc[idx,col]))
    if any(name not in tables or set(cols)-set(tables[name].columns) for name,cols in REQUIRED.items()):
        return issues
    def fk(child,col,parent,parent_key):
        frame=tables[child]; valid=set(tables[parent][parent_key].dropna())
        missing=frame[col].isna() | frame[col].astype("string").str.strip().eq("")
        invalid=~missing & ~frame[col].isin(valid)
        for idx in frame.index[missing][:100]: issues.append(_issue(child,frame.loc[idx,PKEY[child]],col,"REQUIRED_FK_MISSING",parent_key,frame.loc[idx,col]))
        for idx in frame.index[invalid][:100]: issues.append(_issue(child,frame.loc[idx,PKEY[child]],col,"INVALID_FOREIGN_KEY",parent_key,frame.loc[idx,col]))
    fk("content_items","course_id","courses","course_id")
    fk("content_skills","content_id","content_items","content_id"); fk("content_skills","skill_id","skills","skill_id")
    fk("attempts","learner_id","learners","learner_id"); fk("attempts","content_id","content_items","content_id")
    fk("skill_prerequisites","skill_id","skills","skill_id"); fk("skill_prerequisites","prerequisite_skill_id","skills","skill_id")
    fk("assessment_results","assessment_id","attempts","attempt_id")
    valid_tracks=set(tables["learners"].track_id.dropna())
    invalid_track=~tables["skills"].track_id.isin(valid_tracks)
    for idx in tables["skills"].index[invalid_track][:100]:
        row=tables["skills"].loc[idx]
        issues.append(_issue("skills",row.skill_id,"track_id","INVALID_FOREIGN_KEY","learner track ID",row.track_id))
    for name in ["attempts","assessment_results"]:
        frame=tables[name]
        scores=pd.to_numeric(frame.score,errors="coerce")
        for idx in frame.index[scores.isna() | ~scores.between(0,1)][:100]: issues.append(_issue(name,frame.loc[idx,PKEY[name]],"score","SCORE_OUT_OF_RANGE","0 <= score <= 1",frame.loc[idx,"score"]))
    duration=pd.to_numeric(tables["content_items"].duration_minutes,errors="coerce")
    for idx in tables["content_items"].index[duration.isna() | duration.le(0)][:100]: issues.append(_issue("content_items",tables["content_items"].loc[idx,"content_id"],"duration_minutes","INVALID_DURATION","> 0",tables["content_items"].loc[idx,"duration_minutes"]))
    parsed_dates={}
    for name,col in [("skill_prerequisites","effective_from"),("skill_prerequisites","effective_to"),("attempts","attempted_at")]:
        frame=tables[name]
        if col not in frame:
            if col=="effective_to": parsed=pd.Series(pd.NaT,index=frame.index,dtype="datetime64[ns, UTC]"); parsed_dates_value=parsed
            else:
                issues.append(_issue(name,None,col,"MISSING_COLUMN",col,None)); continue
            parsed_dates[(name,col)]=parsed_dates_value
            continue
        raw=frame[col]; parsed=parse_utc(raw.replace("",pd.NA))
        parsed_dates[(name,col)]=parsed
        bad=raw.notna() & raw.astype("string").str.strip().ne("") & parsed.isna()
        for idx in frame.index[bad][:100]: issues.append(_issue(name,frame.loc[idx,PKEY[name]],col,"INVALID_TIMESTAMP","ISO-8601 timestamp/date",raw.loc[idx]))
    prereqs=tables["skill_prerequisites"]
    starts=parsed_dates[("skill_prerequisites","effective_from")]; ends=parsed_dates[("skill_prerequisites","effective_to")]
    for pos,r in enumerate(prereqs.itertuples(index=False)):
        if pd.notna(r.skill_id) and pd.notna(r.prerequisite_skill_id) and r.skill_id==r.prerequisite_skill_id:
            issues.append(_issue("skill_prerequisites",r.prerequisite_id,"skill_id","SELF_PREREQUISITE","different skill IDs",r.skill_id))
        start=starts.iloc[pos]; end=ends.iloc[pos]
        if pd.notna(start) and pd.notna(end) and end<=start: issues.append(_issue("skill_prerequisites",r.prerequisite_id,"effective_to","INVALID_EFFECTIVE_INTERVAL","> effective_from",end))
    if prereqs.duplicated(["skill_id","prerequisite_skill_id","effective_from","effective_to"]).any(): issues.append(_issue("skill_prerequisites",None,"skill_id","DUPLICATE_PREREQUISITE_EDGE","unique effective edge",None))
    cycles=_graph_cycles(tables["skills"].skill_id.astype(str),prereqs)
    for node in cycles[:100]: issues.append(_issue("skill_prerequisites",node,"skill_id","PREREQUISITE_CYCLE","acyclic directed graph",node))
    roots=set(tables["skills"].skill_id)-set(prereqs.skill_id.dropna())
    if len(tables["skills"]) and not roots: issues.append(_issue("skills",None,"skill_id","NO_PREREQUISITE_ROOT","at least one root skill",None))
    pair_cols=["content_id","skill_id"]
    if tables["content_skills"].duplicated(pair_cols).any(): issues.append(_issue("content_skills",None,"content_id","DUPLICATE_CONTENT_SKILL","unique content-skill pair",None))
    mapped_content=set(tables["content_skills"].content_id.dropna())
    for cid in set(tables["content_items"].content_id.dropna())-mapped_content:
        issues.append(_issue("content_items",cid,"content_id","CONTENT_WITHOUT_SKILL_MAPPING","one or more skill mappings",cid))
    # Attempt chronology is based on parsed event times, not string lexical order.
    attempts=tables["attempts"].copy(); attempts["_time"]=parse_utc(attempts.attempted_at)
    for learner,group in attempts.dropna(subset=["_time"]).groupby("learner_id"):
        by_num=group.sort_values("attempt_number")
        if (by_num._time.diff().dropna()<pd.Timedelta(0)).any(): issues.append(_issue("attempts",learner,"attempted_at","ATTEMPT_ORDER_INVALID","nondecreasing by attempt_number",None))
    if attempts.duplicated(["learner_id","attempt_number"]).any(): issues.append(_issue("attempts",None,"attempt_number","DUPLICATE_ATTEMPT_NUMBER","unique within learner",None))
    attempt_numbers=pd.to_numeric(attempts.attempt_number,errors="coerce")
    for idx in attempts.index[attempt_numbers.isna() | attempt_numbers.le(0) | ((attempt_numbers%1)!=0)][:100]:
        issues.append(_issue("attempts",attempts.loc[idx,"attempt_id"],"attempt_number","INVALID_ATTEMPT_NUMBER","positive integer",attempts.loc[idx,"attempt_number"]))
    for _,group in attempts.sort_values(["learner_id","attempt_number"]).groupby("learner_id",sort=False):
        seen=set()
        for row in group.itertuples(index=False):
            repeated=row.content_id in seen
            expected="RETAKE" if repeated else "INITIAL"
            if row.attempt_kind!=expected: issues.append(_issue("attempts",row.attempt_id,"attempt_kind","ATTEMPT_KIND_MISMATCH",expected,row.attempt_kind))
            seen.add(row.content_id)
    # AssessmentResult is authoritative, and Attempt.score must reconcile exactly to its rounded source.
    assessment=tables["assessment_results"][["assessment_id","score"]].rename(columns={"score":"_assessment_score"})
    joined=tables["attempts"][["attempt_id","score"]].merge(assessment,left_on="attempt_id",right_on="assessment_id",how="left",validate="one_to_one")
    bad=joined._assessment_score.isna() | ((pd.to_numeric(joined.score,errors="coerce")-pd.to_numeric(joined._assessment_score,errors="coerce")).abs()>1e-9)
    for _,row in joined.loc[bad].head(100).iterrows(): issues.append(_issue("assessment_results",row.attempt_id,"score","ASSESSMENT_SCORE_MISMATCH",row.score,row._assessment_score))
    if set(tables["assessment_results"].assessment_id)!=set(tables["attempts"].attempt_id): issues.append(_issue("assessment_results",None,"assessment_id","ASSESSMENT_ATTEMPT_CARDINALITY","one-to-one",None))

    if recommendations is not None:
        for col in ["recommendation_id","learner_id","content_id","skill_id","recommended_at","rank","mastery_at_recommendation"]:
            if col not in recommendations:
                issues.append(_issue("recommendations",None,col,"MISSING_COLUMN",col,None))
        if all(c in recommendations for c in ["recommendation_id","learner_id","content_id","skill_id","recommended_at","rank","mastery_at_recommendation"]):
            if recommendations.recommendation_id.duplicated().any(): issues.append(_issue("recommendations",None,"recommendation_id","DUPLICATE_PRIMARY_KEY","unique",None))
            rec_bad=~recommendations.recommendation_id.astype("string").str.fullmatch(r"(?:REC-\d{9}|BASE-\d{6})",na=False)
            for idx in recommendations.index[rec_bad][:100]: issues.append(_issue("recommendations",recommendations.loc[idx,"recommendation_id"],"recommendation_id","INVALID_ID_FORMAT","REC-######### or BASE-######",recommendations.loc[idx,"recommendation_id"]))
            learners=set(tables["learners"].learner_id); contents=set(tables["content_items"].content_id); skills=set(tables["skills"].skill_id)
            expanded_evidence=expand_evidence(tables)
            evidence_by_learner={k:v for k,v in expanded_evidence.groupby("learner_id",sort=False)}
            mapping=tables["content_skills"].drop_duplicates(["content_id","skill_id"])
            skills_by_content=mapping.groupby("content_id",sort=False).skill_id.apply(lambda values:sorted(set(values))).to_dict()
            content_by_id=tables["content_items"].set_index("content_id").to_dict("index")
            course_by_id=tables["courses"].set_index("course_id").course_status.to_dict()
            learner_by_id=tables["learners"].set_index("learner_id").learner_status.to_dict()
            learner_track_by_id=tables["learners"].set_index("learner_id").track_id.to_dict()
            skill_track_by_id=tables["skills"].set_index("skill_id").track_id.to_dict()
            recommendation_times=parse_utc(recommendations.recommended_at).tolist()
            recommendation_masteries=pd.to_numeric(recommendations.mastery_at_recommendation,errors="coerce").tolist()
            recommendation_ranks=pd.to_numeric(recommendations["rank"],errors="coerce").tolist()
            mastery_cache={}; active_cache={}
            for rec_idx,r in enumerate(recommendations.itertuples(index=False)):
                if r.learner_id not in learners: issues.append(_issue("recommendations",r.recommendation_id,"learner_id","INVALID_FOREIGN_KEY","learner ID",r.learner_id)); continue
                if r.content_id not in contents: issues.append(_issue("recommendations",r.recommendation_id,"content_id","INVALID_FOREIGN_KEY","content ID",r.content_id)); continue
                if r.skill_id not in skills: issues.append(_issue("recommendations",r.recommendation_id,"skill_id","INVALID_FOREIGN_KEY","skill ID",r.skill_id)); continue
                asof=recommendation_times[rec_idx]
                if pd.isna(asof):
                    issues.append(_issue("recommendations",r.recommendation_id,"recommended_at","INVALID_TIMESTAMP","ISO-8601 UTC time",r.recommended_at)); continue
                key=(r.learner_id,asof.isoformat())
                if key not in mastery_cache:
                    mastery_cache[key]=summarize_evidence(evidence_by_learner.get(r.learner_id,expanded_evidence.iloc[0:0]),asof)
                estimate=mastery_cache[key].get(r.skill_id,{"mastery":0.0,"attempt_ids":[],"assessment_ids":[]})
                recorded=recommendation_masteries[rec_idx]
                if pd.isna(recorded) or abs(float(recorded)-estimate["mastery"])>MASTERY_TOLERANCE:
                    issues.append(_issue("recommendations",r.recommendation_id,"mastery_at_recommendation","MASTERY_RECONCILIATION_FAILED",estimate["mastery"],recorded))
                if {"evidence_attempt_ids","evidence_assessment_ids"}.issubset(recommendations.columns):
                    try:
                        exp_a=json.loads(r.evidence_attempt_ids); exp_s=json.loads(r.evidence_assessment_ids)
                    except (TypeError,ValueError): exp_a=[]; exp_s=[]
                    if exp_a!=estimate["attempt_ids"] or exp_s!=estimate["assessment_ids"]:
                        issue_code="TEMPORAL_LEAKAGE" if any(x not in estimate["attempt_ids"] for x in exp_a) else "EVIDENCE_RECONCILIATION_FAILED"
                        issues.append(_issue("recommendations",r.recommendation_id,"evidence_attempt_ids",issue_code,estimate["attempt_ids"],exp_a))
                if "explanation_json" in recommendations:
                    try:
                        details=json.loads(r.explanation_json)
                        cutoff_text=pd.to_datetime(details.get("history_cutoff_at"),format="mixed",utc=True,errors="coerce")
                        if pd.notna(cutoff_text) and cutoff_text!=asof: issues.append(_issue("recommendations",r.recommendation_id,"history_cutoff_at","TEMPORAL_LEAKAGE",asof.isoformat(),details.get("history_cutoff_at")))
                        if details.get("source_attempt_ids")!=estimate["attempt_ids"]: issues.append(_issue("recommendations",r.recommendation_id,"source_attempt_ids","EVIDENCE_RECONCILIATION_FAILED",estimate["attempt_ids"],details.get("source_attempt_ids")))
                    except (TypeError,ValueError,AttributeError):
                        issues.append(_issue("recommendations",r.recommendation_id,"explanation_json","INVALID_EVIDENCE_JSON","valid evidence JSON",getattr(r,"explanation_json",None)))
                if key not in active_cache:
                    active_map=defaultdict(list)
                    for child,parent in active_prerequisites(prereqs,asof): active_map[child].append(parent)
                    active_cache[key]=active_map
                active_map=active_cache[key]
                actual_skills=skills_by_content.get(r.content_id,[])
                if r.skill_id not in actual_skills: issues.append(_issue("recommendations",r.recommendation_id,"skill_id","CONTENT_SKILL_MISMATCH",actual_skills,r.skill_id))
                if any(s not in skills for s in actual_skills): issues.append(_issue("recommendations",r.recommendation_id,"content_id","INVALID_CONTENT_SKILL_MAPPING",skills,actual_skills))
                try:
                    declared=json.loads(r.mapped_skill_ids) if "mapped_skill_ids" in recommendations else actual_skills
                    if sorted(declared)!=actual_skills: issues.append(_issue("recommendations",r.recommendation_id,"mapped_skill_ids","CONTENT_SKILL_SET_MISMATCH",actual_skills,declared))
                except (TypeError,ValueError):
                    declared=[]; issues.append(_issue("recommendations",r.recommendation_id,"mapped_skill_ids","INVALID_EVIDENCE_JSON","JSON skill ID list",r.mapped_skill_ids))
                for mapped_skill in actual_skills:
                    if skill_track_by_id[mapped_skill]!=learner_track_by_id[r.learner_id]:
                        issues.append(_issue("recommendations",r.recommendation_id,"skill_id","TRACK_SKILL_MISMATCH",learner_track_by_id[r.learner_id],mapped_skill))
                    mapped_mastery=mastery_cache[key].get(mapped_skill,{"mastery":0.0})["mastery"]
                    if mapped_mastery>=.8:
                        issues.append(_issue("recommendations",r.recommendation_id,"content_id","MASTERED_CONTENT_RECOMMENDED","all mapped skills below 0.80",mapped_skill))
                    for parent in active_map.get(mapped_skill,[]):
                        if mastery_cache[key].get(parent,{"mastery":0.0})["mastery"]<.7:
                            issues.append(_issue("recommendations",r.recommendation_id,"skill_id","PREREQUISITE_VIOLATION",parent,mapped_skill)); break
                item=content_by_id[r.content_id]
                course=course_by_id[item["course_id"]]
                learner=learner_by_id[r.learner_id]
                if learner!="Active": issues.append(_issue("recommendations",r.recommendation_id,"learner_id","INACTIVE_LEARNER_RECOMMENDED","Active",learner))
                if item["content_status"]!="Active" or course!="Active": issues.append(_issue("recommendations",r.recommendation_id,"content_id","INACTIVE_CONTENT_RECOMMENDED","active content and course",r.content_id))
                rank=recommendation_ranks[rec_idx]
                if pd.isna(rank) or rank<1 or float(rank)!=int(rank): issues.append(_issue("recommendations",r.recommendation_id,"rank","INVALID_RANK",">= 1 integer",r.rank))
                if "status" in recommendations and r.status!="Recommended": issues.append(_issue("recommendations",r.recommendation_id,"status","INVALID_LIFECYCLE_STATE","Recommended",r.status))
                if {"difficulty_target","difficulty_selected","difficulty_fallback"}.issubset(recommendations.columns):
                    mastery_target="Beginner" if estimate["mastery"]<.5 else ("Intermediate" if estimate["mastery"]<.7 else "Advanced")
                    selected_level=item["difficulty_level"]
                    if r.difficulty_target!=mastery_target or r.difficulty_selected!=selected_level or bool(r.difficulty_fallback)!=(selected_level!=mastery_target):
                        issues.append(_issue("recommendations",r.recommendation_id,"difficulty_selected","DIFFICULTY_EXPLANATION_MISMATCH",{"target":mastery_target,"selected":selected_level},r.difficulty_selected))

    if paths is not None:
        expected={"learning_path_id","snapshot_id","learner_id","sequence_no","recommendation_id","content_id","created_at","status"}
        if not expected.issubset(paths.columns): issues.append(_issue("learning_paths",None,"*","MISSING_COLUMNS",sorted(expected-set(paths.columns)),list(paths.columns)))
        elif recommendations is not None:
            rec_by_id=recommendations.set_index("recommendation_id").to_dict("index") if "recommendation_id" in recommendations else {}
            for learner_id,group in paths.groupby("learner_id",dropna=False):
                if learner_id not in set(tables["learners"].learner_id): issues.append(_issue("learning_paths",learner_id,"learner_id","INVALID_FOREIGN_KEY","learner ID",learner_id)); continue
                for path_id,path_group in group.groupby("learning_path_id"):
                    if not re.fullmatch(r"PATH-2026-\d{6}",str(path_id)): issues.append(_issue("learning_paths",path_id,"learning_path_id","INVALID_ID_FORMAT","PATH-2026-######",path_id))
                    seq=sorted(pd.to_numeric(path_group.sequence_no,errors="coerce").dropna().astype(int).tolist())
                    if seq!=list(range(1,len(seq)+1)): issues.append(_issue("learning_paths",path_id,"sequence_no","PATH_SEQUENCE_GAP","contiguous sequence starting at 1",seq))
                    if path_group.content_id.duplicated().any(): issues.append(_issue("learning_paths",path_id,"content_id","NO_PROGRESS_LOOP","no duplicate activity in one path",path_group.content_id.tolist()))
                    if not path_group.status.isin(["Active","Completed","Blocked","Archived"]).all(): issues.append(_issue("learning_paths",path_id,"status","INVALID_LIFECYCLE_STATE","Active/Completed/Blocked/Archived",path_group.status.tolist()))
                    for r in path_group.itertuples(index=False):
                        if r.recommendation_id not in rec_by_id:
                            issues.append(_issue("learning_paths",path_id,"recommendation_id","INVALID_FOREIGN_KEY","recommendation ID",r.recommendation_id)); continue
                        rr=rec_by_id[r.recommendation_id]
                        if r.learner_id!=rr["learner_id"]: issues.append(_issue("learning_paths",path_id,"learner_id","PATH_RECOMMENDATION_OWNER_MISMATCH",rr["learner_id"],r.learner_id))
                        if r.content_id!=rr["content_id"]: issues.append(_issue("learning_paths",path_id,"content_id","PATH_RECOMMENDATION_CONTENT_MISMATCH",rr["content_id"],r.content_id))
                        if r.sequence_no!=rr.get("rank"): issues.append(_issue("learning_paths",path_id,"sequence_no","PATH_RECOMMENDATION_RANK_MISMATCH",rr.get("rank"),r.sequence_no))
                        if r.snapshot_id!=rr["snapshot_id"]: issues.append(_issue("learning_paths",path_id,"snapshot_id","SNAPSHOT_MISMATCH",rr["snapshot_id"],r.snapshot_id))
    if decisions is not None and "learner_id" in decisions:
        missing=set(tables["learners"].learner_id)-set(decisions.learner_id)
        for learner_id in list(missing)[:100]: issues.append(_issue("learner_decisions",learner_id,"decision_code","DECISION_MISSING","one per learner",None))
        if decisions.learner_id.duplicated().any(): issues.append(_issue("learner_decisions",None,"learner_id","DUPLICATE_DECISION","one per learner",None))
        if "decision_code" in decisions and not decisions.decision_code.isin(["INACTIVE_LEARNER","ALL_TARGETS_MASTERED","PREREQUISITE_BLOCKED","NO_ELIGIBLE_CONTENT","RECOMMENDATIONS_CREATED"]).all():
            issues.append(_issue("learner_decisions",None,"decision_code","INVALID_DECISION_CODE","documented decision code",decisions.decision_code.tolist()[:20]))
    if events is not None and "event_id" in events and events.event_id.duplicated().any(): issues.append(_issue("recommendation_events",None,"event_id","DUPLICATE_PRIMARY_KEY","unique",None))
    return issues


def run_anomaly_suite(tables, recommendations, paths):
    """Inject one controlled fault at a time and execute the production validator."""
    results=[]
    def compact(learner_id=None):
        if learner_id is None: attempts=tables["attempts"].iloc[0:0].copy()
        else: attempts=tables["attempts"].loc[tables["attempts"].learner_id.eq(learner_id)].copy()
        ids=set(attempts.attempt_id)
        return {**tables,"attempts":attempts,"assessment_results":tables["assessment_results"].loc[tables["assessment_results"].assessment_id.isin(ids)].copy()}
    def run(name,expected,t,recs=None,path_rows=None,payload=None):
        detected=sorted({x["issue_type"] for x in validate(t,recs,path_rows)})
        results.append({"case_id":name,"expected_issue_type":expected,"detected_issue_types":json.dumps(detected),
                        "result":"PASS" if expected in detected else "MISS","payload_json":json.dumps(payload or {},sort_keys=True)})
    cold=next((x for x in tables["learners"].learner_id if not (tables["attempts"].learner_id==x).any()),tables["learners"].iloc[0].learner_id)
    base_rec=recommendations.iloc[0:1].copy()
    prereq=tables["skill_prerequisites"]
    if len(prereq):
        edge=prereq.iloc[0]; content=tables["content_skills"].loc[tables["content_skills"].skill_id.eq(edge.skill_id),"content_id"]
        if len(content):
            base_rec.loc[base_rec.index[0],"learner_id"]=cold
            base_rec.loc[base_rec.index[0],"skill_id"]=edge.skill_id
            base_rec.loc[base_rec.index[0],"content_id"]=content.iloc[0]
            mapped=sorted(tables["content_skills"].loc[tables["content_skills"].content_id.eq(content.iloc[0]),"skill_id"].unique())
            base_rec.loc[base_rec.index[0],"mapped_skill_ids"]=json.dumps(mapped)
            base_rec.loc[base_rec.index[0],"recommended_at"]="2026-01-01T00:00:00+00:00"
            base_rec.loc[base_rec.index[0],"mastery_at_recommendation"]=0.0
            base_rec.loc[base_rec.index[0],"evidence_attempt_ids"]="[]"; base_rec.loc[base_rec.index[0],"evidence_assessment_ids"]="[]"
            base_rec.loc[base_rec.index[0],"explanation_json"]=json.dumps({"history_cutoff_at":"2026-01-01T00:00:00+00:00","source_attempt_ids":[],"source_assessment_ids":[]},sort_keys=True)
            run("ANOM-001","PREREQUISITE_VIOLATION",compact(cold),base_rec,paths.iloc[0:0].copy(),{"learner_id":cold,"skill_id":edge.skill_id,"prerequisite_skill_id":edge.prerequisite_skill_id,"mastery":0.0})
    ordered=tables["attempts"].copy(); learner=ordered.learner_id.iloc[0]; ix=ordered.index[ordered.learner_id.eq(learner)][:2]
    if len(ix)==2:
        ordered.loc[ix[1],"attempted_at"]=(parse_utc(pd.Series([ordered.loc[ix[0],"attempted_at"]])).iloc[0]-pd.Timedelta(days=1)).isoformat()
        bad=compact(learner); bad["attempts"]=ordered.loc[ix].copy(); ids=set(bad["attempts"].attempt_id); bad["assessment_results"]=tables["assessment_results"].loc[tables["assessment_results"].assessment_id.isin(ids)].copy()
        run("ANOM-002","ATTEMPT_ORDER_INVALID",bad,payload={"learner_id":learner,"attempt_ids":ordered.loc[ix,"attempt_id"].tolist(),"timestamps":ordered.loc[ix,"attempted_at"].tolist()})
    mappings=tables["content_skills"].copy()
    if len(mappings):
        mappings.loc[mappings.index[0],"skill_id"]=None
        bad=compact(tables["attempts"].learner_id.iloc[0]); bad["content_skills"]=mappings
        run("ANOM-003","REQUIRED_VALUE_MISSING",bad,payload={"content_skill_id":mappings.iloc[0].content_skill_id,"skill_id":None})
    if len(recommendations):
        evidence_rows=recommendations
        if "evidence_attempt_ids" in recommendations:
            evidence_rows=recommendations[recommendations.evidence_attempt_ids.astype(str).ne("[]")]
        leaked=evidence_rows.iloc[0:1].copy() if len(evidence_rows) else recommendations.iloc[0:1].copy()
        leaked.loc[leaked.index[0],"recommended_at"]="2025-12-31T00:00:00+00:00"
        run("ANOM-004","TEMPORAL_LEAKAGE",compact(leaked.iloc[0].learner_id),leaked,paths[paths.recommendation_id.isin(leaked.recommendation_id)].copy(),{"recommendation_id":leaked.iloc[0].recommendation_id,"invalid_as_of":"2025-12-31T00:00:00+00:00"})
    if len(paths):
        path=paths.iloc[0:1].copy(); duplicate=path.copy(); duplicate.loc[duplicate.index[0],"sequence_no"]=2
        repeated=pd.concat([path,duplicate],ignore_index=True)
        recs=recommendations[recommendations.recommendation_id.isin(repeated.recommendation_id)].copy()
        run("ANOM-005","NO_PROGRESS_LOOP",compact(path.iloc[0].learner_id),recs,repeated,payload={"learning_path_id":path.iloc[0].learning_path_id,"content_id":path.iloc[0].content_id,"sequence_numbers":[1,2]})
    return pd.DataFrame(results,columns=["case_id","expected_issue_type","detected_issue_types","result","payload_json"])
