import sys
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'redesign'))
import formal_rides as study
import ride_agent as agent


class FinalProtocolTests(unittest.TestCase):
    def test_gate_counts_swapped_pairs_and_individual_mechanical_faults(self):
        rows={key:dict(stable_pair_correct=3,correct_single=6) for key in study.CORE}
        rows['feet_raised']['stable_pair_correct']=2
        self.assertTrue(study.calibration_gate(rows,3))
        rows['wheel_reversed']['stable_pair_correct']=2
        self.assertFalse(study.calibration_gate(rows,3))
        rows['wheel_reversed']['stable_pair_correct']=3
        rows['crank_stopped']['correct_single']=4
        self.assertFalse(study.calibration_gate(rows,3))

    def test_budget_and_strategy_switch_on_unlaunchable_source(self):
        inputs=[]
        def respond(slot,model,rule,message,temperature):
            inputs.append((slot,model,rule,message))
            return '<html><body><!-- REPAIR_STRATEGY=fix_module -->Example</body></html>'
        fake=SimpleNamespace(final_call=respond)
        def measured(slot,vehicle,protocol):
            return dict(course=False,mechanics=False,checks={},issues=['Module missing'])
        with TemporaryDirectory() as tmp,patch.object(agent,'MODEL','qwen3.8-flash'),patch.object(agent,'final_measure',measured):
            dest=Path(tmp)
            agent.run_final_start(dest,'qwen3.8-flash','toucan','tricycle',fake)
            self.assertEqual(len(inputs),10)
            self.assertEqual(len(set(item[1] for item in inputs)),1)
            self.assertEqual(len({item[3] for item in inputs[:7]}),1)
            self.assertNotIn('cyclePose',inputs[1][2])
            self.assertIn('cyclePose',inputs[4][2])
            self.assertEqual(study.read_json(dest/'D/try-2/invalid.json')['reason'],'Missing or repeated strategy: fix_module')
            self.assertEqual(set(study.read_json(dest/'selected.json')),set('ABCD'))
            agent.run_final_start(dest,'qwen3.8-flash','toucan','tricycle',fake)
            self.assertEqual(len(inputs),10)

    def test_static_review_skip_is_not_recorded_as_a_tie(self):
        with TemporaryDirectory() as tmp,patch.object(study,'FINAL_ROOT',Path(tmp)):
            study.write_json(study.FINAL_ROOT/'protocol/gate.json',dict(passed=True,version=0))
            entry=(study.FINAL_MODELS[0],'toucan','tricycle',1)
            folder=study.case_folder(entry)
            study.write_json(folder/'selected.json',{a:dict(path='A',sha256=None,measurement=dict(course=False,mechanics=False,observed=False)) for a in 'ABCD'})
            with patch.object(study,'judge',side_effect=AssertionError('Static inputs must skip visual calls')):
                study.study_scores(entry)
            result=study.read_json(study.FINAL_ROOT/'evaluation'/entry[0]/'toucan-tricycle-01/summary.json')
            self.assertTrue(all(r['verdict']=='unavailable' for r in result['pairs'].values()))
            self.assertTrue(all('skipped' in r['status'] for r in result['singles'].values()))
