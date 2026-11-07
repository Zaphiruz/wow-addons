"""Runs Bushel.lua against a small fake WoW API. Usage: python run_tests.py path/to/Bushel.lua"""
import pathlib
import sys
from lupa import lua51

ADDON = open(sys.argv[1], encoding="utf-8").read()
GUARD = (pathlib.Path(__file__).parent.parent / "guard_globals.lua").read_text(encoding="utf-8")

MOCK = r'''
out, events = {}, {}
function print(...) local t = {} for i = 1, select("#", ...) do t[#t+1] = tostring(select(i, ...)) end out[#out+1] = table.concat(t, " ") end
format, tinsert, tremove = string.format, table.insert, table.remove
function strtrim(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end
SlashCmdList = {}
UISpecialFrames = {}
StaticPopupDialogs = {}

player = { name = "Zaphiruz", realm = "Whitemane", class = "PRIEST" }
function UnitName(u) if u == "player" then return player.name end end
function GetRealmName() return player.realm end
function UnitClass(u) if u == "player" then return "Priest", player.class end end
now = 100
function GetTime() return now end

timers = {}
C_Timer = { After = function(d, fn) table.insert(timers, { at = now + d, fn = fn }) end }
function advance(seconds)
  local stop = now + seconds
  while true do
    local nextIdx
    for i, t in ipairs(timers) do
      if t.at <= stop and (not nextIdx or t.at < timers[nextIdx].at) then nextIdx = i end
    end
    if not nextIdx then break end
    local t = table.remove(timers, nextIdx)
    if t.at > now then now = t.at end
    t.fn()
  end
  now = stop
end

-- Spells by ID, as the Classic Era client names them.
SPELLS = { [2575] = "Mining", [2576] = "Mining", [2366] = "Herb Gathering", [8613] = "Skinning",
           [7620] = "Fishing", [1804] = "Pick Lock", [585] = "Smite", [999001] = "Mining" }
function GetSpellInfo(id) return SPELLS[id], nil, 136248 end

-- Forever hides some values from addons ("secret values").
SECRET = setmetatable({}, { __index = function() error("read a secret value") end,
                            __eq = function() error("compared a secret value") end })
function issecretvalue(v) return v == nil and false or rawequal(v, SECRET) end

-- Loot: the node or corpse the open loot window came from.
lootSource = nil
function GetLootSourceInfo(slot) if lootSource then return lootSource, 1 end end

-- Frames: only what the addon uses.
local noop = function() end
local widgetMT = { __index = function() return noop end }
function widget(kind, name)
  local w = setmetatable({ kind = kind, name = name, scripts = {}, hooks = {}, shown = false, text = "" }, widgetMT)
  function w:SetScript(s, fn) self.scripts[s] = fn end
  function w:GetScript(s) return self.scripts[s] end
  function w:HookScript(s, fn) self.hooks[s] = self.hooks[s] or {}; table.insert(self.hooks[s], fn) end
  function w:RunHooks(s, ...) for _, fn in ipairs(self.hooks[s] or {}) do fn(self, ...) end end
  function w:RegisterEvent(e) events[e] = self end
  function w:GetName() return self.name end
  function w:SetText(t) self.text = t end
  function w:GetText() return self.text end
  return w
end
function CreateFrame(kind, name) local w = widget(kind, name); if name then _G[name] = w end; return w end

-- The game tooltip, with the hooks the client offers.
GameTooltip = widget("GameTooltip", "GameTooltip")
GameTooltipTextLeft1 = widget("FontString", "GameTooltipTextLeft1")
GameTooltip.lines, GameTooltip.item = {}, false
function GameTooltip:AddLine(t) table.insert(self.lines, t); if #self.lines == 1 then GameTooltipTextLeft1:SetText(t) end end
function GameTooltip:ClearLines() self.lines = {}; GameTooltipTextLeft1:SetText(nil); self.item = false; self:RunHooks("OnTooltipCleared") end
function GameTooltip:Show() self.shown = true; self:RunHooks("OnShow") end
function GameTooltip:Hide() self.shown = false end
function GameTooltip:GetItem() return self.item end
Enum = { TooltipDataType = { Item = 0, Spell = 1, Unit = 2, Object = 33 } }
postCalls = {}
TooltipDataProcessor = { AddTooltipPostCall = function(kind, fn)
  postCalls[kind] = postCalls[kind] or {}; table.insert(postCalls[kind], fn) end }

-- Point the mouse at something: the client fills the tooltip, runs the
-- post-calls for its data type, then shows it.
function hover(kind, name, opts)
  opts = opts or {}
  GameTooltip:ClearLines()
  GameTooltip:AddLine(name)
  for _, l in ipairs(opts.extra or {}) do GameTooltip:AddLine(l) end
  if kind == "Item" then GameTooltip.item = name end
  if not opts.noPostCall then
    for _, fn in ipairs(postCalls[Enum.TooltipDataType[kind]] or {}) do
      fn(GameTooltip, { type = Enum.TooltipDataType[kind], lines = { { leftText = name } } })
    end
  end
  GameTooltip:Show()
  return tip()
end
local function plain(s) return (tostring(s):gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", "")) end
-- The tooltip's lines after the first, without colour codes.
function tip() local t = {} for i = 2, #GameTooltip.lines do t[#t+1] = plain(GameTooltip.lines[i]) end return table.concat(t, "\n") end

-- Cast a gather spell at a node and loot it. guid = the node, or nil.
casts = 0
function gather(spellID, target, guid, opts)
  opts = opts or {}
  casts = casts + 1
  local cast = "Cast-3-0-0-" .. tostring(spellID) .. "-" .. casts
  fire("UNIT_SPELLCAST_SENT", opts.unit or "player", target, cast, spellID)
  if opts.fail then
    fire("UNIT_SPELLCAST_FAILED", "player", cast, spellID)
    return
  end
  fire("UNIT_SPELLCAST_SUCCEEDED", opts.unit or "player", cast, spellID)
  if opts.noLoot then return end
  lootSource = guid
  fire("LOOT_OPENED", true)
  fire("LOOT_CLOSED")
  lootSource = nil
end
function mine(target, guid) gather(2575, target, guid) end
function herb(target, guid) gather(2366, target, guid) end
function skin(target, guid) gather(8613, target, guid) end
nodes = 0
function node() nodes = nodes + 1; return "GameObject-0-1-0-0-1731-" .. nodes end

function fire(e, ...) local f = events[e]; if f then f.scripts.OnEvent(f, e, ...) end end
function login(saved)
  BushelDB = saved
  events = {}
  timers = {}
  postCalls = {}
  GameTooltip.hooks = {}
  assert(loadstring(ADDON_SRC, "Bushel.lua"))("Bushel")
  fire("ADDON_LOADED", "Bushel")
  fire("PLAYER_LOGIN")
end
function cmd(s) out = {}; SlashCmdList.BUSHEL(s); return table.concat(out, "\n") end
function ok(c, m) if not c then error("FAIL: " .. m, 2) end end
function me() return BushelDB.chars["Zaphiruz-Whitemane"] end
function alt(counts) return { name = "Bankalt", realm = "Whitemane", class = "MAGE", counts = counts } end
'''

SCENARIOS = {
# ---- counting ----
"first login starts this character with nothing gathered": r'''
  login(nil)
  ok(me() and me().name == "Zaphiruz" and me().realm == "Whitemane" and me().class == "PRIEST", "entry made")
  ok(next(me().counts.mining) == nil and next(me().counts.herbalism) == nil and next(me().counts.skinning) == nil, "empty")
''',
"mining, herbs and skinning are counted by type": r'''
  login(nil)
  mine("Copper Vein", node())
  mine("Copper Vein", node())
  mine("Tin Vein", node())
  herb("Peacebloom", node())
  skin("Plainstrider", "Creature-0-1-0-0-2955-1")
  ok(me().counts.mining["Copper Vein"] == 2, "copper " .. tostring(me().counts.mining["Copper Vein"]))
  ok(me().counts.mining["Tin Vein"] == 1, "tin")
  ok(me().counts.herbalism.Peacebloom == 1, "peacebloom")
  ok(me().counts.skinning.Plainstrider == 1, "plainstrider")
''',
"a vein mined several times counts once": r'''
  login(nil)
  local vein = node()
  mine("Copper Vein", vein); mine("Copper Vein", vein); mine("Copper Vein", vein)
  ok(me().counts.mining["Copper Vein"] == 1, "got " .. tostring(me().counts.mining["Copper Vein"]))
  mine("Copper Vein", node())
  ok(me().counts.mining["Copper Vein"] == 2, "a new vein counts")
''',
"a node remembered long ago counts again": r'''
  login(nil)
  local vein = node()
  mine("Copper Vein", vein)
  advance(3600)   -- the same spawn point, an hour later
  mine("Copper Vein", vein)
  ok(me().counts.mining["Copper Vein"] == 2, "got " .. tostring(me().counts.mining["Copper Vein"]))
''',
"a gather that fails or is interrupted doesn't count": r'''
  login(nil)
  gather(2575, "Copper Vein", node(), { fail = true })
  advance(10)
  ok(me().counts.mining["Copper Vein"] == nil, "counted a failed gather")
''',
"other spells don't count": r'''
  login(nil)
  gather(7620, "", node())                 -- fishing
  gather(1804, "Battered Chest", node())   -- pick lock
  gather(585, "Plainstrider", "Creature-0-1-0-0-2955-2")
  for _, k in ipairs({ "mining", "herbalism", "skinning" }) do ok(next(me().counts[k]) == nil, k) end
''',
"another rank or game version's gather spell is known by its name": r'''
  login(nil)
  gather(2576, "Tin Vein", node())         -- Journeyman Mining
  gather(999001, "Silver Vein", node())    -- an ID this addon has never seen
  ok(me().counts.mining["Tin Vein"] == 1 and me().counts.mining["Silver Vein"] == 1, "by name")
''',
"other players' casts don't count": r'''
  login(nil)
  gather(2575, "Copper Vein", node(), { unit = "party1" })
  advance(10)
  ok(me().counts.mining["Copper Vein"] == nil, "counted someone else")
''',
"a gather still counts if no loot window shows": r'''
  login(nil)
  gather(2575, "Copper Vein", node(), { noLoot = true })
  ok(me().counts.mining["Copper Vein"] == nil, "not yet")
  advance(5)
  ok(me().counts.mining["Copper Vein"] == 1, "counted after waiting")
''',
"without loot sources, every gather counts": r'''
  GetLootSourceInfo = nil
  login(nil)
  mine("Copper Vein", "x"); mine("Copper Vein", "x")
  ok(me().counts.mining["Copper Vein"] == 2, "got " .. tostring(me().counts.mining["Copper Vein"]))
''',
"counts are kept for the next session": r'''
  login(nil)
  mine("Copper Vein", node())
  login(BushelDB)
  mine("Copper Vein", node())
  ok(me().counts.mining["Copper Vein"] == 2, "got " .. tostring(me().counts.mining["Copper Vein"]))
''',

# ---- tooltips ----
"a node's tooltip shows this character and the account": r'''
  login({ chars = { ["Bankalt-Whitemane"] = alt({ mining = { ["Copper Vein"] = 5 }, herbalism = {}, skinning = {} }) } })
  mine("Copper Vein", node())
  local t = hover("Object", "Copper Vein", { extra = { "Requires Mining" } })
  ok(t == "Requires Mining\nMined: 1 (account 6)", t)
  t = hover("Unit", "Plainstrider")
  ok(t == "", "nothing for a type never gathered: " .. t)
''',
"each kind has its own word": r'''
  login(nil)
  herb("Peacebloom", node())
  skin("Plainstrider", "Creature-0-1-0-0-2955-1")
  ok(hover("Object", "Peacebloom") == "Gathered: 1 (account 1)", tip())
  ok(hover("Unit", "Plainstrider") == "Skinned: 1 (account 1)", tip())
''',
"only alts have gathered it: shows zero here": r'''
  login({ chars = { ["Bankalt-Whitemane"] = alt({ mining = { ["Tin Vein"] = 1234 }, herbalism = {}, skinning = {} }) } })
  ok(hover("Object", "Tin Vein") == "Mined: 0 (account 1,234)", tip())
''',
"the count is added once per tooltip": r'''
  login(nil)
  mine("Copper Vein", node())
  local t = hover("Object", "Copper Vein")
  ok(t == "Mined: 1 (account 1)", t)
  GameTooltip:Show()   -- shown again without being cleared
  ok(tip() == "Mined: 1 (account 1)", tip())
''',
"tooltips without the data hook still get the count": r'''
  TooltipDataProcessor = nil
  login(nil)
  mine("Copper Vein", node())
  ok(hover("Object", "Copper Vein", { noPostCall = true }) == "Mined: 1 (account 1)", tip())
''',
"items named like a herb don't get the count": r'''
  login(nil)
  herb("Peacebloom", node())
  ok(hover("Item", "Peacebloom", { noPostCall = true }) == "", tip())
''',
"the count updates the next time the tooltip shows": r'''
  login(nil)
  mine("Copper Vein", node())
  hover("Object", "Copper Vein")
  mine("Copper Vein", node())
  ok(hover("Object", "Copper Vein") == "Mined: 2 (account 2)", tip())
''',

# ---- Forever ----
"on Forever, spells are named through C_Spell": r'''
  GetSpellInfo = nil
  C_Spell = { GetSpellName = function(id) return SPELLS[id] end }
  login(nil)
  mine("Copper Vein", node())
  ok(me().counts.mining["Copper Vein"] == 1, "counted")
''',
"hidden (secret) values are skipped without errors": r'''
  login(nil)
  gather(2575, SECRET, node())
  gather(SECRET, "Copper Vein", node())
  fire("UNIT_SPELLCAST_SENT", "player", "Copper Vein", SECRET, 2575)
  fire("UNIT_SPELLCAST_SUCCEEDED", "player", SECRET, 2575)
  advance(10)
  ok(next(me().counts.mining) == nil, "counted a hidden gather")
  mine("Copper Vein", node())
  -- a tooltip whose name is hidden
  GameTooltip:ClearLines(); GameTooltip:AddLine(SECRET)
  for _, fn in ipairs(postCalls[Enum.TooltipDataType.Object]) do fn(GameTooltip, { lines = { { leftText = SECRET } } }) end
  GameTooltip:Show()
  ok(#GameTooltip.lines == 1, "added a line to a hidden tooltip")
  lootSource = SECRET
  gather(2575, "Tin Vein", nil)
  ok(me().counts.mining["Tin Vein"] == 1, "a hidden loot source still counts")
''',

# ---- commands ----
"/bushel list shows this character's counts, most first": r'''
  login({ chars = { ["Bankalt-Whitemane"] = alt({ mining = { ["Copper Vein"] = 10 }, herbalism = {}, skinning = {} }) } })
  mine("Tin Vein", node())
  mine("Copper Vein", node()); mine("Copper Vein", node())
  herb("Peacebloom", node())
  local o = cmd("list")
  ok(o:find("Mining") and o:find("Herbalism"), o)
  ok(not o:find("Skinning"), "no empty kinds: " .. o)
  ok(o:find("Copper Vein: 2 %(account 12%)") and o:find("Tin Vein: 1 %(account 1%)"), o)
  ok(o:find("Copper Vein") < o:find("Tin Vein"), "most first: " .. o)
''',
"/bushel list on a fresh character": r'''
  login(nil)
  ok(cmd("list"):find("nothing gathered"), cmd("list"))
''',
"/bushel help, debug and unknown words": r'''
  login(nil)
  local o = cmd("help")
  ok(o:find("/bushel list") and o:find("/bushel debug"), o)
  o = cmd("banana")
  ok(o:find("banana") and o:find("/bushel help"), o)
  cmd("debug")
  out = {}
  mine("Copper Vein", node())
  ok(table.concat(out, "\n"):find("Copper Vein"), "debug prints the gather: " .. table.concat(out, "\n"))
  cmd("")
  ok(true, "bare /bushel works")
''',
"/bushel says so if loading failed": r'''
  login(nil)
  local saved = BushelDB
  -- load again without the saved-data event, as when an error stopped it
  events = {}
  assert(loadstring(ADDON_SRC, "Bushel.lua"))("Bushel")
  ok(cmd("list"):find("didn't finish loading"), cmd("list"))
''',
}

failed = 0
for name, body in SCENARIOS.items():
    L = lua51.LuaRuntime()
    L.globals().ADDON_SRC = ADDON
    try:
        L.execute(MOCK)
        L.execute(GUARD)
        L.execute(body)
        print("PASS", name)
    except Exception as e:
        failed += 1
        print("FAIL", name, "->", str(e).splitlines()[0])
print("failed:", failed)
sys.exit(1 if failed else 0)
