import json
import unittest
from itertools import product

from proof_loop.finite_matching import check_matching


class FiniteMatchingTests(unittest.TestCase):
    def check_graph(self, left, right, edges):
        document = {"instances": [{"name": "sample", "left": left, "right": right,
                                    "edges": [[left[i], right[j]] for i, j in edges]}]}
        result = check_matching(json.dumps(document), 2)
        self.assertEqual(result["status"], "completed")
        return json.loads(result["output"])["cases"][0]

    def test_complete_and_hall_witness(self):
        complete = self.check_graph(["a", "b"], ["x", "y"], {(0, 0), (0, 1), (1, 1)})
        self.assertTrue(complete["all_left_matched"])
        self.assertEqual(complete["maximum_matching_size"], 2)
        self.assertEqual(len(complete["matching"]), 2)
        self.assertEqual(len({pair[0] for pair in complete["matching"]}), 2)
        self.assertEqual(len({pair[1] for pair in complete["matching"]}), 2)
        failed = self.check_graph(["a", "b", "c"], ["x", "y"], {(0, 0), (1, 0), (2, 1)})
        self.assertFalse(failed["all_left_matched"])
        witness = failed["hall_witness"]
        self.assertEqual(set(witness["left"]), {"a", "b"})
        self.assertEqual(set(witness["neighbors"]), {"x"})
        self.assertEqual(witness["deficiency"], 1)

    def test_all_small_graphs_against_brute_force(self):
        left = ["a", "b", "c"]
        right = ["x", "y", "z"]
        possible = list(product(range(3), repeat=2))
        for mask in range(1 << len(possible)):
            edges = {edge for i, edge in enumerate(possible) if mask & (1 << i)}
            result = self.check_graph(left, right, edges)
            self.assertEqual(len(result["matching"]), result["maximum_matching_size"])
            self.assertTrue(all((left.index(a), right.index(b)) in edges for a, b in result["matching"]))
            self.assertEqual(len({a for a, _ in result["matching"]}), len(result["matching"]))
            self.assertEqual(len({b for _, b in result["matching"]}), len(result["matching"]))

            def brute(index, used):
                if index == len(left):
                    return True
                return any(j not in used and brute(index + 1, used | {j})
                           for i, j in edges if i == index)

            self.assertEqual(result["all_left_matched"], brute(0, set()))
            if not result["all_left_matched"]:
                witness = result["hall_witness"]
                neighbors = {right[j] for i, j in edges if left[i] in witness["left"]}
                self.assertEqual(neighbors, set(witness["neighbors"]))
                self.assertGreater(len(witness["left"]), len(neighbors))

    def test_rejects_invalid_edge(self):
        result = check_matching(json.dumps({"instances": [{"name": "bad", "left": ["a"],
                                             "right": ["x"], "edges": [["a", "missing"]]}]}), 2)
        self.assertEqual(result["status"], "failed")


if __name__ == "__main__":
    unittest.main()
