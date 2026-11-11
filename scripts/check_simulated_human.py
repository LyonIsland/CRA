"""Scheduling regressions: disconnect, pause, reset and exactly-once action."""
import unittest
from simulated_human import SimulatedHuman

class SchedulerChecks(unittest.TestCase):
    def test_no_action_without_permission(self):
        h=SimulatedHuman(response_seconds=.5,action_seconds=.5)
        for _ in range(100):self.assertIsNone(h.advance(1,.25,False))
        self.assertEqual(h.elapsed,0.)
        h.enabled=False
        for _ in range(100):self.assertIsNone(h.advance(1,.25,True))
        self.assertEqual(h.elapsed,0.)

    def test_pause_preserves_remaining_time_and_action_once(self):
        h=SimulatedHuman(response_seconds=.5,action_seconds=.5)
        self.assertEqual(h.advance(1,.25,True),'announced')
        for _ in range(40):self.assertIsNone(h.advance(1,.25,False))
        events=[h.advance(1,.25,True) for _ in range(20)]
        self.assertEqual([e for e in events if e],['action_started','action_completed'])

    def test_reset_cancels_previous_request(self):
        h=SimulatedHuman(response_seconds=.5,action_seconds=.5)
        for _ in range(3):h.advance(1,.25,True)
        h.reset()
        self.assertIsNone(h.advance(None,.25,True))
        self.assertEqual(h.advance(2,.25,True),'announced')
        self.assertFalse(h.applied)

if __name__=='__main__':unittest.main()
