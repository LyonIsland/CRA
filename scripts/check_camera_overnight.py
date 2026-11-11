"""Supervisor control-flow checks with fake workers; no generated test data is retained."""
import argparse
import json
from pathlib import Path
import tempfile
import unittest
from camera_overnight import Supervisor,write_json


class OvernightChecks(unittest.TestCase):
    def supervisor(self,root):
        tasks=root/'tasks.json'
        write_json(tasks,{'train':['a','b'],'validation':['a','c']})
        return Supervisor(argparse.Namespace(out=root/'run',hours=1,frames=32,max_rounds=1,
                                            python=Path('python'),tasks=tasks))

    def worker(self,supervisor):
        calls=[]
        def fake(command,log,**kwargs):
            command=[str(x) for x in command];calls.append(command)
            if '--camera-output' in command:
                out=Path(command[command.index('--camera-output')+1]);out.mkdir(parents=True)
                write_json(out/'collection.json',{'mean_pixel_change':1.,'transitions':32})
            elif '--test-checkpoint' in command:
                write_json(Path(command[command.index('--out')+1]),{'test_only':True})
            else:
                out=Path(command[command.index('--out')+1]);out.mkdir(parents=True)
                score=.3 if 'initial-1e4' in str(out) else .2
                write_json(out/'report.json',{'best_metrics':{'selection_score':score}})
                (out/'best.pt').touch();(out/'encoder.pt').touch()
        supervisor.child=fake
        return calls

    def test_full_sequence_and_final_test_is_last(self):
        with tempfile.TemporaryDirectory() as directory:
            supervisor=self.supervisor(Path(directory));calls=self.worker(supervisor)
            supervisor.run()
            self.assertEqual(supervisor.status['stage'],'completed')
            self.assertEqual(supervisor.status['training_transitions'],8*32)
            self.assertIn('--test-checkpoint',calls[-1])
            training=[c for c in calls if '--epochs' in c]
            self.assertEqual(len(training),3)
            resumed=training[-1][training[-1].index('--resume')+1]
            self.assertIn('initial-3e4',resumed)
            self.assertTrue((supervisor.out/'latest.json').is_file())

    def test_stop_before_start_does_not_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            supervisor=self.supervisor(Path(directory));calls=self.worker(supervisor)
            (supervisor.out/'STOP').touch()
            with self.assertRaises(InterruptedError):supervisor.run()
            self.assertEqual(calls,[])
            self.assertEqual(supervisor.status['stage'],'stopped')

    def test_child_failure_is_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            supervisor=self.supervisor(Path(directory))
            def failure(*args,**kwargs):raise RuntimeError('owned worker failed')
            supervisor.child=failure
            with self.assertRaises(RuntimeError):supervisor.run()
            self.assertEqual(supervisor.status['stage'],'failed')
            self.assertIn('owned worker failed',(supervisor.out/'error.txt').read_text())


if __name__=='__main__':unittest.main()
