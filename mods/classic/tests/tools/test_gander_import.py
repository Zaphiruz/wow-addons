"""Tests for tools/gander_import.py. Run: python -m unittest discover -s mods/classic/tests/tools"""
import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tools"))
import gander_import  # noqa: E402

HEADER = "11/24/2026 20:18:39.739-5  COMBAT_LOG_VERSION,22,ADVANCED_LOG_ENABLED,0,BUILD_VERSION,1.60.1,PROJECT_ID,18"
ZONE = '11/24/2026 20:18:39.740-5  ZONE_CHANGE,48,"Blackfathom Deeps",1'
MOB = 'Creature-0-6834-48-3652-4798-0002063119,"Fallenroot Shadowstalker",0x10a48,0x80000000'
MOB2 = 'Creature-0-6834-48-3652-4798-0000863119,"Fallenroot Shadowstalker",0xa48,0x80000000'
KELRIS = 'Creature-0-6834-48-3652-4832-0000063119,"Twilight Lord Kelris",0xa48,0x80000000'
PLAYER = 'Player-6933-004AF9C2,"Buffy-Mcbufferson-Normal-US",0x512,0x80000000'
TOTEM = 'Creature-0-6834-48-3652-2630-0000063786,"Earthbind Totem"'
NOBODY = "0000000000000000,nil,0x80000000,0x80000000"


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
        self.data = self.root / "data" / "abilities.json"
        self.state = self.root / "data" / "state.json"
        self.lua = self.root / "Gander" / "Abilities.lua"
        self.out = []

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, lines, name="WoWCombatLog-112426_201839.txt", age=3600):
        path = self.logs / name
        with open(path, "ab") as f:
            f.write(("\n".join(lines) + "\n").encode("utf-8"))
        old = 1795000000 - age
        os.utime(path, (old, old))
        return path

    def run_import(self, **kw):
        self.out = []
        return gander_import.run([self.logs], self.data, self.state, self.lua, now=1795000000,
                                 out=self.out.append, **kw)

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
        self.run_import()
        for path in (self.data, self.lua):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("Buffy", text)
            self.assertNotIn("Player-", text)

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
        os.utime(era / "WoWCombatLog.txt", (1794000000, 1794000000))
        self.write(fight())
        data = gander_import.run([self.logs, era], self.data, self.state, self.lua, now=1795000000, out=self.out.append)
        self.assertEqual(sorted(data["games"]), ["classic", "forever"])
        self.assertEqual(sorted(data["games"]["classic"]["mobs"]), ["4832"])

    def test_the_addon_file_loads_as_lua(self):
        from lupa import lua51
        self.write(fight())
        self.run_import()
        text = self.lua.read_text(encoding="utf-8")
        lua = lua51.LuaRuntime()
        ns = lua.eval("{}")
        lua.execute("load_addon = function(src, ns) assert(loadstring(src))('Gander', ns) end")
        lua.globals().load_addon(text, ns)
        forever = ns.abilities.forever
        self.assertEqual(list(forever.mobs[4798].values()), [6205])
        self.assertEqual(forever.spells[6205], "Curse of Weakness")
        self.assertEqual(forever.instances[48], 1)  # whole minutes
        self.assertIn("Fallenroot Shadowstalker", text)  # as a comment, for reviewing the file

    def test_spells_are_listed_most_seen_first(self):
        self.write([HEADER, ZONE,
                    line("20:19:00", "SPELL_CAST_SUCCESS", KELRIS, PLAYER, 15, "Rare"),
                    line("20:19:01", "SPELL_CAST_SUCCESS", KELRIS, PLAYER, 8399, "Sleep"),
                    line("20:19:02", "SPELL_CAST_SUCCESS", KELRIS, PLAYER, 8399, "Sleep")])
        self.run_import()
        self.assertIn("[4832] = { 8399, 15 }", self.lua.read_text(encoding="utf-8"))

    def test_no_logs_says_so(self):
        self.run_import()
        self.assertIn("no combat logs found", self.out[0])


if __name__ == "__main__":
    unittest.main()
