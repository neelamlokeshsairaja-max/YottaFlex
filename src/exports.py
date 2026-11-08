"""Portable CSV, JSONL, and constrained SQLite snapshot exports."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pandas as pd

TABLE_TARGETS={
 "Learner":"master/learners","Course":"master/courses","Skill":"master/skills",
 "SkillPrerequisite":"master/skill_prerequisites","ContentItem":"master/content_items","ContentSkill":"master/content_skills",
 "Attempt":"transactions/attempts","AssessmentResult":"transactions/assessment_results",
 "Recommendation":"outputs/recommendations","BaselinePolicyRecommendation":"outputs/baseline_policy_recommendations",
 "LearningPath":"outputs/learning_paths","LearnerDecision":"outputs/learner_decisions","DomainEvent":"outputs/domain_events",
 "RecommendationOutcome":"ground_truth/recommendation_outcomes"}


def write_csv_jsonl(frame, directory: Path, name: str):
    directory.mkdir(parents=True,exist_ok=True)
    csv_path=directory/f"{name}.csv"; json_path=directory/f"{name}.jsonl"
    frame.to_csv(csv_path,index=False,lineterminator="\n",na_rep="")
    frame.to_json(json_path,orient="records",lines=True,date_format="iso",force_ascii=False,double_precision=10)
    return [csv_path,json_path]


def _safe_rows(frame, chunk_size=5000):
    for start in range(0,len(frame),chunk_size):
        chunk=frame.iloc[start:start+chunk_size]
        for row in chunk.itertuples(index=False,name=None):
            yield tuple(None if pd.isna(v) else (int(v) if hasattr(v,"item") and isinstance(v.item(),int) else v.item() if hasattr(v,"item") else v) for v in row)


def build_sqlite(path: Path, schema_path: Path, frames: dict):
    """Load all submitted entity/event tables into the constrained schema, then check it."""
    if path.exists(): path.unlink()
    conn=sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        for table,source in TABLE_TARGETS.items():
            frame=frames.get(table)
            if frame is None: continue
            columns=list(frame.columns)
            placeholders=",".join("?" for _ in columns)
            names=",".join('"'+c+'"' for c in columns)
            sql=f'INSERT INTO "{table}" ({names}) VALUES ({placeholders})'
            conn.executemany(sql,_safe_rows(frame))
            conn.commit()
        fk_errors=conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_errors: raise ValueError(f"SQLite foreign-key violations: {fk_errors[:10]}")
        score_mismatches=int(conn.execute("SELECT COUNT(*) FROM Attempt a JOIN AssessmentResult r ON r.assessment_id=a.attempt_id WHERE ABS(a.score-r.score)>0.000000001").fetchone()[0])
        if score_mismatches: raise ValueError(f"SQLite score reconciliation failed for {score_mismatches} attempts")
        joined_rows=int(conn.execute("SELECT COUNT(*) FROM Attempt a JOIN ContentSkill cs ON cs.content_id=a.content_id JOIN AssessmentResult ar ON ar.assessment_id=a.attempt_id").fetchone()[0])
        if frames.get("Attempt") is not None and len(frames["Attempt"]) and joined_rows==0: raise ValueError("SQLite representative attempt/content-skill/assessment join is empty")
        counts={table:int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]) for table in TABLE_TARGETS if table in frames}
        for table,source in TABLE_TARGETS.items():
            if table in frames and counts[table]!=len(frames[table]): raise ValueError(f"SQLite row count mismatch for {table}")
        return {"row_counts":counts,"foreign_key_violation_count":0,"assessment_score_mismatch_count":score_mismatches,"attempt_mapping_join_rows":joined_rows}
    finally:
        conn.close()


def sha256(path: Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()


def artifact_manifest(root: Path, file_list, row_counts):
    files={}
    for path in sorted(file_list,key=lambda x:x.relative_to(root).as_posix()):
        rel=path.relative_to(root).as_posix()
        entry={"sha256":sha256(path),"bytes":path.stat().st_size}
        if rel in row_counts: entry["rows"]=int(row_counts[rel])
        files[rel]=entry
    return files
