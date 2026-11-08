"""Focused regression and acceptance checks; runnable with stdlib unittest."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.generator import generate
from src.mastery import compute_mastery, active_prerequisites
from src.recommender import recommend
from src.validation import validate, run_anomaly_suite
from src.evaluation import derive_outcomes
from src.exports import build_sqlite
from src.pipeline import run_pipeline

ROOT=Path(__file__).resolve().parents[1]


class LearningPipelineChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables=generate(40,20,80,8,20261022)
        cls.recs,cls.paths,cls.baseline,cls.decisions,cls.events=recommend(cls.tables,"snapshot-test")

    def test_baseline_constraints_and_coverage(self):
        t=self.tables
        self.assertEqual(validate(t,pd.concat([self.recs,self.baseline],ignore_index=True),self.paths,self.decisions,self.events),[])
        self.assertEqual(len(t["attempts"]),280)
        self.assertTrue((t["attempts"].groupby(["learner_id","content_id"]).size()>1).any())
        self.assertGreater(len(t["content_skills"]),len(t["content_items"]))
        self.assertEqual(set(t["content_items"].content_type),{"Video","PDF","Quiz","Exercise","Project"})
        by_difficulty=t["attempts"].merge(t["content_items"][["content_id","difficulty_level"]],on="content_id").groupby("difficulty_level").score.mean()
        self.assertGreater(by_difficulty["Beginner"],by_difficulty["Advanced"])
        repeated=t["attempts"].sort_values("attempt_number").groupby(["learner_id","content_id"]).score.agg(["first","last","count"])
        repeated=repeated[repeated["count"]>1]
        self.assertGreater(repeated["last"].mean(),repeated["first"].mean())
        self.assertEqual(set(t["skills"].track_id),set(t["learners"].track_id))
        self.assertGreater(self.recs.content_id.nunique(),3)
        learner_tracks=t["learners"].set_index("learner_id").track_id
        skill_tracks=t["skills"].set_index("skill_id").track_id
        self.assertTrue(all(learner_tracks[r.learner_id]==skill_tracks[r.skill_id] for r in self.recs.itertuples()))
        self.assertEqual(t["learners"].loc[~t["learners"].learner_id.isin(t["attempts"].learner_id),"track_id"].nunique(),5)

    def test_mastery_is_asof_learner_scoped_and_future_invariant(self):
        t=self.tables; learner=t["attempts"].learner_id.iloc[0]
        asof=t["attempts"].loc[t["attempts"].learner_id.eq(learner),"attempted_at"].iloc[1]
        before=compute_mastery(t,learner,asof)
        changed={k:v.copy() for k,v in t.items()}
        row=t["attempts"].loc[t["attempts"].learner_id.eq(learner)].iloc[-1].to_dict()
        row.update(attempt_id="ATT-LRN-000001-999999",attempt_number=999999,attempted_at="2030-01-01T00:00:00+00:00",score=.99)
        changed["attempts"]=pd.concat([changed["attempts"],pd.DataFrame([row])],ignore_index=True)
        changed["assessment_results"]=pd.concat([changed["assessment_results"],pd.DataFrame([{"assessment_id":row["attempt_id"],"score":.99,"assessment_type":"ActivityScore"}])],ignore_index=True)
        self.assertEqual(before,compute_mastery(changed,learner,asof))
        self.assertTrue(all(x.startswith(f"ATT-{learner}-") for v in before.values() for x in v["attempt_ids"]))
        other_learner=t["attempts"].learner_id.unique()[1]
        other=compute_mastery(t,other_learner,asof)
        self.assertTrue(all(x.startswith(f"ATT-{other_learner}-") for v in other.values() for x in v["attempt_ids"]))

    def test_future_evidence_and_fabricated_mastery_are_rejected(self):
        learner=self.tables["attempts"].iloc[0].learner_id
        evidence=self.tables["attempts"].loc[self.tables["attempts"].learner_id.eq(learner)].iloc[0]
        skill=self.tables["content_skills"].loc[self.tables["content_skills"].content_id.eq(evidence.content_id),"skill_id"].iloc[0]
        sample=self.recs.iloc[0:1].copy()
        sample.loc[sample.index[0],"learner_id"]=learner
        sample.loc[sample.index[0],"skill_id"]=skill
        sample.loc[sample.index[0],"mapped_skill_ids"]=json.dumps([skill])
        sample.loc[sample.index[0],"evidence_attempt_ids"]=json.dumps([evidence.attempt_id])
        sample.loc[sample.index[0],"evidence_assessment_ids"]=json.dumps([evidence.attempt_id])
        sample.loc[sample.index[0],"recommended_at"]="2025-12-31T00:00:00+00:00"
        sample.loc[sample.index[0],"mastery_at_recommendation"]=1.0
        paths=self.paths[self.paths.recommendation_id.isin(sample.recommendation_id)].copy()
        codes={x["issue_type"] for x in validate(self.tables,sample,paths)}
        self.assertIn("TEMPORAL_LEAKAGE",codes)
        self.assertIn("MASTERY_RECONCILIATION_FAILED",codes)

    def test_effective_edges_and_graph_cycles(self):
        edge=self.tables["skill_prerequisites"].iloc[0:1].copy()
        edge.loc[edge.index[0],"effective_from"]="2027-01-01"
        self.assertEqual(active_prerequisites(edge,"2026-12-31T23:59:59Z"),[])
        edge.loc[edge.index[0],"effective_from"]="2026-01-01"; edge.loc[edge.index[0],"effective_to"]="2026-02-01"
        self.assertEqual(len(active_prerequisites(edge,"2026-01-31T23:59:59Z")),1)
        self.assertEqual(active_prerequisites(edge,"2026-02-01T00:00:00Z"),[])
        bad={k:v.copy() for k,v in self.tables.items()}
        bad["skill_prerequisites"].loc[bad["skill_prerequisites"].index[0],"prerequisite_skill_id"]=bad["skill_prerequisites"].iloc[0].skill_id
        codes={x["issue_type"] for x in validate(bad)}
        self.assertTrue({"SELF_PREREQUISITE","PREREQUISITE_CYCLE"}&codes)

    def test_nm_order_independent_and_unmet_skill_blocks_item(self):
        t={k:v.copy() for k,v in self.tables.items()}
        edge=t["skill_prerequisites"].iloc[0]; child=edge.skill_id
        child_track=t["skills"].set_index("skill_id").loc[child,"track_id"]
        cold=next(x for x in t["learners"].learner_id if t["learners"].set_index("learner_id").loc[x,"track_id"]==child_track and x not in set(t["attempts"].learner_id))
        content=t["content_skills"].loc[t["content_skills"].skill_id.eq(child),"content_id"].iloc[0]
        pair=t["content_skills"].loc[t["content_skills"].content_id.eq(content),"skill_id"]
        if edge.prerequisite_skill_id not in set(pair):
            t["content_skills"]=pd.concat([t["content_skills"],pd.DataFrame([{"content_skill_id":"CSM-999999","content_id":content,"skill_id":edge.prerequisite_skill_id}])],ignore_index=True)
        r1,*_=recommend(t,"snapshot-test")
        self.assertFalse(((r1.learner_id==cold)&(r1.content_id==content)).any())
        t["content_skills"]=t["content_skills"].iloc[::-1].reset_index(drop=True)
        r2,*_=recommend(t,"snapshot-test")
        cols=["learner_id","content_id","skill_id","rank","reason_code"]
        pd.testing.assert_frame_equal(r1[cols].reset_index(drop=True),r2[cols].reset_index(drop=True))

    def test_empty_candidate_and_lifecycle_decisions(self):
        t={k:v.copy() for k,v in self.tables.items()}; t["content_items"].loc[:,"content_status"]="Inactive"
        recs,paths,base,decisions,events=recommend(t,"empty-snapshot")
        self.assertTrue(recs.empty and paths.empty and base.empty)
        self.assertIn("recommendation_id",recs.columns); self.assertIn("sequence_no",paths.columns)
        self.assertIn("NO_ELIGIBLE_CONTENT",set(decisions.decision_code))
        self.assertLessEqual(set(decisions.decision_code),{"NO_ELIGIBLE_CONTENT","ALL_TARGETS_MASTERED","PREREQUISITE_BLOCKED"})
        self.assertEqual(validate(t,pd.concat([recs,base]),paths,decisions,events),[])

    def test_invalid_values_mixed_timestamps_and_path_ownership(self):
        bad={k:v.copy() for k,v in self.tables.items()}
        bad["content_skills"].loc[bad["content_skills"].index[0],"skill_id"]=None
        bad["assessment_results"].loc[bad["assessment_results"].index[0],"score"]=99
        bad["attempts"].loc[bad["attempts"].index[0],"attempted_at"]="2026-01-01 00:00:00+00:00"
        codes={x["issue_type"] for x in validate(bad)}
        self.assertIn("REQUIRED_VALUE_MISSING",codes); self.assertIn("SCORE_OUT_OF_RANGE",codes)
        self.assertNotIn("INVALID_TIMESTAMP",codes)
        bad_path=self.paths.iloc[0:1].copy(); bad_path.loc[bad_path.index[0],"learner_id"]="LRN-999999"
        self.assertIn("INVALID_FOREIGN_KEY",{x["issue_type"] for x in validate(self.tables,self.recs,bad_path)})

    def test_recommendations_stay_within_the_learner_track(self):
        bad_rec=self.recs.iloc[0:1].copy()
        skill_track=self.tables["skills"].set_index("skill_id").loc[bad_rec.iloc[0].skill_id,"track_id"]
        other_track=next(x for x in self.tables["learners"].track_id.unique() if x!=skill_track)
        learner=self.tables["learners"].loc[self.tables["learners"].track_id.eq(other_track),"learner_id"].iloc[0]
        bad_rec.loc[bad_rec.index[0],"learner_id"]=learner
        self.assertIn("TRACK_SKILL_MISMATCH",{x["issue_type"] for x in validate(self.tables,bad_rec)})

    def test_all_five_negative_scenarios_execute(self):
        result=run_anomaly_suite(self.tables,self.recs,self.paths)
        self.assertEqual(len(result),5); self.assertTrue(result.result.eq("PASS").all())

    def test_outcomes_reference_real_later_events(self):
        outcomes=derive_outcomes(self.recs,self.tables)
        self.assertEqual(set(outcomes.recommendation_id),set(self.recs.recommendation_id))
        linked=outcomes[outcomes.ground_truth_label.ne("NO_FOLLOWUP")]
        self.assertTrue(set(linked.followup_attempt_id)<=set(self.tables["attempts"].attempt_id))
        self.assertTrue(set(linked.followup_assessment_id)<=set(self.tables["assessment_results"].assessment_id))
        self.assertTrue((pd.to_datetime(linked.followup_at,utc=True)>pd.to_datetime(linked.observation_window_start,utc=True)).all())

    def test_sqlite_seed_constraints_and_reconciliations(self):
        outcomes=derive_outcomes(self.recs,self.tables); base_outcomes=derive_outcomes(self.baseline,self.tables)
        frames={"Learner":self.tables["learners"],"Course":self.tables["courses"],"Skill":self.tables["skills"],"SkillPrerequisite":self.tables["skill_prerequisites"],
                "ContentItem":self.tables["content_items"],"ContentSkill":self.tables["content_skills"],"Attempt":self.tables["attempts"],"AssessmentResult":self.tables["assessment_results"],
                "Recommendation":self.recs,"BaselinePolicyRecommendation":self.baseline,"LearningPath":self.paths,"LearnerDecision":self.decisions,"DomainEvent":self.events,"RecommendationOutcome":outcomes}
        with tempfile.TemporaryDirectory(dir=ROOT/"data") as d:
            db=Path(d)/"seed.sqlite"; result=build_sqlite(db,ROOT/"sql"/"schema.sql",frames)
            self.assertEqual(result["foreign_key_violation_count"],0); self.assertEqual(result["assessment_score_mismatch_count"],0)
            self.assertEqual(result["row_counts"]["Attempt"],len(self.tables["attempts"]))
            connection=sqlite3.connect(db)
            try: self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(),[])
            finally: connection.close()

    def test_invalid_master_does_not_publish_or_replace_current_pointer(self):
        bad={k:v.copy() for k,v in self.tables.items()}
        bad["content_skills"].loc[bad["content_skills"].index[0],"skill_id"]="SKL-999999"
        with tempfile.TemporaryDirectory(dir=ROOT/"data") as d:
            root=Path(d)/"runs"; root.mkdir(); pointer=root/"current_run.json"; pointer.write_text('{"current_run":"previous"}')
            with patch("src.pipeline.generate",return_value=bad):
                with self.assertRaises(ValueError): run_pipeline(False,20261022,root)
            self.assertEqual(json.loads(pointer.read_text())["current_run"],"previous")
            records=list((root/"executions").glob("*.json"))
            self.assertEqual(json.loads(records[0].read_text())["status"],"FAILED")
            self.assertEqual(list(root.glob("run-*")),[])


if __name__=="__main__":
    unittest.main()
