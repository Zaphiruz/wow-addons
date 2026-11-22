"""Runs Gander.lua against a small fake WoW API. Usage: python run_tests.py path/to/Gander.lua"""
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
now = 100
function GetTime() return now end
clock = 1795000000  -- the calendar time, which moves with the game time
function time() return clock end
date = os.date
math.random = function(a, b) if a then return b or a end return 0.5 end

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
    if t.at > now then clock = clock + (t.at - now); now = t.at end
    t.fn()
  end
  clock = clock + (stop - now)
  now = stop
end

-- Forever hides some values from addons ("secret values").
SECRET = setmetatable({}, { __index = function() error("read a secret value") end,
                            __lt = function() error("compared a secret value") end,
                            __le = function() error("compared a secret value") end,
                            __concat = function() error("joined a secret value") end })
function issecretvalue(v) return rawequal(v, SECRET) end

-- Which game: Forever has the modern tooltip hooks and UnitDefenseSkill.
forever = true

-- Units. A mob: name, level, guid, and the stats the game sends for it.
-- Unset stats read as zero, the way the game reports a stat it doesn't send.
-- hidden = the game hides its stats; noid = the game hides who it is.
units = { player = { name = "Zaphiruz", level = 30, isPlayer = true, guid = "Player-1-00000001" } }
function mob(id, p)
  p.guid = p.guid or ("Creature-0-4444-1-55-" .. id .. "-0000ABCDEF")
  p.isPlayer = false
  p.hidden, p.noid = p.hidden or false, p.noid or false
  return p
end
BOAR = function() return mob(3100, { name = "Elder Mottled Boar", level = 9, def = 45, speed = 2 }) end
local function U(u) return units[u] end
local function stat(u, field, ...)
  local x = U(u)
  if not x then return nil end
  if x.hidden then return SECRET end
  if select("#", ...) > 0 then return ... end
  return x[field] or 0
end
function UnitExists(u) return U(u) ~= nil end
function UnitIsPlayer(u) local x = U(u); return x ~= nil and x.isPlayer == true end
function UnitLevel(u) local x = U(u); return x and x.level or 0 end
-- Where you are, and what kind of creature a mob is: its type ("Beast") and
-- rank ("elite", "rare", ...; "normal" when unset).
zoneName = "Durotar"
function GetRealZoneText() return zoneName end
function UnitCreatureType(u) local x = U(u); if not x then return nil end if x.noid then return SECRET end return x.type end
function UnitClassification(u) local x = U(u); return x and x.rank or "normal" end
function UnitAffectingCombat(u) local x = U(u); return x ~= nil and x.combat == true end
function UnitName(u) local x = U(u); if not x then return nil end if x.noid then return SECRET end return x.name end
function UnitGUID(u) local x = U(u); if not x then return nil end if x.noid then return SECRET end return x.guid end
function UnitDefenseSkill(u) local x = U(u); if x and x.hidden then return SECRET, SECRET end return x and x.def or 0, 0 end
function UnitAttackSpeed(u) local x = U(u); if x and x.hidden then return SECRET end return x and x.speed or 0, x and x.offhand end
function UnitHealthMax(u) return stat(u, "hp") end
function UnitPowerMax(u) return stat(u, "power") end
function UnitPowerType(u) local x = U(u); return 0, x and x.powerType or "MANA" end
function UnitArmor(u) local x = U(u); if x and x.hidden then return SECRET, SECRET, SECRET, SECRET end
  local a = x and x.armor or 0; return a, a, a, 0 end
function UnitResistance(u, school) local x = U(u); if x and x.hidden then return SECRET, SECRET, SECRET, SECRET end
  local r = x and x.res and x.res[school] or 0; return r, r, r, 0 end
function UnitDamage(u) local x = U(u); if x and x.hidden then return SECRET, SECRET end
  local d = x and x.damage or { 0, 0 }; return d[1], d[2], 0, 0, 0, 0, 1 end
function UnitAttackPower(u) local x = U(u); if x and x.hidden then return SECRET, SECRET, SECRET end return x and x.ap or 0, 0, 0 end
function UnitRangedDamage(u) local x = U(u); if x and x.hidden then return SECRET, SECRET, SECRET end
  local r = x and x.ranged or { 0, 0, 0 }; return r[1], r[2], r[3], 0, 0, 1 end
function UnitStat(u, i) local x = U(u); if x and x.hidden then return SECRET, SECRET, SECRET, SECRET end
  local s = x and x.stats and x.stats[i] or 0; return s, s, 0, 0 end
function GetUnitSpeed(u) local x = U(u); if x and x.hidden then return SECRET, SECRET, SECRET, SECRET end return 0, x and x.run or 0, 0, 0 end
function UnitClass(u) local x = U(u); if not x then return nil end if x.noid then return SECRET, SECRET end
  if x.class then return x.class:sub(1, 1) .. x.class:sub(2):lower(), x.class end end
function UnitCreatureFamily(u) local x = U(u); if not x then return nil end if x.noid then return SECRET end return x.family end
LOCALIZED_CLASS_NAMES_MALE = { MAGE = "Mage", WARRIOR = "Warrior", PALADIN = "Paladin" }
function GetRealmName() return "Whitemane" end
function GetNormalizedRealmName() return "Whitemane" end

-- Guild, group and addon messages.
guild, grouped, raid, lockdown, encounter = true, false, false, false, false
function IsInGuild() return guild end
function IsInGroup() return grouped end
function IsInRaid() return raid end
C_InstanceEncounter = { IsEncounterInProgress = function() return encounter end }  -- Forever's name
sent, prefixes = {}, {}
-- Gander signs its messages: "<payload>#<8 hex digits>". This is the test's
-- own copy of the checksum, so a change to the addon's must be deliberate.
SIGN_KEY = "Gander:honk:4d7e1c9a"
function sign(payload)
  local h, text = 7, SIGN_KEY .. payload .. SIGN_KEY
  for i = 1, #text do h = (h * 131 + text:byte(i)) % 2147483647 end
  return payload .. "#" .. string.format("%08x", h)
end
unsignedSent = 0
fullMessages = false
function withoutInfo(payload)
  local head, body = payload:match("^(%d:%u:%d+:%-?%d+:)(.*)$")
  if not head then return payload end
  local keep = {}
  for part in body:gmatch("[^,]+") do
    local key = part:match("^(%w+)=")
    if not (key == "n" or key == "ty" or key == "rk" or key == "z") then keep[#keep + 1] = part end
  end
  return head .. table.concat(keep, ",")
end
-- Custom chat channels: the names joined, in order. channelResult is what the
-- game answers to an addon message sent to a channel (0 = sent).
channels, channelResult = {}, 0
refusals = {}  -- channel sends the game answered with an error
function JoinTemporaryChannel(name) for _, c in ipairs(channels) do if c == name then return end end table.insert(channels, name) end
function LeaveChannelByName(name) for i, c in ipairs(channels) do if c == name then table.remove(channels, i) return end end end
function GetChannelName(name) for i, c in ipairs(channels) do if c == name then return i, c, 0 end end return 0, nil, 0 end
Enum = Enum or {}
Enum.SendAddonMessageResult = { Success = 0, AddonMessageThrottle = 3, InvalidChatType = 4, InvalidChannel = 7, ChannelThrottle = 8 }
echo = "Zaphiruz-Whitemane"  -- how the game names you as the sender of your own messages
C_ChatInfo = {
  RegisterAddonMessagePrefix = function(p) prefixes[p] = true; return true end,
  SendAddonMessage = function(prefix, text, channel, target)
    assert(#text <= 255, "addon message too long: " .. #text)
    local wire = text
    local payload = text:match("^(.*)#%x+$")
    if not payload or sign(payload) ~= text then unsignedSent = unsignedSent + 1 end
    text = payload or text
    if not fullMessages then text = withoutInfo(text) end
    assert(not lockdown and not encounter, "sent while chat is locked")
    if channel == "CHANNEL" then
      assert(channels[target] ~= nil, "sent to a channel that isn't joined: " .. tostring(target))
      if channelResult ~= 0 then table.insert(refusals, channelResult); return channelResult end
      table.insert(sent, "CHANNEL " .. channels[target] .. ": " .. text)
    else
      table.insert(sent, channel .. ": " .. text)
    end
    -- The game sends your own guild and group messages back to you.
    if echo then fire("CHAT_MSG_ADDON", prefix, wire, channel, echo, echo) end
    return 0
  end,
  InChatMessagingLockdown = function() return lockdown end,
}
-- A message exactly as given, with no signature added.
function hearRaw(text, sender, channel)
  fire("CHAT_MSG_ADDON", "Gander", text, channel or "GUILD", sender or "Bob-Whitemane", sender or "Bob-Whitemane")
end
-- A message from another player running Gander: properly signed.
function hear(text, sender, channel) hearRaw(sign(text), sender, channel) end

-- Frames: what the settings panel and tooltip use.
local noop = function() end
local widgetMT = { __index = function() return noop end }
function widget(kind, name, parent, template)
  local w = setmetatable({ kind = kind, name = name, parent = parent, template = template, scripts = {},
                           hooks = {}, shown = true, text = "", checked = false, enabled = true }, widgetMT)
  function w:SetScript(s, fn) self.scripts[s] = fn end
  function w:GetScript(s) return self.scripts[s] end
  function w:HookScript(s, fn) self.hooks[s] = self.hooks[s] or {}; table.insert(self.hooks[s], fn) end
  function w:RunHooks(s, ...) for _, fn in ipairs(self.hooks[s] or {}) do fn(self, ...) end end
  function w:RegisterEvent(e) events[e] = self end
  function w:SetText(t) self.text = t == nil and "" or tostring(t) end
  function w:GetText() return self.text end
  function w:SetChecked(v) self.checked = not not v end
  function w:GetChecked() return self.checked end
  function w:Show() self.shown = true; if self.scripts.OnShow then self.scripts.OnShow(self) end end
  function w:Hide() self.shown = false end
  function w:IsShown() return self.shown end
  function w:SetShown(v) if v then self:Show() else self:Hide() end end
  function w:ClearAllPoints() self.point = nil end
  function w:SetPoint(...) self.point = { ... } end
  function w:SetEnabled(v) self.enabled = not not v end
  function w:IsEnabled() return self.enabled end
  function w:GetStringHeight() return 0 end
  function w:SetMaxLetters(n) self.maxLetters = n end
  -- The player types into an edit box.
  function w:Type(t)
    if self.maxLetters and #t > self.maxLetters then t = t:sub(1, self.maxLetters) end
    self.text = t
    if self.scripts.OnTextChanged then self.scripts.OnTextChanged(self, true) end
  end
  function w:CreateFontString(n) return widget("FontString", n, self) end
  function w:CreateTexture(n) return widget("Texture", n, self) end
  function w:Click(button)
    if self.kind == "CheckButton" then self.checked = not self.checked end
    if self.scripts.OnClick then self.scripts.OnClick(self, button or "LeftButton") end
  end
  return w
end
function CreateFrame(kind, name, parent, template)
  local w = widget(kind, name, parent, template)
  if name then _G[name] = w end
  return w
end
UIParent = widget("Frame", "UIParent")
Minimap = widget("Frame", "Minimap")
function Minimap:GetCenter() return 100, 100 end
function Minimap:GetWidth() return 140 end
function Minimap:GetEffectiveScale() return 1 end
cursorX, cursorY = 0, 0
function GetCursorPosition() return cursorX, cursorY end

GameTooltip = widget("GameTooltip", "GameTooltip")
GameTooltip.lines, GameTooltip.unit = {}, false
function GameTooltip:AddLine(t) table.insert(self.lines, t) end
function GameTooltip:ClearLines() self.lines = {}; self:RunHooks("OnTooltipCleared") end
function GameTooltip:GetUnit() if self.unit then return UnitName(self.unit), self.unit end end
Enum.TooltipDataType = { Item = 0, Unit = 2 }
postCalls = {}
TooltipDataProcessor = { AddTooltipPostCall = function(kind, fn)
  postCalls[kind] = postCalls[kind] or {}; table.insert(postCalls[kind], fn) end }
function plain(s) return (s:gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", "")) end
-- Mouse over a unit: returns the lines the addon added, joined with " | ".
function hover(u)
  GameTooltip:ClearLines()
  GameTooltip.unit = u
  GameTooltip:AddLine("name")
  GameTooltip:AddLine("Level 9 Beast")
  if TooltipDataProcessor then
    for _, fn in ipairs(postCalls[Enum.TooltipDataType.Unit] or {}) do fn(GameTooltip, { type = 2 }) end
  else
    GameTooltip:RunHooks("OnTooltipSetUnit")
  end
  local t = {}
  for i = 3, #GameTooltip.lines do t[#t+1] = plain(GameTooltip.lines[i]) end
  return table.concat(t, " | ")
end
-- Classic Era: the old tooltip hooks, and no UnitDefenseSkill.
function classicEra()
  forever = false; TooltipDataProcessor = nil; UnitDefenseSkill = nil
  C_InstanceEncounter = nil
  function IsEncounterInProgress() return encounter end
end

-- The game's settings window.
categories, opened = {}, nil
Settings = {
  RegisterCanvasLayoutCategory = function(frame, name)
    local c = { frame = frame, name = name, id = 77 }
    function c:GetID() return self.id end
    return c
  end,
  RegisterAddOnCategory = function(c) table.insert(categories, c) end,
  OpenToCategory = function(id) opened = id end,
}

function fire(e, ...) local f = events[e]; if f then f.scripts.OnEvent(f, e, ...) end end
function login(saved)
  GanderDB = saved
  events, timers, categories, postCalls = {}, {}, {}, {}
  GameTooltip.hooks = {}
  assert(loadstring(ADDON_SRC, "Gander.lua"))("Gander")
  fire("ADDON_LOADED", "Gander")
  fire("PLAYER_LOGIN")
end
function cmd(s) out = {}; SlashCmdList.GANDER(s); return table.concat(out, "\n") end
function ok(c, m) if not c then error("FAIL: " .. tostring(m), 2) end end
function list(t) return table.concat(t, " | ") end
function panel() return categories[1].frame end
-- Log in with the channel switched off, for tests about guild and group only.
function loginNoChannel() login({ channel = false }) end
function check(key) return panel().checks[key] end
function known(id, level, values, age)
  GanderDB.mobs[id] = GanderDB.mobs[id] or { lv = {}, heard = {} }
  GanderDB.mobs[id].lv[level] = { at = clock - (age or 0), v = values }
end
-- Three mobs: two seen in Stranglethorn Vale, one heard about from Bob.
function sampleMobs()
  zoneName = "Stranglethorn Vale"
  units.mouseover = mob(681, { name = "Young Stranglethorn Tiger", level = 30, def = 150, speed = 1.3,
                               type = "Beast", family = "Cat" })
  hover("mouseover")
  units.mouseover = mob(1108, { name = "Mistvale Gorilla", level = 33, def = 165, speed = 2, type = "Beast", rank = "elite" })
  hover("mouseover")
  hear("2:M:4000:20:spd=2.5,n=Defias Wizard,ty=Humanoid,z=Westfall", "Bob-Whitemane")
end
function rowText(r) return r.name:GetText() .. " / " .. r.level:GetText() .. " / " .. r.kind:GetText() .. " / " .. r.zone:GetText() end
function today() return tonumber(os.date("%d", clock)) .. " " .. os.date("%b", clock) end
'''

SCENARIOS = {
# ---- settings and saved data ----
"first login sets up the defaults": r'''
  login(nil)
  ok(GanderDB.tooltips == true and GanderDB.remembered == true and GanderDB.share == true, "switches on")
  ok(GanderDB.channel == true, "channel on")
  ok(GanderDB.signedOnly == true, "signed only on")
  ok(GanderDB.minimap.hide == false and GanderDB.minimap.angle == 225, "minimap button on, bottom left")
  ok(type(GanderDB.mobs) == "table" and next(GanderDB.mobs) == nil, "empty memory")
  for _, k in ipairs({ "defense", "armor", "resist", "health", "power", "speed", "damage", "ap", "ranged",
                       "stats", "run", "class", "family" }) do
    ok(GanderDB.lines[k] == true, "line " .. k .. " on")
  end
''',
"saved settings are kept and missing ones filled in": r'''
  login({ tooltips = false, lines = { speed = false }, mobs = { [7] = { lv = {} } } })
  ok(GanderDB.tooltips == false and GanderDB.lines.speed == false, "kept")
  ok(GanderDB.share == true and GanderDB.lines.defense == true, "filled in")
  ok(GanderDB.mobs[7] ~= nil, "memory kept")
''',

# ---- tooltip lines ----
"a mob's tooltip shows its defense and attack speed": r'''
  login(nil)
  units.mouseover = BOAR()
  local t = hover("mouseover")
  ok(t == "Defense: 45 | Attack speed: 2.0", t)
''',
"stats the game doesn't send (zero) get no line": r'''
  login(nil)
  units.mouseover = mob(3100, { name = "Boar", level = 9, def = 45 })
  local t = hover("mouseover")
  ok(t == "Defense: 45", t)
''',
"every stat the game does send gets a line": r'''
  login(nil)
  units.mouseover = mob(4000, { name = "Defias Wizard", level = 20, def = 100, armor = 1200,
    res = { [2] = 50, [4] = 20 }, hp = 1240, power = 2300, powerType = "MANA", speed = 2, offhand = 1.5,
    damage = { 12, 18.6 }, ap = 120, ranged = { 2.8, 10, 14 }, stats = { 20, 15, 30, 10, 12 }, run = 8,
    class = "MAGE", family = "Boar" })
  local t = hover("mouseover")
  local want = { "Defense: 100", "Armor: 1,200", "Resistances: Fire 50, Frost 20", "Health: 1,240",
    "Mana: 2,300", "Attack speed: 2.0 / 1.5", "Damage: 12 - 19", "Attack power: 120",
    "Ranged: 10 - 14, speed 2.8", "Stats: Str 20, Agi 15, Sta 30, Int 10, Spi 12", "Run speed: 114%",
    "Class: Mage", "Family: Boar" }
  ok(t == table.concat(want, " | "), t)
''',
"power is named after its kind": r'''
  login(nil)
  units.mouseover = mob(5, { name = "Cat", level = 9, def = 45, power = 100, powerType = "ENERGY" })
  ok(hover("mouseover"):find("Energy: 100"), hover("mouseover"))
  units.mouseover = mob(6, { name = "Odd", level = 9, def = 45, power = 100, powerType = "FURY" })
  ok(hover("mouseover"):find("Power: 100"), hover("mouseover"))
''',
"an attack speed that isn't round keeps its decimals": r'''
  login(nil)
  units.mouseover = mob(5, { name = "Cat", level = 9, def = 45, speed = 1.33 })
  ok(hover("mouseover"):find("Attack speed: 1.33"), hover("mouseover"))
  units.mouseover.speed = 2.6
  ok(hover("mouseover"):find("Attack speed: 2.6$"), hover("mouseover"))
''',
"players get no lines": r'''
  login(nil)
  units.mouseover = { name = "Bob", level = 30, isPlayer = true, guid = "Player-1-00000002", def = 150, speed = 2 }
  ok(hover("mouseover") == "", hover("mouseover"))
  ok(next(GanderDB.mobs) == nil, "remembered a player")
''',
"switching a line off hides it, and the main switch hides them all": r'''
  login(nil)
  units.mouseover = BOAR()
  GanderDB.lines.speed = false
  ok(hover("mouseover") == "Defense: 45", hover("mouseover"))
  GanderDB.lines.speed, GanderDB.lines.defense = true, false
  ok(hover("mouseover") == "Attack speed: 2.0", hover("mouseover"))
  GanderDB.tooltips = false
  ok(hover("mouseover") == "", hover("mouseover"))
''',

# ---- Classic Era ----
"on Classic Era defense is worked out from level, and lines aren't added twice": r'''
  classicEra()
  login(nil)
  units.mouseover = mob(3100, { name = "Boar", level = 9, speed = 2 })
  local t = hover("mouseover")
  ok(t == "Defense: 45 | Attack speed: 2.0", t)
  GameTooltip:RunHooks("OnTooltipSetUnit")  -- the game can set a unit twice
  ok(#GameTooltip.lines == 4, "added twice: " .. #GameTooltip.lines)
''',
"a skull-level mob has no worked-out defense": r'''
  classicEra()
  login(nil)
  units.mouseover = mob(11502, { name = "Ragnaros", level = -1, speed = 2 })
  ok(hover("mouseover") == "Attack speed: 2.0", hover("mouseover"))
''',

# ---- remembering ----
"hidden stats show what was remembered, in the mob's tooltip": r'''
  login(nil)
  units.mouseover = mob(4000, { name = "Wizard", level = 20, def = 100, speed = 2.5, hp = 900 })
  hover("mouseover")
  units.mouseover.hidden = true
  local t = hover("mouseover")
  ok(t == "Defense: 100 | Health: 900 (seen " .. today() .. ") | Attack speed: 2.5 (seen " .. today() .. ")", t)
''',
"a defense that isn't level x 5 is remembered too": r'''
  login(nil)
  units.mouseover = mob(4000, { name = "Wizard", level = 20, def = 130, speed = 2 })
  hover("mouseover")
  units.mouseover.hidden = true
  ok(hover("mouseover"):find("Defense: 130 %(seen " .. today() .. "%)"), hover("mouseover"))
''',
"remembered values can be switched off; defense is still worked out": r'''
  login(nil)
  units.mouseover = BOAR()
  hover("mouseover")
  units.mouseover.hidden = true
  GanderDB.remembered = false
  ok(hover("mouseover") == "Defense: 45", hover("mouseover"))
''',
"the same mob at another level reuses only what doesn't change with level": r'''
  login(nil)
  units.mouseover = mob(4000, { name = "Wizard", level = 20, def = 100, speed = 2.5, hp = 900, class = "MAGE" })
  hover("mouseover")
  units.mouseover = mob(4000, { name = "Wizard", level = 21, hidden = true })
  local t = hover("mouseover")
  ok(t == "Defense: 105 | Attack speed: 2.5 (seen " .. today() .. ") | Class: Mage (seen " .. today() .. ")", t)
''',
"memory is kept while tooltips are off, and across logins": r'''
  login(nil)
  GanderDB.tooltips = false
  units.mouseover = BOAR()
  hover("mouseover")
  local saved = GanderDB
  login(saved)
  GanderDB.tooltips = true
  units.mouseover.hidden = true
  ok(hover("mouseover"):find("Attack speed: 2.0 %(seen"), hover("mouseover"))
''',
"targeting a mob remembers it as well": r'''
  login(nil)
  units.target = BOAR()
  fire("PLAYER_TARGET_CHANGED")
  ok(GanderDB.mobs[3100] and GanderDB.mobs[3100].lv[9].v.spd == 2, "not remembered")
''',
"a mob the game won't identify shows live stats but isn't remembered": r'''
  login(nil)
  units.mouseover = BOAR()
  units.mouseover.noid = true
  ok(hover("mouseover") == "Defense: 45 | Attack speed: 2.0", hover("mouseover"))
  ok(next(GanderDB.mobs) == nil, "remembered an unknown mob")
''',
"a hidden, unidentified mob still gets its worked-out defense, without errors": r'''
  login(nil)
  units.mouseover = BOAR()
  units.mouseover.noid, units.mouseover.hidden = true, true
  ok(hover("mouseover") == "Defense: 45", hover("mouseover"))
''',
"a mob that's fighting shows live stats but isn't remembered, since debuffs change them": r'''
  login(nil)
  units.mouseover = BOAR()
  units.mouseover.combat = true
  units.mouseover.speed = 2.4  -- slowed
  ok(hover("mouseover") == "Defense: 45 | Attack speed: 2.4", hover("mouseover"))
  ok(next(GanderDB.mobs) == nil, "remembered a fighting mob")
''',
"a pet shows live stats but isn't remembered": r'''
  login(nil)
  units.mouseover = mob(1, { name = "Cat", level = 9, def = 45, speed = 2, guid = "Pet-0-4444-1-55-1-0000ABCDEF" })
  ok(hover("mouseover") == "Defense: 45 | Attack speed: 2.0", hover("mouseover"))
  ok(next(GanderDB.mobs) == nil, "remembered a pet")
''',

# ---- sharing ----
"a newly learned mob is sent to guild and group, once": r'''
  login(nil)
  grouped = true
  units.mouseover = mob(4000, { name = "Wizard", level = 20, def = 100, speed = 2.5, hp = 900, class = "MAGE" })
  hover("mouseover")
  ok(#sent == 0, "sent at once")
  advance(10)
  ok(list(sent) == "GUILD: 2:M:4000:20:hp=900,spd=2.5,class=MAGE | PARTY: 2:M:4000:20:hp=900,spd=2.5,class=MAGE", list(sent))
  hover("mouseover"); advance(10)
  ok(#sent == 2, "sent again unchanged: " .. list(sent))
  units.mouseover.speed = 2
  hover("mouseover"); advance(10)
  ok(#sent == 4 and sent[3]:find("spd=2,"), "changed value: " .. list(sent))
''',
"in a raid the group message goes to the raid": r'''
  login(nil)
  guild, grouped, raid = false, true, true
  units.mouseover = BOAR()
  hover("mouseover"); advance(10)
  ok(list(sent) == "RAID: 2:M:3100:9:spd=2", list(sent))
''',
"nothing is sent with sharing off, or with nobody to tell": r'''
  login(nil)
  GanderDB.share = false
  units.mouseover = BOAR()
  hover("mouseover"); advance(10)
  ok(#sent == 0, list(sent))
  GanderDB.share, guild = true, false
  units.mouseover = mob(5, { name = "Cat", level = 9, def = 45, speed = 1.5 })
  hover("mouseover"); advance(10)
  ok(#sent == 0, list(sent))
''',
"sending waits while chat is locked or a boss fight is on": r'''
  loginNoChannel()
  units.mouseover = BOAR()
  encounter = true
  hover("mouseover"); advance(30)
  ok(#sent == 0, "sent in an encounter")
  encounter, lockdown = false, true
  advance(30)
  ok(#sent == 0, "sent in lockdown")
  lockdown = false
  advance(30)
  -- Held back for over a minute, so it says how long ago the mob was seen.
  ok(#sent == 1 and sent[1]:find("^GUILD: 2:M:3100:9:spd=2,t=6%d$"), list(sent))
''',
"on Classic Era sending waits for a boss fight to end too": r'''
  classicEra()
  loginNoChannel()
  units.mouseover = mob(3100, { name = "Boar", level = 9, speed = 2 })
  encounter = true
  hover("mouseover"); advance(30)
  ok(#sent == 0, "sent in an encounter")
  encounter = false
  advance(30)
  ok(list(sent) == "GUILD: 2:M:3100:9:spd=2", list(sent))
''',
"many new mobs are sent a few at a time": r'''
  loginNoChannel()
  for i = 1, 6 do
    units.mouseover = mob(100 + i, { name = "Mob" .. i, level = 9, def = 45, speed = 2 })
    hover("mouseover")
  end
  advance(4)
  ok(#sent >= 1 and #sent <= 2, "burst: " .. #sent)
  advance(60)
  ok(#sent == 6, "all sent in the end: " .. #sent)
''',
"what another player learned is shown as theirs": r'''
  loginNoChannel()
  hear("2:M:4000:20:hp=900,spd=2.5,class=MAGE,armor=1200,r2=50", "Bob-Whitemane")
  units.mouseover = mob(4000, { name = "Wizard", level = 20, def = 100 })
  local t = hover("mouseover")
  ok(t == "Defense: 100 | Armor: 1,200 (from Bob) | Resistances: Fire 50 (from Bob) | Health: 900 (from Bob) | "
       .. "Attack speed: 2.5 (from Bob) | Class: Mage (from Bob)", t)
  advance(30)
  ok(#sent == 0, "passed on someone else's data: " .. list(sent))
  -- Seeing it yourself shows your values as live, and keeps Bob's for the rest.
  units.mouseover.speed = 2
  hover("mouseover")
  units.mouseover.hidden = true
  t = hover("mouseover")
  ok(t:find("Attack speed: 2.0 %(seen") and t:find("Armor: 1,200 %(from Bob%)"), t)
  advance(30)
  ok(list(sent) == "GUILD: 2:M:4000:20:spd=2", "sent only what you saw: " .. list(sent))
''',
"the most recently seen value wins, whoever saw it": r'''
  login(nil)
  units.mouseover = BOAR()
  hover("mouseover")                       -- you see it: speed 2
  advance(60)
  hear("2:M:3100:9:spd=3", "Bob-Whitemane")  -- Bob sees it later: speed 3
  units.mouseover.hidden = true
  ok(hover("mouseover"):find("Attack speed: 3.0 %(from Bob%)"), "Bob's is newer: " .. hover("mouseover"))
  advance(60)
  hear("2:M:3100:9:spd=5,t=86400", "Ann-Whitemane")  -- Ann saw it a day ago
  ok(hover("mouseover"):find("Attack speed: 3.0 %(from Bob%)"), "an older sighting replaced a newer one: " .. hover("mouseover"))
  hear("2:M:3100:9:spd=2.5,t=20", "Ann-Whitemane")   -- and again 20 seconds ago
  ok(hover("mouseover"):find("Attack speed: 2.5 %(from Ann%)"), "newest among others: " .. hover("mouseover"))
  units.mouseover.hidden = false
  ok(hover("mouseover") == "Defense: 45 | Attack speed: 2.0", "live beats everything: " .. hover("mouseover"))
  units.mouseover.hidden = true
  ok(hover("mouseover"):find("Attack speed: 2.0 %(seen"), "you saw it last: " .. hover("mouseover"))
''',
"your own messages coming back aren't taken as someone else's, however the game names you": r'''
  loginNoChannel()
  grouped = true
  cmd("debug")
  -- Forever characters can have a surname, and the sender name needn't match UnitName.
  for i, name in ipairs({ "Zaphiruz Antikleia", "Zaphiruz Antikleia-Whitemane", "Zaphiruz-White Mane" }) do
    echo = name
    out = {}
    units.mouseover = mob(200 + i, { name = "Mob" .. i, level = 9, def = 45, speed = 2 })
    hover("mouseover"); advance(10)
    ok(#sent == i * 2, "sent to guild and party: " .. list(sent))
    ok(next(GanderDB.mobs[200 + i].heard) == nil, "stored your own message as heard from " .. name)
    ok(not table.concat(out, " / "):find("heard"), "said it heard you: " .. table.concat(out, " / "))
  end
  -- The same values from someone else, later, are still theirs.
  advance(60)
  hear("2:M:201:9:spd=2", "Bob-Whitemane")
  ok(GanderDB.mobs[201].heard[9].by == "Bob", "ignored Bob")
''',
"the Gander channel is joined a while after login, not at once": r'''
  login(nil)
  ok(#channels == 0, "joined at login")
  advance(20)
  ok(#channels == 0, "joined before the game's own channels")
  advance(20)
  ok(list(channels) == "Gander", list(channels))
''',
"the channel isn't joined with sharing or the channel switched off": r'''
  login({ share = false })
  advance(60)
  ok(#channels == 0, "joined with sharing off")
  login({ channel = false })
  advance(60)
  ok(#channels == 0, "joined with the channel off")
''',
"a newly learned mob goes to the channel as well as guild and group": r'''
  login(nil)
  advance(40)
  units.mouseover = BOAR()
  hover("mouseover"); advance(10)
  ok(list(sent) == "GUILD: 2:M:3100:9:spd=2 | CHANNEL Gander: 2:M:3100:9:spd=2", list(sent))
  ok(next(GanderDB.mobs[3100].heard) == nil, "took its own channel message as someone else's")
  guild = false
  units.mouseover = mob(5, { name = "Cat", level = 9, def = 45, speed = 1.5 })
  hover("mouseover"); advance(10)
  ok(sent[3] == "CHANNEL Gander: 2:M:5:9:spd=1.5" and #sent == 3, "with no guild or group: " .. list(sent))
''',
"/gander debug says where each share went": r'''
  login(nil)
  grouped = true
  cmd("debug")
  out = {}
  units.mouseover = BOAR()
  hover("mouseover"); advance(10)
  ok(table.concat(out, " / "):find("shared 2:M:3100:9:spd=2,n=Elder Mottled Boar,z=Durotar with guild, party"), "before the channel is joined: " .. table.concat(out, " / "))
  ok(table.concat(out, " / "):find("not in the Gander channel yet"), "says why not the channel: " .. table.concat(out, " / "))
  advance(40)
  out = {}
  units.mouseover = mob(5, { name = "Cat", level = 9, def = 45, speed = 1.5 })
  hover("mouseover"); advance(10)
  ok(table.concat(out, " / "):find("shared 2:M:5:9:spd=1.5,n=Cat,z=Durotar with guild, party, the Gander channel"), table.concat(out, " / "))
  guild, grouped = false, false
  hear("2:M:6:9:spd=3,n=Owl,z=Durotar", "Eve-Whitemane", "CHANNEL")
  out = {}
  units.mouseover = mob(6, { name = "Owl", level = 9, def = 45, speed = 3 })
  hover("mouseover"); advance(10)
  ok(table.concat(out, " / "):find("shared with nobody") and table.concat(out, " / "):find("already had it"), table.concat(out, " / "))
  channelResult = Enum.SendAddonMessageResult.ChannelThrottle
  out = {}
  units.mouseover = mob(7, { name = "Bat", level = 9, def = 45, speed = 1 })
  hover("mouseover"); advance(4)
  ok(table.concat(out, " / "):find("channel is throttled"), table.concat(out, " / "))
''',
"a newer telling replaces an older one, whichever way it came": r'''
  login(nil)
  hear("2:M:3100:9:spd=3", "Bob-Whitemane", "GUILD")
  advance(5)
  hear("2:M:3100:9:spd=9", "Eve-Whitemane", "CHANNEL")
  ok(GanderDB.mobs[3100].heard[9].by == "Eve", "the newer channel telling wasn't taken")
  hear("2:M:3100:9:spd=3,t=3600", "Bob-Whitemane", "GUILD")
  ok(GanderDB.mobs[3100].heard[9].by == "Eve", "an hour-old telling replaced a fresh one")
  hear("2:M:3100:9:spd=4,t=999999999999", "Bob-Whitemane", "GUILD")
  ok(GanderDB.mobs[3100].heard[9].by == "Eve", "a nonsense age was accepted")
''',
"a mob the channel already told you, with the same values, isn't sent to the channel again": r'''
  login(nil)
  advance(40)
  hear("2:M:3100:9:spd=2,n=Elder Mottled Boar,z=Durotar", "Eve-Whitemane", "CHANNEL")
  units.mouseover = BOAR()
  hover("mouseover"); advance(10)
  ok(list(sent) == "GUILD: 2:M:3100:9:spd=2", list(sent))
  hear("2:M:5:9:spd=3", "Eve-Whitemane", "CHANNEL")
  units.mouseover = mob(5, { name = "Cat", level = 9, def = 45, speed = 1.5 })
  hover("mouseover"); advance(10)
  ok(sent[#sent] == "CHANNEL Gander: 2:M:5:9:spd=1.5", "different values are sent: " .. list(sent))
''',
"if the game refuses channel messages, Gander stops trying": r'''
  login(nil)
  advance(40)
  cmd("debug")
  channelResult = Enum.SendAddonMessageResult.InvalidChatType
  out = {}
  for i = 1, 3 do
    units.mouseover = mob(100 + i, { name = "Mob" .. i, level = 9, def = 45, speed = 2 })
    hover("mouseover"); advance(10)
  end
  ok(#refusals == 1, "kept trying: " .. #refusals)
  ok(#sent == 3, "guild still gets them: " .. list(sent))
  ok(table.concat(out, " / "):find("refuses"), "debug says so: " .. table.concat(out, " / "))
''',
"a throttled channel message is tried again later, without repeating it to the guild": r'''
  login(nil)
  advance(40)
  channelResult = Enum.SendAddonMessageResult.ChannelThrottle
  units.mouseover = BOAR()
  hover("mouseover"); advance(4)
  ok(list(sent) == "GUILD: 2:M:3100:9:spd=2" and #refusals == 1, list(sent))
  channelResult = 0
  advance(30)
  ok(list(sent) == "GUILD: 2:M:3100:9:spd=2 | CHANNEL Gander: 2:M:3100:9:spd=2", list(sent))
  channelResult = Enum.SendAddonMessageResult.ChannelThrottle
  refusals = {}
  units.mouseover = mob(5, { name = "Cat", level = 9, def = 45, speed = 1.5 })
  hover("mouseover"); advance(120)
  ok(#refusals >= 2 and #refusals <= 5, "retries, then gives up: " .. #refusals)
''',
"the channel switch joins and leaves the channel": r'''
  login(nil)
  advance(40)
  panel():Show()
  check("channel"):Click()
  ok(GanderDB.channel == false and #channels == 0, "left the channel")
  check("channel"):Click()
  ok(GanderDB.channel == true and list(channels) == "Gander", "joined again")
  check("share"):Click()
  ok(#channels == 0, "sharing off leaves the channel")
  check("share"):Click()
  ok(list(channels) == "Gander", "sharing on joins it again")
''',
"a share says how long ago the mob was seen, once that's more than a minute": r'''
  loginNoChannel()
  units.mouseover = BOAR()
  hover("mouseover"); advance(10)
  ok(list(sent) == "GUILD: 2:M:3100:9:spd=2", "a fresh sighting has no age: " .. list(sent))
  hear("2:M:5:9:spd=2,t=86400", "Bob-Whitemane")
  ok(GanderDB.mobs[5].heard[9].at == clock - 86400, "stored when it was seen: " .. tostring(GanderDB.mobs[5].heard[9].at - clock))
''',
"a hidden mob you know nothing about is asked for, once": r'''
  login(nil)
  advance(40)
  cmd("debug")
  out = {}
  units.mouseover = mob(4000, { name = "Wizard", level = 20, hidden = true })
  hover("mouseover"); advance(10)
  ok(list(sent) == "GUILD: 2:Q:4000:20 | CHANNEL Gander: 2:Q:4000:20", list(sent))
  ok(table.concat(out, " / "):find("asked"), "debug says it asked: " .. table.concat(out, " / "))
  hover("mouseover"); advance(60)
  ok(#sent == 2, "asked again too soon: " .. list(sent))
  advance(600)
  hover("mouseover"); advance(10)
  ok(#sent == 4, "asks again after ten minutes: " .. list(sent))
''',
"the answer to a question shows on the tooltip": r'''
  login(nil)
  advance(40)
  units.mouseover = mob(4000, { name = "Wizard", level = 20, hidden = true })
  hover("mouseover"); advance(5)
  hear("2:M:4000:20:hp=900,spd=2.5,t=7200", "Bob-Whitemane", "CHANNEL")
  local t = hover("mouseover")
  ok(t == "Defense: 100 | Health: 900 (from Bob) | Attack speed: 2.5 (from Bob)", t)
''',
"nothing is asked when the mob is visible, remembered, unidentified, or sharing is off": r'''
  login(nil)
  advance(40)
  units.mouseover = BOAR()                                   -- visible
  hover("mouseover"); advance(10)
  sent = {}
  units.mouseover.hidden = true                              -- remembered
  hover("mouseover"); advance(10)
  hear("2:M:5:9:spd=2", "Bob-Whitemane")
  units.mouseover = mob(5, { name = "Cat", level = 9, hidden = true })   -- heard of
  hover("mouseover"); advance(10)
  units.mouseover = mob(6, { name = "Owl", level = 9, hidden = true, noid = true })  -- unidentified
  hover("mouseover"); advance(10)
  ok(#sent == 0, "asked: " .. list(sent))
  GanderDB.share = false
  units.mouseover = mob(7, { name = "Bat", level = 9, hidden = true })
  hover("mouseover"); advance(10)
  ok(#sent == 0, "asked with sharing off: " .. list(sent))
''',
"someone else's question for the same mob saves you asking": r'''
  login(nil)
  advance(40)
  hear("2:Q:4000:20", "Bob-Whitemane", "CHANNEL")
  units.mouseover = mob(4000, { name = "Wizard", level = 20, hidden = true })
  hover("mouseover"); advance(10)
  ok(#sent == 0, "asked anyway: " .. list(sent))
''',
"a question is answered by someone who saw the mob, the way it came, with its age": r'''
  login(nil)
  advance(40)
  cmd("debug")
  known(3100, 9, { spd = 2, class = "WARRIOR" }, 7200)
  out = {}
  hear("2:Q:3100:9", "Bob-Whitemane", "CHANNEL")
  ok(#sent == 0, "answered at once, before anyone else could")
  advance(10)
  ok(list(sent) == "CHANNEL Gander: 2:M:3100:9:spd=2,class=WARRIOR,t=7202", list(sent))
  ok(table.concat(out, " / "):find("answer"), "debug says it answered: " .. table.concat(out, " / "))
  hear("2:Q:3100:9", "Ann-Whitemane", "GUILD")
  advance(10)
  ok(sent[2] and sent[2]:find("^GUILD: 2:M:3100:9:spd=2,class=WARRIOR,t=72%d%d$"), "a guild question is answered in guild: " .. list(sent))
  grouped = true
  hear("2:Q:3100:9", "Ann-Whitemane", "PARTY")
  advance(10)
  ok(sent[3] and sent[3]:find("^PARTY: "), "a party question is answered in party: " .. list(sent))
''',
"no answer when you only heard about the mob, don't know it, or sharing is off": r'''
  login(nil)
  advance(40)
  hear("2:M:5:9:spd=2", "Eve-Whitemane")
  hear("2:Q:5:9", "Bob-Whitemane", "CHANNEL")      -- only heard of it
  hear("2:Q:6:9", "Bob-Whitemane", "CHANNEL")      -- never heard of it
  known(7, 9, { spd = 2 })
  hear("2:Q:7:10", "Bob-Whitemane", "CHANNEL")     -- another level
  advance(10)
  ok(#sent == 0, list(sent))
  GanderDB.share = false
  hear("2:Q:7:9", "Bob-Whitemane", "CHANNEL")
  advance(10)
  ok(#sent == 0, "answered with sharing off: " .. list(sent))
''',
"if someone else answers first, you stay quiet": r'''
  login(nil)
  advance(40)
  known(3100, 9, { spd = 2 })
  hear("2:Q:3100:9", "Bob-Whitemane", "CHANNEL")
  advance(1)
  hear("2:M:3100:9:spd=2", "Ann-Whitemane", "CHANNEL")
  advance(10)
  ok(#sent == 0, "answered after Ann did: " .. list(sent))
  hear("2:Q:3100:9", "Bob-Whitemane", "CHANNEL")   -- asked again later: nobody answers this time
  advance(10)
  ok(#sent == 1, "a later question is answered: " .. list(sent))
''',
"the same question asked many times gets one answer, and a flood of questions is capped": r'''
  login(nil)
  advance(40)
  known(3100, 9, { spd = 2 })
  for i = 1, 5 do hear("2:Q:3100:9", "Bob-Whitemane", "CHANNEL") end
  advance(10)
  ok(#sent == 1, "answered a repeat: " .. #sent)
  sent = {}
  for i = 1, 40 do known(100 + i, 9, { spd = 2 }) end
  for i = 1, 40 do hear("2:Q:" .. (100 + i) .. ":9", "Eve-Whitemane", "CHANNEL") end
  advance(30)
  ok(#sent >= 5 and #sent <= 12, "a flood from one player: " .. #sent)
''',
"no answer is sent while chat is locked or a boss fight is on": r'''
  login(nil)
  advance(40)
  known(3100, 9, { spd = 2 })
  encounter = true
  hear("2:Q:3100:9", "Bob-Whitemane", "CHANNEL")
  advance(10)
  ok(#sent == 0, list(sent))
''',
"everything Gander sends is signed": r'''
  login(nil)
  grouped = true
  advance(40)
  units.mouseover = BOAR()
  hover("mouseover"); advance(10)                  -- a share
  units.mouseover = mob(4000, { name = "Wizard", level = 20, hidden = true })
  hover("mouseover"); advance(10)                  -- a question
  known(7, 9, { spd = 2 }, 7200)
  hear("2:Q:7:9", "Bob-Whitemane", "CHANNEL"); advance(10)   -- an answer
  ok(#sent == 7, "share and question to three places, one answer: " .. list(sent))
  ok(unsignedSent == 0, unsignedSent .. " messages went out unsigned")
''',
"a message typed by hand, without Gander's signature, is ignored": r'''
  login(nil)
  cmd("debug")
  out = {}
  hearRaw("2:M:3100:9:spd=40")                      -- no signature
  hearRaw("2:M:3100:9:spd=40#00000000")             -- a made-up one
  hearRaw("1:M:3100:9:spd=40")                      -- the old unsigned kind
  local tampered = sign("2:M:3100:9:spd=2"):gsub("spd=2", "spd=40")
  ok(tampered:find("^2:M:3100:9:spd=40#%x+$"), tampered)
  hearRaw(tampered)                                 -- a real message with its values changed
  hearRaw("2:Q:3100:9")
  ok(next(GanderDB.mobs) == nil, "a forged message was stored")
  local _, refused = table.concat(out, " / "):gsub("isn't signed", "")
  ok(refused == 5, "each one is refused for its signature, " .. refused .. " were: " .. table.concat(out, " / "))
  hear("2:M:3100:9:spd=2")
  ok(GanderDB.mobs[3100].heard[9].v.spd == 2, "a signed message wasn't taken")
''',
"with signed only switched off, unsigned messages are taken too": r'''
  login({ signedOnly = false })
  ok(GanderDB.signedOnly == false, "the saved switch wasn't kept")
  advance(40)
  cmd("debug")
  out = {}
  hearRaw("1:M:3100:9:spd=3", "Old-Whitemane")             -- a version before 0.4.0
  ok(GanderDB.mobs[3100] and GanderDB.mobs[3100].heard[9].by == "Old", "the old unsigned kind wasn't taken")
  hearRaw("2:M:5:9:spd=2.5", "Bob-Whitemane")              -- typed by hand
  ok(GanderDB.mobs[5] and GanderDB.mobs[5].heard[9].v.spd == 2.5, "a hand-typed message wasn't taken")
  hearRaw("2:M:6:9:spd=4#00000000", "Bob-Whitemane")       -- a wrong signature
  ok(GanderDB.mobs[6] and GanderDB.mobs[6].heard[9].v.spd == 4, "a wrongly signed message wasn't taken")
  hear("2:M:7:9:spd=2", "Ann-Whitemane")                   -- signed ones still work
  ok(GanderDB.mobs[7] and GanderDB.mobs[7].heard[9].by == "Ann", "a signed message wasn't taken")
  ok(table.concat(out, " / "):find("unsigned"), "debug says it was unsigned: " .. table.concat(out, " / "))
  hearRaw("1:M:abc:9:spd=2"); hearRaw("nonsense"); hearRaw("#"); hearRaw("1:M:8:9:spd=-1#zz")
  ok(GanderDB.mobs[8] == nil, "junk was stored")
  known(3100, 9, { spd = 2 })
  hearRaw("1:Q:3100:9", "Old-Whitemane", "CHANNEL")        -- an unsigned question is answered
  advance(10)
  ok(#sent == 1 and unsignedSent == 0, "answered, and still signs what it sends: " .. list(sent))
''',
"the signed only switch in the panel takes effect at once": r'''
  login(nil)
  panel():Show()
  hearRaw("1:M:3100:9:spd=3")
  ok(GanderDB.mobs[3100] == nil, "unsigned taken while signed only is on")
  check("signedOnly"):Click()
  ok(GanderDB.signedOnly == false, "switch off")
  hearRaw("1:M:3100:9:spd=3")
  ok(GanderDB.mobs[3100] ~= nil, "unsigned not taken after switching it off")
  check("signedOnly"):Click()
  hearRaw("1:M:5:9:spd=3")
  ok(GanderDB.signedOnly == true and GanderDB.mobs[5] == nil, "switch back on")
''',
"an unsigned question gets no answer": r'''
  login(nil)
  advance(40)
  known(3100, 9, { spd = 2 })
  hearRaw("2:Q:3100:9", "Bob-Whitemane", "CHANNEL")
  advance(10)
  ok(#sent == 0, list(sent))
''',
"a long message still fits with its signature": r'''
  login(nil)
  units.mouseover = mob(4000, { name = "Defias Wizard", level = 20, def = 130, armor = 123456,
    res = { 111111, 222222, 333333, 444444, 555555, 666666 }, hp = 1234567, power = 2345678, powerType = "MANA",
    speed = 2.25, offhand = 1.75, damage = { 123456, 234567 }, ap = 345678, ranged = { 2.85, 123456, 234567 },
    stats = { 11111, 22222, 33333, 44444, 55555 }, run = 8.25, class = "MAGE", family = "A Very Long Family Name" })
  hover("mouseover"); advance(10)
  ok(#sent == 1 and unsignedSent == 0, "sent " .. #sent .. ", unsigned " .. unsignedSent)
''',
"junk and unknown messages are ignored": r'''
  login(nil)
  hear("2:M:abc:9:spd=2")
  hear("2:M:3100:900:spd=2")
  hear("2:M:3101:9:spd=-4,hp=99999999999,class=mage,fam=<b>|cff,bogus=7")
  hear("3:M:3102:9:spd=2")
  hear("1:Z:3103:9:spd=2")
  hear("2:M:3104:9:spd=2", "Zaphiruz-Whitemane")
  hear("2:Q:abc:9"); hear("2:Q:3100:900"); hear("2:Q:3100"); hear("2:Q:3100:9:extra")
  fire("CHAT_MSG_ADDON", "OtherAddon", "2:M:3105:9:spd=2", "GUILD", "Bob-Whitemane")
  fire("CHAT_MSG_ADDON", "Gander", SECRET, "GUILD", "Bob-Whitemane")
  for id in pairs(GanderDB.mobs) do ok(false, "stored mob " .. tostring(id)) end
  hear("2:M:3106:9:spd=2,newthing=5")
  ok(GanderDB.mobs[3106].heard[9].v.spd == 2 and GanderDB.mobs[3106].heard[9].v.newthing == nil, "kept the known part")
''',
"heard values aren't stored with sharing off": r'''
  login(nil)
  GanderDB.share = false
  hear("2:M:3100:9:spd=3")
  ok(next(GanderDB.mobs) == nil, "stored with sharing off")
''',

# ---- settings panel ----
"the panel is in Options under AddOns, with a switch for every line": r'''
  login(nil)
  ok(#categories == 1 and categories[1].name == "Gander", "registered")
  panel():Show()
  for _, k in ipairs({ "tooltips", "remembered", "share", "channel", "signedOnly", "minimap", "defense", "armor", "resist", "health", "power",
                       "speed", "damage", "ap", "ranged", "stats", "run", "class", "family" }) do
    ok(check(k) and check(k):GetChecked() == true, "switch " .. k)
  end
  check("speed"):Click()
  ok(GanderDB.lines.speed == false, "line switch")
  check("share"):Click(); check("remembered"):Click(); check("tooltips"):Click()
  ok(GanderDB.share == false and GanderDB.remembered == false and GanderDB.tooltips == false, "main switches")
  units.mouseover = BOAR()
  hover("mouseover")
  panel():Show()
  ok(check("speed"):GetChecked() == false, "shows the saved state")
  ok(panel().count:GetText():find("1 mob"), panel().count:GetText())
''',

# ---- commands ----
# ---- the minimap button ----
"the minimap button opens the bestiary, and right-click opens the settings": r'''
  login(nil)
  local b = GanderMinimapButton
  ok(b and b:IsShown() and b.parent == Minimap, "no button on the minimap")
  b:Click()
  ok(GanderBestiary and GanderBestiary:IsShown(), "a click didn't open the bestiary")
  b:Click()
  ok(not GanderBestiary:IsShown(), "a second click didn't close it")
  b:Click("RightButton")
  ok(opened == 77 and not GanderBestiary:IsShown(), "a right-click didn't open the settings")
''',
"the minimap button can be switched off in the settings, and that's remembered": r'''
  login(nil)
  panel():Show()
  check("minimap"):Click()
  ok(GanderDB.minimap.hide == true and not GanderMinimapButton:IsShown(), "still shown")
  local saved = GanderDB
  login(saved)
  ok(not GanderMinimapButton:IsShown(), "shown after logging back in")
  panel():Show()
  ok(check("minimap"):GetChecked() == false, "the switch shows it as off")
  check("minimap"):Click()
  ok(GanderDB.minimap.hide == false and GanderMinimapButton:IsShown(), "didn't come back")
''',
"dragging moves the button around the minimap's edge, and the place is kept": r'''
  login(nil)
  local b = GanderMinimapButton
  local x, y = b.point[4], b.point[5]
  ok(b.point[2] == Minimap and x < -40 and y < -40, "starts bottom left: " .. tostring(x) .. ", " .. tostring(y))
  b:GetScript("OnDragStart")(b)
  cursorX, cursorY = 100, 300            -- straight above the minimap's centre
  b:GetScript("OnUpdate")(b, 0.1)
  b:GetScript("OnDragStop")(b)
  ok(math.abs(GanderDB.minimap.angle - 90) < 0.01, "angle " .. tostring(GanderDB.minimap.angle))
  x, y = b.point[4], b.point[5]
  ok(math.abs(x) < 0.01 and y > 60, "now at the top: " .. tostring(x) .. ", " .. tostring(y))
  ok(b:GetScript("OnUpdate") == nil, "still following the cursor after the drag")
  local saved = GanderDB
  login(saved)
  x, y = GanderMinimapButton.point[4], GanderMinimapButton.point[5]
  ok(math.abs(x) < 0.01 and y > 60, "kept after logging back in: " .. tostring(x) .. ", " .. tostring(y))
''',
"a click at the end of a drag doesn't open the bestiary": r'''
  login(nil)
  local b = GanderMinimapButton
  b:GetScript("OnDragStart")(b)
  ok(b:GetScript("OnClick") ~= nil, "no click handler")
  b:GetScript("OnDragStop")(b)
  ok(GanderBestiary == nil or not GanderBestiary:IsShown(), "dragging opened the bestiary")
''',
"a game with no minimap frame still loads": r'''
  getmetatable(_G).__index.Minimap = nil   -- where the guard keeps the game's globals
  ok(Minimap == nil, "the mock minimap is still there")
  login(nil)
  ok(GanderMinimapButton == nil, "made a button with nowhere to put it")
  panel():Show()
  check("minimap"):Click()
  ok(cmd("help"):find("/gander settings"), "commands still work")
''',
"/gander settings opens the settings": r'''
  login(nil)
  cmd("settings")
  ok(opened == 77, "opened " .. tostring(opened))
  ok(cmd("help"):find("/gander settings"), cmd("help"))
''',
"a mob's name, type, rank and zone are remembered": r'''
  login(nil)
  sampleMobs()
  local tiger, gorilla = GanderDB.mobs[681].lv[30].v, GanderDB.mobs[1108].lv[33].v
  ok(tiger.n == "Young Stranglethorn Tiger" and tiger.ty == "Beast" and tiger.z == "Stranglethorn Vale", "tiger")
  ok(tiger.rk == nil, "a normal mob has no rank: " .. tostring(tiger.rk))
  ok(gorilla.n == "Mistvale Gorilla" and gorilla.rk == "ELITE", "gorilla: " .. tostring(gorilla.rk))
  local t = hover("mouseover")
  ok(t == "Defense: 165 | Attack speed: 2.0", "the tooltip gets no extra lines: " .. t)
''',
"the first zone a mob was seen in is kept, and wandering doesn't re-send it": r'''
  loginNoChannel()
  units.mouseover = BOAR()
  hover("mouseover"); advance(10)
  zoneName = "The Barrens"
  hover("mouseover"); advance(10)
  ok(GanderDB.mobs[3100].lv[9].v.z == "Durotar", GanderDB.mobs[3100].lv[9].v.z)
  ok(#sent == 1, "sent again for a new zone: " .. #sent)
''',
"names, types, ranks and zones are shared and heard": r'''
  loginNoChannel()
  fullMessages = true
  zoneName = "Stranglethorn Vale"
  units.mouseover = mob(1108, { name = "Mistvale Gorilla", level = 33, def = 165, speed = 2, type = "Beast", rank = "elite" })
  hover("mouseover"); advance(10)
  ok(list(sent) == "GUILD: 2:M:1108:33:spd=2,n=Mistvale Gorilla,ty=Beast,rk=ELITE,z=Stranglethorn Vale", list(sent))
  hear("2:M:4000:20:spd=2.5,n=Defias Wizard,ty=Humanoid,rk=RARE,z=Westfall", "Bob-Whitemane")
  local v = GanderDB.mobs[4000].heard[20].v
  ok(v.n == "Defias Wizard" and v.ty == "Humanoid" and v.rk == "RARE" and v.z == "Westfall", "heard")
  hear("2:M:4001:20:spd=2.5,n=" .. string.rep("x", 60) .. ",z=|cffff0000red", "Bob-Whitemane")
  v = GanderDB.mobs[4001].heard[20].v
  ok(v.n == nil and v.z == nil and v.spd == 2.5, "a silly name or zone is dropped, the rest kept")
''',
"a mob remembered before names were kept gets its name the next time it's seen": r'''
  loginNoChannel()
  known(3100, 9, { spd = 2 }, 86400)
  units.mouseover = BOAR()
  hover("mouseover"); advance(10)
  ok(GanderDB.mobs[3100].lv[9].v.n == "Elder Mottled Boar", "no name")
  ok(#sent == 1, "the name is passed on: " .. #sent)
''',

# ---- the bestiary window ----
"/gander opens the bestiary, a list of every remembered mob": r'''
  login(nil)
  sampleMobs()
  ok(GanderBestiary == nil or not GanderBestiary:IsShown(), "open before it was asked for")
  cmd("")
  local w = GanderBestiary
  ok(w and w:IsShown(), "not shown")
  ok(w.count:GetText() == "3 mobs", w.count:GetText())
  ok(rowText(w.rows[1]) == "Defias Wizard / 20 / Humanoid / Westfall", rowText(w.rows[1]))
  ok(rowText(w.rows[2]) == "Mistvale Gorilla (Elite) / 33 / Beast / Stranglethorn Vale", rowText(w.rows[2]))
  ok(rowText(w.rows[3]) == "Young Stranglethorn Tiger / 30 / Beast / Stranglethorn Vale", rowText(w.rows[3]))
  ok(w.rows[3]:IsShown() and not w.rows[4]:IsShown(), "rows shown")
  local escapes = false
  for _, n in ipairs(UISpecialFrames) do if n == "GanderBestiary" then escapes = true end end
  ok(escapes, "Escape doesn't close it")
  cmd("")
  ok(not w:IsShown(), "a second /gander didn't close it")
''',
"a mob seen at several levels shows the range; a skull level shows ??": r'''
  login(nil)
  units.mouseover = mob(681, { name = "Tiger", level = 30, def = 150, speed = 1.3 })
  hover("mouseover")
  units.mouseover = mob(681, { name = "Tiger", level = 32, def = 160, speed = 1.3 })
  hover("mouseover")
  hear("2:M:681:31:spd=1.3", "Bob-Whitemane")
  units.mouseover = mob(11502, { name = "Ragnaros", level = -1, speed = 2, rank = "worldboss" })
  hover("mouseover")
  cmd("")
  local w = GanderBestiary
  ok(rowText(w.rows[1]):find("^Ragnaros %(Boss%) / %?%? /"), rowText(w.rows[1]))
  ok(rowText(w.rows[2]):find("^Tiger / 30%-32 /"), rowText(w.rows[2]))
''',
"a mob with no name yet is listed by its number, after the named ones": r'''
  login(nil)
  known(1108, 33, { spd = 2 })
  known(681, 30, { spd = 1.3, n = "Young Stranglethorn Tiger" })
  cmd("")
  local w = GanderBestiary
  ok(w.rows[1].name:GetText() == "Young Stranglethorn Tiger", w.rows[1].name:GetText())
  ok(w.rows[2].name:GetText() == "Mob #1108", w.rows[2].name:GetText())
''',
"searching narrows the list by name, zone, type or number": r'''
  login(nil)
  sampleMobs()
  cmd("")
  local w = GanderBestiary
  w.search:Type("TIGER")
  ok(w.rows[1].name:GetText() == "Young Stranglethorn Tiger" and not w.rows[2]:IsShown(), "by name")
  ok(w.count:GetText() == "1 of 3 mobs", w.count:GetText())
  w.search:Type("westfall")
  ok(w.rows[1].name:GetText() == "Defias Wizard" and not w.rows[2]:IsShown(), "by zone")
  w.search:Type("beast")
  ok(w.rows[2]:IsShown() and not w.rows[3]:IsShown(), "by type")
  w.search:Type("1108")
  ok(w.rows[1].name:GetText() == "Mistvale Gorilla (Elite)" and not w.rows[2]:IsShown(), "by number")
  w.search:Type("(")
  ok(w.rows[1]:IsShown() and w.rows[1].name:GetText() == "Mistvale Gorilla (Elite)", "a bracket is plain text, not a pattern")
  w.search:Type("zzz")
  ok(not w.rows[1]:IsShown() and w.count:GetText() == "0 of 3 mobs", w.count:GetText())
  w.search:Type("")
  ok(w.rows[3]:IsShown() and w.count:GetText() == "3 mobs", "cleared")
''',
"the list can show everything, only what you saw, or only what you heard": r'''
  login(nil)
  sampleMobs()
  cmd("")
  local w = GanderBestiary
  ok(w.filters.all:IsEnabled() == false and w.filters.seen:IsEnabled() == true, "All is the one picked")
  w.filters.heard:Click()
  ok(w.rows[1].name:GetText() == "Defias Wizard" and not w.rows[2]:IsShown(), "heard")
  ok(w.filters.heard:IsEnabled() == false and w.filters.all:IsEnabled() == true, "Heard is the one picked")
  w.filters.seen:Click()
  ok(w.rows[1].name:GetText() == "Mistvale Gorilla (Elite)" and w.rows[2]:IsShown() and not w.rows[3]:IsShown(), "seen")
  w.filters.all:Click()
  ok(w.rows[3]:IsShown(), "all")
''',
"clicking a mob shows everything known about it": r'''
  login(nil)
  sampleMobs()
  hear("2:M:681:31:spd=1.4,t=86400", "Bob-Whitemane")
  cmd("")
  local w = GanderBestiary
  ok(plain(w.detail:GetText()):find("Click a mob"), "a hint before anything is picked: " .. w.detail:GetText())
  w.rows[3]:Click()
  local d = plain(w.detail:GetText())
  ok(d:find("Young Stranglethorn Tiger") and d:find("id 681"), d)
  ok(d:find("Beast, Cat") and d:find("Stranglethorn Vale"), d)
  ok(d:find("Level 30 %- seen " .. today()), d)
  ok(d:find("Defense 150") and d:find("Attack speed 1.3"), d)
  ok(d:find("Level 31 %- from Bob, "), d)
  ok(d:find("Defense 155") and d:find("Attack speed 1.4"), d)
  w.rows[2]:Click()
  d = plain(w.detail:GetText())
  ok(d:find("Mistvale Gorilla") and d:find("Elite") and not d:find("Tiger"), d)
''',
"more mobs than fit are scrolled with the mouse wheel": r'''
  login(nil)
  for i = 1, 25 do known(100 + i, 9, { spd = 2, n = string.format("Mob %02d", i) }) end
  cmd("")
  local w = GanderBestiary
  local last = #w.rows
  ok(last >= 8 and last < 25, "rows: " .. last)
  ok(w.rows[1].name:GetText() == "Mob 01" and w.rows[last].name:GetText() == string.format("Mob %02d", last), "top")
  ok(w.count:GetText() == "25 mobs", w.count:GetText())
  w.list:GetScript("OnMouseWheel")(w.list, -1)
  ok(w.rows[1].name:GetText() == "Mob 04", "one notch down: " .. w.rows[1].name:GetText())
  for i = 1, 20 do w.list:GetScript("OnMouseWheel")(w.list, -1) end
  ok(w.rows[last].name:GetText() == "Mob 25" and w.rows[last]:IsShown(), "stops at the end: " .. w.rows[last].name:GetText())
  for i = 1, 20 do w.list:GetScript("OnMouseWheel")(w.list, 1) end
  ok(w.rows[1].name:GetText() == "Mob 01", "stops at the top")
  w.list:GetScript("OnMouseWheel")(w.list, -1)
  w.search:Type("Mob 2")
  ok(w.rows[1].name:GetText() == "Mob 20", "a search starts from the top: " .. w.rows[1].name:GetText())
''',
"the open list updates when something is learned or heard": r'''
  login(nil)
  cmd("")
  local w = GanderBestiary
  ok(w.count:GetText() == "0 mobs" and not w.rows[1]:IsShown(), w.count:GetText())
  units.mouseover = BOAR()
  hover("mouseover")
  ok(w.count:GetText() == "1 mob" and w.rows[1].name:GetText() == "Elder Mottled Boar", w.count:GetText())
  hear("2:M:4000:20:spd=2.5,n=Defias Wizard", "Bob-Whitemane")
  ok(w.count:GetText() == "2 mobs" and w.rows[1].name:GetText() == "Defias Wizard", w.count:GetText())
''',
"the bestiary's Settings button opens the settings": r'''
  login(nil)
  cmd("")
  GanderBestiary.settings:Click()
  ok(opened == 77, "opened " .. tostring(opened))
''',
"/gander help, debug and unknown words": r'''
  login(nil)
  local o = cmd("help")
  ok(o:find("/gander debug") and o:find("/gander help"), o)
  o = cmd("banana")
  ok(o:find("banana") and o:find("/gander help"), o)
  units.target = mob(4000, { name = "Wizard", level = 20, def = 100, speed = 2.5 })
  o = cmd("debug")
  ok(o:find("debug on"), o)
  ok(o:find("Wizard") and o:find("4000") and o:find("def=100") and o:find("spd=2.5"), o)
  ok(o:find("not sent") and o:find("armor"), "says what the game doesn't send: " .. o)
  units.target.hidden = true
  cmd("debug"); o = cmd("debug")
  ok(o:find("hidden") , "says what the game hides: " .. o)
  out = {}
  hear("2:M:3100:9:spd=3")
  ok(table.concat(out, "\n"):find("Bob"), "debug prints what it hears: " .. table.concat(out, "\n"))
''',
"/gander says so if loading failed": r'''
  login(nil)
  events = {}
  assert(loadstring(ADDON_SRC, "Gander.lua"))("Gander")
  ok(cmd("help"):find("didn't finish loading"), cmd("help"))
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
