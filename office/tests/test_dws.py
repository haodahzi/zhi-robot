import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dws_client as d  # noqa: E402


def fake(stdout="{}", code=0, calls=None):
    def runner(cmd, **kw):
        if calls is not None:
            calls.append(cmd)
        return subprocess.CompletedProcess(cmd, code, stdout, "boom")
    return runner


class DwsTest(unittest.TestCase):
    def test_to_iso_and_day_range(self):
        self.assertEqual(d.to_iso("2026-03-10 14:00"), "2026-03-10T14:00:00+08:00")
        self.assertEqual(d.day_range("2026-03-10"), ("2026-03-10T00:00:00+08:00", "2026-03-10T23:59:59+08:00"))

    def test_find_person_parses_nested(self):
        r = fake('{"result":{"list":[{"userId":"u1","name":"张三"}]}}')
        self.assertEqual(d.find_person("张三", r)[0]["userId"], "u1")

    def test_create_event_args_are_a_list_with_yes(self):
        calls = []
        d.create_event("周会", "S", "E", ["u1", "u2"], ["r1"], "", fake(calls=calls))
        c = calls[0]
        self.assertEqual(c[:4], ["dws", "calendar", "event", "create"])
        self.assertIn("u1,u2", c)
        self.assertIn("r1", c)
        self.assertIn("--yes", c)

    def test_errors(self):
        with self.assertRaises(d.DwsError):
            d.run(["x"], fake(code=1))
        with self.assertRaises(d.DwsError):
            d.run(["x"], fake("not json"))


if __name__ == "__main__":
    unittest.main()
