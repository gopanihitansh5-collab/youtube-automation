import ast
import pathlib
import unittest

class ReviewerModelListTests(unittest.TestCase):
    def test_exact_verified_free_rails(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        tree = ast.parse((root/'long-videos/reviewer_agents.py').read_text())
        lists = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.List):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in ('models','or_models'):
                        lists[target.id] = ast.literal_eval(node.value)
        self.assertEqual(lists['models'], ['openai/gpt-oss-120b','openai/gpt-oss-20b'])
        self.assertEqual(lists['or_models'], ['nvidia/nemotron-3-super-120b-a12b:free',
                        'google/gemma-4-31b-it:free','google/gemma-4-26b-a4b-it:free'])
        self.assertTrue(all(m.endswith(':free') for m in lists['or_models']))

if __name__ == '__main__': unittest.main()
