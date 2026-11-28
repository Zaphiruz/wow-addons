"""Tests for tools/gander_submit.py. Run: python -m unittest discover -s mods/classic/tests/tools"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tools"))
import gander_import  # noqa: E402
import gander_submit as gs  # noqa: E402

NOW = 1795600000          # 25 November 2026
T0 = NOW - 86400


def base():
    """A small database: one Forever mob with stats and a spell, one instance,
    and a Classic Era mob that is only a name."""
    return {"version": 2, "games": {
        "forever": {
            "instances": {"48": {"name": "Blackfathom Deeps", "minutes": 24.0}},
            "spells": {"5401": "Lizard Bolt"},
            "mobs": {"3238": {
                "name": "Stormhide",
                "spells": {"5401": {"n": 4, "spawns": 2, "at": "2026-11-24", "build": "1.60.1"}},
                "levels": {"22": {"at": T0, "v": {"n": "Stormhide", "spd": 2, "class": "WARRIOR", "ty": "Beast",
                                                  "z": "The Barrens"}}}}}},
        "classic": {"instances": {}, "spells": {"744": "Poison"},
                    "mobs": {"4798": {"name": "Fallenroot Shadowstalker", "spells": {}, "levels": {}}}}}}


def sub(mobs=None, game="forever", **more):
    return {"format": 1, "game": game, "mobs": mobs or {}, **more}


def seen(at=None, **v):
    return {"at": at or NOW - 3600, "v": v}


def issue(number, payload, user=100, assoc="NONE", labels=("gander-data",), **more):
    body = payload if isinstance(payload, str) else "### Data\n\n```text\n" + json.dumps(payload) + "\n```\n"
    return {"number": number, "body": body, "user": {"id": user, "login": f"user{user}"},
            "author_association": assoc, "labels": [{"name": name} for name in labels], **more}


def comment(ident, body, login="owner", liked=0):
    return {"id": ident, "body": body, "user": {"login": login}, "reactions": {"+1": liked}}


STORMER = {"3273": {"name": "Kolkar Stormer", "levels": {"12": seen(spd=2, armor=300, ty="Beast", z="The Barrens")}}}


class Checks(unittest.TestCase):
    def clean(self, payload):
        return gs.validate(payload, NOW)

    def test_finds_the_data_inside_the_issue_form(self):
        got = gs.parse_body("### Data\n\n```text\n" + json.dumps(sub(STORMER)) + "\n```\n\nthanks!")
        self.assertEqual(got["game"], "forever")

    def test_refuses_what_it_cannot_read(self):
        for body in ("hello", "{not json}", "[1, 2]", '{"format": 1, "x": NaN}', None, "{" * 5000 + "}" * 5000):
            with self.assertRaises(gs.Rejected, msg=repr(body)[:40]):
                gs.parse_body(body)

    def test_refuses_another_format_or_game(self):
        for payload in ({**sub(STORMER), "format": 2}, sub(STORMER, game="retail"), sub({}), sub("mobs")):
            with self.assertRaises(gs.Rejected, msg=str(payload)[:60]):
                self.clean(payload)

    def test_leaves_out_values_no_mob_could_have(self):
        clean, dropped, _ = self.clean(sub({"3273": {"name": "Kolkar Stormer", "levels": {
            "12": seen(spd=2, armor=-5, hp=10 ** 12, run=True, nonsense=4, pow="lots"),
            "99": seen(spd=2),                       # no such level
            "13": seen(at=NOW + 10 * 86400, spd=2),  # seen in the future
            "14": seen(at=1000, spd=2),              # before Gander existed
        }}}))
        self.assertEqual(clean["mobs"]["3273"]["levels"], {"12": {"at": NOW - 3600, "v": {"spd": 2}}})
        self.assertEqual(dropped, 8)

    def test_defense_must_match_the_level_on_forever_only(self):
        mobs = {"3273": {"name": "Kolkar Stormer", "levels": {"12": seen(**{"def": 60}), "13": seen(**{"def": 300})}}}
        clean, dropped, _ = self.clean(sub(mobs))
        self.assertEqual(list(clean["mobs"]["3273"]["levels"]), ["12"])
        self.assertEqual(dropped, 1)
        clean, dropped, _ = self.clean(sub(mobs, game="classic"))
        self.assertEqual(sorted(clean["mobs"]["3273"]["levels"]), ["12", "13"])

    def test_a_damage_range_must_be_the_right_way_round(self):
        clean, dropped, _ = self.clean(sub({"3273": {"levels": {"12": seen(dmin=50, dmax=20, spd=2)}}}))
        self.assertEqual(clean["mobs"]["3273"]["levels"]["12"]["v"], {"spd": 2})
        self.assertEqual(dropped, 2)

    def test_names_are_plain_text_only(self):
        for bad in ("@everyone hello", "<b>Boar</b>", "[link](http://x)", "Boar_", "  Boar", "Boar  King", "12345",
                    "B" * 41, "Boar\nKing", "`Boar`", "", 7):
            clean, _, _ = self.clean(sub({"3273": {"name": bad, "levels": {"12": seen(spd=2)}}}))
            self.assertNotIn("name", clean["mobs"]["3273"], repr(bad))
        for good in ("Kolkar Stormer", '"Sea Wolf" MacKinley', "Venture Co. Geologist", "Sir S. J. Erlgadin", "Gor'mul",
                     "Twilight Lord Kelris"):
            clean, _, _ = self.clean(sub({"3273": {"name": good, "levels": {"12": seen(spd=2)}}}))
            self.assertEqual(clean["mobs"]["3273"].get("name"), good)

    def test_the_name_inside_a_sighting_is_never_taken(self):
        clean, dropped, _ = self.clean(sub({"3273": {"name": "Kolkar Stormer", "levels": {"12": seen(spd=2, n="Rude")}}}))
        self.assertEqual(clean["mobs"]["3273"]["levels"]["12"]["v"], {"spd": 2})
        self.assertEqual(dropped, 0)

    def test_a_game_not_in_english_gives_numbers_but_no_words(self):
        clean, dropped, english = self.clean(sub(
            {"3273": {"name": "Kolkar-Sturmrufer", "levels": {"12": seen(spd=2, ty="Humanoid", z="Brachland")},
                      "spells": {"5401": {"n": 2, "spawns": 1, "at": "2026-11-24"}}}},
            locale="deDE", spells={"5401": "Echsenblitz"}, instances={"48": {"minutes": 5, "name": "Tiefschwarze Grotte"}}))
        self.assertFalse(english)
        self.assertEqual(clean["mobs"]["3273"]["levels"]["12"]["v"], {"spd": 2})
        self.assertNotIn("name", clean["mobs"]["3273"])
        self.assertEqual(clean["spells"], {})
        self.assertEqual(clean["instances"], {"48": {"minutes": 5}})
        self.assertEqual(dropped, 0)

    def test_casts_are_counted_within_limits(self):
        clean, dropped, _ = self.clean(sub({"3238": {"spells": {
            "5401": {"n": 99999, "spawns": 5, "at": "2026-11-24", "build": "1.60.1"},
            "1604": {"n": 3, "spawns": 1, "at": "2026-11-24"},      # Dazed: every mob does it
            "6205": {"n": 2, "spawns": 9, "at": "2026-11-24", "build": "rm -rf"},
            "7000": {"n": 2, "spawns": 1, "at": "2031-01-01"},
            "0": {"n": 2, "spawns": 1, "at": "2026-11-24"},
        }}}, spells={"5401": "Lizard Bolt", "6205": "Curse of Weakness", "9": "Unused"}))
        self.assertEqual(clean["mobs"]["3238"]["spells"], {
            "5401": {"n": gs.MAX_CASTS, "spawns": 5, "at": "2026-11-24", "build": "1.60.1"},
            "6205": {"n": 2, "spawns": 2, "at": "2026-11-24"}})
        self.assertEqual(clean["spells"], {"5401": "Lizard Bolt", "6205": "Curse of Weakness"})
        self.assertEqual(dropped, 3)

    def test_the_dungeons_a_mob_was_logged_in_are_kept_as_ids_only(self):
        cast = {"5401": {"n": 1, "spawns": 1, "at": "2026-11-24"}}
        clean, dropped, _ = self.clean(sub({
            "3238": {"spells": cast, "in": ["48", "33", "48", "048"]},
            "3239": {"spells": cast, "in": ["Blackfathom Deeps", "0", 48, None, "@x", "99999999999"]},
            "3240": {"spells": cast, "in": "48"},
            "3241": {"spells": cast, "in": [str(n) for n in range(1, 60)]},
            "3242": {"spells": cast}}))
        self.assertEqual(clean["mobs"]["3238"]["in"], ["33", "48"])
        for mob in ("3239", "3240", "3242"):
            self.assertNotIn("in", clean["mobs"][mob], mob)
        self.assertEqual(len(clean["mobs"]["3241"]["in"]), gs.MAX_PLACES)
        self.assertEqual(dropped, 0, "a dungeon left out isn't a fact left out")

    def test_the_zones_a_mob_was_logged_in_are_plain_names(self):
        cast = {"5401": {"n": 1, "spawns": 1, "at": "2026-11-24"}}
        mobs = {"3238": {"spells": cast, "zones": ["The Barrens", "Ashenvale", "The Barrens", "@everyone", "<b>Durotar</b>",
                                                  "[x](http://y)", 7, None, ["Mulgore"], "B" * 41, ""]},
                "3239": {"spells": cast, "zones": "The Barrens"},
                "3240": {"spells": cast, "zones": [f"Zone {chr(65 + n // 26)}{chr(65 + n % 26)}" for n in range(60)]},
                "3241": {"spells": cast}}
        clean, dropped, _ = self.clean(sub(mobs))
        self.assertEqual(clean["mobs"]["3238"]["zones"], ["Ashenvale", "The Barrens"])
        for mob in ("3239", "3241"):
            self.assertNotIn("zones", clean["mobs"][mob], mob)
        self.assertEqual(len(clean["mobs"]["3240"]["zones"]), gs.MAX_PLACES)
        self.assertEqual(dropped, 0, "a zone left out isn't a fact left out")
        clean, _, english = self.clean(sub(mobs, locale="deDE"))
        self.assertFalse(english)
        self.assertNotIn("zones", clean["mobs"]["3238"], "zone names in another language aren't kept")

    def test_junk_in_any_shape_never_breaks_the_check(self):
        junk = [None, 7, "x", [], [1], {"a": 1}, True, 1e400]
        for thing in junk:
            for payload in (sub({"3273": thing}), sub({"3273": {"levels": thing, "spells": thing, "name": thing}}),
                            sub({"3273": {"levels": {"12": thing}, "spells": {"5401": thing}}}),
                            sub({"3273": {"levels": {"12": {"at": thing, "v": thing}}}}),
                            sub({"3273": {"levels": {"12": seen(spd=thing, ty=thing, z=thing)}}}),
                            sub({"3273": {"spells": {"5401": {"n": thing, "spawns": thing, "at": thing, "build": thing}}}}),
                            sub({"3238": {"spells": {"5401": {"n": 1, "at": "2026-11-24"}}, "in": thing}}),
                            sub({"3238": {"spells": {"5401": {"n": 1, "at": "2026-11-24"}}, "in": [thing]}}),
                            sub({"3238": {"spells": {"5401": {"n": 1, "at": "2026-11-24"}}, "zones": thing}}),
                            sub({"3238": {"spells": {"5401": {"n": 1, "at": "2026-11-24"}}, "zones": [thing]}}),
                            sub(STORMER, spells=thing), sub(STORMER, instances=thing),
                            sub(STORMER, instances={"48": thing}), sub(STORMER, instances={"48": {"minutes": thing, "name": thing}}),
                            sub(STORMER, locale=thing, sender=thing), sub(thing), {"format": thing, "game": thing}):
                try:
                    clean, _, _ = self.clean(payload)
                except gs.Rejected:
                    continue
                json.dumps(clean)   # what is kept is plain data
                self.assertGreater(gs.facts(clean), 0)

    def test_refuses_a_submission_with_nothing_usable(self):
        with self.assertRaises(gs.Rejected):
            self.clean(sub({"3273": {"name": "Kolkar Stormer", "levels": {"99": seen(spd=2)}}}))


class Intake(unittest.TestCase):
    def setUp(self):
        self.data = base()
        self.held = gs.new_held()

    def go(self, issues=(), comments=(), **kw):
        return gs.process(self.data, self.held, list(issues), list(comments), "owner", NOW, **kw)

    def forever(self):
        return self.data["games"]["forever"]

    # ---- what goes straight in ----
    def test_stats_for_a_mob_already_listed_go_straight_in(self):
        r = self.go([issue(1, sub({"3238": {"name": "Stormhide", "levels": {
            "22": seen(spd=2, armor=950), "23": seen(spd=2, armor=990, z="The Barrens")}}}))])
        levels = self.forever()["mobs"]["3238"]["levels"]
        self.assertEqual(levels["22"]["v"]["armor"], 950)
        self.assertEqual(levels["22"]["at"], NOW - 3600, "an agreeing sighting should refresh the date")
        self.assertEqual(levels["23"]["v"], {"n": "Stormhide", "spd": 2, "armor": 990, "z": "The Barrens"})
        self.assertEqual(self.held["pending"], [])
        self.assertEqual(r["issues"][0]["reason"], "completed")
        self.assertIn("5 facts", r["issues"][0]["comment"])

    def test_casts_for_a_listed_mob_and_spell_add_up(self):
        self.go([issue(1, sub({"3238": {"spells": {"5401": {"n": 3, "spawns": 1, "at": "2026-11-25", "build": "1.60.2"}}}},
                              spells={"5401": "Something Rude"}))])
        self.assertEqual(self.forever()["mobs"]["3238"]["spells"]["5401"],
                         {"n": 7, "spawns": 3, "at": "2026-11-25", "build": "1.60.2"})
        self.assertEqual(self.forever()["spells"]["5401"], "Lizard Bolt", "a listed name is never replaced")

    def test_the_dungeon_a_listed_mob_was_logged_in_goes_in_with_its_casts(self):
        cast = {"5401": {"n": 1, "spawns": 1, "at": "2026-11-25"}}
        self.go([issue(1, sub({"3238": {"spells": cast, "in": ["48"]}}))])
        self.assertEqual(self.forever()["mobs"]["3238"]["in"], ["48"])
        self.go([issue(2, sub({"3238": {"spells": cast, "in": ["33", "48"]}}), user=200)])
        self.assertEqual(self.forever()["mobs"]["3238"]["in"], ["33", "48"])
        self.assertEqual(self.held["pending"], [])

    def test_a_mob_is_never_listed_in_more_dungeons_than_a_mob_could_be_in(self):
        cast = {"5401": {"n": 1, "spawns": 1, "at": "2026-11-25"}}
        for n in range(3):
            self.go([issue(n + 1, sub({"3238": {"spells": cast, "in": [str(100 * n + i) for i in range(1, 15)]}}),
                           user=100 + n)])
        self.assertEqual(len(self.forever()["mobs"]["3238"]["in"]), gs.MAX_PLACES)

    def test_a_new_mobs_dungeon_waits_with_it(self):
        mob = {"4832": {"name": "Twilight Lord Kelris", "in": ["48"],
                        "spells": {"5401": {"n": 1, "spawns": 1, "at": "2026-11-25"}}}}
        self.go([issue(1, sub(mob))])
        self.assertNotIn("4832", self.forever()["mobs"])
        self.go([issue(2, sub(mob), user=200)])
        self.assertEqual(self.forever()["mobs"]["4832"]["in"], ["48"])

    def test_a_zone_the_database_knows_goes_in_with_the_casts(self):
        cast = {"5401": {"n": 1, "spawns": 1, "at": "2026-11-25"}}
        r = self.go([issue(1, sub({"3238": {"spells": cast, "zones": ["The Barrens", "Blackfathom Deeps"]}}))])
        self.assertEqual(self.forever()["mobs"]["3238"]["zones"], ["Blackfathom Deeps", "The Barrens"],
                         "a zone a sighting names, and an instance's name, are both known")
        self.assertEqual(self.held["pending"], [])
        self.assertIn("3 facts", r["issues"][0]["comment"])

    def test_a_new_zone_for_a_logged_mob_waits_but_its_casts_do_not(self):
        cast = {"5401": {"n": 1, "spawns": 1, "at": "2026-11-25"}}
        r = self.go([issue(1, sub({"3238": {"spells": cast, "zones": ["Winterspring", "The Barrens"]}}))])
        mob = self.forever()["mobs"]["3238"]
        self.assertEqual((mob["spells"]["5401"]["n"], mob["zones"]), (5, ["The Barrens"]))
        self.assertEqual(self.held["pending"][0]["mobs"], {"3238": {"levels": {}, "spells": {}, "zones": ["Winterspring"]}})
        self.assertIn("2 facts went into the database", r["issues"][0]["comment"])
        self.assertIn("1 is waiting", r["issues"][0]["comment"])
        text, total = gs.render_held(self.data, self.held)
        self.assertEqual(total, 1)
        self.assertIn("New zones", text)
        self.assertIn("- Winterspring (1 sender", text)
        self.go([issue(2, sub({"3273": {"name": "Kolkar Stormer", "spells": cast, "zones": ["Winterspring"]}}), user=200)])
        self.assertEqual(self.forever()["mobs"]["3238"]["zones"], ["The Barrens", "Winterspring"],
                         "a second sender naming the zone confirms it")

    def test_the_owner_can_approve_or_drop_a_logged_mobs_new_zone(self):
        cast = {"5401": {"n": 1, "spawns": 1, "at": "2026-11-25"}}
        self.go([issue(1, sub({"3238": {"spells": cast, "zones": ["Winterspring"]}}))])
        r = self.go(comments=[comment(11, "approve zones")])
        self.assertEqual(self.forever()["mobs"]["3238"]["zones"], ["Winterspring"])
        self.assertEqual(self.held["pending"], [])
        self.assertIn("1 fact went into the database", r["commands"][0]["reply"])
        self.assertTrue(r.get("approved"), "the whole list went in")
        self.go([issue(2, sub({"3238": {"spells": cast, "zones": ["Felwood"]}}), user=200)])
        r = self.go(comments=[comment(12, "drop zones")])
        self.assertEqual(self.held["pending"], [])
        self.assertEqual(self.forever()["mobs"]["3238"]["zones"], ["Winterspring"])
        self.assertIn("Dropped 1 fact", r["commands"][0]["reply"])

    def test_a_listed_name_is_never_replaced(self):
        self.go([issue(1, sub({"3238": {"name": "Something Rude", "levels": {"22": seen(armor=950)}}}))])
        self.assertEqual(self.forever()["mobs"]["3238"]["name"], "Stormhide")
        self.assertEqual(self.forever()["mobs"]["3238"]["levels"]["22"]["v"]["n"], "Stormhide")

    def test_minutes_in_a_listed_instance_add_up(self):
        self.go([issue(1, sub(instances={"48": {"minutes": 30.5, "name": "Blackfathom Deeps"}}))])
        self.assertEqual(self.forever()["instances"]["48"], {"name": "Blackfathom Deeps", "minutes": 54.5})

    def test_a_mob_with_the_same_name_in_the_other_game_goes_in(self):
        self.go([issue(1, sub({"4798": {"name": "Fallenroot Shadowstalker", "levels": {"24": seen(spd=1.33)}},
                               "4799": {"name": "Fallenroot Hellcaller", "levels": {"25": seen(spd=2)}}}))])
        self.assertEqual(self.forever()["mobs"]["4798"]["levels"]["24"]["v"], {"n": "Fallenroot Shadowstalker", "spd": 1.33})
        self.assertNotIn("4799", self.forever()["mobs"])

    # ---- what waits ----
    def test_a_new_mob_waits_for_a_second_sender(self):
        r = self.go([issue(1, sub(STORMER))])
        self.assertNotIn("3273", self.forever()["mobs"])
        self.assertEqual(len(self.held["pending"]), 1)
        self.assertIn("4 are waiting", r["issues"][0]["comment"])
        self.go([issue(2, sub(STORMER), user=100)])           # the same sender again: a duplicate
        self.go([issue(3, sub({"3273": {"name": "Kolkar Stormer", "levels": {"12": seen(spd=2)}}}), user=100)])
        self.assertNotIn("3273", self.forever()["mobs"], "one sender can't confirm their own data")
        self.go([issue(4, sub({"3273": {"name": "Kolkar Stormer", "levels": {"13": seen(spd=2)}}}), user=200)])
        mob = self.forever()["mobs"]["3273"]
        self.assertEqual(mob["name"], "Kolkar Stormer")
        self.assertEqual(sorted(mob["levels"]), ["12", "13"])
        self.assertEqual(mob["levels"]["12"]["v"], {"n": "Kolkar Stormer", "spd": 2, "armor": 300, "ty": "Beast",
                                                    "z": "The Barrens"})
        self.assertEqual(self.held["pending"], [])

    # ---- mobs with no name ----
    def nameless(self):
        """Gander saw this mob before it kept names: it is listed, with stats and no name."""
        self.forever()["mobs"]["1421"] = {"name": "", "spells": {}, "levels": {"31": {"at": T0, "v": {"spd": 2}}}}

    def test_stats_for_a_listed_mob_with_no_name_go_in(self):
        self.nameless()
        r = self.go([issue(1, sub({"1421": {"levels": {"31": seen(spd=2, armor=1247)}}}))])
        self.assertEqual(self.forever()["mobs"]["1421"]["levels"]["31"]["v"], {"spd": 2, "armor": 1247})
        self.assertEqual(self.held["pending"], [])
        self.assertIn("2 facts went into", r["issues"][0]["comment"])

    def test_a_name_for_a_listed_mob_that_has_none_waits_but_its_stats_do_not(self):
        self.nameless()
        self.go([issue(1, sub({"1421": {"name": "Private Merle", "levels": {"31": seen(armor=1247)}}}))])
        mob = self.forever()["mobs"]["1421"]
        self.assertEqual((mob["name"], mob["levels"]["31"]["v"]["armor"]), ("", 1247))
        text, count = gs.render_held(self.data, self.held)
        self.assertEqual(count, 1)
        self.assertIn("`m1421` Private Merle", text)
        self.go([issue(2, sub({"1421": {"name": "Private Merle", "levels": {"31": seen(spd=2)}}}), user=200)])
        self.assertEqual(self.forever()["mobs"]["1421"]["name"], "Private Merle")
        self.assertEqual(self.held["pending"], [])

    def test_casts_and_a_zone_for_a_listed_mob_with_no_name_go_in_and_its_name_waits(self):
        self.nameless()
        r = self.go([issue(1, sub({"1421": {"name": "Private Merle", "zones": ["The Barrens"],
                                            "spells": {"5401": {"n": 3, "spawns": 2, "at": "2026-11-25"}}}},
                                  spells={"5401": "Lizard Bolt"}))])
        mob = self.forever()["mobs"]["1421"]
        self.assertEqual((mob["name"], mob["spells"]["5401"]["n"], mob["zones"]), ("", 3, ["The Barrens"]))
        self.assertIn("2 facts went into", r["issues"][0]["comment"])
        self.assertIn("`m1421` Private Merle", gs.render_held(self.data, self.held)[0])

    def test_a_new_mob_sent_without_a_name_can_be_seen_and_approved(self):
        self.go([issue(1, sub({"5555": {"levels": {"20": seen(spd=2)}}}))])
        self.assertNotIn("5555", self.forever()["mobs"])
        text, count = gs.render_held(self.data, self.held)
        self.assertEqual(count, 1)
        self.assertIn("`m5555` (no name sent)", text)
        self.go(comments=[comment(11, "approve m5555")])
        self.assertEqual(self.forever()["mobs"]["5555"]["levels"]["20"]["v"], {"spd": 2})
        self.assertEqual(self.forever()["mobs"]["5555"]["name"], "")
        self.assertEqual(self.held["pending"], [])

    def test_two_senders_who_disagree_about_a_name_both_wait(self):
        self.go([issue(1, sub(STORMER)),
                 issue(2, sub({"3273": {"name": "Rude Name", "levels": {"12": seen(spd=2)}}}), user=200)])
        self.assertNotIn("3273", self.forever()["mobs"])

    def test_a_value_that_disagrees_waits_and_the_old_one_stays(self):
        fast = sub({"3238": {"levels": {"22": seen(spd=9, armor=950)}}})
        r = self.go([issue(1, fast)])
        v = self.forever()["mobs"]["3238"]["levels"]["22"]["v"]
        self.assertEqual((v["spd"], v["armor"]), (2, 950))
        self.assertIn("1 is waiting", r["issues"][0]["comment"])
        self.go([issue(2, sub({"3238": {"levels": {"22": seen(spd=9)}}}), user=200)])
        self.assertEqual(self.forever()["mobs"]["3238"]["levels"]["22"]["v"]["spd"], 9)
        self.assertEqual(self.held["pending"], [])

    def test_a_new_spell_name_waits_but_the_rest_goes_in(self):
        payload = sub({"3238": {"levels": {"22": seen(armor=950)},
                                "spells": {"6205": {"n": 2, "spawns": 1, "at": "2026-11-25"}}}},
                      spells={"6205": "Curse of Weakness"})
        self.go([issue(1, payload)])
        self.assertEqual(self.forever()["mobs"]["3238"]["levels"]["22"]["v"]["armor"], 950)
        self.assertNotIn("6205", self.forever()["mobs"]["3238"]["spells"])
        self.go([issue(2, sub({"3238": {"spells": {"6205": {"n": 1, "spawns": 1, "at": "2026-11-24"}}}},
                              spells={"6205": "Curse of Weakness"}), user=200)])
        self.assertEqual(self.forever()["spells"]["6205"], "Curse of Weakness")
        self.assertEqual(self.forever()["mobs"]["3238"]["spells"]["6205"], {"n": 3, "spawns": 2, "at": "2026-11-25"})

    def test_a_new_zone_or_word_holds_only_that_value(self):
        self.go([issue(1, sub({"3238": {"levels": {"23": seen(spd=2, z="Zephras Isle", ty="Aberration", rk="ELITE")}}}))])
        self.assertEqual(self.forever()["mobs"]["3238"]["levels"]["23"]["v"], {"n": "Stormhide", "spd": 2})
        left = self.held["pending"][0]["mobs"]["3238"]["levels"]["23"]["v"]
        self.assertEqual(left, {"z": "Zephras Isle", "ty": "Aberration", "rk": "ELITE"})

    def test_a_zone_for_a_mob_listed_somewhere_else_is_let_go(self):
        self.go([issue(1, sub({"3238": {"levels": {"22": seen(z="Blackfathom Deeps")}}}))])
        self.assertEqual(self.forever()["mobs"]["3238"]["levels"]["22"]["v"]["z"], "The Barrens")
        self.assertEqual(self.held["pending"], [])

    def test_a_new_instance_waits(self):
        self.go([issue(1, sub(instances={"36": {"minutes": 40, "name": "The Deadmines"}}))])
        self.assertNotIn("36", self.forever()["instances"])
        self.go([issue(2, sub(instances={"36": {"minutes": 10, "name": "The Deadmines"}}), user=200)])
        self.assertEqual(self.forever()["instances"]["36"], {"name": "The Deadmines", "minutes": 50})

    def test_what_waits_goes_in_once_the_database_knows_the_mob(self):
        self.go([issue(1, sub(STORMER))])
        self.assertNotIn("3273", self.forever()["mobs"])
        # The importer, run by hand, adds the mob from the owner's own game.
        self.forever()["mobs"]["3273"] = {"name": "Kolkar Stormer", "spells": {}, "levels": {}}
        self.go()
        self.assertEqual(self.forever()["mobs"]["3273"]["levels"]["12"]["v"]["armor"], 300)
        self.assertEqual(self.held["pending"], [])

    def test_what_waits_too_long_is_forgotten(self):
        self.go([issue(1, sub(STORMER))])
        gs.process(self.data, self.held, [], [], "owner", NOW + (gs.HELD_DAYS + 1) * 86400)
        self.assertEqual(self.held["pending"], [])

    # ---- the issues themselves ----
    def test_a_bad_submission_is_refused_with_the_reason(self):
        r = self.go([issue(1, "just saying hello"), issue(2, sub(STORMER, game="retail"))])
        self.assertEqual([i["reason"] for i in r["issues"]], ["not planned", "not planned"])
        self.assertIn("no data block", r["issues"][0]["comment"])
        self.assertEqual(self.held, gs.new_held())

    def test_the_same_submission_twice_is_only_counted_once(self):
        payload = sub({"3238": {"spells": {"5401": {"n": 3, "spawns": 1, "at": "2026-11-25"}}}})
        self.go([issue(1, payload)])
        r = self.go([issue(2, payload)])
        self.assertEqual(self.forever()["mobs"]["3238"]["spells"]["5401"]["n"], 7)
        self.assertIn("already", r["issues"][0]["comment"])
        self.go([issue(3, payload, user=200)])                 # the same facts from someone else do count
        self.assertEqual(self.forever()["mobs"]["3238"]["spells"]["5401"]["n"], 10)

    def test_the_reply_says_what_was_left_out(self):
        r = self.go([issue(1, sub({"3238": {"levels": {"22": seen(armor=950, hp=-1)}}}))])
        self.assertIn("1 fact went into", r["issues"][0]["comment"])
        self.assertIn("1 was left out", r["issues"][0]["comment"])

    def test_pull_requests_and_stuck_issues_are_skipped(self):
        r = self.go([issue(1, sub(STORMER), labels=("gander-data", "gander-stuck")),
                     issue(2, sub(STORMER), pull_request={"url": "x"})])
        self.assertEqual(r["issues"], [])
        self.assertEqual(self.held["pending"], [])

    def test_who_sent_what_is_not_written_down(self):
        self.go([issue(1, sub(STORMER), user=987654321)])
        text = json.dumps(self.held)
        self.assertNotIn("987654321", text)
        self.assertNotIn("user987654321", text)

    def test_only_the_owners_own_issues_can_carry_a_sender_stamp(self):
        def stamped(mark):
            return sub(STORMER, sender=mark)
        self.go([issue(1, stamped("aaaa"), user=100), issue(2, stamped("bbbb"), user=100)])
        self.assertNotIn("3273", self.forever()["mobs"], "a stranger's stamp was believed")
        self.held = gs.new_held()
        self.go([issue(3, stamped("aaaa"), user=1, assoc="OWNER"), issue(4, stamped("aaaa"), user=1, assoc="OWNER")])
        self.assertNotIn("3273", self.forever()["mobs"], "the same stamp twice is one sender")
        self.go([issue(5, stamped("cccc"), user=1, assoc="OWNER")])
        self.assertIn("3273", self.forever()["mobs"])

    # ---- the owner's say ----
    def waiting(self):
        self.go([issue(1, sub({**STORMER, "3238": {"levels": {"22": seen(spd=9), "23": seen(spd=2, z="Zephras Isle")},
                                                  "spells": {"6205": {"n": 2, "spawns": 1, "at": "2026-11-25"}}}},
                              spells={"6205": "Curse of Weakness"}, instances={"36": {"minutes": 40, "name": "The Deadmines"}}))])

    def test_approve_all_from_the_owner_adds_everything(self):
        self.waiting()
        r = self.go(comments=[comment(11, "approve all")])
        f = self.forever()
        self.assertEqual(f["mobs"]["3273"]["name"], "Kolkar Stormer")
        self.assertEqual(f["mobs"]["3238"]["levels"]["22"]["v"]["spd"], 9)
        self.assertEqual(f["mobs"]["3238"]["levels"]["23"]["v"]["z"], "Zephras Isle")
        self.assertIn("6205", f["mobs"]["3238"]["spells"])
        self.assertIn("36", f["instances"])
        self.assertEqual(self.held["pending"], [])
        self.assertEqual(r["commands"][0]["id"], 11)
        self.assertIn("Approved", r["commands"][0]["reply"])

    def test_a_comment_that_approves_the_whole_list_merges_the_held_pull_request(self):
        # "approved" tells the workflow to merge through the held pull request
        # itself, so it shows as merged and not as closed.
        self.waiting()
        r = self.go(comments=[comment(11, "approve all")])
        self.assertTrue(r["approved"])
        self.assertIn("approved by the repository owner", r["body"])

    def test_approving_the_last_of_the_list_piece_by_piece_merges_it_too(self):
        self.waiting()
        r = self.go(comments=[comment(11, "approve m3238 zones s6205 i36")])
        self.assertFalse(r["approved"], "the pull request still lists a mob nobody approved")
        r = self.go(comments=[comment(12, "approve m3273")])
        self.assertEqual(self.held["pending"], [])
        self.assertTrue(r["approved"])

    def test_a_comment_that_only_drops_doesnt_merge_the_held_pull_request(self):
        self.waiting()
        r = self.go(comments=[comment(11, "drop all")])
        self.assertEqual(self.held["pending"], [])
        self.assertFalse(r["approved"], "nothing was approved, so there is nothing to show as merged")

    def test_a_comment_nobody_understood_merges_nothing(self):
        self.waiting()
        r = self.go(comments=[comment(11, "approve the lot please")])
        self.assertFalse(r["approved"])

    def test_nobody_elses_comment_counts(self):
        self.waiting()
        r = self.go(comments=[comment(11, "approve all", login="stranger"), comment(12, "approve all", liked=1),
                              comment(13, "looks good to me")])
        self.assertNotIn("3273", self.forever()["mobs"])
        self.assertEqual(r["commands"], [])

    def test_approving_one_mob_leaves_the_rest_waiting(self):
        self.waiting()
        self.go(comments=[comment(11, "Approve m3238")])
        f = self.forever()
        self.assertEqual(f["mobs"]["3238"]["levels"]["22"]["v"]["spd"], 9)
        self.assertNotIn("3273", f["mobs"])
        self.assertNotIn("z", f["mobs"]["3238"]["levels"]["23"]["v"])
        self.go(comments=[comment(12, "approve zones s6205, i36")])
        f = self.forever()
        self.assertEqual(f["mobs"]["3238"]["levels"]["23"]["v"]["z"], "Zephras Isle")
        self.assertIn("6205", f["mobs"]["3238"]["spells"])
        self.assertIn("36", f["instances"])
        self.assertEqual(list(self.held["pending"][0]["mobs"]), ["3273"])

    def test_drop_throws_waiting_data_away(self):
        self.waiting()
        self.go(comments=[comment(11, "drop m3273 s6205 zones")])
        left = self.held["pending"][0]
        self.assertEqual(left["mobs"], {"3238": {"levels": {"22": {"at": NOW - 3600, "v": {"spd": 9}}}, "spells": {}}})
        self.assertEqual(left["spells"], {})
        self.go(comments=[comment(12, "drop all")])
        self.assertEqual(self.held["pending"], [])
        self.assertNotIn("3273", self.forever()["mobs"])

    def test_a_command_it_does_not_understand_changes_nothing(self):
        self.waiting()
        r = self.go(comments=[comment(11, "approve everything please")])
        self.assertNotIn("3273", self.forever()["mobs"])
        self.assertIn("didn't understand", r["commands"][0]["reply"])

    def test_approving_the_pull_request_adds_what_was_shown(self):
        self.waiting()
        shown = gs.held_hash(self.held)
        self.go([issue(2, sub({"9999": {"name": "Late Arrival", "levels": {"5": seen(spd=2)}}}), user=200)])
        r = self.go(approve_hash=shown)
        self.assertTrue(r["stale"])
        self.assertFalse(r["approved"])
        self.assertNotIn("3273", self.forever()["mobs"], "approved data the owner never saw")
        r = self.go(approve_hash=gs.held_hash(self.held))
        self.assertTrue(r["approved"])
        self.assertIn("3273", self.forever()["mobs"])
        self.assertIn("9999", self.forever()["mobs"])
        self.assertEqual(self.held["pending"], [])

    # ---- the list the owner reads ----
    def test_the_held_list_names_everything_waiting(self):
        self.waiting()
        text, count = gs.render_held(self.data, self.held)
        self.assertEqual(count, 5)
        for line in ("`m3273` Kolkar Stormer (1 sender, since 2026-11-25)", "`s6205` Curse of Weakness",
                     "`i36` The Deadmines", "Zephras Isle", "`m3238` Stormhide, level 22: attack speed 2 → 9",
                     "approve zones", "Approving this pull request"):
            self.assertIn(line, text)
        self.assertNotIn("The Barrens", text, "a zone the database already has isn't waiting")

    def test_an_empty_held_list_says_so(self):
        text, count = gs.render_held(self.data, self.held)
        self.assertEqual(count, 0)
        self.assertIn("Nothing is waiting", text)

    def test_the_pull_request_says_what_it_adds(self):
        r = self.go([issue(7, sub({"3238": {"spells": {"5401": {"n": 3, "spawns": 1, "at": "2026-11-25"}}},
                                   "4798": {"name": "Fallenroot Shadowstalker", "levels": {"24": seen(spd=1.33)}}}))])
        self.assertEqual(r["title"], "Gander data: 1 submission")
        self.assertIn("#7", r["body"])
        self.assertIn("stats for 1 more mob", r["body"])
        self.assertIn("passed the checks", r["body"])
        self.assertNotIn("approved by the repository owner", r["body"])

    def test_an_approved_pull_request_says_the_owner_approved_it(self):
        self.waiting()
        r = self.go(approve_hash=gs.held_hash(self.held))
        self.assertIn("approved by the repository owner", r["body"])
        self.assertNotIn("without review", r["body"])


LOG_A, LOG_B = "a" * 16, "b" * 16


def cast(n):
    """A block's worth of casts for a mob and spell the database already has (4 so far)."""
    return {"3238": {"spells": {"5401": {"n": n, "spawns": 1, "at": "2026-11-25"}}}}


class LogRecord(unittest.TestCase):
    """Casts are added up, so a part of a combat log must only be counted
    once, whoever sends it. The record says how far each log has been read."""

    def setUp(self):
        self.data = base()
        self.held = gs.new_held()
        self.logs = gander_import.new_logs()

    def go(self, *issues):
        return gs.process(self.data, self.held, list(issues), [], "owner", NOW, logs=self.logs)

    def casts(self):
        return self.data["games"]["forever"]["mobs"]["3238"]["spells"]["5401"]["n"]

    def test_a_block_from_a_log_is_taken_and_the_record_says_how_far_it_was_read(self):
        r = self.go(issue(1, sub(cast(3), logs={LOG_A: [0, 5000]})))
        self.assertEqual(self.casts(), 7)
        self.assertEqual(self.logs["logs"][LOG_A], {"to": 5000, "at": "2026-11-25"})
        self.assertEqual(r["issues"][0]["reason"], "completed")

    def test_the_same_part_of_a_log_is_not_counted_again_whoever_sends_it(self):
        self.go(issue(1, sub(cast(3), logs={LOG_A: [0, 5000]})))
        r = self.go(issue(2, sub(cast(3), logs={LOG_A: [0, 5000]}), user=200))
        self.assertEqual(self.casts(), 7)
        self.assertIn("already has", r["issues"][0]["comment"])
        self.assertEqual(r["issues"][0]["reason"], "completed")
        self.assertEqual(self.held["pending"], [])

    def test_an_overlap_refuses_the_whole_block(self):
        self.go(issue(1, sub(cast(3), logs={LOG_A: [0, 5000]})))
        self.go(issue(2, sub(cast(2), logs={LOG_A: [4000, 9000], LOG_B: [0, 100]})))
        self.assertEqual(self.casts(), 7)
        self.assertEqual(self.logs["logs"][LOG_A]["to"], 5000)
        self.assertNotIn(LOG_B, self.logs["logs"], "a refused block mustn't move the record")

    def test_the_next_part_of_a_log_is_taken_and_so_is_one_after_a_gap(self):
        self.go(issue(1, sub(cast(3), logs={LOG_A: [0, 5000]})))
        self.go(issue(2, sub(cast(2), logs={LOG_A: [5000, 9000]})))
        self.assertEqual(self.casts(), 9)
        self.go(issue(3, sub(cast(1), logs={LOG_A: [9500, 9900]})))
        self.assertEqual(self.casts(), 10)
        self.assertEqual(self.logs["logs"][LOG_A]["to"], 9900)

    def test_a_send_in_several_blocks_is_all_taken_but_no_block_twice(self):
        logs = {LOG_A: [0, 5000], LOG_B: [100, 300]}
        self.go(issue(1, sub(cast(3), logs=logs, part=1, parts=2)))
        self.go(issue(2, sub(cast(2), logs=logs, part=2, parts=2)))
        self.assertEqual(self.casts(), 9)
        r = self.go(issue(3, sub(cast(5), logs=logs, part=2, parts=2)))
        self.assertEqual(self.casts(), 9, "the second block was counted twice")
        self.assertIn("already has", r["issues"][0]["comment"])
        self.assertEqual(self.logs["logs"][LOG_B]["to"], 300)

    def test_two_blocks_in_one_run(self):
        self.go(issue(1, sub(cast(3), logs={LOG_A: [0, 5000]})), issue(2, sub(cast(2), logs={LOG_A: [0, 5000]}), user=200))
        self.assertEqual(self.casts(), 7)

    def test_stats_from_gander_need_no_log(self):
        self.go(issue(1, sub({"3238": {"levels": {"22": seen(armor=950)}}})))
        self.assertEqual(self.data["games"]["forever"]["mobs"]["3238"]["levels"]["22"]["v"]["armor"], 950)
        self.assertEqual(self.logs["logs"], {})

    def test_casts_without_a_log_are_still_taken(self):
        # An older copy of the page, or a Worker that hasn't been deployed
        # again yet, sends no record. Its casts count as they always did.
        self.go(issue(1, sub(cast(3))))
        self.assertEqual(self.casts(), 7)

    def test_a_damaged_log_record_refuses_the_block(self):
        bad = [{"xyz": [0, 5]}, {LOG_A: [5, 5]}, {LOG_A: [-1, 5]}, {LOG_A: [0, 2 ** 60]}, {LOG_A: "0-5"},
               {LOG_A: [0, 5, 9]}, {LOG_A: [0.5, 5]}, {LOG_A: [True, 5]}, "everything", {}]
        for number, logs in enumerate(bad, 1):
            r = self.go(issue(number, sub(cast(3), logs=logs)))
            self.assertEqual(r["issues"][0]["reason"], "not planned", logs)
        for number, more in enumerate([{"part": 0}, {"part": 3, "parts": 2}, {"parts": 99}, {"part": "1"}], 50):
            r = self.go(issue(number, sub(cast(3), logs={LOG_A: [0, 5]}, **more)))
            self.assertEqual(r["issues"][0]["reason"], "not planned", more)
        self.assertEqual(self.casts(), 4)
        self.assertEqual(self.logs["logs"], {})

    def test_what_waits_for_approval_still_counts_as_read(self):
        new_mob = {"3273": {"name": "Kolkar Stormer", "spells": {"5401": {"n": 2, "spawns": 1, "at": "2026-11-25"}}}}
        self.go(issue(1, sub(new_mob, logs={LOG_A: [0, 5000]})))
        self.assertEqual(self.logs["logs"][LOG_A]["to"], 5000)
        self.assertEqual(len(self.held["pending"]), 1)
        self.assertNotIn("logs", self.held["pending"][0], "the waiting list has no use for the record")
        self.assertNotIn("part", self.held["pending"][0])

    def test_checking_keeps_the_record(self):
        clean, _, _ = gs.validate(sub(cast(3), logs={LOG_A: [0, 5000]}, part=1, parts=2), NOW)
        self.assertEqual(clean["logs"], {LOG_A: [0, 5000]})
        self.assertEqual((clean["part"], clean["parts"]), (1, 2))
        clean, _, _ = gs.validate(sub(cast(3)), NOW)
        self.assertNotIn("logs", clean)

    def test_the_record_forgets_the_logs_it_heard_about_longest_ago(self):
        for day, ident in (("2026-11-01", "1" * 16), ("2026-11-03", "3" * 16), ("2026-11-02", "2" * 16)):
            self.logs["logs"][ident] = {"to": 10, "at": day}
        gander_import.note_log(self.logs, LOG_A, 5000, "2026-11-25", keep=3)
        self.assertEqual(sorted(self.logs["logs"]), sorted(["2" * 16, "3" * 16, LOG_A]))

    def test_the_record_never_moves_back(self):
        gander_import.note_log(self.logs, LOG_A, 5000, "2026-11-25")
        gander_import.note_log(self.logs, LOG_A, 3000, "2026-11-26")
        self.assertEqual(self.logs["logs"][LOG_A], {"to": 5000, "at": "2026-11-25"})
        self.assertEqual(gander_import.log_read_to(self.logs, LOG_A), 5000)
        self.assertEqual(gander_import.log_read_to(self.logs, LOG_B), 0)


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.data, self.held, self.addon, self.out = root / "data.json", root / "held.json", root / "GanderData", root / "out"
        self.logs = root / "logs.json"
        self.addon.mkdir()
        (self.addon / "GanderData.toc").write_text("## Title: GanderData\n## Version: 1.0.3\nGanderData.lua\n", encoding="utf-8")
        (self.addon / "CHANGELOG.md").write_text("# GanderData changelog\n\n## 1.0.3 (2026-11-24)\n\n- Earlier.\n", encoding="utf-8")
        gander_import.save_json(self.data, base())
        self.lua = self.addon / "GanderData.lua"
        self.lua.write_text(gander_import.to_lua(base(), "1.0.3"), encoding="utf-8", newline="\n")
        self.issues, self.comments = root / "issues.json", root / "comments.json"

    def tearDown(self):
        self.tmp.cleanup()

    def paths(self):
        return ["--data", str(self.data), "--held-file", str(self.held), "--logs-file", str(self.logs),
                "--addon", str(self.addon), "--out", str(self.out)]

    def run_tool(self, issues=(), comments=(), *more):
        self.issues.write_text(json.dumps(list(issues)), encoding="utf-8")
        self.comments.write_text(json.dumps(list(comments)), encoding="utf-8")
        code = gs.main(["run", "--issues", str(self.issues), "--comments", str(self.comments), "--owner", "owner",
                        "--now", str(NOW), *more, *self.paths()])
        self.assertEqual(code, 0)
        return json.loads((self.out / "result.json").read_text(encoding="utf-8"))

    def test_the_addon_file_passes_its_checks_when_a_mob_with_no_name_gets_casts(self):
        # Issue 83: the database had this mob from Gander's own sightings, with
        # stats and no name. A combat log's casts and zone went in, the name
        # waited, and the checks on the file failed the run.
        data = base()
        data["games"]["forever"]["mobs"]["1421"] = {"name": "", "spells": {},
                                                    "levels": {"31": {"at": T0, "v": {"spd": 2}}}}
        gander_import.save_json(self.data, data)
        self.run_tool([issue(1, sub({"1421": {"name": "Private Merle", "zones": ["The Barrens"], "in": ["48"],
                                              "spells": {"5401": {"n": 3, "spawns": 2, "at": "2026-11-25"}}}},
                                    spells={"5401": "Lizard Bolt"}))])
        text = self.lua.read_text(encoding="utf-8")
        self.assertIn("[1421] = { 5401 }", text)
        self.assertIn("[1421] = { 48 }", text)
        self.assertIn('[1421] = { "The Barrens" }', text)
        self.assertNotIn("Private Merle", text)
        checks = pathlib.Path(__file__).resolve().parents[1] / "ganderdata" / "run_tests.py"
        done = subprocess.run([sys.executable, str(checks), str(self.lua)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stdout[-1500:] + done.stderr[-500:])

    def test_a_run_saves_the_record_of_logs(self):
        r = self.run_tool([issue(1, sub(cast(3), logs={LOG_A: [0, 5000]}))])
        self.assertTrue(r["changed"])
        saved = json.loads(self.logs.read_text(encoding="utf-8"))
        self.assertEqual(saved["logs"][LOG_A]["to"], 5000)
        # The record is read back on the next run: the same part isn't counted again.
        self.run_tool([issue(2, sub(cast(3), logs={LOG_A: [0, 5000]}), user=200)])
        data = json.loads(self.data.read_text(encoding="utf-8"))
        self.assertEqual(data["games"]["forever"]["mobs"]["3238"]["spells"]["5401"]["n"], 7)

    def test_a_run_writes_the_database_the_addon_file_and_the_replies(self):
        r = self.run_tool([issue(1, sub({"3238": {"levels": {"22": seen(armor=950)}}})), issue(2, sub(STORMER)),
                           issue(3, "hello")])
        self.assertTrue(r["changed"])
        self.assertEqual(r["issues"], [{"number": 1, "reason": "completed"}, {"number": 2, "reason": "completed"},
                                       {"number": 3, "reason": "not planned"}])
        self.assertIn("armor = 950", self.lua.read_text(encoding="utf-8"))
        self.assertIn('version = "1.0.3"', self.lua.read_text(encoding="utf-8"), "a merge isn't a release")
        self.assertEqual(len(json.loads(self.held.read_text(encoding="utf-8"))["pending"]), 1)
        self.assertIn("went into", (self.out / "issue-1.md").read_text(encoding="utf-8"))
        self.assertIn("#1, #2", (self.out / "pr_body.md").read_text(encoding="utf-8"))
        self.assertEqual(r["title"], "Gander data: 2 submissions")

    def test_a_run_with_nothing_to_add_changes_no_file(self):
        before = self.lua.read_text(encoding="utf-8")
        r = self.run_tool([issue(1, "hello")])
        self.assertFalse(r["changed"])
        self.assertFalse(self.held.exists())
        self.assertEqual(self.lua.read_text(encoding="utf-8"), before)
        self.assertEqual(r["issues"], [{"number": 1, "reason": "not planned"}])

    def test_the_held_command_shows_the_list_and_builds_the_approved_files(self):
        self.run_tool([issue(1, sub(STORMER))])
        self.assertEqual(gs.main(["held", *self.paths()]), 0)
        info = json.loads((self.out / "held.json").read_text(encoding="utf-8"))
        self.assertEqual((info["count"], info["title"]), (1, "Held Gander data: 1 waiting"))
        self.assertEqual(len(info["hash"]), 16)
        self.assertIn("Kolkar Stormer", (self.out / "held.md").read_text(encoding="utf-8"))
        self.assertIn("Kolkar Stormer", self.lua.read_text(encoding="utf-8"), "the branch should hold the approved result")
        self.assertEqual(json.loads(self.held.read_text(encoding="utf-8"))["pending"], [])

    def test_approving_with_the_hash_from_the_held_command_works(self):
        self.run_tool([issue(1, sub(STORMER))])
        kept = (self.data.read_text(encoding="utf-8"), self.held.read_text(encoding="utf-8"), self.lua.read_text(encoding="utf-8"))
        gs.main(["held", *self.paths()])
        info = json.loads((self.out / "held.json").read_text(encoding="utf-8"))
        for path, text in zip((self.data, self.held, self.lua), kept):   # the held branch isn't main
            path.write_text(text, encoding="utf-8", newline="\n")
        r = self.run_tool((), (), "--approve-hash", info["hash"])
        self.assertTrue(r["approved"] and r["changed"])
        self.assertIn("Kolkar Stormer", self.lua.read_text(encoding="utf-8"))
        self.assertEqual(r["title"], "Gander data: approved held data")

    def test_a_release_gets_the_next_version_and_a_line_for_players(self):
        old = self.data.parent / "old.json"
        old.write_text(self.data.read_text(encoding="utf-8"), encoding="utf-8")
        self.run_tool([issue(1, sub({"4798": {"name": "Fallenroot Shadowstalker", "levels": {"24": seen(spd=1.33)}}}))])
        version = gander_import.prepare_release(old, self.data, self.addon, "2026-11-26")
        self.assertEqual(version, "1.0.4")
        self.assertIn("## Version: 1.0.4", (self.addon / "GanderData.toc").read_text(encoding="utf-8"))
        self.assertIn("## 1.0.4 (2026-11-26)\n\n- Forever: stats for 1 more mob.",
                      (self.addon / "CHANGELOG.md").read_text(encoding="utf-8"))
        self.assertIn('version = "1.0.4"', self.lua.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
