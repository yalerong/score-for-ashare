import json
from pathlib import Path
import tempfile
import unittest

from market_sentiment_evaluator import load_sentiment_history


class EvaluationModelTests(unittest.TestCase):
    def read(self, versions):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            rows = []
            for index, version in enumerate(versions):
                record = {"date": f"2026-09-{index + 1:02d}", "sentiment_score": 40 + index}
                if version is not None:
                    record["model_version"] = version
                rows.append(record)
            path.write_text(json.dumps(rows), encoding="utf-8")
            return load_sentiment_history(path)

    def test_rejects_mixed_versions_including_untagged_legacy(self):
        for versions in [(None, "2.0-directional-volume"), ("1", "2"), ("2", "2-manual")]:
            with self.subTest(versions=versions):
                with self.assertRaisesRegex(ValueError, "[Mm]odel|版本"):
                    self.read(versions)

    def test_accepts_one_version_or_all_legacy(self):
        self.assertEqual(len(self.read(["2.0-directional-volume"] * 2)), 2)
        self.assertEqual(len(self.read([None, None])), 2)


if __name__ == "__main__":
    unittest.main()
