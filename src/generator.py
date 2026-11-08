"""Deterministic synthetic master and event data for the learning recommender."""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone

SEED = 20261022
DOMAINS = ["Python", "Analytics", "Databases", "Statistics", "AI"]
FORMATS = ["Video", "PDF", "Quiz", "Exercise", "Project"]
LEVELS = ["Beginner", "Intermediate", "Advanced"]


def generate(n_learners=100, n_skills=20, n_content=50, attempts_per_learner=8,
             seed=SEED, target_attempts=None):
    """Build parent tables, a branching five-track DAG, content bridge and attempts.

    Every fifth eligible event is a practice retake of an earlier content item.
    AssessmentResult.score is the authoritative score; Attempt.score is retained
    as the submitted score and validated against it.
    """
    if min(n_learners, n_skills, n_content, attempts_per_learner) < 1:
        raise ValueError("scale parameters must be positive")
    rng = np.random.default_rng(seed)
    tracks = min(5, n_skills)
    learners = pd.DataFrame([{
        "learner_id": f"LRN-{i:06d}", "learner_name": f"Learner {i:06d}",
        "track_id": f"TRK-{(i-1)%tracks+1:02d}",
        "experience_level": str(rng.choice(LEVELS, p=[.5, .35, .15])),
        "learner_status": "Active"
    } for i in range(1, n_learners+1)])
    courses = pd.DataFrame([{
        "course_id": f"CRS-{i:06d}", "course_name": f"{DOMAINS[(i-1)%len(DOMAINS)]} Foundations {i:02d}",
        "course_status": "Active"
    } for i in range(1, 21)])
    skill_rows=[]
    for i in range(1, n_skills+1):
        track=(i-1)%tracks; level=(i-1)//tracks+1
        skill_rows.append({"skill_id":f"SKL-{i:06d}","skill_name":f"{DOMAINS[track]} Skill {level:03d}",
                           "domain":DOMAINS[track],"difficulty_level":LEVELS[min(2,(level-1)//max(1,((n_skills+tracks-1)//tracks)//3))]})
    skills=pd.DataFrame(skill_rows)
    prereq_rows=[]
    for i in range(1,n_skills+1):
        track=(i-1)%tracks; level=(i-1)//tracks+1
        if level>2:
            parent_level=level//2
            parent=(parent_level-1)*tracks+track+1
            prereq_rows.append({"prerequisite_id":f"PRQ-{len(prereq_rows)+1:06d}","skill_id":f"SKL-{i:06d}",
                                "prerequisite_skill_id":f"SKL-{parent:06d}","effective_from":"2026-01-01","effective_to":None})
    prereqs=pd.DataFrame(prereq_rows,columns=["prerequisite_id","skill_id","prerequisite_skill_id","effective_from","effective_to"])

    content_rows=[]; bridge_rows=[]; skill_to_items={f"SKL-{i:06d}":[] for i in range(1,n_skills+1)}
    for i in range(1,n_content+1):
        main=((i*37-1)%n_skills)+1
        level=(i-1)%3
        content_id=f"CNT-{i:06d}"
        content_rows.append({"content_id":content_id,"course_id":f"CRS-{(i-1)%20+1:06d}",
                             "content_title":f"{DOMAINS[(main-1)%tracks]} Activity {i:04d}",
                             "content_type":FORMATS[(i-1)%len(FORMATS)],"difficulty_level":LEVELS[level],
                             "duration_minutes":[15,30,45,60][i%4],"content_status":"Active"})
        targets=[main]
        if i%3==0 and n_skills>1:
            second=((main-1+tracks)%n_skills)+1
            if second!=main: targets.append(second)
        for sk in targets:
            bridge_rows.append({"content_skill_id":f"CSM-{len(bridge_rows)+1:06d}","content_id":content_id,"skill_id":f"SKL-{sk:06d}"})
            skill_to_items[f"SKL-{sk:06d}"].append((i,level))
    content=pd.DataFrame(content_rows)
    content_skills=pd.DataFrame(bridge_rows,columns=["content_skill_id","content_id","skill_id"])
    for sk, options in skill_to_items.items():
        if not options:
            raise ValueError(f"no content is mapped to {sk}; increase n_content")

    active=[i for i in range(1,n_learners+1) if i%20]
    counts=np.full(len(active),attempts_per_learner,dtype=np.int32)
    if target_attempts is not None:
        base,rem=divmod(int(target_attempts),len(active))
        counts=np.full(len(active),base,dtype=np.int32); counts[:rem]+=1
    # Build different prerequisite-respecting topological practice orders per learner.
    parent_by_skill={f"SKL-{i:06d}":[] for i in range(1,n_skills+1)}
    children_by_skill={key:[] for key in parent_by_skill}
    for r in prereq_rows: parent_by_skill[r["skill_id"]].append(r["prerequisite_skill_id"])
    for child,parents in parent_by_skill.items():
        for parent in parents: children_by_skill[parent].append(child)
    attempt_rows=[]; assessment_rows=[]; start=datetime(2026,1,1,tzinfo=timezone.utc)
    for learner_num,count in zip(active,counts):
        track=(learner_num-1)%tracks
        track_skills=[f"SKL-{i:06d}" for i in range(1,n_skills+1) if (i-1)%tracks==track]
        seen=set(); frontier=[sk for sk in track_skills if not parent_by_skill[sk]]; order=[]
        while frontier:
            sk=frontier.pop(int(rng.integers(len(frontier))))
            if sk in seen: continue
            seen.add(sk); order.append(sk)
            for child in children_by_skill[sk]:
                if child not in seen and child not in frontier and all(p in seen for p in parent_by_skill[child]): frontier.append(child)
        if not order: order=track_skills
        ability=float(np.clip(rng.normal(.63,.12),.25,.95)); practice={}; prior_content={}; seen_content=set(); practice_order_index=0
        for j in range(int(count)):
            planned_retake=(j>0 and j%5==4 and bool(practice))
            if planned_retake:
                sk=min(practice,key=lambda x:(practice[x],x)); content_num=prior_content[sk]
            else:
                sk=order[min(practice_order_index,len(order)-1)]
                practice_order_index+=1
                options=skill_to_items[sk]
                content_num=options[int(rng.integers(len(options)))][0]
            retake=content_num in seen_content
            seen_content.add(content_num)
            practice[sk]=practice.get(sk,0)+1; prior_content.setdefault(sk,content_num)
            level=(content_num-1)%3
            noise=float(rng.normal(0,.09))
            score=float(np.clip(ability-.10*(level-1)+.055*min(practice[sk]-1,4)+noise,0,1))
            attempt_num=j+1; attempt_id=f"ATT-LRN-{learner_num:06d}-{attempt_num:06d}"
            event_time=start+timedelta(days=3*j+learner_num%17,minutes=learner_num%60)
            row={"attempt_id":attempt_id,"learner_id":f"LRN-{learner_num:06d}","content_id":f"CNT-{content_num:06d}",
                 "attempted_at":event_time.isoformat(),"score":round(score,4),"attempt_number":attempt_num,
                 "attempt_kind":"RETAKE" if retake else "INITIAL"}
            attempt_rows.append(row)
            assessment_rows.append({"assessment_id":attempt_id,"score":row["score"],"assessment_type":"ActivityScore"})
    attempts=pd.DataFrame(attempt_rows,columns=["attempt_id","learner_id","content_id","attempted_at","score","attempt_number","attempt_kind"])
    assessments=pd.DataFrame(assessment_rows,columns=["assessment_id","score","assessment_type"])
    return {"learners":learners,"courses":courses,"skills":skills,"skill_prerequisites":prereqs,
            "content_items":content,"content_skills":content_skills,"attempts":attempts,"assessment_results":assessments}
