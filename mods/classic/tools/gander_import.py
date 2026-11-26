"""Builds GanderData, the database addon Gander reads: what each mob casts, and its stats.

Usage: python gander_import.py              import everything new, then delete the logs
       python gander_import.py --keep       import, but leave the log files alone
       python gander_import.py --dry-run    show what an import would do; change nothing
       python gander_import.py --no-bump    don't give GanderData a new version
       python gander_import.py --logs DIR   read combat logs from DIR (repeatable)
       python gander_import.py --release-since OLD_JSON
                                            import nothing: give data merged from players'
                                            submissions (gander_submit.py) the next version
       python gander_import.py --saved GAME=FILE
                                            read a saved Gander database (repeatable);
                                            GAME is forever or classic

It reads two things from the game folders:

  Combat logs (Logs/WoWCombatLog-<date>.txt), written while combat logging is
  on (/combatlog, or Gander's "log combat" setting). Addons can't read them.
  One kind of fact is kept: "this hostile mob cast or applied this spell".
  Players, their pets and their totems are skipped.

  Gander's saved database (WTF/Account/<account>/SavedVariables/Gander.lua):
  the stats this player saw with their own eyes. What Gander only heard from
  other players is left out, and so is who it heard it from.

No player or account name is written anywhere. What it writes:

  mods/classic/data/gander_data.json           everything imported so far (kept in git)
  mods/classic/GanderData/GanderData.lua       the same data for the game to load
  mods/classic/GanderData/GanderData.toc       a new patch version, when the data changed
  mods/classic/GanderData/CHANGELOG.md         and a line saying what was added
  mods/classic/data/gander_import_state.json   how far into each kept log it has read
                                               (this PC only, not in git)

A log is deleted once it has been read to the end, unless --keep is given or
the file changed in the last ten minutes (the game may still be writing it).
The game keeps its current log open until it exits, so that one is only
deleted on a later run.
"""
import argparse
import csv
import datetime
import hashlib
import json
import pathlib
import re
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent  # mods/classic
DATA = ROOT / "data" / "gander_data.json"
STATE = ROOT / "data" / "gander_import_state.json"
LOGS = ROOT / "data" / "gander_logs.json"
LOGS_KEPT = 5000      # combat logs the record remembers
BATCH_DAYS = 14       # how long a send in several blocks is remembered
ADDON = ROOT / "GanderData"
GAME_DIR = pathlib.Path(r"D:\Battle.net\Games\World of Warcraft")
# Game folder -> the name Gander uses for that game.
FOLDERS = {"_forever_": "forever", "_classic_era_": "classic"}

# PROJECT_ID in a log's header line -> game.
GAMES = {"18": "forever", "2": "classic"}
EVENTS = {"SPELL_CAST_START", "SPELL_CAST_SUCCESS", "SPELL_AURA_APPLIED"}
# Effects every mob can cause, which say nothing about the mob.
IGNORED_SPELLS = {1604: "Dazed"}
# Unit flags (COMBATLOG_OBJECT_*): who controls the unit and how it reacts to you.
FRIENDLY, HOSTILE, PLAYER_CONTROL, NPC_CONTROL = 0x10, 0x40, 0x100, 0x200
GAP = 30       # seconds: a longer pause between log lines isn't counted as fighting
IN_USE = 600   # seconds: a log changed more recently than this may still be open in the game

# The stats Gander stores for a mob, as in Gander.lua's FIELDS: numbers,
# or short pieces of text (the mob's name, type, zone and so on).
NUMBERS = {"def", "armor", "r1", "r2", "r3", "r4", "r5", "r6", "hp", "pow", "spd", "oh", "dmin", "dmax", "ap",
           "rspd", "rmin", "rmax", "s1", "s2", "s3", "s4", "s5", "run"}
TEXTS = {"ptype": 20, "class": 20, "rk": 20, "fam": 24, "ty": 24, "n": 40, "z": 40}
INFO = {"n", "ty", "rk", "z"}  # which mob it is, not a stat
MAX_NUMBER = 1000000000

LINE = re.compile(r"^(\d+)/(\d+)(?:/(\d+))? (\d+):(\d+):(\d+)\.(\d+)\S*  (.*)$")


def empty_data():
    return {"version": 2, "games": {}}


# ---- the record of combat logs ----
# Casts are added up, so a part of a combat log must be counted once only,
# whoever reads it: this importer, or the page a player sends from (site/).
# The record (data/gander_logs.json) says how many bytes of each log the
# database has had. A log is known by a scramble of its first line, which
# holds a time and the game's version and nothing about the player.
def new_logs():
    return {"version": 1, "logs": {}, "batches": {}}


def log_id(first_line):
    """The name the record knows a log by, from its first line (bytes)."""
    return hashlib.sha256(first_line.rstrip(b"\r\n")).hexdigest()[:16]


def log_read_to(logs, ident):
    """How many bytes of a log the database has had."""
    return logs["logs"].get(ident, {}).get("to", 0)


def note_log(logs, ident, to, day, keep=None):
    """Remember that a log has been read up to a byte. The record never moves
    back, and forgets the logs it heard about longest ago."""
    if to <= log_read_to(logs, ident):
        return
    logs["logs"][ident] = {"to": to, "at": day}
    keep = LOGS_KEPT if keep is None else keep
    if len(logs["logs"]) > keep:
        oldest = sorted(logs["logs"], key=lambda key: (logs["logs"][key]["at"], key))
        for key in oldest[:len(logs["logs"]) - keep]:
            del logs["logs"][key]


def game_data(data, game):
    return data["games"].setdefault(game, {"instances": {}, "spells": {}, "mobs": {}})


def mob_entry(g, mob, name=None):
    entry = g["mobs"].setdefault(str(mob), {"name": name or "", "spells": {}, "levels": {}})
    entry.setdefault("spells", {})
    entry.setdefault("levels", {})
    if name:
        entry["name"] = name
    return entry


def creature_id(guid):
    """The creature ID in a mob's GUID, or None for players, pets and anything else."""
    parts = guid.split("-")
    if len(parts) >= 7 and parts[0] in ("Creature", "Vehicle") and parts[5].isdigit():
        return int(parts[5])


def flags_of(text):
    try:
        return int(text, 16)
    except ValueError:
        return 0


def player_owned(guid, flags):
    return guid.startswith(("Player-", "Pet-")) or bool(flags & PLAYER_CONTROL)


class Reader:
    """Reads log lines into data. ctx carries what the earlier part of a log
    said (which game, build and instance), so a log can be read in pieces."""

    def __init__(self, data, ctx=None, year=None):
        self.data = data
        self.ctx = ctx or {}
        self.year = year or datetime.date.today().year
        self.last = None          # time of the previous line
        self.summoned = set()     # GUIDs of things players summoned: totems, pets
        self.spawns = {}          # (game, mob, spell) -> GUIDs seen using it
        self.lines = 0
        self.new_mobs = 0
        self.new_spells = 0

    def feed(self, lines):
        for line in lines:
            m = LINE.match(line.rstrip("\r\n"))
            if m:
                self.lines += 1
                self.read(m)
        for (game, mob, spell), guids in self.spawns.items():
            game_data(self.data, game)["mobs"][mob]["spells"][spell]["spawns"] += len(guids)
        self.spawns = {}

    def read(self, m):
        month, day, year, hour, minute, second, _, rest = m.groups()
        when = datetime.datetime(int(year or self.year), int(month), int(day), int(hour), int(minute), int(second))
        event = rest.split(",", 1)[0]
        if event == "COMBAT_LOG_VERSION":
            f = rest.split(",")
            pairs = dict(zip(f[0::2], f[1::2]))  # NAME,value,NAME,value...
            project = pairs.get("PROJECT_ID")
            self.ctx["game"] = GAMES.get(project, project)
            self.ctx["build"] = pairs.get("BUILD_VERSION")
        elif event == "ZONE_CHANGE":
            f = next(csv.reader([rest]))
            if len(f) >= 3:
                # The last field is the difficulty: 0 is the open world, where
                # the "instance" is a whole continent and the name just a zone.
                inside = len(f) < 4 or f[3] != "0"
                self.ctx["instance"] = f[1] if inside else None
                self.ctx["instance_name"] = f[2] if inside else None
                self.last = None  # the gap before this was travel, not fighting
        game = self.ctx.get("game")
        if not game:
            return
        self.count_time(game, when)
        if event == "SPELL_SUMMON":
            f = next(csv.reader([rest]))
            if len(f) >= 6 and player_owned(f[1], flags_of(f[3])):
                self.summoned.add(f[5])
        elif event in EVENTS:
            self.read_spell(game, next(csv.reader([rest])), when)

    def count_time(self, game, when):
        instance = self.ctx.get("instance")
        if instance and self.last:
            gap = (when - self.last).total_seconds()
            if 0 < gap <= GAP:
                entry = game_data(self.data, game)["instances"].setdefault(
                    instance, {"name": self.ctx.get("instance_name", ""), "minutes": 0})
                entry["minutes"] = round(entry["minutes"] + gap / 60, 3)
        if self.last is None or when > self.last:
            self.last = when

    def read_spell(self, game, f, when):
        if len(f) < 11:
            return
        guid, name, flags = f[1], f[2], flags_of(f[3])
        mob = creature_id(guid)
        if mob is None or guid in self.summoned:
            return
        if not (flags & HOSTILE and flags & NPC_CONTROL) or flags & (PLAYER_CONTROL | FRIENDLY):
            return
        if not f[9].isdigit() or int(f[9]) <= 0 or int(f[9]) in IGNORED_SPELLS:
            return
        g = game_data(self.data, game)
        mob, spell = str(mob), f[9]
        g["spells"][spell] = f[10]
        if not g["mobs"].get(mob, {}).get("spells"):
            self.new_mobs += 1
        entry = mob_entry(g, mob, name)
        if spell not in entry["spells"]:
            entry["spells"][spell] = {"n": 0, "spawns": 0}
            self.new_spells += 1
        seen = entry["spells"][spell]
        seen["n"] += 1
        seen["at"] = when.date().isoformat()
        if self.ctx.get("build"):
            seen["build"] = self.ctx["build"]
        self.spawns.setdefault((game, mob, spell), set()).add(guid)


# --------------------------------------------------------------- saved stats
def clean_values(values):
    """The fields of one saved sighting that are real stats, cleaned up."""
    out = {}
    for key, value in values.items():
        if key in NUMBERS:
            if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value <= MAX_NUMBER:
                out[key] = int(value) if float(value).is_integer() else round(float(value), 2)
        elif key in TEXTS:
            if isinstance(value, str) and 0 < len(value) <= TEXTS[key] and value.isprintable():
                out[key] = value
    return out


def lua_to_python(value):
    if hasattr(value, "items"):  # a Lua table
        return {lua_to_python(k): lua_to_python(v) for k, v in value.items()}
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def read_saved(path):
    """GanderDB.mobs from a saved-variables file, as plain Python values. The
    file is Lua, so it runs in a bare Lua state with nothing to reach out with."""
    from lupa import lua51
    lua = lua51.LuaRuntime(register_eval=False, register_builtins=False)
    lua.execute("os, io, require, dofile, loadfile, load, loadstring, package, debug, python = nil")
    lua.execute(pathlib.Path(path).read_text(encoding="utf-8", errors="replace"))
    saved = lua.globals().GanderDB
    mobs = saved.mobs if saved is not None else None
    return lua_to_python(mobs) if mobs is not None else {}


def has_stats(entry):
    return any(lv["v"].keys() - INFO for lv in entry.get("levels", {}).values())


def merge_saved(data, game, mobs):
    """Add this player's own sightings. Returns how many mobs and levels were new."""
    g = game_data(data, game)
    new_mobs = new_levels = 0
    for mob, record in mobs.items():
        if not isinstance(mob, int) or mob <= 0 or not isinstance(record, dict):
            continue
        for level, seen in (record.get("lv") or {}).items():
            if not isinstance(level, int) or not isinstance(seen, dict) or not isinstance(seen.get("v"), dict):
                continue
            values = clean_values(seen["v"])
            at = seen.get("at")
            if not values or not isinstance(at, (int, float)):
                continue
            had_stats = has_stats(g["mobs"].get(str(mob), {}))
            entry = mob_entry(g, mob, values.get("n"))
            old = entry["levels"].get(str(level))
            if old is None:
                entry["levels"][str(level)] = {"at": int(at), "v": values}
                new_levels += 1
            elif at >= old["at"]:
                old["v"] = {**old["v"], **values}  # the newer sighting wins, field by field
                old["at"] = int(at)
            else:
                old["v"] = {**values, **old["v"]}
            if not had_stats and has_stats(entry):
                new_mobs += 1
    return new_mobs, new_levels


# ------------------------------------------------------------------ writing
def lua_string(text):
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def lua_value(value):
    if isinstance(value, str):
        return lua_string(value)
    return repr(value) if isinstance(value, float) else str(int(value))


def lua_comment(text):
    return str(text).replace("\n", " ").replace("\r", " ")


def to_lua(data, version):
    """The addon's copy. Per game: minutes logged in each instance, spell
    names, mob names, each mob's spells (most often seen first), and each
    mob's stats in the shape Gander keeps its own sightings in."""
    out = ["-- GanderData: what each mob casts and its stats, for the Gander addon.",
           "-- Generated by mods/classic/tools/gander_import.py. Don't edit by hand.",
           "GanderData = {",
           f"  version = {lua_string(version)},"]
    for game in sorted(data["games"]):
        g = data["games"][game]
        casts, stats, names = {}, {}, {}
        for mob, entry in g["mobs"].items():
            spells = [s for s in entry.get("spells", {}) if int(s) not in IGNORED_SPELLS]
            spells.sort(key=lambda s: (-entry["spells"][s]["n"], int(s)))
            if spells:
                casts[mob] = spells
            if entry.get("levels"):
                stats[mob] = entry["levels"]
            if (spells or entry.get("levels")) and entry.get("name"):
                names[mob] = entry["name"]
        used = sorted({int(s) for spells in casts.values() for s in spells})
        out.append(f"  {game} = {{")
        out.append("    instances = {  -- minutes of fighting logged in each")
        for instance in sorted(g["instances"], key=int):
            entry = g["instances"][instance]
            out.append(f"      [{int(instance)}] = {int(entry['minutes'])},  -- {lua_comment(entry['name'])}")
        out.append("    },")
        out.append("    spells = {")
        for spell in used:
            out.append(f"      [{spell}] = {lua_string(g['spells'].get(str(spell), ''))},")
        out.append("    },")
        out.append("    names = {")
        for mob in sorted(names, key=int):
            out.append(f"      [{int(mob)}] = {lua_string(names[mob])},")
        out.append("    },")
        out.append("    casts = {")
        for mob in sorted(casts, key=int):
            out.append(f"      [{int(mob)}] = {{ {', '.join(casts[mob])} }},")
        out.append("    },")
        out.append("    stats = {")
        for mob in sorted(stats, key=int):
            out.append(f"      [{int(mob)}] = {{")
            for level in sorted(stats[mob], key=int):
                seen = stats[mob][level]
                values = ", ".join(f"{key} = {lua_value(seen['v'][key])}" for key in sorted(seen["v"]))
                out.append(f"        [{int(level)}] = {{ at = {int(seen['at'])}, v = {{ {values} }} }},")
            out.append("      },")
        out.append("    },")
        out.append("  },")
    out.append("}")
    return "\n".join(out) + "\n"


def load_json(path, default):
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")


def size(n):
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    return f"{n / 1024:.0f} KB"


def counts(data):
    """Per game: mobs with casts, abilities in all, mobs with stats."""
    out = {}
    for game, g in data["games"].items():
        with_casts = [m for m in g["mobs"].values() if m.get("spells")]
        out[game] = (len(with_casts), sum(len(m["spells"]) for m in with_casts),
                     sum(1 for m in g["mobs"].values() if has_stats(m)))
    return out


def some(n, one, many):
    return f"{n} {one if n == 1 else many}"


def changelog_line(before, after):
    """One line for players saying what an import added, or None if nothing."""
    titles = {"forever": "Forever", "classic": "Classic Era"}
    parts = []
    for game in sorted(after):
        b, a = before.get(game, (0, 0, 0)), after[game]
        added = []
        if a[0] > b[0]:
            added.append(f"what {some(a[0] - b[0], 'more mob casts', 'more mobs cast')}")
        elif a[1] > b[1]:
            added.append(f"{some(a[1] - b[1], 'more ability', 'more abilities')} for mobs already listed")
        if a[2] > b[2]:
            added.append(f"stats for {some(a[2] - b[2], 'more mob', 'more mobs')}")
        if added:
            parts.append(f"{titles.get(game, game)}: {' and '.join(added)}.")
    return " ".join(parts) or None


def utc_day(now=None):
    """The date a version is given, in UTC: the release workflow's clock, so
    versions made here and there are dated in order."""
    if now is None:
        return datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    return datetime.datetime.fromtimestamp(now, datetime.timezone.utc).date().isoformat()


def bump(addon, note, today):
    """Give GanderData the next patch version and a changelog entry. Returns the version."""
    toc = addon / f"{addon.name}.toc"
    text = toc.read_text(encoding="utf-8")
    m = re.search(r"^## Version:\s*(\d+)\.(\d+)\.(\d+)\s*$", text, re.M)
    if not m:
        raise SystemExit(f"{toc} has no '## Version: x.y.z' line")
    version = f"{m.group(1)}.{m.group(2)}.{int(m.group(3)) + 1}"
    toc.write_text(text[:m.start()] + f"## Version: {version}" + text[m.end():], encoding="utf-8", newline="\n")
    log = addon / "CHANGELOG.md"
    old = log.read_text(encoding="utf-8") if log.is_file() else f"# {addon.name} changelog\n"
    head, sep, rest = old.partition("\n## ")
    entry = f"## {version} ({today})\n\n- {note}\n"
    log.write_text(f"{head.rstrip()}\n\n{entry}{sep}{rest}" if sep else f"{old.rstrip()}\n\n{entry}",
                   encoding="utf-8", newline="\n")
    return version


def prepare_release(old_path, data_path=DATA, addon=ADDON, today=None):
    """Give GanderData its next version for data that was merged without one
    (see gander_submit.py). old_path is the database as last released, for
    the changelog line. Returns the new version."""
    old = load_json(pathlib.Path(old_path), empty_data())
    data = load_json(pathlib.Path(data_path), empty_data())
    note = changelog_line(counts(old), counts(data)) or "Refreshed the stats of mobs already in the database."
    version = bump(addon, note, today or utc_day())
    (addon / f"{addon.name}.lua").write_text(to_lua(data, version), encoding="utf-8", newline="\n")
    return version


def current_version(addon):
    toc = addon / f"{addon.name}.toc"
    m = toc.is_file() and re.search(r"^## Version:\s*(\S+)", toc.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "0.0.0"


def run(log_dirs, saved=(), data_path=DATA, state_path=STATE, addon=ADDON, keep=False, dry_run=False,
        bump_version=True, now=None, out=print, logs_path=LOGS):
    now = time.time() if now is None else now
    record = load_json(logs_path, new_logs())
    record_before = json.dumps(record, sort_keys=True)
    data = load_json(data_path, empty_data())
    data["version"] = 2
    before = counts(data)
    state = load_json(state_path, {})
    left_on_disk = 0
    found = set()
    for folder in log_dirs:
        folder = pathlib.Path(folder)
        for log in sorted(folder.glob("WoWCombatLog*.txt")):
            key = f"{folder.parent.name}/{log.name}"
            found.add(key)
            seen = state.get(key, {})
            offset = seen.get("offset", 0)
            raw = log.read_bytes()
            if offset > len(raw):
                offset, seen = 0, {}  # a different file under an old name
            mtime = log.stat().st_mtime
            year = datetime.date.fromtimestamp(mtime).year
            ctx = dict(seen.get("ctx", {}))
            # The record says how much of this log the database has had,
            # from here or from the page. Past what this importer has read
            # itself, walk to that point without counting, to know which
            # dungeon the log is in by then.
            ident = log_id(raw[:raw.find(b"\n")]) if b"\n" in raw else None
            had = min(log_read_to(record, ident), len(raw)) if ident else 0
            skipped = max(had - offset, 0)
            if skipped:
                walker = Reader(empty_data(), ctx, year)
                walker.feed(raw[offset:had].decode("utf-8", errors="replace").splitlines())
                ctx, offset = walker.ctx, had
            fresh = raw[offset:]
            fresh = fresh[:fresh.rfind(b"\n") + 1]  # whole lines only
            reader = Reader(data, ctx, year)
            reader.feed(fresh.decode("utf-8", errors="replace").splitlines())
            if ident:
                note_log(record, ident, offset + len(fresh), utc_day(now))
            note = f"{reader.lines} lines, {reader.new_mobs} new mobs, {reader.new_spells} new abilities"
            if skipped:
                note += f" ({size(skipped)} of it was already in the database)"
            in_use = now - mtime < IN_USE
            if keep or in_use or dry_run:
                state[key] = {"offset": offset + len(fresh), "ctx": reader.ctx}
                left_on_disk += len(raw)
                why = "kept (--keep)" if keep else "kept: changed in the last ten minutes" if in_use else "would delete"
                out(f"{key}: {note}; {why}, {size(len(raw))}")
            else:
                try:
                    log.unlink()
                    state.pop(key, None)
                    out(f"{key}: {note}; deleted, freed {size(len(raw))}")
                except OSError as e:
                    state[key] = {"offset": offset + len(fresh), "ctx": reader.ctx}
                    left_on_disk += len(raw)
                    out(f"{key}: {note}; couldn't delete it ({e.strerror}), {size(len(raw))}")
    for key in [k for k in state if k not in found]:
        del state[key]  # a log that has gone
    if not found:
        out("no combat logs found. Switch logging on in game with /combatlog or Gander's setting.")
    for game, path in saved:
        new_mobs, new_levels = merge_saved(data, game, read_saved(path))
        out(f"saved Gander database ({game}): stats for {new_mobs} new mobs, {new_levels} new mob levels")

    after = counts(data)
    totals = ", ".join(f"{game}: casts for {c[0]} mobs, stats for {c[2]}" for game, c in sorted(after.items()))
    out(f"the database now has {totals or 'nothing'}; {size(left_on_disk)} of logs left on disk.")
    lua_path = addon / f"{addon.name}.lua"
    version = current_version(addon)
    changed = not lua_path.is_file() or lua_path.read_text(encoding="utf-8") != to_lua(data, version)
    if dry_run:
        out("dry run: nothing was written or deleted." + (" The data would change." if changed else ""))
        return data
    save_json(data_path, data)
    save_json(state_path, state)
    if json.dumps(record, sort_keys=True) != record_before:
        save_json(logs_path, record)
    if changed and bump_version and (addon / f"{addon.name}.toc").is_file():
        note = changelog_line(before, after) or "Refreshed the stats of mobs already in the database."
        version = bump(addon, note, utc_day(now))
        out(f"GanderData is now {version}: {note}")
    if changed:
        addon.mkdir(parents=True, exist_ok=True)
        lua_path.write_text(to_lua(data, version), encoding="utf-8", newline="\n")
    else:
        out("nothing new for GanderData.")
    return data


def default_sources():
    logs, saved = [], []
    for folder, game in FOLDERS.items():
        logs.append(GAME_DIR / folder / "Logs")
        for path in sorted((GAME_DIR / folder / "WTF" / "Account").glob("*/SavedVariables/Gander.lua")):
            saved.append((game, path))
    return logs, saved


def main(argv=None):
    p = argparse.ArgumentParser(description="Import combat logs and saved stats into GanderData.")
    p.add_argument("--logs", action="append", help="a Logs folder to read (repeatable)")
    p.add_argument("--saved", action="append", metavar="GAME=FILE",
                   help="a saved Gander database to read (repeatable)")
    p.add_argument("--keep", action="store_true", help="don't delete logs after importing them")
    p.add_argument("--dry-run", action="store_true", help="change nothing; just report")
    p.add_argument("--no-bump", action="store_true", help="don't give GanderData a new version")
    p.add_argument("--release-since", metavar="OLD_JSON",
                   help="import nothing: give the data merged since OLD_JSON (the database as last "
                        "released) the next version, and print it")
    args = p.parse_args(argv)
    if args.release_since:
        print(prepare_release(args.release_since))
        return 0
    logs, saved = default_sources()
    if args.logs or args.saved:
        logs = args.logs or []
        saved = []
        for item in args.saved or []:
            game, _, path = item.partition("=")
            if game not in FOLDERS.values() or not path:
                p.error(f"--saved wants GAME=FILE with GAME one of {sorted(FOLDERS.values())}, not {item!r}")
            saved.append((game, pathlib.Path(path)))
    run(logs, saved, keep=args.keep, dry_run=args.dry_run, bump_version=not args.no_bump)
    return 0


if __name__ == "__main__":
    sys.exit(main())
