"""Tests for tools/gander_import.py. Run: python -m unittest discover -s mods/classic/tests/tools"""
import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tools"))
import gander_import  # noqa: E402

NOW = 1795000000
HEADER = "11/24/2026 20:18:39.739-5  COMBAT_LOG_VERSION,22,ADVANCED_LOG_ENABLED,0,BUILD_VERSION,1.60.1,PROJECT_ID,18"
ZONE = '11/24/2026 20:18:39.740-5  ZONE_CHANGE,48,"Blackfathom Deeps",1'
MOB = 'Creature-0-6834-48-3652-4798-0002063119,"Fallenroot Shadowstalker",0x10a48,0x80000000'
MOB2 = 'Creature-0-6834-48-3652-4798-0000863119,"Fallenroot Shadowstalker",0xa48,0x80000000'
KELRIS = 'Creature-0-6834-48-3652-4832-0000063119,"Twilight Lord Kelris",0xa48,0x80000000'
PLAYER = 'Player-6933-004AF9C2,"Buffy-Mcbufferson-Normal-US",0x512,0x80000000'
TOTEM = 'Creature-0-6834-48-3652-2630-0000063786,"Earthbind Totem"'
NOBODY = "0000000000000000,nil,0x80000000,0x80000000"

# A saved Gander database: two mobs this player saw, one of them also heard
# about from another player, and one only heard about.
SAVED = '''
GanderDB = {
  ["tooltips"] = true,
  ["mobs"] = {
    [3239] = {
      ["lv"] = {
        [21] = { ["at"] = 1794990000, ["v"] = { ["spd"] = 2, ["run"] = 8, ["class"] = "WARRIOR",
                                                ["n"] = "Thunderhead", ["ty"] = "Beast", ["z"] = "The Barrens" } },
        [22] = { ["at"] = 1794990500, ["v"] = { ["spd"] = 2, ["def"] = 130, ["n"] = "Thunderhead" } },
      },
      ["heard"] = {
        [21] = { ["at"] = 1794999000, ["by"] = "Bob-Whitemane", ["ch"] = true, ["v"] = { ["spd"] = 9.9 } },
      },
    },
    [4798] = {
      ["lv"] = { [24] = { ["at"] = 1794990900, ["v"] = { ["spd"] = 1.33, ["n"] = "Fallenroot Shadowstalker" } } },
      ["heard"] = {},
    },
    [5000] = {
      ["lv"] = {},
      ["heard"] = { [30] = { ["at"] = 1794999000, ["by"] = "Bob-Whitemane", ["v"] = { ["spd"] = 3 } } },
    },
    [6000] = {
      ["lv"] = { [10] = { ["at"] = 1794990000, ["v"] = { ["n"] = "Hidden One", ["z"] = "Durotar" } } },
      ["heard"] = {},
    },
  },
}
'''


def line(clock, event, source, dest, spell, name, tail="0x20"):
    return f'11/24/2026 {clock}.000-5  {event},{source},{dest},{spell},"{name}",{tail}'


def fight():
    return [
        HEADER, ZONE,
        line("20:19:00", "SPELL_CAST_SUCCESS", MOB, PLAYER, 6205, "Curse of Weakness"),
        line("20:19:10", "SPELL_CAST_SUCCESS", MOB, PLAYER, 6205, "Curse of Weakness"),
        line("20:19:20", "SPELL_CAST_SUCCESS", MOB2, PLAYER, 6205, "Curse of Weakness"),
        line("20:19:30", "SPELL_AURA_APPLIED", MOB, PLAYER, 1604, "Dazed", "0x1,DEBUFF"),
        line("20:19:40", "SPELL_CAST_START", KELRIS, NOBODY, 8399, "Sleep"),
        line("20:19:50", "SPELL_AURA_APPLIED", KELRIS, PLAYER, 8399, "Sleep", "0x20,DEBUFF"),
        # A player, a player's totem and a friendly NPC: none of these are mob abilities.
        line("20:20:00", "SPELL_CAST_SUCCESS", PLAYER, MOB, 133, "Fireball"),
        line("20:20:01", "SPELL_SUMMON", PLAYER, TOTEM + ",0xa28,0x80000000", 2484, "Earthbind Totem"),
        line("20:20:02", "SPELL_AURA_APPLIED", TOTEM + ",0xa48,0x80000000", MOB, 3600, "Earthbind", "0x8,DEBUFF"),
        line("20:20:03", "SPELL_CAST_SUCCESS", TOTEM + ",0x2112,0x80000000", NOBODY, 3600, "Earthbind"),
        line("20:20:04", "SPELL_CAST_SUCCESS", 'Creature-0-6834-48-3652-900-0000063119,"Guard",0xa18,0x80000000',
             PLAYER, 55, "Guard Heal"),
        '11/24/2026 20:20:05.000-5  SWING_DAMAGE,' + MOB + "," + PLAYER + ",12,0",
    ]


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.logs = self.root / "_forever_" / "Logs"
        self.logs.mkdir(parents=True)
        self.data = self.root / "data" / "gander_data.json"
        self.state = self.root / "data" / "state.json"
        self.addon = self.root / "GanderData"
        self.lua = self.addon / "GanderData.lua"
        self.saved = self.root / "Gander.lua"
        self.saved.write_text(SAVED, encoding="utf-8")
        self.out = []

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, lines, name="WoWCombatLog-112426_201839.txt", age=3600):
        path = self.logs / name
        with open(path, "ab") as f:
            f.write(("\n".join(lines) + "\n").encode("utf-8"))
        os.utime(path, (NOW - age, NOW - age))
        return path

    def release(self, version="1.0.0"):
        """Give the addon folder a toc and changelog, as a released GanderData has."""
        self.addon.mkdir(exist_ok=True)
        (self.addon / "GanderData.toc").write_text(
            f"## Interface: 11509, 16001\n## Title: GanderData\n## Version: {version}\nGanderData.lua\n",
            encoding="utf-8")
        (self.addon / "CHANGELOG.md").write_text(
            f"# GanderData changelog\n\n## {version} (2026-11-24)\n\n- First release.\n", encoding="utf-8")

    def run_import(self, saved=(), dirs=None, **kw):
        self.out = []
        return gander_import.run(dirs or [self.logs], saved, self.data, self.state, self.addon, now=NOW,
                                 out=self.out.append, **kw)

    def load_lua(self):
        from lupa import lua51
        lua = lua51.LuaRuntime()
        lua.execute(self.lua.read_text(encoding="utf-8"))
        return lua.globals().GanderData

    # ---- combat logs ----
    def test_keeps_only_hostile_mob_spells(self):
        self.write(fight())
        data = self.run_import()
        mobs = data["games"]["forever"]["mobs"]
        self.assertEqual(sorted(mobs), ["4798", "4832"])
        self.assertEqual(mobs["4798"]["name"], "Fallenroot Shadowstalker")
        self.assertEqual(sorted(mobs["4798"]["spells"]), ["6205"])  # Dazed is ignored
        self.assertEqual(sorted(mobs["4832"]["spells"]), ["8399"])
        self.assertEqual(data["games"]["forever"]["spells"]["8399"], "Sleep")

    def test_counts_events_spawns_date_and_build(self):
        self.write(fight())
        seen = self.run_import()["games"]["forever"]["mobs"]["4798"]["spells"]["6205"]
        self.assertEqual(seen, {"n": 3, "spawns": 2, "at": "2026-11-24", "build": "1.60.1"})

    def test_no_player_names_are_stored(self):
        self.write(fight())
        self.run_import([("forever", self.saved)])
        for path in (self.data, self.lua):
            text = path.read_text(encoding="utf-8")
            for word in ("Buffy", "Player-", "Bob", "Whitemane"):
                self.assertNotIn(word, text)

    def test_counts_minutes_of_fighting_per_instance(self):
        lines = fight() + [line("20:30:00", "SPELL_CAST_SUCCESS", MOB, PLAYER, 6205, "Curse of Weakness"),
                           line("20:30:20", "SPELL_CAST_SUCCESS", MOB, PLAYER, 6205, "Curse of Weakness")]
        self.write(lines)
        entry = self.run_import()["games"]["forever"]["instances"]["48"]
        self.assertEqual(entry["name"], "Blackfathom Deeps")
        # 20:18:39 to 20:20:05 without a long pause, then 20 seconds after a ten minute break.
        self.assertAlmostEqual(entry["minutes"], (86 + 20) / 60, places=2)

    def test_the_open_world_is_not_counted_as_an_instance(self):
        self.write(fight() + ['11/24/2026 20:20:06.000-5  ZONE_CHANGE,1,"Ashenvale",0',
                              line("20:20:10", "SPELL_CAST_SUCCESS", KELRIS, PLAYER, 8399, "Sleep"),
                              line("20:20:20", "SPELL_CAST_SUCCESS", KELRIS, PLAYER, 8399, "Sleep")])
        data = self.run_import()["games"]["forever"]
        self.assertEqual(sorted(data["instances"]), ["48"])
        self.assertAlmostEqual(data["instances"]["48"]["minutes"], 86 / 60, places=2)
        self.assertEqual(data["mobs"]["4832"]["spells"]["8399"]["n"], 4)  # the casts still count

    def test_an_imported_log_is_deleted(self):
        path = self.write(fight())
        self.run_import()
        self.assertFalse(path.exists())
        self.assertIn("deleted", self.out[0])
        self.assertEqual(json.loads(self.state.read_text(encoding="utf-8")), {})

    def test_keep_leaves_the_log_and_never_counts_it_twice(self):
        path = self.write(fight())
        self.run_import(keep=True)
        self.assertTrue(path.exists())
        data = self.run_import(keep=True)
        self.assertEqual(data["games"]["forever"]["mobs"]["4798"]["spells"]["6205"]["n"], 3)

    def test_a_log_still_being_written_is_kept_and_continued_later(self):
        path = self.write(fight(), age=60)
        self.run_import()
        self.assertTrue(path.exists(), "deleted a log the game may still have open")
        self.assertIn("ten minutes", self.out[0])
        # The game adds more, without repeating the header.
        self.write([line("20:21:00", "SPELL_CAST_SUCCESS", KELRIS, PLAYER, 8399, "Sleep"),
                    line("20:21:05", "SPELL_CAST_SUCCESS", KELRIS, PLAYER, 9999, "Mind Blast")], age=3600)
        data = self.run_import()
        spells = data["games"]["forever"]["mobs"]["4832"]["spells"]
        self.assertEqual(spells["8399"]["n"], 3)
        self.assertIn("9999", spells)
        self.assertEqual(data["games"]["forever"]["mobs"]["4798"]["spells"]["6205"]["n"], 3)
        self.assertFalse(path.exists())

    def test_half_written_last_line_waits_for_the_next_import(self):
        path = self.logs / "WoWCombatLog-1.txt"
        whole = "\n".join(fight()) + "\n"
        cut = line("20:21:00", "SPELL_CAST_SUCCESS", KELRIS, PLAYER, 9999, "Mind Blast")
        path.write_bytes((whole + cut[:60]).encode("utf-8"))
        data = self.run_import(keep=True)
        self.assertNotIn("9999", data["games"]["forever"]["mobs"]["4832"]["spells"])
        with open(path, "ab") as f:
            f.write((cut[60:] + "\n").encode("utf-8"))
        data = self.run_import(keep=True)
        self.assertEqual(data["games"]["forever"]["mobs"]["4832"]["spells"]["9999"]["n"], 1)

    def test_dry_run_changes_nothing(self):
        path = self.write(fight())
        data = self.run_import(dry_run=True)
        self.assertIn("4798", data["games"]["forever"]["mobs"])
        self.assertTrue(path.exists())
        self.assertFalse(self.data.exists() or self.lua.exists() or self.state.exists())

    def test_later_logs_add_to_the_list(self):
        self.write(fight())
        self.run_import()
        self.write([HEADER.replace("1.60.1", "1.60.2"), ZONE,
                    line("21:00:00", "SPELL_CAST_SUCCESS", MOB, PLAYER, 6205, "Curse of Weakness"),
                    line("21:00:05", "SPELL_CAST_SUCCESS", MOB, PLAYER, 700, "Sleep")], name="WoWCombatLog-2.txt")
        spells = self.run_import()["games"]["forever"]["mobs"]["4798"]["spells"]
        self.assertEqual(spells["6205"]["n"], 4)
        self.assertEqual(spells["6205"]["build"], "1.60.2")
        self.assertIn("700", spells)

    def test_each_game_has_its_own_list(self):
        era = self.root / "_classic_era_" / "Logs"
        era.mkdir(parents=True)
        (era / "WoWCombatLog.txt").write_text(
            "\n".join([HEADER.replace("PROJECT_ID,18", "PROJECT_ID,2"), ZONE,
                       line("20:19:00", "SPELL_CAST_SUCCESS", KELRIS, PLAYER, 8399, "Sleep")]) + "\n", encoding="utf-8")
        os.utime(era / "WoWCombatLog.txt", (NOW - 9000, NOW - 9000))
        self.write(fight())
        data = self.run_import(dirs=[self.logs, era])
        self.assertEqual(sorted(data["games"]), ["classic", "forever"])
        self.assertEqual(sorted(data["games"]["classic"]["mobs"]), ["4832"])

    def test_no_logs_says_so(self):
        self.run_import()
        self.assertIn("no combat logs found", self.out[0])

    # ---- saved stats ----
    def test_saved_stats_are_this_players_own_sightings_only(self):
        data = self.run_import([("forever", self.saved)])
        mobs = data["games"]["forever"]["mobs"]
        self.assertEqual(sorted(mobs), ["3239", "4798", "6000"])  # 5000 was only heard about
        levels = mobs["3239"]["levels"]
        self.assertEqual(sorted(levels), ["21", "22"])
        self.assertEqual(levels["21"], {"at": 1794990000, "v": {
            "spd": 2, "run": 8, "class": "WARRIOR", "n": "Thunderhead", "ty": "Beast", "z": "The Barrens"}})
        self.assertEqual(mobs["3239"]["name"], "Thunderhead")
        self.assertEqual(mobs["4798"]["levels"]["24"]["v"]["spd"], 1.33)
        self.assertIn("stats for 2 new mobs", " / ".join(self.out))  # 6000 has a name but no stats

    def test_saved_stats_join_what_the_logs_say_about_a_mob(self):
        self.write(fight())
        mobs = self.run_import([("forever", self.saved)])["games"]["forever"]["mobs"]
        self.assertEqual(sorted(mobs["4798"]["spells"]), ["6205"])
        self.assertEqual(sorted(mobs["4798"]["levels"]), ["24"])

    def test_a_newer_sighting_replaces_an_older_one_field_by_field(self):
        self.run_import([("forever", self.saved)])
        self.saved.write_text('''GanderDB = { mobs = { [3239] = { lv = {
          [21] = { at = 1794995000, v = { spd = 2.5, def = 120 } },
          [22] = { at = 1794000000, v = { spd = 7, armor = 900 } },
        } } } }''', encoding="utf-8")
        levels = self.run_import([("forever", self.saved)])["games"]["forever"]["mobs"]["3239"]["levels"]
        self.assertEqual(levels["21"]["v"]["spd"], 2.5)             # newer: replaces
        self.assertEqual(levels["21"]["v"]["def"], 120)             # newer: adds
        self.assertEqual(levels["21"]["v"]["n"], "Thunderhead")     # what the newer one lacks is kept
        self.assertEqual(levels["21"]["at"], 1794995000)
        self.assertEqual(levels["22"]["v"]["spd"], 2)               # older: doesn't replace
        self.assertEqual(levels["22"]["v"]["armor"], 900)           # older: still fills a gap
        self.assertEqual(levels["22"]["at"], 1794990500)

    def test_importing_the_same_saved_file_twice_changes_nothing(self):
        self.release()
        self.run_import([("forever", self.saved)])
        first = self.lua.read_text(encoding="utf-8")
        self.run_import([("forever", self.saved)])
        self.assertEqual(self.lua.read_text(encoding="utf-8"), first)
        self.assertIn("nothing new", self.out[-1])

    def test_bad_values_in_a_saved_file_are_dropped(self):
        self.saved.write_text('''GanderDB = { mobs = {
          [10] = { lv = { [5] = { at = 1794990000, v = { spd = -1, def = "lots", hp = 5e12, armor = 40,
                                                         n = "''' + "x" * 60 + '''", bogus = 3, z = "A\\nB" } } } },
          ["eleven"] = { lv = { [5] = { at = 1794990000, v = { spd = 2 } } } },
          [12] = { lv = { ["five"] = { at = 1794990000, v = { spd = 2 } }, [6] = { v = { spd = 2 } }, [7] = "no" } },
        } }''', encoding="utf-8")
        mobs = self.run_import([("forever", self.saved)])["games"]["forever"]["mobs"]
        self.assertEqual(sorted(mobs), ["10"])
        self.assertEqual(mobs["10"]["levels"]["5"]["v"], {"armor": 40})

    def test_a_saved_file_cannot_run_code_on_this_pc(self):
        marker = self.root / "made-by-saved-file.txt"
        self.saved.write_text(
            'GanderDB = { mobs = {} }\n'
            f'if io then io.open({json.dumps(str(marker))}, "w"):close() end\n'
            f'if os then os.remove({json.dumps(str(self.saved))}) end\n', encoding="utf-8")
        self.run_import([("forever", self.saved)])
        self.assertFalse(marker.exists())
        self.assertTrue(self.saved.exists())

    # ---- the addon's files ----
    def test_the_addon_file_loads_as_lua(self):
        self.release("1.2.3")
        self.write(fight())
        self.run_import([("forever", self.saved)], bump_version=False)
        data = self.load_lua()
        self.assertEqual(data.version, "1.2.3")
        forever = data.forever
        self.assertEqual(list(forever.casts[4798].values()), [6205])
        self.assertEqual(forever.spells[6205], "Curse of Weakness")
        self.assertEqual(forever.names[4798], "Fallenroot Shadowstalker")
        self.assertEqual(forever.names[3239], "Thunderhead")
        self.assertEqual(forever.instances[48], 1)  # whole minutes
        seen = forever.stats[3239][21]
        self.assertEqual(seen.at, 1794990000)
        self.assertEqual((seen.v.spd, seen.v.run, seen.v["class"], seen.v.z), (2, 8, "WARRIOR", "The Barrens"))
        self.assertAlmostEqual(forever.stats[4798][24].v.spd, 1.33)

    def test_spells_are_listed_most_seen_first(self):
        self.write([HEADER, ZONE,
                    line("20:19:00", "SPELL_CAST_SUCCESS", KELRIS, PLAYER, 15, "Rare"),
                    line("20:19:01", "SPELL_CAST_SUCCESS", KELRIS, PLAYER, 8399, "Sleep"),
                    line("20:19:02", "SPELL_CAST_SUCCESS", KELRIS, PLAYER, 8399, "Sleep")])
        self.run_import()
        self.assertIn("[4832] = { 8399, 15 }", self.lua.read_text(encoding="utf-8"))

    def test_new_data_gives_the_addon_a_patch_version_and_a_changelog_line(self):
        self.release("1.0.0")
        self.write(fight())
        self.run_import([("forever", self.saved)])
        toc = (self.addon / "GanderData.toc").read_text(encoding="utf-8")
        self.assertIn("## Version: 1.0.1\n", toc)
        self.assertNotIn("1.0.0", toc)
        log = (self.addon / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertTrue(log.startswith("# GanderData changelog\n\n## 1.0.1 ("), log[:80])
        self.assertIn("- Forever: what 2 more mobs cast and stats for 2 more mobs.\n\n## 1.0.0 (2026-11-24)", log)
        self.assertEqual(self.load_lua().version, "1.0.1")
        self.assertIn("GanderData is now 1.0.1", "\n".join(self.out))

    def test_no_new_data_leaves_the_version_alone(self):
        self.release("1.0.0")
        self.write(fight())
        self.run_import()
        self.run_import()
        self.assertIn("## Version: 1.0.1\n", (self.addon / "GanderData.toc").read_text(encoding="utf-8"))

    def test_no_bump_writes_the_data_under_the_current_version(self):
        self.release("1.0.0")
        self.write(fight())
        self.run_import(bump_version=False)
        self.assertIn("## Version: 1.0.0\n", (self.addon / "GanderData.toc").read_text(encoding="utf-8"))
        self.assertEqual(self.load_lua().version, "1.0.0")

    def test_the_changelog_says_what_kind_of_thing_was_added(self):
        line_for = gander_import.changelog_line
        self.assertEqual(line_for({}, {"forever": (1, 1, 0)}), "Forever: what 1 more mob casts.")
        self.assertEqual(line_for({"forever": (3, 5, 2)}, {"forever": (3, 6, 2)}),
                         "Forever: 1 more ability for mobs already listed.")
        self.assertEqual(line_for({"classic": (0, 0, 4)}, {"classic": (0, 0, 9), "forever": (2, 3, 0)}),
                         "Classic Era: stats for 5 more mobs. Forever: what 2 more mobs cast.")
        self.assertIsNone(line_for({"forever": (3, 5, 2)}, {"forever": (3, 5, 2)}))


if __name__ == "__main__":
    unittest.main()
