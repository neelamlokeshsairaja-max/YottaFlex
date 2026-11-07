"""Reproducible synthetic learning-path recommendation pipeline."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20261022
ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "data" / "master"
TXN = ROOT / "data" / "transactions"
OUT = ROOT / "data" / "outputs"
TRUTH = ROOT / "data" / "ground_truth"
SKILL_NAMES = ["Python Basics", "Variables", "Data Types", "Operators", "Conditionals", "Loops", "Functions", "Lists", "Tuples", "Dictionaries", "Sets", "Strings", "File Handling", "Exceptions", "OOP", "SQL Basics", "SQL Joins", "SQL Group By", "Statistics", "Data Visualization"]
COURSE_NAMES = ["Python Programming", "Data Analytics", "Machine Learning", "SQL Database", "Statistics", "Data Science", "Web Development", "Artificial Intelligence", "Deep Learning", "Business Analytics", "Python for Data Science", "Advanced SQL", "Data Visualization", "Excel Analytics", "Probability", "Linear Algebra", "Flask Development", "Database Management", "Data Engineering", "Generative AI"]


def sid(i): return f"SKL-{i:06d}"
def cid(i): return f"CNT-{i:06d}"
def lid(i): return f"LRN-{i:06d}"


def generate(n_learners=100, n_skills=20, n_content=50, attempts_per_learner=8, seed=SEED, target_attempts=None):
    """Generate valid base tables and chronological attempt events."""
    rng = np.random.default_rng(seed)
    skills = pd.DataFrame([{"skill_id": sid(i), "skill_name": SKILL_NAMES[(i-1) % len(SKILL_NAMES)] + (f" {i}" if i > len(SKILL_NAMES) else ""), "difficulty_level": ("Beginner" if i <= n_skills // 3 else "Intermediate" if i <= 2*n_skills//3 else "Advanced")} for i in range(1, n_skills+1)])
    learners = pd.DataFrame([{"learner_id": lid(i), "learner_name": f"Learner {i:06d}", "experience_level": rng.choice(["Beginner", "Intermediate", "Advanced"], p=[.5,.35,.15]), "learner_status": "Active"} for i in range(1, n_learners+1)])
    courses = pd.DataFrame([{"course_id": f"CRS-{i:06d}", "course_name": COURSE_NAMES[(i-1)%len(COURSE_NAMES)], "course_status": "Active"} for i in range(1, 21)])
    prereqs = pd.DataFrame([{"prerequisite_id": f"PRQ-{i:06d}", "skill_id": sid(i), "prerequisite_skill_id": sid(i-1), "effective_from": "2026-01-01", "effective_to": ""} for i in range(2, n_skills+1)])
    types = ["Video", "PDF", "Quiz", "Exercise", "Project"]
    content = pd.DataFrame([{"content_id": cid(i), "course_id": f"CRS-{(i-1)%20+1:06d}", "content_title": f"Learning Activity {i}", "content_type": types[(i-1)%len(types)], "difficulty_level": ("Beginner" if i % 3 == 1 else "Intermediate" if i%3 == 2 else "Advanced"), "duration_minutes": [15,30,45,60][i%4], "content_status":"Active"} for i in range(1,n_content+1)])
    content_skills = pd.DataFrame([{"content_skill_id":f"CSM-{i:06d}", "content_id":cid(i), "skill_id":sid((i-1)%n_skills+1)} for i in range(1,n_content+1)])
    start=pd.Timestamp("2026-01-01",tz="UTC")
    active_learners=np.array([i for i in range(1,n_learners+1) if i%20!=0],dtype=np.int32)
    base_count=attempts_per_learner
    if target_attempts is None:
        counts=np.full(len(active_learners),base_count,dtype=np.int32)
    else:
        base_count,remainder=divmod(int(target_attempts),len(active_learners))
        counts=np.full(len(active_learners),base_count,dtype=np.int32)
        counts[:remainder]+=1
    learner_numbers=np.repeat(active_learners,counts)
    offsets=np.concatenate([np.arange(c,dtype=np.int32) for c in counts]) if len(counts) else np.array([],dtype=np.int32)
    skill_numbers=offsets%n_skills+1
    content_numbers=(skill_numbers-1)%n_content+1
    timestamp=start+pd.to_timedelta(offsets*3+learner_numbers%17,unit="D")+pd.to_timedelta(learner_numbers%60,unit="m")
    baseline=rng.uniform(.35,.95,size=len(offsets))
    scores=np.clip(rng.normal(baseline+.08*offsets/max(attempts_per_learner,1),.13),0,1)
    attempt_ids=[f"ATT-{lid(int(li))}-{int(j)+1:06d}" for li,j in zip(learner_numbers,offsets)]
    attempt_frame=pd.DataFrame({"attempt_id":attempt_ids,"learner_id":[lid(int(i)) for i in learner_numbers],"content_id":[cid(int(i)) for i in content_numbers],"attempted_at":timestamp.astype(str),"score":np.round(scores,4),"attempt_number":offsets+1})
    assessments=attempt_frame[["attempt_id","score"]].rename(columns={"attempt_id":"assessment_id","score":"score"}).copy()
    assessments["assessment_type"]="ActivityScore"
    return {"learners":learners,"courses":courses,"skills":skills,"skill_prerequisites":prereqs,"content_items":content,"content_skills":content_skills,"attempts":attempt_frame,"assessment_results":assessments}


def mastery_at(attempts, mapping, as_of):
    by_content=dict(zip(mapping.content_id,mapping.skill_id))
    rows=attempts.loc[attempts.attempted_at<=as_of,["content_id","score"]].copy()
    if rows.empty: return {}
    rows["skill_id"]=rows.content_id.map(by_content)
    return rows.groupby("skill_id",sort=False).score.mean().to_dict()


def recommend(tables):
    skills, prereqs, content, mapping, attempts = (tables[k] for k in ["skills","skill_prerequisites","content_items","content_skills","attempts"])
    attempts=attempts.copy(); attempts["attempted_at"]=pd.to_datetime(attempts.attempted_at,utc=True)
    # Compute all learner-skill mastery in one grouped pass, at each learner's
    # chronological 60% cutoff, instead of running thousands of small joins.
    counts=attempts.groupby("learner_id").size().to_dict()
    history_n={learner:max(1,int(n*.6)) for learner,n in counts.items()}
    attempts["skill_id"]=attempts.content_id.map(dict(zip(mapping.content_id,mapping.skill_id)))
    attempts["history_cutoff"]=attempts.learner_id.map(history_n)
    history=attempts[attempts.attempt_number<=attempts.history_cutoff]
    mastery_rows=history.groupby(["learner_id","skill_id"],sort=False).score.mean()
    mastery_by_learner={}
    for (learner,skill),score in mastery_rows.items(): mastery_by_learner.setdefault(learner,{})[skill]=float(score)
    cutoff_rows=attempts[attempts.attempt_number==attempts.history_cutoff]
    cutoff_by_learner=cutoff_rows.set_index("learner_id").attempted_at.to_dict()
    prereq_map=prereqs.groupby("skill_id").prerequisite_skill_id.apply(list).to_dict()
    difficulty_rank={"Beginner":0,"Intermediate":1,"Advanced":2}
    active=mapping.merge(content,on="content_id")
    active=active[active.content_status=="Active"].sort_values("content_id")
    content_by_skill={}
    for skill,options in active.groupby("skill_id",sort=False):
        content_by_skill[skill]={level:options.iloc[min(range(len(options)),key=lambda i:(abs(difficulty_rank.get(options.iloc[i].difficulty_level,0)-difficulty_rank[level]),options.iloc[i].content_id))] for level in difficulty_rank}
    rows=[]; path_rows=[]; rid=0
    learner_ids=tables["learners"].learner_id.to_list()
    for learner_index,learner in enumerate(learner_ids,1):
        if learner_index%2000==0: print(f"Recommendation progress: {learner_index}/{len(learner_ids)} learners",flush=True)
        scores=mastery_by_learner.get(learner,{})
        as_of=cutoff_by_learner.get(learner,pd.Timestamp("2026-01-01",tz="UTC"))
        eligible=[]
        for sk in skills.skill_id:
            if scores.get(sk,0)>=.8: continue
            req=prereq_map.get(sk,[])
            if any(scores.get(p,0)<.7 for p in req): continue
            eligible.append(sk)
        # Recommend the least mastered eligible skills first; on cold start, begin at graph roots.
        if not scores:
            eligible=[s for s in eligible if s not in prereq_map]
        eligible.sort(key=lambda s:(scores.get(s,0),s))
        path_id=f"PATH-2026-{int(learner[-6:]):06d}"
        for order,sk in enumerate(eligible[:3],1):
            target_difficulty="Beginner" if scores.get(sk,0)<.5 else ("Intermediate" if scores.get(sk,0)<.7 else "Advanced")
            row=content_by_skill.get(sk,{}).get(target_difficulty)
            if row is None: continue
            reason="COLD_START_FOUNDATION" if not scores else ("PREREQUISITES_MET_LOW_MASTERY" if scores.get(sk,0)<.7 else "MASTERY_REINFORCEMENT")
            rid+=1; rec_id=f"REC-{rid:09d}"
            rows.append({"recommendation_id":rec_id,"learner_id":learner,"content_id":row.content_id,"skill_id":sk,"recommended_at":as_of.isoformat(),"rank":order,"reason_code":reason,"mastery_at_recommendation":round(scores.get(sk,0),4),"status":"Recommended"})
            path_rows.append({"learning_path_id":path_id,"learner_id":learner,"sequence_no":order,"recommendation_id":rec_id,"created_at":as_of.isoformat(),"status":"Active"})
    return pd.DataFrame(rows),pd.DataFrame(path_rows)


def validate(t, recommendations=None, paths=None):
    issues=[]
    def unique(name,key):
        if t[name][key].duplicated().any(): issues.append(f"{name}: duplicate primary key {key}")
    for name,key in [("learners","learner_id"),("courses","course_id"),("skills","skill_id"),("skill_prerequisites","prerequisite_id"),("content_items","content_id"),("content_skills","content_skill_id"),("attempts","attempt_id")]: unique(name,key)
    def fk(child,col,parent,key):
        bad=set(t[child][col].dropna())-set(t[parent][key]);
        if bad: issues.append(f"{child}.{col}: {len(bad)} invalid foreign keys")
    fk("content_items","course_id","courses","course_id"); fk("content_skills","content_id","content_items","content_id"); fk("content_skills","skill_id","skills","skill_id")
    fk("attempts","learner_id","learners","learner_id"); fk("attempts","content_id","content_items","content_id")
    fk("skill_prerequisites","skill_id","skills","skill_id"); fk("skill_prerequisites","prerequisite_skill_id","skills","skill_id")
    a=t["attempts"]
    if not a.score.between(0,1).all(): issues.append("attempts.score outside [0,1]")
    if a.duplicated(["learner_id","attempt_number"]).any(): issues.append("duplicate learner attempt number")
    ordered=a.assign(_time=pd.to_datetime(a.attempted_at,utc=True)).sort_values(["learner_id","attempt_number"])
    if (ordered.groupby("learner_id")._time.diff().dropna()<pd.Timedelta(0)).any(): issues.append("attempt timestamps move backward within learner history")
    if t["assessment_results"].assessment_id.duplicated().any(): issues.append("duplicate assessment result ID")
    if set(t["assessment_results"].assessment_id)!=set(a.attempt_id): issues.append("assessment results do not match attempts one-to-one")
    if t["content_skills"].duplicated(["content_id","skill_id"]).any(): issues.append("duplicate content-skill mapping")
    if recommendations is not None:
        if recommendations.recommendation_id.duplicated().any(): issues.append("duplicate recommendation ID")
        if not set(recommendations.learner_id)<=set(t["learners"].learner_id): issues.append("recommendations contain invalid learner IDs")
        if not set(recommendations.content_id)<=set(t["content_items"].content_id): issues.append("recommendations contain invalid content IDs")
        if not set(recommendations.skill_id)<=set(t["skills"].skill_id): issues.append("recommendations contain invalid skill IDs")
        mapped=set(zip(t["content_skills"].content_id,t["content_skills"].skill_id))
        if any((r.content_id,r.skill_id) not in mapped for r in recommendations.itertuples()): issues.append("recommendation content does not map to recommended skill")
        prereq_map=t["skill_prerequisites"].groupby("skill_id").prerequisite_skill_id.apply(list).to_dict()
        counts=a.groupby("learner_id").size().to_dict()
        cutoff={learner:max(1,int(n*.6)) for learner,n in counts.items()}
        mapped_attempts=a.copy()
        mapped_attempts["skill_id"]=mapped_attempts.content_id.map(dict(zip(t["content_skills"].content_id,t["content_skills"].skill_id)))
        mapped_attempts["cutoff"]=mapped_attempts.learner_id.map(cutoff)
        mastery_rows=mapped_attempts[mapped_attempts.attempt_number<=mapped_attempts.cutoff].groupby(["learner_id","skill_id"],sort=False).score.mean()
        mastery_by_learner={}
        for (learner,skill),score in mastery_rows.items(): mastery_by_learner.setdefault(learner,{})[skill]=float(score)
        for r in recommendations.itertuples():
            required=prereq_map.get(r.skill_id,[])
            if not required: continue
            learner_mastery=mastery_by_learner.get(r.learner_id,{})
            if any(learner_mastery.get(parent,0)<.7 for parent in required):
                issues.append("recommendation violates prerequisite mastery threshold")
                break
    if paths is not None and recommendations is not None:
        if paths.duplicated(["learning_path_id","sequence_no"]).any(): issues.append("duplicate learning path sequence")
        if not set(paths.recommendation_id)<=set(recommendations.recommendation_id): issues.append("learning path references missing recommendation")
    return issues


def write(t, recommendations, paths, full=False, seed=SEED):
    for d in [MASTER,TXN,OUT,TRUTH]: d.mkdir(parents=True,exist_ok=True)
    for k in ["learners","courses","skills","skill_prerequisites","content_items","content_skills"]: t[k].to_csv(MASTER/f"{k}.csv",index=False)
    t["attempts"].to_csv(TXN/"attempts.csv",index=False)
    t["assessment_results"].to_csv(TXN/"assessment_results.csv",index=False)
    recommendations.to_csv(OUT/"recommendations.csv",index=False); paths.to_csv(OUT/"learning_paths.csv",index=False)
    print("Wrote master, attempt, and recommendation tables.",flush=True)
    # Outcome labels are generated from a separate later attempt, never recommendation features.
    a=t["attempts"].copy(); a["attempted_at"]=pd.to_datetime(a.attempted_at,utc=True)
    mapping=t["content_skills"]
    rec_keys=recommendations[["recommendation_id","learner_id","skill_id","recommended_at"]].copy()
    rec_keys["recommended_at"]=pd.to_datetime(rec_keys.recommended_at,utc=True)
    future=rec_keys.merge(a,on="learner_id").merge(mapping,on="content_id")
    future=future[(future.attempted_at>future.recommended_at)&(future.skill_id_x==future.skill_id_y)]
    first=future.sort_values("attempted_at").drop_duplicates("recommendation_id").set_index("recommendation_id").score
    labels=recommendations[["recommendation_id"]].copy()
    labels["later_skill_score"]=labels.recommendation_id.map(first)
    labels["ground_truth_label"]=np.select([labels.later_skill_score.ge(.7),labels.later_skill_score.notna()], ["COMPLETED_SUCCESS","FOLLOWUP_BELOW_THRESHOLD"], default="NO_FOLLOWUP")
    labels["issue_type"]=""
    labels[["recommendation_id","ground_truth_label","issue_type"]].to_csv(TRUTH/"recommendation_outcomes.csv",index=False)
    print("Wrote temporal outcome labels.",flush=True)
    # Deliberate anomalies live only in the label file; never contaminate baseline inputs.
    anomaly=[{"case_id":"ANOM-001","issue_type":"recommendation_violates_prerequisite","ground_truth_label":"INVALID_RECOMMENDATION","description":"Reject any recommendation where a required skill has mastery below 0.70."},{"case_id":"ANOM-002","issue_type":"attempt_timestamp_order_invalid","ground_truth_label":"INVALID_ATTEMPT_ORDER","description":"Reject event sequences with a timestamp earlier than the prior attempt."},{"case_id":"ANOM-003","issue_type":"content_mapped_to_nonexistent_skill","ground_truth_label":"INVALID_FOREIGN_KEY","description":"Reject a content-skill mapping to an absent skill ID."},{"case_id":"ANOM-004","issue_type":"mastery_uses_future_attempt","ground_truth_label":"TEMPORAL_LEAKAGE","description":"Mastery at recommendation time must include only attempts at or before that time."},{"case_id":"ANOM-005","issue_type":"path_loops_without_progress","ground_truth_label":"NO_PROGRESS_LOOP","description":"Reject repeated path content without a mastery or sequence progression."}]
    pd.DataFrame(anomaly).to_csv(TRUTH/"anomaly_cases.csv",index=False)
    # Concrete negative fixtures are isolated from production-like input tables.
    cold_id=next((x for x in t["learners"].learner_id if not (t["attempts"].learner_id==x).any()),t["learners"].iloc[0].learner_id)
    cold_num=int(cold_id[-6:])
    first_history=t["attempts"][t["attempts"].learner_id=="LRN-000001"].sort_values("attempt_number")
    earlier=first_history.iloc[0]
    later=first_history.iloc[1] if len(first_history)>1 else earlier
    later_time=pd.Timestamp(later.attempted_at)
    leak_row=t["attempts"].iloc[-1]
    leak_skill=t["content_skills"].set_index("content_id").loc[leak_row.content_id,"skill_id"]
    fixture_rows=[
        {"case_id":"ANOM-001","issue_type":"recommendation_violates_prerequisite","entity_id":"REC-ANOM-001","payload_json":json.dumps({"learner_id":cold_id,"content_id":"CNT-000002","skill_id":"SKL-000002","prerequisite_skill_id":"SKL-000001","prerequisite_mastery":0.0},sort_keys=True),"ground_truth_label":"INVALID_RECOMMENDATION"},
        {"case_id":"ANOM-002","issue_type":"attempt_timestamp_order_invalid","entity_id":f"ATT-{lid(1)}-999999","payload_json":json.dumps({"learner_id":lid(1),"previous_attempt_at":earlier.attempted_at,"attempted_at":(pd.Timestamp(earlier.attempted_at)-pd.Timedelta(days=1)).isoformat(),"attempt_number":2},sort_keys=True),"ground_truth_label":"INVALID_ATTEMPT_ORDER"},
        {"case_id":"ANOM-003","issue_type":"content_mapped_to_nonexistent_skill","entity_id":"CSM-ANOM-003","payload_json":json.dumps({"content_id":"CNT-000001","skill_id":"SKL-999999"},sort_keys=True),"ground_truth_label":"INVALID_FOREIGN_KEY"},
        {"case_id":"ANOM-004","issue_type":"mastery_uses_future_attempt","entity_id":f"REC-ANOM-004-{leak_row.attempt_id}","payload_json":json.dumps({"learner_id":leak_row.learner_id,"skill_id":leak_skill,"recommendation_at":(pd.Timestamp(leak_row.attempted_at)-pd.Timedelta(days=1)).isoformat(),"future_attempt_id":leak_row.attempt_id,"future_attempt_at":leak_row.attempted_at,"future_score":float(leak_row.score)},sort_keys=True),"ground_truth_label":"TEMPORAL_LEAKAGE"},
        {"case_id":"ANOM-005","issue_type":"path_loops_without_progress","entity_id":f"PATH-2026-{cold_num:06d}","payload_json":json.dumps({"learner_id":cold_id,"sequence":[{"sequence_no":1,"content_id":"CNT-000001","mastery_before":0.2,"mastery_after":0.2},{"sequence_no":2,"content_id":"CNT-000001","mastery_before":0.2,"mastery_after":0.2}]},sort_keys=True),"ground_truth_label":"NO_PROGRESS_LOOP"}
    ]
    pd.DataFrame(fixture_rows).to_csv(TRUTH/"anomaly_examples.csv",index=False)
    issues=validate(t,recommendations,paths)
    print("Completed integrity validation.",flush=True)
    metrics={"seed":seed,"scale":"full" if full else "starter","rows":{k:len(v) for k,v in t.items()},"recommendations":len(recommendations),"cold_start_learners":int((t["attempts"].learner_id.value_counts().reindex(t["learners"].learner_id,fill_value=0)==0).sum()),"recommendation_reason_codes":recommendations.reason_code.value_counts().to_dict(),"validation_issues":issues}
    # Precision proxy on the temporal outcome label (the synthetic ground-truth rule).
    labels=pd.read_csv(TRUTH/"recommendation_outcomes.csv")
    metrics["observed_success_rate"]=round(float((labels.ground_truth_label=="COMPLETED_SUCCESS").mean()),4) if len(labels) else 0
    followed=labels.ground_truth_label!="NO_FOLLOWUP"
    metrics["holdout_followup_coverage"]=round(float(followed.mean()),4) if len(labels) else 0
    metrics["success_rate_among_followups"]=round(float((labels.loc[followed,"ground_truth_label"]=="COMPLETED_SUCCESS").mean()),4) if followed.any() else 0
    (OUT/"validation_summary.json").write_text(json.dumps(metrics,indent=2),encoding="utf-8")
    manifest={"seed":seed,"generator":"src/pipeline.py","files":{}}
    for f in sorted([*MASTER.glob("*.csv"),*TXN.glob("*.csv"),*OUT.glob("*.csv"),*TRUTH.glob("*.csv")]):
        manifest["files"][str(f.relative_to(ROOT))]={"rows":max(0,sum(1 for _ in f.open(encoding="utf-8"))-1),"sha256":hashlib.sha256(f.read_bytes()).hexdigest()}
    (OUT/"source_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print("Wrote source manifest.",flush=True)
    print(json.dumps(metrics,indent=2))
    if issues: raise SystemExit("Validation failed: "+"; ".join(issues))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--full",action="store_true",help="Generate 10,000 learners, 500 skills, 2,000 items and 500,000 attempts")
    p.add_argument("--seed",type=int,default=SEED)
    a=p.parse_args()
    print("Generating synthetic tables...",flush=True)
    t=generate(10000 if a.full else 100,500 if a.full else 20,2000 if a.full else 50,50 if a.full else 8,a.seed,500000 if a.full else None)
    print(f"Generated {len(t['attempts']):,} attempts; building recommendations...",flush=True)
    rec,paths=recommend(t)
    print(f"Built {len(rec):,} recommendations; writing and validating outputs...",flush=True)
    write(t,rec,paths,a.full,a.seed)

if __name__=="__main__": main()
