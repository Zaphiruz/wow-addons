"""Tests for site/gander-log.js, the combat log reader of the page players
send data from. It must read a log exactly as tools/gander_import.py does, and
every block it makes must pass tools/gander_submit.py's checks.

Needs Node.js. Run: python -m unittest discover -s mods/classic/tests/tools"""
import json
import pathlib
import shutil
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gander_import  # noqa: E402
import gander_submit as gs  # noqa: E402

DRIVER = ROOT / "tests" / "site" / "read_logs.js"
NODE = shutil.which("node")
NOW = 1795700000  # after the days the sample logs are from

HEADER = "11/24/2026 20:18:39.739-5  COMBAT_LOG_VERSION,22,ADVANCED_LOG_ENABLED,0,BUILD_VERSION,1.60.1,PROJECT_ID,18"
ZONE = '11/24/2026 20:18:39.740-5  ZONE_CHANGE,48,"Blackfathom Deeps",1'
MOB = 'Creature-0-6834-48-3652-4798-0002063119,"Fallenroot Shadowstalker",0x10a48,0x80000000'
MOB2 = 'Creature-0-6834-48-3652-4798-0000863119,"Fallenroot Shadowstalker",0xa48,0x80000000'
KELRIS = 'Creature-0-6834-48-3652-4832-0000063119,"Twilight Lord Kelris",0xa48,0x80000000'
PLAYER = 'Player-6933-004AF9C2,"Buffy-Mcbufferson-Normal-US",0x512,0x80000000'
TOTEM = 'Creature-0-6834-48-3652-2630-0000063786,"Earthbind Totem"'
NOBODY = "0000000000000000,nil,0x80000000,0x80000000"


def line(clock, event, source, dest, spell, name, tail="0x20", day="11/24/2026"):
    return f'{day} {clock}.000-5  {event},{source},{dest},{spell},"{name}",{tail}'


def fight():
    """The same fight the importer's tests read."""
    return [
        HEADER, ZONE,
        line("20:19:00", "SPELL_CAST_SUCCESS", MOB, PLAYER, 6205, "Curse of Weakness"),
        line("20:19:10", "SPELL_CAST_SUCCESS", MOB, PLAYER, 6205, "Curse of Weakness"),
        line("20:19:20", "SPELL_CAST_SUCCESS", MOB2, PLAYER, 6205, "Curse of Weakness"),
        line("20:19:30", "SPELL_AURA_APPLIED", MOB, PLAYER, 1604, "Dazed", "0x1,DEBUFF"),
        line("20:19:40", "SPELL_CAST_START", KELRIS, NOBODY, 8399, "Sleep"),
        line("20:19:50", "SPELL_AURA_APPLIED", KELRIS, PLAYER, 8399, "Sleep", "0x20,DEBUFF"),
        line("20:20:00", "SPELL_CAST_SUCCESS", PLAYER, MOB, 133, "Fireball"),
        line("20:20:01", "SPELL_SUMMON", PLAYER, TOTEM + ",0xa28,0x80000000", 2484, "Earthbind Totem"),
        line("20:20:02", "SPELL_AURA_APPLIED", TOTEM + ",0xa48,0x80000000", MOB, 3600, "Earthbind", "0x8,DEBUFF"),
        line("20:20:03", "SPELL_CAST_SUCCESS", TOTEM + ",0x2112,0x80000000", NOBODY, 3600, "Earthbind"),
        line("20:20:04", "SPELL_CAST_SUCCESS", 'Creature-0-6834-48-3652-900-0000063119,"Guard",0xa18,0x80000000',
             PLAYER, 55, "Guard Heal"),
        '11/24/2026 20:20:05.000-5  SWING_DAMAGE,' + MOB + "," + PLAYER + ",12,0",
    ]


def awkward():
    """Lines that are easy to read wrongly: commas and quotes inside names,
    travel between zones, long pauses, damaged lines and odd GUIDs."""
    loud = 'Creature-0-6834-1-3652-3273-0000063119,"Kolkar, the ""Loud""",0xa48,0x80000000'
    vehicle = 'Vehicle-0-6834-1-3652-7777-0000063119,"War Wagon",0xa48,0x80000000'
    pet = 'Pet-0-6834-1-3652-417-0000063119,"Jhuuroon",0x1112,0x80000000'
    short_guid = 'Creature-0-6834-1,"Broken",0xa48,0x80000000'
    bad_flags = 'Creature-0-6834-1-3652-3274-0000063119,"Kolkar Pack Runner",0xzz,0x80000000'
    minion = 'Creature-0-6834-1-3652-8888-0000099999,"Summoned Imp"'
    return [
        HEADER,
        '11/24/2026 21:00:00.000-5  ZONE_CHANGE,1,"The Barrens",0',
        line("21:00:05", "SPELL_CAST_SUCCESS", loud, PLAYER, 5401, "Lizard Bolt"),
        line("21:00:06", "SPELL_CAST_START", vehicle, NOBODY, 9001, "Ram, Charge"),
        line("21:00:07", "SPELL_CAST_SUCCESS", pet, MOB, 17253, "Bite"),
        line("21:00:08", "SPELL_CAST_SUCCESS", short_guid, PLAYER, 9002, "Nothing"),
        line("21:00:09", "SPELL_CAST_SUCCESS", bad_flags, PLAYER, 9003, "Nothing Either"),
        line("21:00:10", "SPELL_CAST_SUCCESS", loud, PLAYER, 0, "No Spell"),
        line("21:00:11", "SPELL_CAST_SUCCESS", loud, PLAYER, "abc", "Not A Number"),
        "this line is not from the combat log at all",
        "",
        "11/24/2026 21:00:12.000-5  SPELL_CAST_SUCCESS," + loud,
        line("21:00:13", "SPELL_SUMMON", pet, minion + ",0xa48,0x80000000", 688, "Summon Imp"),
        line("21:00:14", "SPELL_CAST_SUCCESS", minion + ",0xa48,0x80000000", PLAYER, 3110, "Firebolt"),
        '11/24/2026 21:10:00.000-5  ZONE_CHANGE,48,"Blackfathom Deeps",1',
        line("21:10:01", "SPELL_CAST_SUCCESS", MOB, PLAYER, 6205, "Curse of Weakness"),
        line("21:10:02", "SPELL_CAST_SUCCESS", MOB, PLAYER, 6205, "Curse of Weakness"),
        line("21:10:31", "SPELL_CAST_SUCCESS", MOB, PLAYER, 6205, "Curse of Weakness"),
        # A pause longer than half a minute isn't fighting, and isn't counted.
        line("21:20:00", "SPELL_CAST_SUCCESS", KELRIS, PLAYER, 8399, "Sleep"),
        line("21:20:07", "SPELL_CAST_SUCCESS", KELRIS, PLAYER, 8399, "Sleep"),
        '11/24/2026 21:25:00.000-5  ZONE_CHANGE,1,"Ashenvale",0',
        line("21:25:05", "SPELL_CAST_SUCCESS", loud, PLAYER, 5401, "Lizard Bolt", day="11/25/2026"),
    ]


def classic():
    """Classic Era writes no year in its lines."""
    mob = 'Creature-0-4444-1-55-3273-00000A1B2C,"Kolkar Stormer",0xa48,0x0'
    return [
        "11/24 20:18:39.739  COMBAT_LOG_VERSION,9,ADVANCED_LOG_ENABLED,0,BUILD_VERSION,1.15.9,PROJECT_ID,2",
        '11/24 20:18:40.000  ZONE_CHANGE,389,"Ragefire Chasm",1',
        '11/24 20:19:00.000  SPELL_CAST_SUCCESS,' + mob + "," + PLAYER + ',9532,"Lightning Bolt",0x8',
        '11/24 20:19:20.000  SPELL_CAST_SUCCESS,' + mob + "," + PLAYER + ',9532,"Lightning Bolt",0x8',
    ]


def retail():
    """A log from a game the database doesn't cover."""
    return [HEADER.replace("PROJECT_ID,18", "PROJECT_ID,1")] + fight()[1:]


def crowd(n=400):
    lines = [HEADER, ZONE]
    for i in range(n):
        mob = (f'Creature-0-6834-48-3652-{20000 + i}-0000063119,'
               f'"A Mob With A Rather Long Name Number {i}",0xa48,0x80000000')
        lines.append(line("20:19:00", "SPELL_CAST_SUCCESS", mob, PLAYER, 30000 + i,
                          f"A Spell With A Rather Long Name {i}"))
    return lines


def by_python(logs):
    """What the importer makes of these logs. Each log is a list of pieces."""
    data = gander_import.empty_data()
    for pieces in logs:
        ctx = {}
        for piece in pieces:
            reader = gander_import.Reader(data, dict(ctx), 2026)
            reader.feed(piece)
            ctx = reader.ctx
    return data["games"]


@unittest.skipUnless(NODE, "Node.js isn't installed")
class SiteReader(unittest.TestCase):
    maxDiff = None

    def by_page(self, logs, **options):
        job = dict(options, logs=[{"pieces": ["\r\n".join(piece) + "\r\n" for piece in pieces], "year": 2026}
                                  for pieces in logs])
        done = subprocess.run([NODE, str(DRIVER)], input=json.dumps(job), capture_output=True, text=True,
                              encoding="utf-8")
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def same(self, logs, **options):
        """The page and the importer agree about these logs. Returns the page's answer."""
        page = self.by_page(logs, **options)
        want = by_python(logs)
        got = page["data"]["games"]
        for game in set(want) | set(got):
            for key, entry in want.get(game, {}).get("instances", {}).items():
                mine = got.get(game, {}).get("instances", {}).get(key, {})
                self.assertAlmostEqual(mine.get("minutes"), entry["minutes"], delta=0.0015, msg=(game, key))
                mine["minutes"] = entry["minutes"]
        self.assertEqual(got, want)
        return page

    # ---- reading ----
    def test_reads_a_fight_as_the_importer_does(self):
        page = self.same([[fight()]])
        mobs = page["data"]["games"]["forever"]["mobs"]
        self.assertEqual(sorted(mobs), ["4798", "4832"])
        self.assertEqual(mobs["4798"]["spells"]["6205"], {"n": 3, "spawns": 2, "at": "2026-11-24", "build": "1.60.1"})

    def test_reads_awkward_lines_as_the_importer_does(self):
        page = self.same([[awkward()]])
        forever = page["data"]["games"]["forever"]
        self.assertEqual(forever["mobs"]["3273"]["name"], 'Kolkar, the "Loud"')
        self.assertEqual(forever["spells"]["9001"], "Ram, Charge")
        self.assertNotIn("8888", forever["mobs"])  # a player's pet summoned it
        self.assertEqual(forever["mobs"]["3273"]["spells"]["5401"]["at"], "2026-11-25")
        self.assertEqual(list(forever["instances"]), ["48"])

    def test_reads_a_classic_era_log_as_the_importer_does(self):
        page = self.same([[classic()]])
        self.assertEqual(page["data"]["games"]["classic"]["mobs"]["3273"]["spells"]["9532"]["at"], "2026-11-24")

    def test_reads_several_logs_together(self):
        self.same([[fight()], [awkward()], [classic()]])

    def test_a_log_read_in_two_pieces_carries_on_where_it_stopped(self):
        whole = awkward()
        for cut in (1, 3, 16, len(whole) - 1):
            self.same([[whole[:cut], whole[cut:]]])

    def test_logs_read_one_by_one_and_merged_match_logs_read_together(self):
        self.same([[fight()], [awkward()], [classic()], [fight()]], separate=True)

    def test_text_arriving_in_chunks_reads_the_same(self):
        for chunk in (7, 100, 4096):
            self.same([[fight()], [awkward()]], chunk=chunk)

    def test_a_last_line_that_isnt_finished_is_left_unread(self):
        whole = self.by_page([[fight()]])
        unfinished = "11/24/2026 20:21:00.000-5  SPELL_CAST_SUCC"
        job = {"logs": [{"pieces": ["\r\n".join(fight() + [unfinished])], "year": 2026}], "chunk": 50}
        done = subprocess.run([NODE, str(DRIVER)], input=json.dumps(job), capture_output=True, text=True,
                              encoding="utf-8")
        page = json.loads(done.stdout)
        self.assertEqual(page["data"], whole["data"])
        self.assertEqual(page["unread"], ["11/24/2026 20:21:00.000-5  SPELL_CAST_SUCC"])

    # ---- blocks ----
    def test_blocks_pass_the_intake_checks(self):
        page = self.by_page([[fight()], [awkward()], [classic()]])
        self.assertEqual(len(page["blocks"]), 2)  # one for each game
        games = {}
        for text in page["blocks"]:
            self.assertLessEqual(len(text), 30000)
            clean, dropped, english = gs.validate(json.loads(text), NOW)
            self.assertEqual((dropped, english), (0, True), text[:200])
            games[clean["game"]] = clean
        data = page["data"]["games"]
        for game, clean in games.items():
            self.assertEqual({mob: entry["spells"] for mob, entry in clean["mobs"].items()},
                             {mob: entry["spells"] for mob, entry in data[game]["mobs"].items()})
            self.assertEqual({mob: entry["name"] for mob, entry in clean["mobs"].items()},
                             {mob: entry["name"] for mob, entry in data[game]["mobs"].items()})
            self.assertEqual(clean["spells"], data[game]["spells"])
            self.assertEqual(sorted(clean["instances"]), sorted(data[game]["instances"]))
        self.assertEqual(games["forever"]["instances"]["48"]["name"], "Blackfathom Deeps")

    def test_a_block_names_no_player(self):
        page = self.by_page([[fight()], [awkward()]])
        for text in page["blocks"]:
            for word in ("Buffy", "Mcbufferson", "Player-", "Jhuuroon", "Pet-"):
                self.assertNotIn(word, text)

    def test_many_mobs_are_split_into_blocks_that_each_fit(self):
        page = self.by_page([[crowd()]], size=6000)
        self.assertGreater(len(page["blocks"]), 5)
        mobs, spells, instances = {}, {}, 0
        for text in page["blocks"]:
            self.assertLessEqual(len(text), 6000)
            clean, dropped, _ = gs.validate(json.loads(text), NOW)
            self.assertEqual(dropped, 0)
            self.assertEqual(set(clean["spells"]), {s for entry in clean["mobs"].values() for s in entry["spells"]})
            self.assertFalse(set(mobs) & set(clean["mobs"]), "a mob is in two blocks")
            mobs.update(clean["mobs"])
            spells.update(clean["spells"])
            instances += len(clean["instances"])
        self.assertEqual((len(mobs), len(spells), instances), (400, 400, 1))

    def test_a_game_that_isnt_in_english_sends_no_names(self):
        page = self.by_page([[fight()]], english=False)
        text = page["blocks"][0]
        for word in ("Fallenroot", "Kelris", "Curse of Weakness", "Blackfathom"):
            self.assertNotIn(word, text)
        clean, dropped, english = gs.validate(json.loads(text), NOW)
        self.assertEqual((dropped, english), (0, False))
        self.assertEqual(clean["mobs"]["4798"]["spells"]["6205"]["n"], 3)

    def test_a_log_from_another_game_makes_no_block(self):
        page = self.by_page([[retail()]])
        self.assertEqual(page["blocks"], [])
        self.assertEqual(page["summary"], [])

    def test_nothing_to_send_makes_no_block(self):
        page = self.by_page([[[HEADER, ZONE]]])
        self.assertEqual(page["blocks"], [])

    # ---- what the page tells the player ----
    def test_the_summary_counts_mobs_and_names_the_dungeons(self):
        page = self.by_page([[fight()], [classic()]])
        summary = {entry["game"]: entry for entry in page["summary"]}
        self.assertEqual(summary["forever"]["mobs"], 2)
        self.assertEqual(summary["forever"]["spells"], 2)
        self.assertEqual([i["name"] for i in summary["forever"]["instances"]], ["Blackfathom Deeps"])
        self.assertEqual(summary["classic"]["mobs"], 1)


if __name__ == "__main__":
    unittest.main()
