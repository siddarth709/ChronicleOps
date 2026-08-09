import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.incident_matching import rank_similar_incidents, tokenize

class TestTokenize(unittest.TestCase):
  def test_ignores_short_tokens_and_punctuation(self):
    tokens = tokenize("Error: DB connection lost at 03:14, retrying x2!")
    self.assertIn("error", tokens)
    self.assertIn("connection", tokens)
    self.assertIn("retrying", tokens)
    self.assertNotIn("x2", tokens)

  def test_empty_input(self):
    self.assertEqual(tokenize(""), [])
    self.assertEqual(tokenize(None), [])

class TestRankSimilarIncidents(unittest.TestCase):
  def setUp(self):
    self.past_incidents = [
      {
        "id": "inc-1",
        "log_excerpt": "connection refused to postgres database timeout after 30 seconds pool exhausted",
      },
      {
        "id": "inc-2",
        "log_excerpt": "out of memory killed process oom killer invoked cgroup limit exceeded",
      },
      {
        "id": "inc-3",
        "log_excerpt": "connection refused to postgres timeout pool exhausted retry failed",
      }
    ]
  
  def test_empty_history_returns_empty(self):
    self.assertEqual(rank_similar_incidents("anything", []), [])

  def test_matches_relevant_incident_higher_than_unrelated_one(self):
    query = "postgres connection timeout pool exhausted database refused"
    ranked = rank_similar_incidents(query, self.past_incidents, top_k=3)
    ids_in_order = [r["id"] for r in ranked]
    self.assertLess(ids_in_order.index("inc-2"), 999)
    oom_rank = ids_in_order.index("inc-2")
    db_ranks = [ids_in_order.index("inc-1"), ids_in_order.index("inc-3")]
    self.assertTrue(all(r < oom_rank for r in db_ranks))

  def test_respects_top_k(self):
    ranked = rank_similar_incidents("postgres timeout", self.past_incidents, top_k=1)
    self.assertEqual(len(ranked), 1)

  def test_similarity_score_is_included_and_bounded_reasonably(self):
    ranked = rank_similar_incidents("postgres timeout pool", self.past_incidents, top_k=3)
    for r in ranked:
      self.assertIn("similarity", r)
      self.assertGreaterEqual(r["similarity"], 0.0)

if __name__ == "__main__":
  unittest.main()


