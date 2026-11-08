"""Deterministic, explainable end-to-end learning recommender pipeline."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from .generator import generate, SEED
    from .recommender import recommend
    from .validation import validate, run_anomaly_suite
    from .evaluation import derive_outcomes, evaluate
    from .exports import write_csv_jsonl, build_sqlite, artifact_manifest
except ImportError:
    from generator import generate, SEED
    from recommender import recommend
    from validation import validate, run_anomaly_suite
    from evaluation import derive_outcomes, evaluate
    from exports import write_csv_jsonl, build_sqlite, artifact_manifest

ROOT=Path(__file__).resolve().parents[1]
GENERATOR_VERSION="2.0.0"


def _utc_now(): return datetime.now(timezone.utc).isoformat()


def _json_write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(data,indent=2,sort_keys=True,ensure_ascii=False)+"\n",encoding="utf-8",newline="\n")
    os.replace(temp,path)


def _source_identity(seed,full,params):
    files=[Path(__file__),Path(__file__).with_name("generator.py"),Path(__file__).with_name("mastery.py"),
           Path(__file__).with_name("recommender.py"),Path(__file__).with_name("validation.py"),
           Path(__file__).with_name("evaluation.py"),Path(__file__).with_name("exports.py")]
    h=hashlib.sha256()
    for path in files:
        h.update(path.name.encode()); h.update(path.read_bytes())
    code_hash=h.hexdigest()
    payload=json.dumps({"seed":seed,"full":full,"parameters":params,"generator_version":GENERATOR_VERSION,"code_hash":code_hash},sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:20],code_hash


def _git_commit():
    try:
        return subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,stderr=subprocess.DEVNULL,text=True,timeout=2).strip()
    except Exception: return "uncommitted"


def _rows_mapping(tables,recs,baseline,paths,decisions,events,outcomes,base_outcomes,anomaly_results):
    return {"Learner":tables["learners"],"Course":tables["courses"],"Skill":tables["skills"],
            "SkillPrerequisite":tables["skill_prerequisites"],"ContentItem":tables["content_items"],"ContentSkill":tables["content_skills"],
            "Attempt":tables["attempts"],"AssessmentResult":tables["assessment_results"],"Recommendation":recs,
            "BaselinePolicyRecommendation":baseline,"LearningPath":paths,"LearnerDecision":decisions,"DomainEvent":events,
            "RecommendationOutcome":outcomes}


def _write_snapshot(stage,tables,recs,baseline,paths,decisions,events,outcomes,base_outcomes,anomaly_results,metrics,run_meta):
    written=[]; counts={}
    base_dir=stage/"master"
    source_files={
      "master": {"learners":tables["learners"],"courses":tables["courses"],"skills":tables["skills"],"skill_prerequisites":tables["skill_prerequisites"],"content_items":tables["content_items"],"content_skills":tables["content_skills"]},
      "transactions":{"attempts":tables["attempts"],"assessment_results":tables["assessment_results"]},
      "outputs":{"recommendations":recs,"baseline_policy_recommendations":baseline,"learning_paths":paths,"learner_decisions":decisions,"domain_events":events,"validation_issues":pd.DataFrame(columns=["entity","primary_key","field","issue_type","expected","observed"])},
      "ground_truth":{"recommendation_outcomes":outcomes,"baseline_outcomes":base_outcomes,"anomaly_results":anomaly_results,
                      "anomaly_cases":pd.DataFrame([
                          {"case_id":"ANOM-001","expected_issue_type":"PREREQUISITE_VIOLATION"},
                          {"case_id":"ANOM-002","expected_issue_type":"ATTEMPT_ORDER_INVALID"},
                          {"case_id":"ANOM-003","expected_issue_type":"REQUIRED_VALUE_MISSING"},
                          {"case_id":"ANOM-004","expected_issue_type":"TEMPORAL_LEAKAGE"},
                          {"case_id":"ANOM-005","expected_issue_type":"NO_PROGRESS_LOOP"}])}}
    for folder,items in source_files.items():
        for name,frame in items.items():
            for file in write_csv_jsonl(frame,stage/folder,name):
                written.append(file)
                if file.suffix==".csv": counts[file.relative_to(stage).as_posix()]=len(frame)
    # Keep a single small JSON metadata file in addition to entity JSONL exports.
    (stage/"outputs").mkdir(exist_ok=True)
    summary=stage/"outputs"/"validation_summary.json"
    _json_write(summary,metrics); written.append(summary)
    metadata={**run_meta,"counts":{name:len(frame) for name,frame in _rows_mapping(tables,recs,baseline,paths,decisions,events,outcomes,base_outcomes,anomaly_results).items()},
              "units":{"score":"0-1 inclusive","mastery":"arithmetic mean of official assessment scores","time":"ISO-8601 UTC"},
              "provenance":"Synthetic records generated by this project; no personal or external data."}
    meta=stage/"run_metadata.json"; _json_write(meta,metadata); written.append(meta)
    # The SQLite snapshot is a populated, constraint-checked SQL seed database.
    db=stage/"learning_recommender.sqlite"
    db_counts=build_sqlite(db,ROOT/"sql"/"schema.sql",_rows_mapping(tables,recs,baseline,paths,decisions,events,outcomes,base_outcomes,anomaly_results))
    written.append(db)
    metrics["sqlite_row_counts"]=db_counts
    _json_write(summary,metrics)
    files=artifact_manifest(stage,written,counts)
    manifest={**run_meta,"artifacts":files,"row_counts":counts}
    manifest_path=stage/"source_manifest.json"; _json_write(manifest_path,manifest)
    return manifest


def run_pipeline(full=False,seed=SEED,output_dir=None):
    params={"n_learners":10000 if full else 100,"n_skills":500 if full else 20,"n_content":2000 if full else 50,
            "attempts_per_learner":50 if full else 8,"target_attempts":500000 if full else None}
    run_id,code_hash=_source_identity(seed,full,params)
    snapshot_id=f"snapshot-{run_id}"
    output_root=Path(output_dir) if output_dir else ROOT/"data"/"runs"
    if not output_root.is_absolute(): output_root=ROOT/output_root
    output_root=output_root.resolve(); output_root.mkdir(parents=True,exist_ok=True)
    executions=output_root/"executions"; executions.mkdir(parents=True,exist_ok=True)
    execution_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+"-"+uuid.uuid4().hex[:8]
    execution_path=executions/f"{execution_id}.json"
    execution={"execution_id":execution_id,"run_id":run_id,"status":"STARTED","started_at":_utc_now(),"stage":"initializing",
               "seed":seed,"scale":"full" if full else "starter","parameters":params,"source_commit":_git_commit(),"code_sha256":code_hash}
    _json_write(execution_path,execution)
    stage=Path(tempfile.mkdtemp(prefix=f".staging-{run_id}-",dir=output_root))
    try:
        execution["stage"]="generate"; _json_write(execution_path,execution)
        tables=generate(**params,seed=seed)
        issues=validate(tables)
        if issues: raise ValueError(f"Input validation failed; first issues: {json.dumps(issues[:20])}")
        execution["stage"]="recommend"; _json_write(execution_path,execution)
        recs,paths,baseline,decisions,events=recommend(tables,snapshot_id)
        derived_issues=validate(tables,pd.concat([recs,baseline],ignore_index=True),paths,decisions,events,snapshot_id)
        if derived_issues: raise ValueError(f"Decision validation failed; first issues: {json.dumps(derived_issues[:20])}")
        execution["stage"]="negative_scenarios"; _json_write(execution_path,execution)
        anomaly_results=run_anomaly_suite(tables,recs,paths)
        if len(anomaly_results)!=5 or not anomaly_results.result.eq("PASS").all():
            raise ValueError(f"Negative scenario suite failed: {anomaly_results.to_dict(orient='records')}")
        outcomes=derive_outcomes(recs,tables); base_outcomes=derive_outcomes(baseline,tables)
        metrics=evaluate(recs,baseline,outcomes,base_outcomes,tables,decisions,anomaly_results.to_dict(orient="records"))
        execution["stage"]="serialize_and_verify"; _json_write(execution_path,execution)
        run_meta={"run_id":run_id,"snapshot_id":snapshot_id,"generator_version":GENERATOR_VERSION,"source_commit":execution["source_commit"],
                  "code_sha256":code_hash,"seed":int(seed),"scale":"full" if full else "starter","parameters":params,
                  "python_version":sys.version.split()[0],"numpy_version":np.__version__,"pandas_version":pd.__version__,
                  "score_source":"AssessmentResult.score; reconciled to Attempt.score","mastery_rule":"mean score per learner-skill from events at or before each recommendation timestamp",
                  "prerequisite_policy":"all active direct parents must have mastery >= 0.70; active interval is [effective_from,effective_to)"}
        manifest=_write_snapshot(stage,tables,recs,baseline,paths,decisions,events,outcomes,base_outcomes,anomaly_results,metrics,run_meta)
        target=output_root/run_id
        if target.exists():
            existing=json.loads((target/"source_manifest.json").read_text(encoding="utf-8"))
            if existing.get("artifacts")!=manifest.get("artifacts"):
                raise RuntimeError("same snapshot identity produced different artifact hashes; existing snapshot was preserved")
            shutil.rmtree(stage)
        else:
            os.replace(stage,target)
        pointer={"current_run":run_id,"snapshot_id":snapshot_id,"manifest":(target/"source_manifest.json").relative_to(output_root).as_posix()}
        _json_write(output_root/"current_run.json",pointer)
        execution.update({"status":"COMPLETE","stage":"published","completed_at":_utc_now(),"counts":manifest["row_counts"],
                          "validation_issue_count":0,"anomaly_scenarios_passed":int(anomaly_results.result.eq("PASS").sum())})
        _json_write(execution_path,execution)
        return target,metrics
    except Exception as exc:
        if stage.exists(): shutil.rmtree(stage,ignore_errors=True)
        execution.update({"status":"FAILED","stage":execution.get("stage"),"completed_at":_utc_now(),"failure":f"{type(exc).__name__}: {exc}"})
        _json_write(execution_path,execution)
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full",action="store_true",help="10k learners, 500 skills, 2k content items, 500k attempts")
    parser.add_argument("--seed",type=int,default=SEED)
    parser.add_argument("--output-dir",default=None,help="snapshot root; defaults to data/runs")
    args=parser.parse_args()
    target,metrics=run_pipeline(args.full,args.seed,args.output_dir)
    print(json.dumps({"published_snapshot":str(target),"metrics":metrics},indent=2,default=str))


if __name__=="__main__": main()
