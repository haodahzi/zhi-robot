import base64
import hashlib
import hmac
import os
import sys
import unittest
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import DingTalkConfig, PendingStore, build_webhook_url, send_group_text, sign  # noqa: E402


class SignTest(unittest.TestCase):
    def test_sign_matches_reference_algorithm(self):
        secret, ts = "SEC123", 1700000000000
        expected = urllib.parse.quote_plus(base64.b64encode(
            hmac.new(secret.encode(), f"{ts}\n{secret}".encode(), hashlib.sha256).digest()))
        self.assertEqual(sign(secret, ts), expected)

    def test_build_url_with_and_without_secret(self):
        self.assertEqual(build_webhook_url("https://x/send?access_token=T", None), "https://x/send?access_token=T")
        url = build_webhook_url("https://x/send?access_token=T", "S", 5)
        self.assertTrue(url.startswith("https://x/send?access_token=T&timestamp=5&sign="))


class SendTest(unittest.TestCase):
    def test_keyword_is_prepended_when_missing(self):
        sent = {}
        def poster(url, payload):
            sent["payload"] = payload
            return {"errcode": 0}
        send_group_text(DingTalkConfig("https://x/send?access_token=T", None, "机器人"), "开会了", poster)
        self.assertEqual(sent["payload"]["text"]["content"], "机器人 开会了")
        send_group_text(DingTalkConfig("https://x/send?access_token=T", None, "机器人"), "机器人说开会了", poster)
        self.assertEqual(sent["payload"]["text"]["content"], "机器人说开会了")


class PendingTest(unittest.TestCase):
    def test_code_is_single_use_and_expires(self):
        store = PendingStore(ttl=10)
        code = store.add("k", {"a": 1}, now=100)
        self.assertEqual(store.pop(code, now=105), ("k", {"a": 1}))
        self.assertIsNone(store.pop(code, now=106))  # 一次有效
        code2 = store.add("k", {}, now=200)
        self.assertIsNone(store.pop(code2, now=211))  # 超时作废


if __name__ == "__main__":
    unittest.main()
