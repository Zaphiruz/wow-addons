"""Runs Huzzah.lua against a small fake WoW API. Usage: python run_tests.py path/to/Huzzah.lua"""
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
GameTooltip = {}
now = 100
function GetTime() return now end
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
    if t.at > now then now = t.at end
    t.fn()
  end
  now = stop
end

-- Units the game can name. Each: name, realm (nil = ours), level, and flags.
units = { player = { name = "Zaphiruz", level = 19, isPlayer = true } }
function GetRealmName() return "Whitemane" end
function GetNormalizedRealmName() return "Whitemane" end
function UnitName(u) local x = units[u]; if x then return x.name, x.realm end end
function UnitLevel(u) local x = units[u]; return x and x.level or 0 end
function UnitExists(u) return units[u] ~= nil end
function UnitIsPlayer(u) local x = units[u]; return x ~= nil and x.isPlayer == true end
function UnitIsUnit(a, b) return units[a] ~= nil and units[a] == units[b] end
function UnitInParty(u) local x = units[u]; return x ~= nil and x.group == true and not raid end
function UnitInRaid(u) local x = units[u]; if x and x.group and raid then return 1 end end
function UnitIsInMyGuild(u) local x = units[u]; return x ~= nil and x.guild == true end
raid = false
function IsInGroup() for u, x in pairs(units) do if x.group then return true end end return false end
function IsInRaid() return raid and IsInGroup() end
function Ambiguate(name, how)
  if how == "short" then return (name:gsub("%-.*$", "")) end
  return (name:gsub("%-Whitemane$", ""))
end
-- A player the game knows under `unit` (party1, target, nameplate3, ...).
function see(unit, p) units[unit] = { name = p.name, realm = p.realm, level = p.level, isPlayer = true,
                                      group = p.group, guild = p.guild } end
-- That unit's player levels up.
function ding(unit, level) units[unit].level = level; fire("UNIT_LEVEL", unit) end

-- Guild roster.
guild = true
roster = {}
rosterRequests = 0
function IsInGuild() return guild end
function GetNumGuildMembers() return #roster, #roster end
function GetGuildRosterInfo(i)
  local m = roster[i]
  if m then return m.name, "Member", 2, m.level, "Mage", "Elwynn Forest", "", "", m.online end
end
C_GuildInfo = { GuildRoster = function() rosterRequests = rosterRequests + 1 end }

-- Chat and emotes.
said, emotes, emoteLines = {}, {}, {}  -- messages, real emotes, custom emote lines
lockdown = false
emoteBlocked = false
-- Which game: 11509 is Classic Era, 16001 is Forever.
tocVersion = 11509
function GetBuildInfo() return "1.15.9", "60000", "Nov 1 2026", tocVersion end
-- Forever blocks emote lines sent without a key press: the call does nothing
-- and raises no error (BugSack shows ADDON_ACTION_BLOCKED).
blocked = {}
C_ChatInfo = {
  SendChatMessage = function(msg, chatType, lang, target)
    assert(#msg <= 255, "message too long")
    if chatType == "EMOTE" then
      if tocVersion >= 16000 then table.insert(blocked, msg); return end
      if emoteBlocked then error("blocked") end
      table.insert(emoteLines, msg)
      return
    end
    table.insert(said, chatType .. (target and (":" .. target) or "") .. ": " .. msg)
  end,
  PerformEmote = function(token, target) table.insert(emotes, token .. (target and (" " .. target) or "")); return false end,
  InChatMessagingLockdown = function() return lockdown end,
}

-- Forever hides some values from addons ("secret values").
SECRET = setmetatable({}, { __index = function() error("read a secret value") end })
function issecretvalue(v) return rawequal(v, SECRET) end

-- Frames: what the settings panel uses.
local noop = function() end
local widgetMT = { __index = function() return noop end }
function widget(kind, name, parent, template)
  local w = setmetatable({ kind = kind, name = name, parent = parent, template = template, scripts = {},
                           shown = true, text = "", checked = false, enabled = true }, widgetMT)
  function w:SetScript(s, fn) self.scripts[s] = fn end
  function w:GetScript(s) return self.scripts[s] end
  function w:RegisterEvent(e) events[e] = self end
  function w:SetText(t) self.text = t == nil and "" or tostring(t) end
  function w:GetText() return self.text end
  function w:SetChecked(v) self.checked = not not v end
  function w:GetChecked() return self.checked end
  function w:Show() self.shown = true; if self.scripts.OnShow then self.scripts.OnShow(self) end end
  function w:Hide() self.shown = false end
  function w:IsShown() return self.shown end
  function w:CreateFontString(n) return widget("FontString", n, self) end
  function w:CreateTexture(n) return widget("Texture", n, self) end
  function w:SetMaxLetters(n) self.maxLetters = n end
  function w:Click(button)
    if self.kind == "CheckButton" then self.checked = not self.checked end
    if self.scripts.OnClick then self.scripts.OnClick(self, button or "LeftButton") end
  end
  -- The player types into an edit box.
  function w:Type(t)
    if self.maxLetters and #t > self.maxLetters then t = t:sub(1, self.maxLetters) end
    self.text = t
    if self.scripts.OnTextChanged then self.scripts.OnTextChanged(self, true) end
  end
  return w
end
function CreateFrame(kind, name, parent, template)
  local w = widget(kind, name, parent, template)
  if name then _G[name] = w end
  return w
end
UIParent = widget("Frame", "UIParent")

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
  HuzzahDB = saved
  events, timers, categories = {}, {}, {}
  assert(loadstring(ADDON_SRC, "Huzzah.lua"))("Huzzah")
  fire("ADDON_LOADED", "Huzzah")
  fire("PLAYER_LOGIN")
end
function cmd(s) out = {}; SlashCmdList.HUZZAH(s); return table.concat(out, "\n") end
function ok(c, m) if not c then error("FAIL: " .. m, 2) end end
function list(t) return table.concat(t, " | ") end
function panel() return categories[1].frame end
function row(kind) return panel().rows[kind] end
-- Turn every kind on, so tests about one kind don't depend on the defaults.
function allOn() for _, k in ipairs({ "group", "guild", "stranger", "self" }) do HuzzahDB[k].on = true end end
'''

SCENARIOS = {
# ---- settings ----
"first login sets up the defaults": r'''
  login(nil)
  ok(HuzzahDB.group.on and HuzzahDB.guild.on, "group and guild on")
  ok(not HuzzahDB.stranger.on and not HuzzahDB.self.on, "strangers and own off")
  ok(HuzzahDB.group.emote == "CHEER" and HuzzahDB.group.message == "Gz {name}, {level}!", "group defaults")
  ok(HuzzahDB.self.emote == "FLEX" and HuzzahDB.self.message == "Ding {level}!", "own defaults")
''',
"saved settings are kept and missing ones filled in": r'''
  login({ group = { on = false, emote = "", message = "yay" } })
  ok(HuzzahDB.group.on == false and HuzzahDB.group.emote == "" and HuzzahDB.group.message == "yay", "kept")
  ok(HuzzahDB.guild.on == true and HuzzahDB.guild.emote == "CONGRATULATE", "filled in")
''',

# ---- group ----
"a group member's ding: emote at them and a party message, after a short wait": r'''
  login(nil)
  see("party1", { name = "Bob", level = 19, group = true })
  fire("GROUP_ROSTER_UPDATE")
  ding("party1", 20)
  ok(#said == 0 and #emotes == 0, "waits first")
  advance(3)
  ok(list(emoteLines) == "cheers for Bob!" and #emotes == 0, list(emoteLines) .. " / " .. list(emotes))
  ok(list(said) == "PARTY: Gz Bob, 20!", list(said))
''',
"in a raid the message goes to raid chat": r'''
  login(nil)
  raid = true
  see("raid4", { name = "Bob", level = 19, group = true })
  fire("GROUP_ROSTER_UPDATE")
  ding("raid4", 20)
  advance(3)
  ok(list(said) == "RAID: Gz Bob, 20!", list(said))
''',
"a level seen for the first time isn't a ding": r'''
  login(nil)
  see("party1", { name = "Bob", level = 25, group = true })
  fire("UNIT_LEVEL", "party1")
  advance(5)
  ok(#said == 0 and #emotes == 0, "reacted to a level it never saw change")
''',
"one ding seen through several units gets one reaction": r'''
  login(nil)
  see("party1", { name = "Bob", level = 19, group = true })
  see("target", { name = "Bob", level = 19, group = true })
  fire("GROUP_ROSTER_UPDATE"); fire("PLAYER_TARGET_CHANGED")
  ding("party1", 20); ding("target", 20)
  advance(3)
  ok(#said == 1 and #emotes == 1, list(said))
''',
"each new level is congratulated": r'''
  login(nil)
  see("party1", { name = "Bob", level = 19, group = true })
  fire("GROUP_ROSTER_UPDATE")
  ding("party1", 20); advance(3)
  ding("party1", 21); advance(3)
  ok(list(said) == "PARTY: Gz Bob, 20! | PARTY: Gz Bob, 21!", list(said))
''',

# ---- guild ----
"your own name on the guild list isn't cheered as a guildmate": r'''
  login(nil)
  HuzzahDB.self.on = true
  roster = { { name = "Zaphiruz-Whitemane", level = 19, online = true } }
  fire("GUILD_ROSTER_UPDATE")
  -- The guild list can show the new level before or after PLAYER_LEVEL_UP.
  roster[1].level = 20
  fire("GUILD_ROSTER_UPDATE")
  fire("PLAYER_LEVEL_UP", 20)
  units.player.level = 21
  fire("PLAYER_LEVEL_UP", 21)
  roster[1].level = 21
  fire("GUILD_ROSTER_UPDATE")
  advance(3)
  ok(list(said) == "GUILD: Ding 20! | GUILD: Ding 21!", list(said))
  ok(#emoteLines == 0, "cheered yourself: " .. list(emoteLines))
''',
"your own name on the guild list isn't cheered while the game hides your name": r'''
  login(nil)
  -- Forever can hide UnitName("player") at restricted moments.
  units.player.name = SECRET
  roster = { { name = "Zaphiruz-Whitemane", level = 19, online = true } }
  fire("GUILD_ROSTER_UPDATE")
  roster[1].level = 20
  fire("GUILD_ROSTER_UPDATE")
  advance(3)
  ok(#said == 0 and #emoteLines == 0, "cheered yourself: " .. list(said) .. " / " .. list(emoteLines))
''',
"your own name on the guild list isn't cheered when its realm is written differently": r'''
  login(nil)
  roster = { { name = "Zaphiruz-White Mane", level = 19, online = true } }
  fire("GUILD_ROSTER_UPDATE")
  roster[1].level = 20
  fire("GUILD_ROSTER_UPDATE")
  advance(3)
  ok(#said == 0 and #emoteLines == 0, "cheered yourself: " .. list(said) .. " / " .. list(emoteLines))
''',
"/huzzah debug shows how the guild list writes your name": r'''
  login(nil)
  roster = { { name = "Ann-Whitemane", level = 10, online = true },
             { name = "Zaphiruz-White Mane", level = 19, online = true } }
  local o = cmd("debug")
  ok(o:find("You are Zaphiruz%-Whitemane; the guild list has you as Zaphiruz%-White Mane"), o)
  roster = {}
  o = cmd("debug"); o = cmd("debug")
  ok(o:find("not on the guild list"), o)
''',
"a unit that is you isn't cheered, even when the game won't say it's you": r'''
  login(nil)
  -- Your own nameplate, where UnitIsUnit(unit, "player") came back false.
  see("nameplate1", { name = "Zaphiruz", level = 19, guild = true })
  fire("NAME_PLATE_UNIT_ADDED", "nameplate1")
  ding("nameplate1", 20)
  advance(3)
  ok(#said == 0 and #emoteLines == 0, "cheered yourself: " .. list(said) .. " / " .. list(emoteLines))
''',
"/huzzah debug says where a ding was seen": r'''
  login(nil)
  cmd("debug")
  roster = { { name = "Ann-Whitemane", level = 10, online = true } }
  fire("GUILD_ROSTER_UPDATE")
  see("target", { name = "Cid", level = 30 })
  fire("PLAYER_TARGET_CHANGED")
  out = {}
  roster[1].level = 11
  fire("GUILD_ROSTER_UPDATE")
  ding("target", 31)
  local o = table.concat(out, "\n")
  ok(o:find("Ann%-Whitemane reached level 11 %(guild, from the guild list%)"), o)
  ok(o:find("Cid%-Whitemane reached level 31 %(stranger, from target%)"), o)
''',
"a guildmate's ding is found when the guild list refreshes": r'''
  login(nil)
  roster = { { name = "Ann-Whitemane", level = 10, online = true } }
  fire("GUILD_ROSTER_UPDATE")
  advance(5)
  ok(#said == 0, "the first look is only remembered")
  roster[1].level = 11
  fire("GUILD_ROSTER_UPDATE")
  advance(3)
  ok(list(emoteLines) == "congratulates Ann!", list(emoteLines))
  ok(list(said) == "GUILD: Grats on 11, Ann!", list(said))
''',
"the guild list is asked for regularly": r'''
  login(nil)
  local before = rosterRequests
  advance(120)
  ok(rosterRequests >= before + 3, "asked " .. (rosterRequests - before) .. " times")
''',
"offline guildmates and other realms are handled": r'''
  login(nil)
  roster = { { name = "Ann-Whitemane", level = 10, online = false },
             { name = "Cid-Mograine", level = 30, online = true } }
  fire("GUILD_ROSTER_UPDATE")
  roster[1].level = 11
  roster[2].level = 31
  fire("GUILD_ROSTER_UPDATE")
  advance(3)
  ok(list(said) == "GUILD: Grats on 31, Cid!", list(said))
  ok(list(emoteLines) == "congratulates Cid!", list(emoteLines))
''',
"a guildmate in your group gets only the group reaction": r'''
  login(nil)
  roster = { { name = "Bob-Whitemane", level = 19, online = true } }
  fire("GUILD_ROSTER_UPDATE")
  see("party1", { name = "Bob", level = 19, group = true, guild = true })
  fire("GROUP_ROSTER_UPDATE")
  ding("party1", 20)
  roster[1].level = 20
  fire("GUILD_ROSTER_UPDATE")
  advance(3)
  ok(list(said) == "PARTY: Gz Bob, 20!", list(said))
''',
"a guildmate you're looking at is congratulated right away, once": r'''
  login(nil)
  roster = { { name = "Ann-Whitemane", level = 10, online = true } }
  fire("GUILD_ROSTER_UPDATE")
  see("target", { name = "Ann", level = 10, guild = true })
  fire("PLAYER_TARGET_CHANGED")
  ding("target", 11)
  advance(3)
  roster[1].level = 11
  fire("GUILD_ROSTER_UPDATE")
  advance(3)
  ok(list(said) == "GUILD: Grats on 11, Ann!", list(said))
''',

# ---- strangers ----
"strangers are off until switched on": r'''
  login(nil)
  see("nameplate3", { name = "Dee", level = 30 })
  fire("NAME_PLATE_UNIT_ADDED", "nameplate3")
  ding("nameplate3", 31)
  advance(3)
  ok(#said == 0 and #emotes == 0 and #emoteLines == 0, "reacted while off")
''',
"a stranger nearby gets an emote and a whisper": r'''
  login(nil); allOn()
  see("nameplate3", { name = "Dee", level = 30 })
  fire("NAME_PLATE_UNIT_ADDED", "nameplate3")
  ding("nameplate3", 31)
  advance(3)
  ok(list(emoteLines) == "applauds Dee.", list(emoteLines))
  ok(list(said) == "WHISPER:Dee: Gz on 31!", list(said))
''',
"a stranger from another realm is whispered by full name": r'''
  login(nil); allOn()
  see("mouseover", { name = "Eve", realm = "Mograine", level = 40 })
  fire("UPDATE_MOUSEOVER_UNIT")
  ding("mouseover", 41)
  advance(3)
  ok(list(said) == "WHISPER:Eve-Mograine: Gz on 41!", list(said))
''',
"monsters levelling don't count": r'''
  login(nil); allOn()
  units.target = { name = "Hogger", level = 11, isPlayer = false }
  fire("PLAYER_TARGET_CHANGED")
  units.target.level = 12; fire("UNIT_LEVEL", "target")
  advance(3)
  ok(#said == 0 and #emotes == 0, "reacted to a monster")
''',

# ---- your own ----
"your own ding: an emote and a guild message, when switched on": r'''
  login(nil)
  fire("PLAYER_LEVEL_UP", 20)
  advance(3)
  ok(#said == 0, "off by default")
  HuzzahDB.self.on = true
  fire("PLAYER_LEVEL_UP", 21)
  advance(3)
  ok(list(emotes) == "FLEX", list(emotes))
  ok(list(said) == "GUILD: Ding 21!", list(said))
''',
"your own ding outside a guild skips the message": r'''
  guild = false
  login(nil); allOn()
  fire("PLAYER_LEVEL_UP", 20)
  advance(3)
  ok(#said == 0 and list(emotes) == "FLEX", list(said) .. " / " .. list(emotes))
''',
"your own UNIT_LEVEL isn't counted twice": r'''
  login(nil); allOn()
  units.player.level = 20
  fire("UNIT_LEVEL", "player")
  fire("PLAYER_LEVEL_UP", 20)
  advance(3)
  ok(#said == 1, list(said))
''',

"the person you're targeting gets the real emote, aimed at them": r'''
  login(nil)
  see("party1", { name = "Bob", level = 19, group = true })
  units.target = units.party1
  fire("GROUP_ROSTER_UPDATE")
  ding("party1", 20); advance(3)
  ok(list(emotes) == "CHEER", "a plain emote aims at the target: " .. list(emotes))
  ok(#emoteLines == 0, list(emoteLines))
''',
"someone else targeted: the custom line still names the one who dinged": r'''
  login(nil)
  see("party1", { name = "Bob", level = 19, group = true })
  see("target", { name = "Ann", level = 40 })
  fire("GROUP_ROSTER_UPDATE")
  ding("party1", 20); advance(3)
  ok(#emotes == 0 and list(emoteLines) == "cheers for Bob!", list(emotes) .. " / " .. list(emoteLines))
''',
"if a custom line can't be sent, a plain emote instead": r'''
  login(nil)
  emoteBlocked = true
  see("party1", { name = "Bob", level = 19, group = true })
  fire("GROUP_ROSTER_UPDATE")
  ding("party1", 20); advance(3)
  ok(list(emotes) == "CHEER" and #emoteLines == 0, list(emotes))
  emoteBlocked, lockdown = false, true
  ding("party1", 21); advance(3)
  ok(list(emotes) == "CHEER | CHEER" and #emoteLines == 0, "locked chat: " .. list(emotes))
''',
"every emote has its own wording": r'''
  login(nil)
  see("party1", { name = "Bob", level = 19, group = true })
  fire("GROUP_ROSTER_UPDATE")
  for i, e in ipairs({ "APPLAUD", "BOW", "CLAP", "DANCE", "FLEX", "GRIN", "HUG", "ROAR", "SALUTE", "WAVE", "LAUGH" }) do
    HuzzahDB.group.emote = e
    ding("party1", 20 + i); advance(3)
  end
  ok(#emoteLines == 11, "got " .. #emoteLines)
  for _, l in ipairs(emoteLines) do ok(l:find("Bob"), l) end
  ok(emoteLines[2] == "bows to Bob." and emoteLines[10] == "waves at Bob.", list(emoteLines))
  ok(emoteLines[11] == "laughs at Bob.", "an emote without its own wording: " .. emoteLines[11])
''',

# ---- what gets sent ----
"an empty emote or message is skipped": r'''
  login(nil)
  HuzzahDB.group.emote = ""
  see("party1", { name = "Bob", level = 19, group = true })
  fire("GROUP_ROSTER_UPDATE")
  ding("party1", 20); advance(3)
  ok(#emotes == 0 and #emoteLines == 0 and #said == 1, "no emote")
  HuzzahDB.group.emote, HuzzahDB.group.message = "CHEER", "  "
  ding("party1", 21); advance(3)
  ok(#emoteLines == 1 and #said == 1, "no message")
''',
"switched off: nothing at all": r'''
  login(nil)
  HuzzahDB.group.on = false
  see("party1", { name = "Bob", level = 19, group = true })
  fire("GROUP_ROSTER_UPDATE")
  ding("party1", 20); advance(3)
  ok(#said == 0 and #emotes == 0 and #emoteLines == 0, "reacted while off")
''',
"names with odd characters are put in safely": r'''
  login(nil)
  HuzzahDB.group.message = "{name}%1 hit {level}! {name}"
  see("party1", { name = "B%ob", level = 19, group = true })
  fire("GROUP_ROSTER_UPDATE")
  ding("party1", 20); advance(3)
  ok(list(said) == "PARTY: B%ob%1 hit 20! B%ob", list(said))
''',
"a message too long for chat isn't sent": r'''
  login(nil)
  HuzzahDB.group.message = string.rep("{name}", 60)
  see("party1", { name = "Bobbington", level = 19, group = true })
  fire("GROUP_ROSTER_UPDATE")
  ding("party1", 20); advance(3)
  ok(#said == 0, "sent a long message")
  ok(#emoteLines == 1, "the emote still happens")
''',
"while chat is locked the message is skipped": r'''
  login(nil)
  lockdown = true
  see("party1", { name = "Bob", level = 19, group = true })
  fire("GROUP_ROSTER_UPDATE")
  ding("party1", 20); advance(3)
  ok(#said == 0, "sent during lockdown")
''',
"if the group is gone by then, no party message": r'''
  login(nil)
  see("party1", { name = "Bob", level = 19, group = true })
  fire("GROUP_ROSTER_UPDATE")
  ding("party1", 20)
  units.party1 = nil
  advance(3)
  ok(#said == 0, list(said))
''',

# ---- Forever ----
"Classic chat functions are used when C_ChatInfo lacks them": r'''
  C_ChatInfo = { InChatMessagingLockdown = function() return false end }
  function SendChatMessage(msg, chatType) table.insert(said, chatType .. ": " .. msg) end
  function DoEmote(token, target) table.insert(emotes, token .. (target and (" " .. target) or "")) end
  login(nil)
  see("party1", { name = "Bob", level = 19, group = true })
  fire("GROUP_ROSTER_UPDATE")
  ding("party1", 20); advance(3)
  ok(list(said) == "EMOTE: cheers for Bob! | PARTY: Gz Bob, 20!", list(said))
''',
"on Forever, a plain emote instead of the emote line, which the game blocks": r'''
  tocVersion = 16001
  login(nil)
  cmd("debug")
  see("party1", { name = "Bob", level = 19, group = true })
  fire("GROUP_ROSTER_UPDATE")
  out = {}
  ding("party1", 20); advance(3)
  ok(#blocked == 0, "tried a blocked emote line: " .. list(blocked))
  ok(list(emotes) == "CHEER" and #emoteLines == 0, list(emotes))
  ok(list(said) == "PARTY: Gz Bob, 20!", "the message still names them: " .. list(said))
  ok(table.concat(out, "\n"):find("plain emote"), "debug says which emote: " .. table.concat(out, "\n"))
  units.target = units.party1
  ding("party1", 21); advance(3)
  ok(list(emotes) == "CHEER | CHEER" and #blocked == 0, "at the target: " .. list(emotes))
  local o = cmd("test")
  ok(o:find("/cheer") and not o:find("cheers for"), o)
''',
"hidden (secret) names and levels are skipped without errors": r'''
  login(nil); allOn()
  see("nameplate1", { name = "Dee", level = 30 })
  fire("NAME_PLATE_UNIT_ADDED", "nameplate1")
  units.nameplate1.level = SECRET
  fire("UNIT_LEVEL", "nameplate1")
  units.nameplate1.level, units.nameplate1.name = 31, SECRET
  fire("UNIT_LEVEL", "nameplate1")
  advance(3)
  ok(#said == 0 and #emotes == 0 and #emoteLines == 0, "reacted to a hidden ding")
''',

# ---- settings panel ----
"the panel is in Options under AddOns, and /huzzah opens it": r'''
  login(nil)
  ok(#categories == 1 and categories[1].name == "Huzzah", "registered")
  cmd("")
  ok(opened == 77, "opened to Huzzah")
''',
"the panel changes the settings": r'''
  login(nil)
  panel():Show()
  ok(row("group").check:GetChecked() == true and row("stranger").check:GetChecked() == false, "checks match")
  ok(row("group").message:GetText() == "Gz {name}, {level}!", row("group").message:GetText())
  row("stranger").check:Click()
  ok(HuzzahDB.stranger.on == true, "turned on")
  row("group").message:Type("Nice one {name}!")
  ok(HuzzahDB.group.message == "Nice one {name}!", HuzzahDB.group.message)
  ok(row("group").message.maxLetters and row("group").message.maxLetters <= 200, "length capped")
''',
"the emote button steps through emotes, and none": r'''
  login(nil)
  panel():Show()
  local b = row("group").emote
  ok(b:GetText() == "Cheer", b:GetText())
  local seen = {}
  for i = 1, 30 do b:Click("LeftButton"); seen[HuzzahDB.group.emote] = true end
  ok(seen[""] and seen.CONGRATULATE and seen.FLEX, "cycles through, including none")
  local before = HuzzahDB.group.emote
  b:Click("LeftButton"); b:Click("RightButton")
  ok(HuzzahDB.group.emote == before, "right-click steps back")
  HuzzahDB.group.emote = ""
  panel():Show()
  ok(b:GetText() == "None", b:GetText())
''',

# ---- commands ----
"/huzzah test previews every reaction without sending": r'''
  login(nil)
  local o = cmd("test")
  ok(o:find("Group") and o:find("/cheer") and o:find("Gz Bob, 20!"), o)
  ok(o:find("Strangers: off"), o)
  ok(#said == 0 and #emotes == 0, "test sent something")
''',
"/huzzah help, debug and unknown words": r'''
  login(nil)
  local o = cmd("help")
  ok(o:find("/huzzah test") and o:find("/huzzah debug"), o)
  o = cmd("banana")
  ok(o:find("banana") and o:find("/huzzah help"), o)
  cmd("debug")
  out = {}
  see("party1", { name = "Bob", level = 19, group = true })
  fire("GROUP_ROSTER_UPDATE")
  ding("party1", 20)
  ok(table.concat(out, "\n"):find("Bob"), "debug prints dings: " .. table.concat(out, "\n"))
''',
"/huzzah says so if loading failed": r'''
  login(nil)
  events = {}
  assert(loadstring(ADDON_SRC, "Huzzah.lua"))("Huzzah")
  ok(cmd("test"):find("didn't finish loading"), cmd("test"))
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
