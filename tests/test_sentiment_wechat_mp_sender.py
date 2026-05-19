import unittest
from unittest.mock import patch

from sentiment_wechat_mp_sender import (
    generate_article,
    get_thumb_media_id,
    send_wechat_mp_report,
)


class WechatMpSenderTests(unittest.TestCase):
    def sample_data(self):
        return {
            "date": "2026-05-19",
            "sentiment_score": 58.42,
            "sentiment_level": "中性",
            "coverage": 0.85,
            "available_components": 6,
            "components": {
                "market_breadth": 62.1,
                "cross_section": 55.3,
                "volume_change": 48.9,
                "volatility": 60.2,
                "north_flow": 50.0,
                "margin_trading": 51.7,
                "trend": 59.4,
            },
            "raw_data": {
                "index_close": 3889.08,
                "index_change": 1.23,
                "daily_return": 0.0123,
                "amount": 1_250_000_000_000,
            },
        }

    def test_generate_article_contains_summary(self):
        article = generate_article(self.sample_data(), {"author": "持志堂", "content_source_url": ""})

        self.assertIn("A股情绪指标日报", article["title"])
        self.assertIn("58.42", article["digest"])
        self.assertIn("市场广度", article["content"])
        self.assertEqual(article["author"], "持志堂")

    def test_get_thumb_media_id_prefers_configured_media(self):
        media_id = get_thumb_media_id("token", {"thumb_media_id": "media-123"})

        self.assertEqual(media_id, "media-123")

    def test_send_wechat_mp_report_skips_without_credentials(self):
        result = send_wechat_mp_report(self.sample_data(), {"appid": "", "secret": ""})

        self.assertFalse(result)

    def test_send_wechat_mp_report_creates_draft(self):
        config = {
            "appid": "appid",
            "secret": "secret",
            "author": "持志堂",
            "thumb_media_id": "thumb",
            "content_source_url": "",
            "auto_publish": False,
            "auto_mass_send": False,
            "timeout": 3,
        }
        with (
            patch("sentiment_wechat_mp_sender.get_access_token", return_value="token") as get_token,
            patch("sentiment_wechat_mp_sender.create_draft", return_value="draft-media") as create_draft,
        ):
            result = send_wechat_mp_report(self.sample_data(), config)

        self.assertTrue(result)
        get_token.assert_called_once()
        create_draft.assert_called_once()


if __name__ == "__main__":
    unittest.main()
