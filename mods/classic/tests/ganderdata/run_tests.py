"""Checks GanderData.lua, the generated database Gander reads. Usage: python run_tests.py path/to/GanderData.lua

The file is data, so these are checks on its shape: the game has to be able
to load it, Gander has to find what it expects, and nothing that names a
player may be in it.
"""
import pathlib
import re
import sys
from lupa import lua51

PATH = pathlib.Path(sys.argv[1])
ADDON = PATH.read_text(encoding="utf-8")
TOC = (PATH.parent / "GanderData.toc").read_text(encoding="utf-8")
GUARD = (pathlib.Path(__file__).parent.parent / "guard_globals.lua").read_text(encoding="utf-8")

MOCK = r'''
SlashCmdList = {}
UISpecialFrames = {}
StaticPopupDialogs = {}
function ok(c, m) if not c then error("FAIL: " .. tostring(m), 2) end end
before = {}
function load()
  for k in pairs(_G) do before[k] = true end   -- every global there was before the addon ran
  assert(loadstring(ADDON_SRC, "GanderData.lua"))("GanderData", {})
end
function count(t) local n = 0 for _ in pairs(t) do n = n + 1 end return n end
GAMES = { "forever", "classic" }
-- The stats Gander knows, as in Gander.lua's FIELDS.
NUMBERS = { def = 1, armor = 1, r1 = 1, r2 = 1, r3 = 1, r4 = 1, r5 = 1, r6 = 1, hp = 1, pow = 1, spd = 1, oh = 1,
            dmin = 1, dmax = 1, ap = 1, rspd = 1, rmin = 1, rmax = 1, s1 = 1, s2 = 1, s3 = 1, s4 = 1, s5 = 1, run = 1 }
TEXTS = { ptype = 20, class = 20, rk = 20, fam = 24, ty = 24, n = 40, z = 40 }
'''

SCENARIOS = {
"it loads and makes one global, GanderData": r'''
  load()
  ok(type(GanderData) == "table", "no GanderData table")
  for k in pairs(_G) do
    ok(before[k] or k == "GanderData", "made another global: " .. tostring(k))
  end
''',
"its version is the one in the .toc": r'''
  load()
  ok(GanderData.version == TOC_VERSION, tostring(GanderData.version) .. " but the .toc says " .. TOC_VERSION)
''',
"each game has the tables Gander reads": r'''
  load()
  local games = 0
  for _, game in ipairs(GAMES) do
    local g = GanderData[game]
    if g ~= nil then
      games = games + 1
      for _, key in ipairs({ "instances", "dungeons", "spells", "names", "casts", "inside", "stats" }) do
        ok(type(g[key]) == "table", game .. " has no " .. key .. " table")
      end
    end
  end
  ok(games > 0, "no game has any data")
  for key, value in pairs(GanderData) do
    ok(key == "version" or key == "forever" or key == "classic", "unexpected key " .. tostring(key))
  end
''',
"every mob's casts are spell ids with a name": r'''
  load()
  for _, game in ipairs(GAMES) do
    local g = GanderData[game] or { casts = {}, spells = {} }
    for mob, spells in pairs(g.casts) do
      ok(type(mob) == "number" and mob > 0 and mob == math.floor(mob), game .. ": mob id " .. tostring(mob))
      ok(type(spells) == "table" and #spells > 0, game .. ": mob " .. mob .. " has no spells")
      ok(#spells == count(spells), game .. ": mob " .. mob .. " has gaps in its spell list")
      local seen = {}
      for _, spell in ipairs(spells) do
        ok(type(spell) == "number" and spell > 0, game .. ": mob " .. mob .. " spell " .. tostring(spell))
        ok(not seen[spell], game .. ": mob " .. mob .. " lists spell " .. spell .. " twice")
        seen[spell] = true
        ok(type(g.spells[spell]) == "string" and g.spells[spell] ~= "", game .. ": spell " .. spell .. " has no name")
      end
    end
  end
''',
"every mob's stats are sightings Gander can read": r'''
  load()
  for _, game in ipairs(GAMES) do
    local g = GanderData[game] or { stats = {} }
    for mob, levels in pairs(g.stats) do
      ok(type(mob) == "number" and mob > 0 and mob == math.floor(mob), game .. ": mob id " .. tostring(mob))
      ok(type(levels) == "table" and next(levels) ~= nil, game .. ": mob " .. mob .. " has no levels")
      for level, seen in pairs(levels) do
        local where = game .. ": mob " .. mob .. " level " .. tostring(level)
        ok(type(level) == "number" and level == math.floor(level), where)
        ok(type(seen.at) == "number" and seen.at > 1700000000, where .. ": when it was seen")
        ok(type(seen.v) == "table" and next(seen.v) ~= nil, where .. ": no values")
        for key, value in pairs(seen.v) do
          if NUMBERS[key] then
            ok(type(value) == "number" and value > 0, where .. ": " .. key .. " = " .. tostring(value))
          else
            ok(TEXTS[key], where .. ": unknown field " .. tostring(key))
            ok(type(value) == "string" and #value > 0 and #value <= TEXTS[key], where .. ": " .. key)
          end
        end
        ok(count(seen) == 2, where .. ": has more than 'at' and 'v'")
      end
    end
  end
''',
"mobs with casts or stats have a name for the bestiary": r'''
  load()
  for _, game in ipairs(GAMES) do
    local g = GanderData[game] or { casts = {}, names = {} }
    for mob in pairs(g.casts) do
      ok(type(g.names[mob]) == "string" and g.names[mob] ~= "", game .. ": mob " .. mob .. " has no name")
    end
    for mob, name in pairs(g.names) do
      ok(type(mob) == "number" and type(name) == "string" and #name <= 60, game .. ": name of " .. tostring(mob))
    end
  end
''',
"instances are minutes of logged fighting": r'''
  load()
  for _, game in ipairs(GAMES) do
    for id, minutes in pairs((GanderData[game] or { instances = {} }).instances) do
      ok(type(id) == "number" and type(minutes) == "number" and minutes >= 0, game .. ": instance " .. tostring(id))
    end
  end
''',
"dungeons have names, and each mob's dungeons are ones that are named": r'''
  load()
  for _, game in ipairs(GAMES) do
    local g = GanderData[game] or { dungeons = {}, inside = {}, instances = {}, names = {} }
    for id, name in pairs(g.dungeons) do
      ok(type(id) == "number" and type(name) == "string" and name ~= "" and #name <= TEXTS.z, game .. ": dungeon " .. tostring(id))
      ok(g.instances[id] ~= nil, game .. ": dungeon " .. id .. " isn't among the instances")
    end
    for mob, list in pairs(g.inside) do
      ok(type(mob) == "number" and g.names[mob] ~= nil, game .. ": mob " .. tostring(mob) .. " is in a dungeon but not on the list")
      ok(type(list) == "table" and #list > 0 and #list == count(list), game .. ": mob " .. mob .. "'s dungeons")
      for _, id in ipairs(list) do
        ok(g.dungeons[id] ~= nil, game .. ": mob " .. mob .. " is in dungeon " .. tostring(id) .. ", which has no name")
      end
    end
  end
''',
"the zones mobs were logged in are short names, for mobs on the list": r'''
  load()
  for _, game in ipairs(GAMES) do
    local g = GanderData[game] or { names = {} }
    -- A file made before zones were recorded has no such table: Gander reads it as empty.
    for mob, list in pairs(g.zones or {}) do
      ok(type(mob) == "number" and g.names[mob] ~= nil, game .. ": mob " .. tostring(mob) .. " has a zone but isn't on the list")
      ok(type(list) == "table" and #list > 0 and #list == count(list), game .. ": mob " .. mob .. "'s zones")
      for _, zone in ipairs(list) do
        ok(type(zone) == "string" and zone ~= "" and #zone <= TEXTS.z, game .. ": mob " .. mob .. " zone " .. tostring(zone))
      end
    end
  end
''',
}

failed = 0
version = re.search(r"^## Version:\s*(\S+)", TOC, re.M).group(1)
for name, body in SCENARIOS.items():
    L = lua51.LuaRuntime()
    L.globals().ADDON_SRC = ADDON
    L.globals().TOC_VERSION = version
    try:
        L.execute(MOCK)
        L.execute(GUARD)
        L.execute(body)
        print("PASS", name)
    except Exception as e:
        failed += 1
        print("FAIL", name, "->", str(e).splitlines()[0])

# Nothing in the file may identify a player: character GUIDs, or the
# "Name-Realm" form the game writes player names in.
for pattern, what in ((r"Player-\d", "a player GUID"), (r"\bPet-\d", "a pet GUID"), (r"\bby\s*=", "who something was heard from")):
    if re.search(pattern, ADDON):
        failed += 1
        print("FAIL", "nothing in the file names a player", "->", "found " + what)
        break
else:
    print("PASS", "nothing in the file names a player")
print("failed:", failed)
sys.exit(1 if failed else 0)
