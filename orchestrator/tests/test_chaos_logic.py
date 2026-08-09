import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.chaos_logic import Action, ExperimentState, next_action, is_expired

class TestChaosLogic(unittest.TestCase):
  def test_healthy_and_never_down_is_noop(self):
    state = ExperimentState(healthy=True, down_at=None, recovered_at=None)
    action, mttr = next_action(state, now=100.0)
    self.assertEqual(action, Action.NOOP)
    self.assertIsNone(mttr)

  def test_goes_unhealthy_marks_down_and_restarts(self):
    state = ExperimentState(healthy=False, down_at=None, recovered_at=None)
    action, mttr = next_action(state, now=100.0)
    self.assertEqual(action, Action.MARK_DOWN_AND_RESTART)
    self.assertIsNone(mttr)

  def test_still_down_after_being_marked_is_noop(self):
    state = ExperimentState(healthy=False, down_at=100.0, recovered_at=None)
    action, mttr = next_action(state, now=105.0)
    self.assertEqual(action, Action.NOOP)
    self.assertIsNone(mttr)

  def test_recovery_computes_correct_mttr(self):
    state = ExperimentState(healthy=True, down_at=100.0, recovered_at=None)
    action, mttr = next_action(state, now=107.5)
    self.assertEqual(action, Action.MARK_RECOVERED)
    self.assertAlmostEqual(mttr, 7.5)

  def test_already_recovered_is_always_noop_even_if_reported_unhealthy_again(self):
    state = ExperimentState(healthy=False, down_at=100.0, recovered_at=110.0)
    action, mttr = next_action(state, now=200.0)
    self.assertEqual(action, Action.NOOP)
    self.assertIsNone(mttr)

  def test_zero_second_recovery_is_valid(self):
    state = ExperimentState(healthy=True, down_at=100.0, recovered_at=None)
    action, mttr = next_action(state, now=100.0)
    self.assertEqual(action, Action.MARK_RECOVERED)
    self.assertEqual(mttr, 0.0)

class TestTTLExpiry(unittest.TestCase):
  def test_not_expired_before_deadline(self):
    self.assertFalse(is_expired(expires_at=200.0, now=100.0))

  def test_expired_after_deadline(self):
    self.assertTrue(is_expired(expires_at=100.0, now=200.0))

  def test_exactly_at_deadline_counts_as_expired(self):
    self.assertTrue(is_expired(expires_at=100.0, now=100.0))

if __name__ == "__main__":
  unittest.main()


