"""Tests for worker/gander-worker.mjs, the Worker that files what the page
sends as issues. Its own tests (worker/test/) run here too, and then the two
ends are joined: what the Worker files must read, in tools/gander_submit.py,
exactly as the block it was given.

Needs Node.js. Run: python -m unittest discover -s mods/classic/tests/tools"""
import json
import pathlib
import shutil
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gander_submit as gs  # noqa: E402
import test_gander_site as site  # noqa: E402

NODE = shutil.which("node")
NOW = site.NOW

# What Gander's /gander send makes: stats, with every kind of value.
STATS = {
    "format": 1, "game": "forever", "locale": "enUS",
    "mobs": {
        "3238": {"name": "Stormhide",
                 "levels": {"22": {"at": NOW - 5000, "v": {"spd": 2, "def": 110, "armor": 912, "dmin": 30.5,
                                                             "dmax": 41.25, "r2": 14, "run": 8, "class": "WARRIOR",
                                                             "ty": "Beast", "fam": "Wind Serpent",
                                                             "z": "The Barrens"}},
                            "-1": {"at": NOW - 4000, "v": {"spd": 2.6, "rk": "elite"}}},
                 "spells": {"5401": {"n": 4, "spawns": 2, "at": "2026-11-24", "build": "1.60.1"}}},
        "5757": {"name": "Lilly", "levels": {"5": {"at": NOW - 3000, "v": {"spd": 2}}}},
        "6497": {"levels": {"12": {"at": NOW - 2000, "v": {"hp": 320, "pow": 150}}}},
    },
    "spells": {"5401": "Lizard Bolt"},
    "instances": {"48": {"minutes": 24.7, "name": "Blackfathom Deeps"}},
}


@unittest.skipUnless(NODE, "Node.js isn't installed")
class Worker(unittest.TestCase):
    maxDiff = None

    def test_the_workers_own_tests_pass(self):
        done = subprocess.run([NODE, "--test", str(REPO / "worker" / "test" / "worker.test.mjs")],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(done.returncode, 0, done.stdout[-3000:] + done.stderr[-1000:])

    def file(self, blocks):
        done = subprocess.run([NODE, str(ROOT / "tests" / "site" / "file_blocks.mjs")], input=json.dumps(blocks),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def blocks(self):
        """The page's blocks from sample logs, and a block of stats as Gander makes it."""
        job = {"logs": [{"pieces": ["\r\n".join(log) + "\r\n"], "year": 2026}
                        for log in (site.fight(), site.awkward(), site.classic())]}
        done = subprocess.run([NODE, str(site.DRIVER)], input=json.dumps(job), capture_output=True, text=True,
                              encoding="utf-8")
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)["blocks"] + [json.dumps(STATS)]

    def test_what_the_worker_files_reads_exactly_as_what_it_was_given(self):
        blocks = self.blocks()
        self.assertEqual(len(blocks), 3)
        for text, filed in zip(blocks, self.file(blocks)):
            self.assertEqual((filed["status"], filed["labels"]), (200, ["gander-data"]))
            want = gs.validate(json.loads(text), NOW)
            self.assertEqual(want[1], 0, "the sample block itself should be clean")
            sub = gs.parse_body(filed["body"])
            self.assertEqual(gs.validate(sub, NOW), want)

    def test_the_stamp_the_worker_adds_is_believed_only_on_the_owners_issues(self):
        filed = self.file(self.blocks()[-1:])[0]
        sub = gs.parse_body(filed["body"])
        self.assertRegex(sub["sender"], gs.STAMP)
        from_page = gs.sender_of({"author_association": "OWNER", "user": {"id": 7}}, sub)
        self.assertEqual(from_page, gs.scramble("gander-sender:w:" + sub["sender"], 12))
        by_hand = gs.sender_of({"author_association": "NONE", "user": {"id": 7}}, sub)
        self.assertEqual(by_hand, gs.scramble("gander-sender:gh:7", 12))

    def test_a_block_with_nothing_usable_is_refused(self):
        filed = self.file([json.dumps({"format": 1, "game": "forever", "mobs": {"x": {}}}), "not a block"])
        self.assertEqual([(f["status"], f["body"]) for f in filed], [(400, None), (400, None)])


if __name__ == "__main__":
    unittest.main()
