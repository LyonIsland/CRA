"""Monitor isolation and path-boundary regression checks."""
import json
from pathlib import Path
import tempfile
import unittest
from grasp_reports import progress


class Checks(unittest.TestCase):
    def test_progress_excludes_private_evaluator_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);report=root/'report';report.mkdir()
            batch=root/'batch';run=batch/'102';run.mkdir(parents=True)
            (report/'progress-source.json').write_text(json.dumps({'evaluation':'batch'}))
            (batch/'summary.json').write_text(json.dumps({'planned_seeds':[101,102],
                'runs':[{'seed':101,'success':False}],'complete':False}))
            (run/'status.json').write_text(json.dumps({'step':40,'phase':'visual_servo','positions':[[1,2,3]]}))
            (run/'evaluation-only.json').write_text('invalid private evaluator data')
            value,frame=progress(report,root)
            self.assertEqual(value['completed'],1);self.assertEqual(value['successes'],0)
            self.assertEqual(value['seed'],102);self.assertEqual(frame,(run/'wrist.png').resolve())
            self.assertNotIn('positions',value)

    def test_pointer_cannot_escape_experiment_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);report=root/'report';report.mkdir()
            (report/'progress-source.json').write_text(json.dumps({'evaluation':'../outside'}))
            with self.assertRaises(ValueError):progress(report,root)


if __name__=='__main__':unittest.main()
