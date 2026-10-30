import unittest
from unittest.mock import patch

import manual_input


class ManualInputTests(unittest.TestCase):
    def run_manual(self, change, volume):
        prompts = []

        def respond(prompt):
            prompts.append(prompt)
            answers = {
                "收盘点位": "3599.02",
                "涨跌幅": str(change),
                "成交额": str(volume),
                "上涨家数": "1000",
                "下跌家数": "4000",
                "涨停家数": "20",
                "跌停家数": "50",
                "净流入": "0",
                "融资余额变化": "10",
                "是否保存": "y",
            }
            for label, answer in answers.items():
                if label in prompt:
                    return answer
            self.fail(f"Unexpected input prompt: {prompt}")

        with (
            patch("builtins.input", side_effect=respond),
            patch("builtins.print"),
            patch("sentiment_tracker.SentimentTracker") as tracker_class,
        ):
            manual_input.main()
        result = tracker_class.return_value.save_result.call_args.args[0]
        return result, prompts

    def test_rising_volume_strengthens_positive_confirmation(self):
        low, _ = self.run_manual(1.0, 5000)
        high, _ = self.run_manual(1.0, 15000)

        self.assertGreater(low["components"]["volume_change"], 50)
        self.assertGreater(high["components"]["volume_change"], low["components"]["volume_change"])

    def test_falling_volume_strengthens_negative_confirmation(self):
        low, _ = self.run_manual(-1.0, 5000)
        high, _ = self.run_manual(-1.0, 15000)

        self.assertLess(low["components"]["volume_change"], 50)
        self.assertLess(high["components"]["volume_change"], low["components"]["volume_change"])

    def test_flat_day_volume_is_neutral(self):
        for amount in [3000, 15000, 20000]:
            with self.subTest(amount=amount):
                result, _ = self.run_manual(0.0, amount)
                self.assertEqual(result["components"]["volume_change"], 50)

    def test_north_is_excluded_and_manual_model_is_tagged(self):
        result, prompts = self.run_manual(-1.0, 15000)

        self.assertFalse(any("净流入" in prompt or "北向" in prompt for prompt in prompts))
        self.assertIsNone(result["components"]["north_flow"])
        self.assertFalse(result["component_availability"]["north_flow"])
        self.assertNotIn("north_flow", result["component_weights"])
        self.assertIsNone(result["raw_data"]["north_flow"])
        self.assertEqual(result["raw_data"]["north_source"], "excluded_unverified_proxy")
        self.assertTrue(result["model_version"].endswith("-manual"))
        self.assertEqual(result["available_components"], 5)


if __name__ == "__main__":
    unittest.main()
