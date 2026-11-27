"""Runs Hitched.lua against a small fake WoW API. Usage: python run_tests.py path/to/Hitched.lua

SCENARIOS run one game each: the other player is played by hand, by firing
the addon messages their game would send. PAIRS run two or three games at
once and carry the addon messages between them.
"""
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

-- Clocks: GetTime counts seconds since the client started, time() is the date.
now = 100
clock = 1795694400  -- 26 Nov 2026
function GetTime() return now end
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
SECRET = setmetatable({}, { __index = function() error("read a secret value") end })
function issecretvalue(v) return rawequal(v, SECRET) end

-- Players the game can name. You are Alice.
A, B, D = "Player-1-0000000A", "Player-1-0000000B", "Player-1-0000000D"
units = { player = { name = "Alice", guid = A, isPlayer = true } }
function UnitGUID(u) local x = units[u]; if x then return x.guid end end
function GetRealmName() return "Whitemane" end
function GetNormalizedRealmName() return "Whitemane" end
function UnitName(u) local x = units[u]; if x then return x.name, x.realm end end
function UnitExists(u) return units[u] ~= nil end
function UnitIsPlayer(u) local x = units[u]; return x ~= nil and x.isPlayer == true end
function UnitIsUnit(a, b) return units[a] ~= nil and units[b] ~= nil and units[a].guid == units[b].guid end
function UnitFactionGroup(u) local x = units[u]; if x then return x.faction or "Alliance" end end
function UnitIsConnected(u) local x = units[u]; return x ~= nil and x.connected ~= false end
function Ambiguate(name, how)
  if how == "short" then return (name:gsub("%-.*$", "")) end
  return (name:gsub("%-Whitemane$", ""))
end
zoneName = "Stormwind City"
function GetRealZoneText() return zoneName end
-- A player the game knows under `unit` (target, mouseover, party1, ...).
function see(unit, p)
  units[unit] = { name = p.name, realm = p.realm, guid = p.guid, isPlayer = p.isPlayer ~= false,
                  faction = p.faction, connected = p.connected }
end
function bob(extra)
  local p = { name = "Bob", guid = B }
  for k, v in pairs(extra or {}) do p[k] = v end
  return p
end
guild, grouped, raid = false, false, false
function IsInGuild() return guild end
function IsInGroup() return grouped end
function IsInRaid() return raid and grouped end

-- Chat, emotes and addon messages.
said, emotes, emoteLines, blocked, sent, prefixes = {}, {}, {}, {}, {}, {}
lockdown = false
clicking = false   -- true while a real click is being handled
tocVersion = 11509 -- 11509 is Classic Era, 16001 is Forever
function GetBuildInfo() return "1.15.9", "60000", "Nov 1 2026", tocVersion end
C_ChatInfo = {
  SendChatMessage = function(msg, chatType, lang, target)
    assert(#msg <= 255, "message too long")
    assert(not lockdown, "sent chat while chat is locked")
    if chatType == "EMOTE" then
      -- Forever blocks emote lines sent without a key press: the call does
      -- nothing and raises no error.
      if tocVersion >= 16000 and not clicking then table.insert(blocked, msg); return end
      table.insert(emoteLines, msg)
      return
    end
    table.insert(said, chatType .. (target and (":" .. target) or "") .. ": " .. msg)
  end,
  -- The game aims a real emote at your target, whoever that is.
  PerformEmote = function(token)
    table.insert(emotes, token .. (units.target and (" at " .. tostring(units.target.name)) or ""))
    return true
  end,
  InChatMessagingLockdown = function() return lockdown end,
  RegisterAddonMessagePrefix = function(p) prefixes[p] = true; return true end,
  SendAddonMessage = function(prefix, msg, route, target)
    assert(prefixes[prefix], "sent with a prefix that was never registered")
    assert(type(msg) == "string" and #msg <= 255, "addon message too long")
    assert(not lockdown, "sent an addon message while chat is locked")
    if route == "WHISPER" then assert(type(target) == "string" and target ~= "", "whisper to nobody") end
    table.insert(sent, { text = msg, route = route, target = target })
    return 0
  end,
}
-- What was sent since the last look: "WHISPER>Bob 1;propose;..." joined by " | ".
function wire()
  local t = {}
  for _, m in ipairs(sent) do t[#t+1] = m.route .. (m.target and (">" .. m.target) or "") .. " " .. m.text end
  sent = {}
  return table.concat(t, " | ")
end
-- For the tests with several games: the next message to carry, or nil.
function nextSent()
  local m = table.remove(sent, 1)
  if m then return m.route .. "\t" .. (m.target or "") .. "\t" .. m.text end
end
-- Another game's addon message arrives.
function hear(msg, route, sender) fire("CHAT_MSG_ADDON", "Hitched", msg, route or "WHISPER", sender or "Bob-Whitemane") end

-- Lines the game prints itself (CHAT_MSG_SYSTEM) go through addons' filters
-- once for every chat window that shows them. shown(text) is true when the
-- line reaches the windows.
ERR_CHAT_PLAYER_NOT_FOUND_S = "No player named '%s' is currently playing."
chatFilters = {}
ChatFrameUtil = { AddMessageEventFilter = function(event, fn)
  chatFilters[event] = chatFilters[event] or {}
  for _, f in ipairs(chatFilters[event]) do if f == fn then return end end
  table.insert(chatFilters[event], fn)
end }
function shown(text)
  local windows = 0
  for w = 1, 2 do
    local discard = false
    for _, fn in ipairs(chatFilters.CHAT_MSG_SYSTEM or {}) do
      -- The game doesn't hand a filter a line it can't read.
      if not issecretvalue(text) and fn({}, "CHAT_MSG_SYSTEM", text, "", "", "") then discard = true; break end
    end
    if not discard then windows = windows + 1 end
  end
  assert(windows == 0 or windows == 2, "hidden in one chat window only")
  return windows == 2
end
-- Does the game's "No player named ..." line for this name stay off the screen?
function gone(name) return not shown(format(ERR_CHAT_PLAYER_NOT_FOUND_S, name)) end

-- The game's own lookup of a player it is showing you.
function UnitTokenFromGUID(guid)
  for _, token in ipairs({ "target", "mouseover", "party1", "party2", "nameplate1", "nameplate2", "nameplate3" }) do
    if units[token] and units[token].guid == guid then return token end
  end
end

-- Frames.
local noop = function() end
local widgetMT = { __index = function() return noop end }
function widget(kind, name, parent, template)
  local w = setmetatable({ kind = kind, name = name, parent = parent, template = template, scripts = {}, hooks = {},
                           shown = false, text = "", checked = false }, widgetMT)
  function w:SetScript(s, fn) self.scripts[s] = fn end
  function w:GetScript(s) return self.scripts[s] end
  function w:HookScript(s, fn) self.hooks[s] = self.hooks[s] or {}; table.insert(self.hooks[s], fn) end
  function w:RunHooks(s, ...) for _, fn in ipairs(self.hooks[s] or {}) do fn(self, ...) end end
  function w:RegisterEvent(e) events[e] = self end
  function w:GetName() return self.name end
  function w:SetText(t) self.text = t == nil and "" or tostring(t) end
  function w:GetText() return self.text end
  function w:SetChecked(v) self.checked = not not v end
  function w:GetChecked() return self.checked end
  function w:Show() self.shown = true; if self.scripts.OnShow then self.scripts.OnShow(self) end end
  function w:Hide()
    local was = self.shown
    self.shown = false
    if was and self.scripts.OnHide then self.scripts.OnHide(self) end
  end
  function w:IsShown() return self.shown end
  function w:CreateFontString(n) return widget("FontString", n, self) end
  -- A real click: Forever lets an addon send an emote line from one.
  function w:Click(button)
    if self.kind == "CheckButton" then self.checked = not self.checked end
    clicking = true
    local ok, err = pcall(function()
      if self.scripts.OnClick then self.scripts.OnClick(self, button or "LeftButton") end
    end)
    clicking = false
    if not ok then error(err, 0) end
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
fighting = false
function InCombatLockdown() return fighting end
Settings = {
  RegisterCanvasLayoutCategory = function(frame, name)
    local c = { frame = frame, name = name, id = 91 }
    function c:GetID() return self.id end
    return c
  end,
  RegisterAddOnCategory = function(c) table.insert(categories, c) end,
  OpenToCategory = function(id)
    assert(not fighting, "opened the settings in combat: the game blocks that and blames the addon")
    opened = id
  end,
}

-- The game tooltip. Forever offers TooltipDataProcessor; Classic Era the
-- OnTooltipSetUnit script.
GameTooltip = widget("GameTooltip", "GameTooltip")
GameTooltip.lines = {}
function GameTooltip:AddLine(t) table.insert(self.lines, t) end
function GameTooltip:ClearLines() self.lines = {}; self:RunHooks("OnTooltipCleared") end
function GameTooltip:GetUnit() if self.unit then return UnitName(self.unit), self.unit end end
Enum = { TooltipDataType = { Item = 0, Unit = 2 } }
postCalls = {}
TooltipDataProcessor = { AddTooltipPostCall = function(kind, fn)
  postCalls[kind] = postCalls[kind] or {}; table.insert(postCalls[kind], fn) end }
function plain(s) return (tostring(s):gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", "")) end
-- What the tooltip says under the name and level lines.
function tip()
  local t = {}
  for i = 3, #GameTooltip.lines do t[#t+1] = plain(GameTooltip.lines[i]) end
  return table.concat(t, "\n")
end
-- Move the mouse over a player: the game fills the tooltip, runs the unit
-- hooks and tells addons. The tooltip stays up until leave().
function hover(u)
  GameTooltip:ClearLines()
  units.mouseover = units[u]
  GameTooltip.unit = u == "player" and "player" or "mouseover"
  GameTooltip:AddLine(tostring(UnitName(u)))
  GameTooltip:AddLine("Level 60 Human Priest (Player)")
  if TooltipDataProcessor then
    for _, fn in ipairs(postCalls[Enum.TooltipDataType.Unit] or {}) do fn(GameTooltip, { type = 2 }) end
  else
    GameTooltip:RunHooks("OnTooltipSetUnit")
  end
  GameTooltip:Show()
  fire("UPDATE_MOUSEOVER_UNIT")
  return tip()
end
function leave() GameTooltip:Hide(); GameTooltip.unit = nil; units.mouseover = nil end

function fire(e, ...) local f = events[e]; if f then f.scripts.OnEvent(f, e, ...) end end
function login(saved, charSaved)
  HitchedDB, HitchedCharDB = saved, charSaved
  events, timers, categories, postCalls, chatFilters = {}, {}, {}, {}, {}
  GameTooltip.hooks = {}
  assert(loadstring(ADDON_SRC, "Hitched.lua"))("Hitched")
  fire("ADDON_LOADED", "Hitched")
  fire("PLAYER_LOGIN")
end
function cmd(s) out = {}; SlashCmdList.HITCHED(s); return table.concat(out, "\n") end
function printed() local s = plain(table.concat(out, "\n")); out = {}; return s end
function ok(c, m) if not c then error("FAIL: " .. tostring(m), 2) end end
function list(t) return table.concat(t, " | ") end
function panel() return categories[1].frame end
-- Saved data of a character married to Bob since yesterday.
function wed()
  return { spouse = { guid = B, name = "Bob", full = "Bob-Whitemane", since = clock - 86400, place = "Ironforge" } }
end
-- Target Bob and propose; Bob's game says it got the proposal.
function propose()
  see("target", bob())
  local o = cmd("propose")
  hear("1;got;" .. B)
  return o
end
-- Your story, as Storied would show it.
function story()
  local t = {}
  for _, e in ipairs(Hitched.story()) do t[#t+1] = e.what end
  return table.concat(t, " | ")
end
'''

SCENARIOS = {
# ---- settings ----
"first login sets up the defaults, a settings page and the message prefix": r'''
  login(nil, nil)
  ok(HitchedDB.tooltips and HitchedDB.cheer and HitchedDB.proposals, "all on")
  ok(HitchedCharDB.spouse == nil and type(HitchedCharDB.story) == "table", "nobody yet")
  ok(type(HitchedCharDB.notices) == "table", "notices")
  ok(categories[1] and categories[1].name == "Hitched", "settings page")
  ok(prefixes.Hitched, "prefix registered")
  cmd("settings")
  ok(opened == 91, "/hitched settings opens the settings")
''',
"saved settings and a saved marriage are kept": r'''
  login({ tooltips = false }, wed())
  ok(HitchedDB.tooltips == false and HitchedDB.cheer == true, "settings")
  ok(HitchedCharDB.spouse.name == "Bob", "marriage")
''',
"the settings page has a switch for each setting": r'''
  login(nil, nil)
  panel():Show()
  for _, key in ipairs({ "tooltips", "cheer", "proposals" }) do
    ok(panel().checks[key].checked == true, key .. " shown on")
    panel().checks[key]:Click()
    ok(HitchedDB[key] == false, key .. " switched off")
  end
''',
"the settings can't be opened in a fight: they open when it ends": r'''
  login(nil, nil)
  fighting = true
  ok(cmd("settings"):find("fight"), "says why")
  ok(opened == nil, "opened in combat")
  fighting = false
  fire("PLAYER_REGEN_ENABLED")
  ok(opened == 91, "opens after")
''',

# ---- proposing ----
"proposing needs a player targeted, and not yourself": r'''
  login(nil, nil)
  ok(cmd("propose"):find("target the player"), "no target")
  see("target", { name = "Hogger", guid = "Creature-0-1-0-0-448-0", isPlayer = false })
  ok(cmd("propose"):find("target the player"), "a mob")
  units.target = units.player
  ok(cmd("propose"):find("can't marry yourself"), "yourself")
  ok(wire() == "" and #emotes == 0, "nothing sent")
''',
"proposing kneels before them and asks their game": r'''
  login(nil, nil)
  see("target", bob())
  local o = cmd("propose")
  ok(list(emotes) == "KNEEL at Bob", list(emotes))
  ok(wire() == "WHISPER>Bob 1;propose;" .. A, "asked")
  ok(o:find("proposed to Bob") and o:find("Waiting"), o)
  ok(HitchedCharDB.spouse == nil, "not married yet")
''',
"a player on another realm is whispered with their realm": r'''
  login(nil, nil)
  see("target", bob({ realm = "Stormrage" }))
  cmd("propose")
  ok(wire() == "WHISPER>Bob-Stormrage 1;propose;" .. A, "asked")
''',
"if their game doesn't answer, they don't have Hitched": r'''
  login(nil, nil)
  see("target", bob())
  cmd("propose")
  out = {}
  advance(5)
  ok(printed():find("Bob doesn't seem to have Hitched"), "says so")
  ok(story() == "", "nothing in your story: " .. story())
  wire(); emotes = {}
  cmd("propose")
  ok(wire() ~= "" and #emotes == 1, "you can try again")
''',
"they say yes: you are married, and you cheer": r'''
  login(nil, nil)
  guild = true
  propose()
  wire(); emotes = {}; out = {}
  advance(20)
  hear("1;yes;" .. B .. ";" .. clock)
  local s = HitchedCharDB.spouse
  ok(s and s.guid == B and s.name == "Bob" and s.since == clock and s.place == "Stormwind City", "married")
  ok(list(emotes) == "CHEER at Bob", list(emotes))
  ok(printed():find("you and Bob are now married"), "says so")
  ok(wire() == "GUILD 1;just;" .. A .. ";" .. B .. ";Bob", "tells the guild")
  ok(story() == "Proposed to Bob | Married Bob", story())
  advance(120)
  ok(printed() == "", "nothing more is said")
''',
"they say no: you cry, and you aren't married": r'''
  login(nil, nil)
  propose()
  emotes = {}; out = {}
  hear("1;no;" .. B .. ";no")
  ok(HitchedCharDB.spouse == nil, "not married")
  ok(printed():find("Bob said no"), "says so")
  ok(list(emotes) == "CRY at Bob", list(emotes))
  ok(story() == "Proposed to Bob | Bob said no", story())
  ok(cmd("propose"):find("proposed to Bob"), "you can ask again")
''',
"other answers are explained, without crying": r'''
  login(nil, nil)
  for reason, words in pairs({ married = "already married", busy = "busy", closed = "isn't taking proposals",
                               timeout = "didn't answer" }) do
    propose()
    emotes = {}; out = {}
    hear("1;no;" .. B .. ";" .. reason)
    ok(printed():find(words), reason)
    ok(#emotes == 0, "cried at " .. reason)
    ok(HitchedCharDB.spouse == nil, "not married")
  end
''',
"an answer that never comes is given up on": r'''
  login(nil, nil)
  propose()
  out = {}
  advance(80)
  ok(printed():find("Bob didn't answer"), "says so")
  ok(cmd("propose"):find("proposed to Bob"), "you can ask again")
''',
"you can't propose while married, or while waiting for an answer": r'''
  login(nil, wed())
  see("target", { name = "Dana", guid = D })
  ok(cmd("propose"):find("already married to Bob"), "married")
  ok(wire() == "", "sent anyway")
  login(nil, nil)
  propose()
  wire()
  ok(cmd("propose"):find("waiting for Bob"), "waiting")
  ok(wire() == "", "sent twice")
''',
"you can't propose to the other faction, someone offline, or while chat is locked": r'''
  login(nil, nil)
  see("target", bob({ faction = "Horde" }))
  ok(cmd("propose"):find("other side"), "other faction")
  see("target", bob({ connected = false }))
  ok(cmd("propose"):find("offline"), "offline")
  see("target", bob())
  lockdown = true
  ok(cmd("propose"):find("blocking"), "locked")
  ok(wire() == "" and #emotes == 0, "nothing sent")
''',
"a hidden target can't be proposed to": r'''
  login(nil, nil)
  see("target", { name = SECRET, guid = SECRET })
  ok(cmd("propose"):find("hiding"), "says so")
  ok(wire() == "", "nothing sent")
''',
"a yes from someone you didn't ask is ignored": r'''
  login(nil, nil)
  hear("1;yes;" .. B .. ";" .. clock)
  ok(HitchedCharDB.spouse == nil, "married by surprise")
  propose()
  hear("1;yes;" .. D .. ";" .. clock, "WHISPER", "Dana-Whitemane")
  ok(HitchedCharDB.spouse == nil, "married the wrong player")
  hear("1;yes;" .. B .. ";" .. clock, "GUILD")
  ok(HitchedCharDB.spouse == nil, "a yes only counts as a whisper")
''',
"a yes that got lost is made up for when their game says it's married to you": r'''
  login(nil, nil)
  propose()
  local saved, char = HitchedDB, HitchedCharDB
  login(saved, char)   -- you reloaded before the answer came
  out = {}
  hear("1;wed;" .. B .. ";" .. A .. ";Alice;" .. (clock - 50), "WHISPER", "Bob-Whitemane")
  ok(HitchedCharDB.spouse and HitchedCharDB.spouse.guid == B, "married after all")
  ok(HitchedCharDB.spouse.since == clock - 50, "since their date")
  ok(printed():find("you and Bob are now married"), "says so")
''',

# ---- being proposed to ----
"a proposal shows a question and tells their game it arrived": r'''
  login(nil, nil)
  hear("1;propose;" .. B)
  ok(wire() == "WHISPER>Bob-Whitemane 1;got;" .. A, "said it arrived")
  ok(HitchedDialog.shown, "question shown")
  ok(HitchedDialog.text.text == "Bob is on one knee.\nWill you marry Bob?", HitchedDialog.text.text)
  ok(HitchedDialog.yes.text == "I do" and HitchedDialog.no.text == "No", "buttons")
  ok(story() == "Bob proposed to you", story())
''',
"saying I do marries you, tells them and everyone nearby": r'''
  login(nil, nil)
  guild = true
  hear("1;propose;" .. B)
  wire()
  HitchedDialog.yes:Click()
  local s = HitchedCharDB.spouse
  ok(s and s.guid == B and s.name == "Bob" and s.full == "Bob-Whitemane" and s.since == clock, "married")
  ok(not HitchedDialog.shown, "question gone")
  ok(wire() == "WHISPER>Bob-Whitemane 1;yes;" .. A .. ";" .. clock .. " | GUILD 1;just;" .. A .. ";" .. B .. ";Bob",
     "told them")
  ok(list(emoteLines) == "says yes to Bob!", list(emoteLines))
  ok(list(emotes) == "CHEER", list(emotes))
  ok(printed():find("you and Bob are now married"), "says so")
  ok(story() == "Bob proposed to you | Married Bob", story())
''',
"saying yes with someone else targeted doesn't cheer at them": r'''
  login(nil, nil)
  see("target", { name = "Dana", guid = D })
  hear("1;propose;" .. B)
  HitchedDialog.yes:Click()
  ok(list(emoteLines) == "says yes to Bob!", list(emoteLines))
  ok(#emotes == 0, "cheered at " .. list(emotes))
''',
"on Forever the yes line goes out with the click": r'''
  tocVersion = 16001
  login(nil, nil)
  see("target", bob())
  hear("1;propose;" .. B)
  HitchedDialog.yes:Click()
  ok(list(emoteLines) == "says yes to Bob!" and #blocked == 0, list(emoteLines) .. " / " .. list(blocked))
  ok(list(emotes) == "CHEER at Bob", list(emotes))
''',
"saying no turns them down gently": r'''
  login(nil, nil)
  hear("1;propose;" .. B)
  wire()
  HitchedDialog.no:Click()
  ok(HitchedCharDB.spouse == nil, "married anyway")
  ok(wire() == "WHISPER>Bob-Whitemane 1;no;" .. A .. ";no", "told them")
  ok(list(emoteLines) == "gently turns Bob down.", list(emoteLines))
  ok(#emotes == 0, "no real emote")
  ok(story() == "Bob proposed to you | You turned Bob down", story())
''',
"a question left alone, or closed, goes away quietly": r'''
  login(nil, nil)
  hear("1;propose;" .. B)
  wire(); out = {}
  advance(60)
  ok(not HitchedDialog.shown, "still up")
  ok(wire() == "WHISPER>Bob-Whitemane 1;no;" .. A .. ";timeout", "told them")
  ok(#emoteLines == 0 and #emotes == 0, "emoted")
  ok(printed():find("didn't answer Bob"), "says so")
  advance(700)
  hear("1;propose;" .. B)
  wire()
  HitchedDialog:Hide()   -- the X in the corner
  ok(wire() == "WHISPER>Bob-Whitemane 1;no;" .. A .. ";timeout", "closing it tells them too")
  ok(HitchedCharDB.spouse == nil, "married by closing")
''',
"a proposal to someone married is turned away by their game": r'''
  login(nil, wed())
  hear("1;propose;" .. D, "WHISPER", "Dana-Whitemane")
  ok(wire() == "WHISPER>Dana-Whitemane 1;no;" .. A .. ";married", "answered")
  ok(not (HitchedDialog and HitchedDialog.shown), "asked anyway")
''',
"a second proposal while one is on screen is told you're busy": r'''
  login(nil, nil)
  hear("1;propose;" .. B)
  wire()
  hear("1;propose;" .. D, "WHISPER", "Dana-Whitemane")
  ok(wire() == "WHISPER>Dana-Whitemane 1;no;" .. A .. ";busy", "answered")
  ok(HitchedDialog.text.text:find("Bob"), "question replaced")
''',
"with proposals switched off, nobody can ask": r'''
  login({ proposals = false }, nil)
  hear("1;propose;" .. B)
  ok(wire() == "WHISPER>Bob-Whitemane 1;no;" .. A .. ";closed", "answered")
  ok(not (HitchedDialog and HitchedDialog.shown), "asked anyway")
  ok(story() == "", story())
''',
"someone you turned down can't ask again for ten minutes": r'''
  login(nil, nil)
  hear("1;propose;" .. B)
  HitchedDialog.no:Click()
  wire()
  advance(300)
  hear("1;propose;" .. B)
  ok(wire() == "WHISPER>Bob-Whitemane 1;no;" .. A .. ";closed", "asked again too soon")
  ok(not HitchedDialog.shown, "question shown")
  advance(400)
  hear("1;propose;" .. B)
  ok(HitchedDialog.shown, "can ask later")
''',
"a proposal only counts as a whisper": r'''
  login(nil, nil)
  hear("1;propose;" .. B, "GUILD")
  ok(wire() == "" and not (HitchedDialog and HitchedDialog.shown), "took a proposal from guild chat")
''',

# ---- tooltips ----
"your spouse's tooltip says since when": r'''
  login(nil, wed())
  see("party1", bob())
  ok(hover("party1") == "Your spouse since 25 Nov 2026", tip())
''',
"your own tooltip says who you're married to": r'''
  login(nil, wed())
  ok(hover("player") == "Married to Bob", tip())
  login(nil, nil)
  ok(hover("player") == "", tip())
''',
"hovering a stranger asks their game, and the answer goes on the tooltip": r'''
  login(nil, nil)
  see("nameplate1", { name = "Dana", guid = D })
  ok(hover("nameplate1") == "", "nothing known yet")
  ok(wire() == "WHISPER>Dana 1;ask;" .. A, "asked")
  hear("1;wed;" .. D .. ";" .. B .. ";Bob;" .. (clock - 5), "WHISPER", "Dana-Whitemane")
  ok(tip() == "Married to Bob", "added to the open tooltip: " .. tip())
  leave()
  ok(hover("nameplate1") == "Married to Bob", tip())
  ok(wire() == "", "asked again")
  advance(601)
  hover("nameplate1")
  ok(wire() == "WHISPER>Dana 1;ask;" .. A, "asks again after ten minutes")
''',
"someone who isn't married has no line": r'''
  login(nil, nil)
  see("nameplate1", { name = "Dana", guid = D })
  hover("nameplate1")
  hear("1;single;" .. D, "WHISPER", "Dana-Whitemane")
  ok(tip() == "", tip())
  leave()
  ok(hover("nameplate1") == "", tip())
''',
"a divorce heard later takes the line away": r'''
  login(nil, nil)
  see("nameplate1", { name = "Dana", guid = D })
  hear("1;wed;" .. D .. ";" .. B .. ";Bob;" .. clock, "GUILD", "Dana-Whitemane")
  ok(hover("nameplate1") == "Married to Bob", tip())
  leave()
  hear("1;single;" .. D, "GUILD", "Dana-Whitemane")
  ok(hover("nameplate1") == "", tip())
''',
"what one player says about another player isn't believed": r'''
  login(nil, nil)
  see("nameplate1", { name = "Dana", guid = D })
  -- Mallory claims to be Dana.
  hear("1;wed;" .. D .. ";" .. B .. ";a goblin;" .. clock, "GUILD", "Mallory-Whitemane")
  ok(hover("nameplate1") == "", tip())
''',
"a Forever name with a surname still matches": r'''
  login(nil, nil)
  see("nameplate1", { name = "Dana", guid = D })
  hear("1;wed;" .. D .. ";" .. B .. ";Bob Stonefist;" .. clock, "GUILD", "Dana Brightblade")
  ok(hover("nameplate1") == "Married to Bob Stonefist", tip())
''',
"the other faction, offline players and mobs aren't asked": r'''
  login(nil, nil)
  see("nameplate1", { name = "Dana", guid = D, faction = "Horde" })
  hover("nameplate1")
  see("nameplate2", { name = "Dana", guid = D, connected = false })
  hover("nameplate2")
  see("nameplate3", { name = "Hogger", guid = "Creature-0-1-0-0-448-0", isPlayer = false })
  hover("nameplate3")
  hover("player")
  ok(wire() == "", wire())
''',
"with tooltips switched off nobody is asked and nothing is added": r'''
  login({ tooltips = false }, wed())
  see("party1", bob())
  ok(hover("party1") == "", tip())
  see("nameplate1", { name = "Dana", guid = D })
  hover("nameplate1")
  ok(wire() == "", wire())
''',
"questions are spaced out, and not sent while chat is locked": r'''
  login(nil, nil)
  for i = 1, 3 do
    see("nameplate" .. i, { name = "Player" .. i, guid = "Player-1-000000C" .. i })
    hover("nameplate" .. i)
  end
  ok(wire() == "WHISPER>Player1 1;ask;" .. A, "one at once")
  advance(1.5)
  ok(wire() == "WHISPER>Player2 1;ask;" .. A, "the next a moment later")
  lockdown = true
  advance(1.5)
  ok(wire() == "", "sent while locked")
  lockdown = false
  advance(1.5)
  ok(wire() == "WHISPER>Player3 1;ask;" .. A, "sent once it can")
''',
"targeting a player asks too": r'''
  login(nil, nil)
  see("target", { name = "Dana", guid = D })
  fire("PLAYER_TARGET_CHANGED")
  ok(wire() == "WHISPER>Dana 1;ask;" .. A, wire())
''',
# ---- players who log out before they're asked ----
"a queued player who went offline isn't asked, and the next one doesn't wait": r'''
  login(nil, nil)
  for i = 1, 3 do
    see("nameplate" .. i, { name = "Player" .. i, guid = "Player-1-000000C" .. i })
    hover("nameplate" .. i)
  end
  ok(wire() == "WHISPER>Player1 1;ask;" .. A, "one at once")
  units.nameplate2.connected = false
  advance(1.5)
  ok(wire() == "WHISPER>Player3 1;ask;" .. A, "the offline one is skipped: " .. wire())
  advance(10)
  ok(wire() == "", "and not asked later")
  units.nameplate2.connected = nil
  leave(); hover("nameplate2")
  ok(wire() == "WHISPER>Player2 1;ask;" .. A, "asked once they're back: " .. wire())
''',
"a queued player the game no longer shows is asked, and the game's reply is hidden": r'''
  login(nil, nil)
  see("nameplate1", { name = "Player1", guid = "Player-1-000000C1" })
  see("nameplate2", { name = "Dana", guid = D })
  hover("nameplate1"); hover("nameplate2"); leave()
  wire()
  ok(not gone("Dana"), "nothing is hidden before the whisper")
  units.nameplate2 = nil   -- logged out, or only out of sight: the game can't say which
  advance(1.5)
  ok(wire() == "WHISPER>Dana 1;ask;" .. A, "asked: " .. wire())
  ok(gone("Dana"), "the game's line is hidden")
  ok(not gone("Erin"), "someone else's isn't")
  ok(shown("You are now AFK."), "other lines are left alone")
  ok(shown("No player named Dana, sorry."), "so is a line that only looks like it")
  advance(6)
  ok(not gone("Dana"), "and Dana's is shown again a little later")
''',
"the hidden line is matched however the game spells the name": r'''
  login(nil, nil)
  see("target", { name = "Dana", realm = "Stormrage", guid = D })
  fire("PLAYER_TARGET_CHANGED")
  ok(wire() == "WHISPER>Dana-Stormrage 1;ask;" .. A, wire())
  ok(gone("Dana-Stormrage") and gone("dana"), "with or without the realm")
  advance(10)
  see("target", { name = "Elicia Antikleia", guid = "Player-1-000000C7" })
  fire("PLAYER_TARGET_CHANGED")
  ok(gone("Elicia Antikleia") and gone("Elicia"), "a Forever name with a surname")
  ok(not gone("Dana"), "Dana's time is up")
''',
"another language's line is hidden too": r'''
  ERR_CHAT_PLAYER_NOT_FOUND_S = "Kein Spieler mit dem Namen '%1$s' spielt zurzeit."
  login(nil, nil)
  see("target", { name = "Dana", guid = D })
  fire("PLAYER_TARGET_CHANGED")
  ok(not shown("Kein Spieler mit dem Namen 'Dana' spielt zurzeit."), "hidden")
  ok(shown("Kein Spieler mit dem Namen 'Erin' spielt zurzeit."), "someone else's isn't")
  ok(shown("Kein Spieler mit dem Namen Dana spielt zurzeit."), "the line has to match")
''',
"a proposal leaves the game's line alone": r'''
  login(nil, nil)
  see("target", bob())
  cmd("propose")
  ok(wire():find("WHISPER>Bob 1;propose;", 1, true), "proposed")
  ok(not gone("Bob"), "it says why nothing came back")
''',
"telling an ex who is offline doesn't show the game's line": r'''
  login(nil, wed())
  cmd("divorce")
  HitchedDialog.yes:Click()
  ok(wire():find("WHISPER>Bob 1;divorce;", 1, true), "told")
  ok(gone("Bob"), "hidden")
''',
"without the game's lookup, the mouse and the target are checked": r'''
  UnitTokenFromGUID = nil
  login(nil, nil)
  see("nameplate1", { name = "Player1", guid = "Player-1-000000C1" })
  see("nameplate2", { name = "Dana", guid = D })
  see("nameplate3", { name = "Erin", guid = "Player-1-000000C9" })
  hover("nameplate1"); hover("nameplate2"); hover("nameplate3")
  see("target", units.nameplate2)
  wire()
  units.target.connected = false   -- still targeted, now offline
  advance(1.5)
  ok(wire() == "WHISPER>Erin 1;ask;" .. A, "Dana is skipped: " .. wire())
''',
"a player whose state the game hides is asked like anyone else": r'''
  login(nil, nil)
  see("nameplate1", { name = "Player1", guid = "Player-1-000000C1" })
  see("nameplate2", { name = "Dana", guid = D })
  hover("nameplate1"); hover("nameplate2")
  wire()
  UnitTokenFromGUID = function() return SECRET end
  UnitIsConnected = function() return SECRET end
  advance(1.5)
  ok(wire() == "WHISPER>Dana 1;ask;" .. A, wire())
''',
"a line the game hides, or a game without filters, is no trouble": r'''
  ChatFrameUtil.AddMessageEventFilter = nil
  local old = {}
  ChatFrame_AddMessageEventFilter = function(event, fn) old[#old + 1] = { event, fn } end
  login(nil, nil)
  ok(#old == 1 and old[1][1] == "CHAT_MSG_SYSTEM", "the older name is used")
  local filter = old[1][2]
  see("target", { name = "Dana", guid = D }); fire("PLAYER_TARGET_CHANGED")
  ok(filter({}, "CHAT_MSG_SYSTEM", SECRET) ~= true, "a hidden line is left alone")
  ok(filter({}, "CHAT_MSG_SYSTEM", nil) ~= true and filter({}, "CHAT_MSG_SYSTEM", 5) ~= true, "so is nonsense")
  ok(filter({}, "CHAT_MSG_SYSTEM", "No player named 'Dana' is currently playing.") == true, "the real one is hidden")
  ChatFrame_AddMessageEventFilter = nil
  ERR_CHAT_PLAYER_NOT_FOUND_S = nil
  local saved, char = HitchedDB, HitchedCharDB
  wire()
  login(saved, char)
  see("target", { name = "Erin", guid = "Player-1-000000C9" }); fire("PLAYER_TARGET_CHANGED")
  ok(wire() == "WHISPER>Erin 1;ask;" .. A, "still asks without a filter: " .. wire())
  ERR_CHAT_PLAYER_NOT_FOUND_S = "No player named '%s' is currently playing."
  ChatFrame_AddMessageEventFilter = function() error("this game won't take a filter") end
  login(saved, char)
  ok(cmd(""):find("aren't married"), "a filter the game refuses doesn't stop loading: " .. cmd(""))
''',
"/hitched debug says once when it hides the game's line, and when it skips someone": r'''
  login(nil, nil)
  cmd("debug")
  see("target", { name = "Dana", guid = D }); fire("PLAYER_TARGET_CHANGED")
  out = {}
  ok(gone("Dana") and gone("Dana"), "hidden")
  local p = printed()
  local _, n = p:gsub("hid the game's line", "")
  ok(n == 1, "said once for two chat windows, twice over: " .. p)
  see("nameplate1", { name = "Erin", guid = "Player-1-000000C9" })
  hover("nameplate1")
  units.nameplate1.connected = false
  advance(1.5)
  ok(printed():find("not asked, they went offline: Erin"), "says who was skipped")
''',
"on Classic Era the tooltip script is used, and a line is added once": r'''
  TooltipDataProcessor = nil
  login(nil, wed())
  see("party1", bob())
  ok(hover("party1") == "Your spouse since 25 Nov 2026", tip())
  GameTooltip:RunHooks("OnTooltipSetUnit")   -- some tooltips are set twice
  ok(tip() == "Your spouse since 25 Nov 2026", "added twice: " .. tip())
''',
"a player the game is hiding gets no line and no error": r'''
  login(nil, wed())
  see("nameplate1", { name = SECRET, guid = SECRET })
  ok(hover("nameplate1") == "", tip())
  ok(wire() == "", wire())
''',

# ---- answering ----
"your game answers who you're married to": r'''
  login(nil, wed())
  hear("1;ask;" .. D, "WHISPER", "Dana-Whitemane")
  ok(wire() == "WHISPER>Dana-Whitemane 1;wed;" .. A .. ";" .. B .. ";Bob;" .. (clock - 86400), wire())
  login(nil, nil)
  hear("1;ask;" .. D, "WHISPER", "Dana-Whitemane")
  ok(wire() == "WHISPER>Dana-Whitemane 1;single;" .. A, wire())
''',
"the same player asking over and over is answered once in a while": r'''
  login(nil, nil)
  for i = 1, 5 do hear("1;ask;" .. D, "WHISPER", "Dana-Whitemane") end
  ok(wire() == "WHISPER>Dana-Whitemane 1;single;" .. A, wire())
''',

# ---- telling guild and group ----
"a married player tells guild and group who they're married to": r'''
  guild = true
  login(nil, wed())
  ok(wire() == "", "not at once")
  advance(8)
  local line = "1;wed;" .. A .. ";" .. B .. ";Bob;" .. (clock - 86400 - 8)
  ok(wire() == "GUILD " .. line, "guild")
  grouped = true
  fire("GROUP_ROSTER_UPDATE")
  advance(2)
  ok(wire() == "PARTY " .. line, "party")
  fire("GROUP_ROSTER_UPDATE")
  advance(30)
  ok(wire() == "", "again within a minute")
  raid = true
  advance(60)
  fire("GROUP_ROSTER_UPDATE")
  advance(2)
  ok(wire() == "RAID " .. line, "raid")
''',
"an unmarried player tells nobody anything": r'''
  guild, grouped = true, true
  login(nil, nil)
  fire("GROUP_ROSTER_UPDATE")
  advance(60)
  ok(wire() == "", wire())
''',
"your own messages coming back are ignored": r'''
  guild = true
  login(nil, wed())
  out = {}
  hear("1;wed;" .. A .. ";" .. B .. ";Bob;" .. clock, "GUILD", "Alice-Whitemane")
  hear("1;just;" .. A .. ";" .. B .. ";Bob", "GUILD", "Alice-Whitemane")
  hear("1;single;" .. A, "GUILD", "Alice-Whitemane")
  advance(5)
  ok(HitchedCharDB.spouse and printed() == "" and #emotes == 0 and #emoteLines == 0, "reacted to itself")
''',

# ---- celebrating ----
"a wedding in your guild is announced and cheered, once": r'''
  login(nil, nil)
  hear("1;just;" .. B .. ";" .. D .. ";Dana", "GUILD", "Bob-Whitemane")
  hear("1;just;" .. D .. ";" .. B .. ";Bob", "GUILD", "Dana-Whitemane")
  ok(printed() == "Hitched: Bob and Dana just got married!", "announced once")
  ok(#emotes == 0 and #emoteLines == 0, "waits a moment")
  advance(3)
  ok(list(emoteLines) == "cheers for Bob and Dana!" and #emotes == 0, list(emoteLines) .. " / " .. list(emotes))
  see("nameplate1", bob())
  ok(hover("nameplate1") == "Married to Dana", "and remembered for the tooltip: " .. tip())
''',
"with the bride or groom targeted, the cheer is a real one at them": r'''
  login(nil, nil)
  see("target", bob())
  hear("1;just;" .. B .. ";" .. D .. ";Dana", "PARTY", "Bob-Whitemane")
  advance(3)
  ok(list(emotes) == "CHEER at Bob" and #emoteLines == 0, list(emotes) .. " / " .. list(emoteLines))
''',
"with cheering switched off a wedding is only announced": r'''
  login({ cheer = false }, nil)
  hear("1;just;" .. B .. ";" .. D .. ";Dana", "GUILD", "Bob-Whitemane")
  advance(3)
  ok(printed():find("just got married"), "announced")
  ok(#emotes == 0 and #emoteLines == 0, "cheered")
''',
"on Forever a wedding is cheered with a real emote, never at a bystander": r'''
  tocVersion = 16001
  login(nil, nil)
  hear("1;just;" .. B .. ";" .. D .. ";Dana", "GUILD", "Bob-Whitemane")
  advance(3)
  ok(list(emotes) == "CHEER" and #emoteLines == 0 and #blocked == 0, list(emotes) .. " / " .. list(blocked))
  emotes = {}
  see("target", { name = "Carl", guid = "Player-1-0000000C" })
  hear("1;just;" .. "Player-1-000000E1" .. ";" .. "Player-1-000000E2" .. ";Eve", "GUILD", "Finn-Whitemane")
  advance(3)
  ok(#emotes == 0 and #blocked == 0, "cheered at Carl: " .. list(emotes))
''',
"your own wedding isn't cheered as a bystander": r'''
  login(nil, nil)
  propose()
  hear("1;yes;" .. B .. ";" .. clock)
  emotes = {}; out = {}
  hear("1;just;" .. B .. ";" .. A .. ";Alice", "GUILD", "Bob-Whitemane")
  advance(3)
  ok(#emotes == 0 and #emoteLines == 0 and printed() == "", "cheered its own wedding")
''',

# ---- divorce ----
"divorce needs a marriage, and asks first": r'''
  login(nil, nil)
  ok(cmd("divorce"):find("aren't married"), "not married")
  login(nil, wed())
  cmd("divorce")
  ok(HitchedDialog.shown and HitchedDialog.text.text == "Really divorce Bob?", "asks")
  ok(HitchedDialog.yes.text == "Divorce" and HitchedDialog.no.text == "Stay married", "buttons")
  HitchedDialog.no:Click()
  ok(HitchedCharDB.spouse and HitchedCharDB.spouse.name == "Bob", "still married")
  ok(wire() == "", wire())
''',
"a divorce ends it at once and tells them": r'''
  guild = true
  login(nil, wed())
  cmd("divorce")
  out = {}
  HitchedDialog.yes:Click()
  ok(HitchedCharDB.spouse == nil, "still married")
  ok(wire() == "WHISPER>Bob 1;divorce;" .. A .. " | GUILD 1;single;" .. A, "told them and the guild")
  ok(#emotes == 0 and #emoteLines == 0, "no emote")
  ok(printed():find("you have divorced Bob"), "says so")
  ok(story() == "Divorced Bob", story())
  ok(HitchedCharDB.notices[B], "remembers to tell them")
  hear("1;divorced;" .. B)
  ok(HitchedCharDB.notices[B] == nil, "they know")
  ok(printed():find("Bob has been told"), "says so")
  see("party1", bob())
  ok(hover("party1") == "", "no spouse line: " .. tip())
''',
"a spouse who wasn't online is told the next time you see them": r'''
  login(nil, wed())
  cmd("divorce")
  HitchedDialog.yes:Click()
  wire()
  local saved, char = HitchedDB, HitchedCharDB
  login(saved, char)   -- another day
  advance(120)
  ok(wire() == "", "not told while they're nowhere to be seen")
  see("nameplate1", bob())
  hover("nameplate1")
  ok(wire() == "WHISPER>Bob 1;divorce;" .. A, "told on sight")
  leave(); hover("nameplate1")
  ok(wire() == "", "not told over and over")
  hear("1;divorced;" .. B)
  advance(120)
  leave(); hover("nameplate1")
  ok(not wire():find("divorce"), "and not after they know")
''',
"your spouse divorcing you ends it and is answered": r'''
  guild = true
  login(nil, wed())
  advance(10); wire(); out = {}
  hear("1;divorce;" .. B)
  ok(HitchedCharDB.spouse == nil, "still married")
  ok(wire() == "WHISPER>Bob-Whitemane 1;divorced;" .. A .. " | GUILD 1;single;" .. A, "answered and told the guild")
  ok(printed():find("Bob has divorced you"), "says so")
  ok(story() == "Bob divorced you", story())
''',
"only your spouse can divorce you": r'''
  login(nil, wed())
  hear("1;divorce;" .. B, "WHISPER", "Mallory-Whitemane")
  hear("1;divorce;" .. D, "WHISPER", "Dana-Whitemane")
  hear("1;divorce;" .. B, "GUILD", "Bob-Whitemane")
  ok(HitchedCharDB.spouse and HitchedCharDB.spouse.name == "Bob", "divorced by a stranger")
''',
"a spouse who says they're single or married to someone else is no longer your spouse": r'''
  login(nil, wed())
  out = {}
  hear("1;single;" .. B, "GUILD", "Bob-Whitemane")
  ok(HitchedCharDB.spouse == nil, "still married")
  ok(printed():find("Bob is no longer married to you"), "says so")
  ok(story() == "Your marriage to Bob ended", story())
  login(nil, wed())
  hear("1;wed;" .. B .. ";" .. D .. ";Dana;" .. clock, "GUILD", "Bob-Whitemane")
  ok(HitchedCharDB.spouse == nil, "still married to a player married to someone else")
  login(nil, wed())
  hear("1;wed;" .. B .. ";" .. A .. ";Alice;" .. clock, "GUILD", "Bob-Whitemane")
  hear("1;single;" .. B, "GUILD", "Mallory-Whitemane")
  ok(HitchedCharDB.spouse and HitchedCharDB.spouse.name == "Bob", "ended by what someone else said")
''',
"someone who thinks they're married to you is told they aren't": r'''
  login(nil, nil)
  hear("1;wed;" .. D .. ";" .. A .. ";Alice;" .. clock, "GUILD", "Dana-Whitemane")
  ok(wire() == "WHISPER>Dana-Whitemane 1;divorce;" .. A, "told")
  hear("1;wed;" .. D .. ";" .. A .. ";Alice;" .. clock, "GUILD", "Dana-Whitemane")
  ok(wire() == "", "not over and over")
  ok(HitchedCharDB.spouse == nil, "married by a claim")
''',

# ---- commands ----
"/hitched says who you're married to": r'''
  login(nil, nil)
  local o = cmd("")
  ok(o:find("aren't married") and o:find("/hitched propose"), o)
  login(nil, wed())
  o = cmd("")
  ok(o:find("married to Bob since 25 Nov 2026") and o:find("Ironforge"), o)
''',
"/hitched help lists every command, and an unknown word says so": r'''
  login(nil, nil)
  local o = cmd("help")
  for _, word in ipairs({ "propose", "divorce", "settings", "debug" }) do ok(o:find("/hitched " .. word), word) end
  o = cmd("banana")
  ok(o:find("banana") and o:find("/hitched help"), o)
''',
"/hitched debug prints who you are and what is sent and heard": r'''
  login(nil, nil)
  local o = cmd("debug")
  ok(o:find("debug on") and o:find("Alice") and o:find(A, 1, true) and o:find("Classic Era"), o)
  out = {}
  hear("1;ask;" .. D, "WHISPER", "Dana-Whitemane")
  local p = printed()
  ok(p:find("heard") and p:find("Dana%-Whitemane") and p:find("sent"), p)
  ok(cmd("debug"):find("debug off"), "off again")
''',
"/hitched says so if loading failed": r'''
  login(nil, nil)
  events = {}
  assert(loadstring(ADDON_SRC, "Hitched.lua"))("Hitched")
  ok(cmd("propose"):find("didn't finish loading"), cmd("propose"))
''',

# ---- for Storied ----
"other addons can read your story and hear about changes": r'''
  login(nil, nil)
  ok(Hitched.spouse() == nil, "nobody yet")
  local changes = 0
  Hitched.watch(function() changes = changes + 1 end)
  propose()
  ok(changes == 1, "a proposal is a change")
  hear("1;yes;" .. B .. ";" .. clock)
  ok(changes == 2, "a wedding is a change")
  local name, since = Hitched.spouse()
  ok(name == "Bob" and since == clock, "spouse")
  local s = Hitched.story()
  ok(#s == 2 and s[2].what == "Married Bob" and s[2].at == clock and s[2].place == "Stormwind City", "story")
  s[2].what = "changed"
  ok(Hitched.story()[2].what == "Married Bob", "a copy is handed out")
''',
"a watcher that breaks doesn't stop the wedding": r'''
  login(nil, nil)
  Hitched.watch(function() error("oops") end)
  propose()
  hear("1;yes;" .. B .. ";" .. clock)
  ok(HitchedCharDB.spouse, "married")
''',

# ---- bad input ----
"damaged and made-up messages are ignored": r'''
  login(nil, wed())
  see("nameplate1", { name = "Dana", guid = D })
  for _, m in ipairs({ "", "1", "1;wed", "2;wed;" .. D .. ";" .. B .. ";Bob;5", "1;wed;notaguid;" .. B .. ";Bob;5",
                       "1;wed;" .. D .. ";" .. B .. ";Bob;soon", "1;wed;" .. D .. ";" .. B .. ";;5",
                       "1;wed;" .. D .. ";" .. B .. ";|TInterface\\Icons\\x:64|t;5",
                       "1;wed;" .. D .. ";" .. B .. ";" .. string.rep("x", 60) .. ";5",
                       "1;dance;" .. D, "1;yes;" .. D, "1;no;" .. D, "1;just;" .. D, ";;;;" }) do
    hear(m, "GUILD", "Dana-Whitemane")
  end
  fire("CHAT_MSG_ADDON", "Hitched", SECRET, "GUILD", "Dana-Whitemane")
  fire("CHAT_MSG_ADDON", "Hitched", "1;single;" .. D, "GUILD", SECRET)
  fire("CHAT_MSG_ADDON", "Other", "1;single;" .. B, "GUILD", "Bob-Whitemane")
  ok(hover("nameplate1") == "", tip())
  ok(HitchedCharDB.spouse and HitchedCharDB.spouse.name == "Bob", "marriage untouched")
''',
"an old saved shape is repaired, not dropped": r'''
  login("nonsense", { spouse = { guid = B, name = "Bob", since = 5 }, story = "x", notices = 7 })
  ok(HitchedDB.tooltips == true, "settings rebuilt")
  ok(HitchedCharDB.spouse.name == "Bob" and type(HitchedCharDB.story) == "table", "marriage kept")
  login(nil, { spouse = { name = "Bob" } })
  ok(HitchedCharDB.spouse == nil, "a marriage with nobody in it is dropped")
''',
"the story keeps its newest two hundred lines": r'''
  login(nil, nil)
  for i = 1, 130 do
    hear("1;propose;" .. B)
    HitchedDialog.no:Click()
    advance(700)
  end
  ok(#HitchedCharDB.story == 200, #HitchedCharDB.story)
  ok(HitchedCharDB.story[200].kind == "refused", "newest kept")
''',
}


# ---- several games at once ----
def game(name, guid, toc=11509):
    L = lua51.LuaRuntime()
    L.globals().ADDON_SRC = ADDON
    L.execute(MOCK)
    L.execute(GUARD)
    L.execute(f'units.player.name, units.player.guid, tocVersion, guild = "{name}", "{guid}", {toc}, true')
    L.execute("login(nil, nil)")
    return L


def carry(games):
    """Deliver every waiting addon message, and the answers to those, until all is quiet."""
    moved = True
    while moved:
        moved = False
        for name, L in games.items():
            while True:
                m = L.eval("nextSent()")
                if m is None:
                    break
                moved = True
                route, target, text = m.split("\t")
                for other, M in games.items():
                    if route == "WHISPER" and other.lower() != target.split("-")[0].lower():
                        continue
                    M.globals().hear(text, route, name + "-Whitemane")


A_ID, B_ID, C_ID = "Player-1-0000000A", "Player-1-0000000B", "Player-1-0000000C"


def couple(toc=11509):
    games = {"Alice": game("Alice", A_ID, toc), "Bob": game("Bob", B_ID, toc), "Carl": game("Carl", C_ID, toc)}
    games["Alice"].execute(f'see("target", {{ name = "Bob", guid = "{B_ID}" }})')
    games["Alice"].execute('cmd("propose")')
    carry(games)
    return games


def wedding(toc=11509):
    games = couple(toc)
    games["Bob"].execute("HitchedDialog.yes:Click()")
    carry(games)
    return games


def pair_yes():
    g = wedding()
    a, b, c = g["Alice"], g["Bob"], g["Carl"]
    assert a.eval("HitchedCharDB.spouse.name") == "Bob", "Alice isn't married to Bob"
    assert b.eval("HitchedCharDB.spouse.name") == "Alice", "Bob isn't married to Alice"
    assert a.eval("HitchedCharDB.spouse.guid") == B_ID and b.eval("HitchedCharDB.spouse.guid") == A_ID
    assert a.eval("HitchedCharDB.spouse.since") == b.eval("HitchedCharDB.spouse.since"), "different dates"
    assert a.eval("list(emotes)") == "KNEEL at Bob | CHEER at Bob", a.eval("list(emotes)")
    assert b.eval("list(emoteLines)") == "says yes to Alice!", b.eval("list(emoteLines)")
    c.execute("advance(3)")
    assert c.eval("list(emoteLines)") == "cheers for Bob and Alice!", c.eval("list(emoteLines)")
    for L in (a, b):
        L.execute("advance(3)")
        assert L.eval("#emoteLines + #emotes") <= 2, "the couple cheered their own wedding"


def pair_no():
    g = couple()
    a, b = g["Alice"], g["Bob"]
    b.execute("HitchedDialog.no:Click()")
    carry(g)
    assert a.eval("HitchedCharDB.spouse") is None and b.eval("HitchedCharDB.spouse") is None
    assert a.eval("list(emotes)") == "KNEEL at Bob | CRY at Bob", a.eval("list(emotes)")
    assert "Bob said no" in a.eval("printed()")


def pair_tooltips():
    g = wedding()
    a, c = g["Alice"], g["Carl"]
    # Carl walks past Bob long after the wedding, with nothing remembered.
    c.execute("login(nil, nil); guild = false")
    c.execute(f'see("nameplate1", {{ name = "Bob", guid = "{B_ID}" }}); hover("nameplate1")')
    carry(g)
    assert c.eval("tip()") == "Married to Alice", c.eval("tip()")
    a.execute(f'see("nameplate1", {{ name = "Bob", guid = "{B_ID}" }})')
    assert a.eval('hover("nameplate1")').startswith("Your spouse since"), a.eval("tip()")


def pair_divorce():
    g = wedding()
    a, b, c = g["Alice"], g["Bob"], g["Carl"]
    b.execute('cmd("divorce"); HitchedDialog.yes:Click()')
    carry(g)
    assert a.eval("HitchedCharDB.spouse") is None and b.eval("HitchedCharDB.spouse") is None
    assert "Bob has divorced you" in a.eval("printed()")
    assert "Alice has been told" in b.eval("printed()")
    assert b.eval("next(HitchedCharDB.notices)") is None, "Bob still thinks Alice doesn't know"
    c.execute(f'see("nameplate1", {{ name = "Bob", guid = "{B_ID}" }})')
    assert c.eval('hover("nameplate1")') == "", "Carl still sees a marriage: " + c.eval("tip()")


def pair_divorce_offline():
    g = wedding()
    a, b = g["Alice"], g["Bob"]
    b.execute('cmd("divorce"); HitchedDialog.yes:Click()')
    b.execute("sent = {}")   # Alice is offline: nothing arrives
    assert a.eval("HitchedCharDB.spouse.name") == "Bob"
    # Later Alice logs in and tells her guild she is married to Bob. Bob's game puts her right.
    a.execute("advance(10); fire('GROUP_ROSTER_UPDATE')")
    b.execute("advance(120)")
    a.execute("sent = {}; advance(120); grouped = true; fire('GROUP_ROSTER_UPDATE'); advance(3)")
    carry(g)
    assert a.eval("HitchedCharDB.spouse") is None, "Alice never learned of the divorce"
    assert b.eval("next(HitchedCharDB.notices)") is None, "Bob still thinks Alice doesn't know"


def pair_lost_yes():
    g = couple()
    a, b = g["Alice"], g["Bob"]
    b.execute("HitchedDialog.yes:Click(); sent = {}")   # the yes never arrives
    assert a.eval("HitchedCharDB.spouse") is None
    a.execute("advance(100)")
    a.execute(f'see("nameplate1", {{ name = "Bob", guid = "{B_ID}" }}); hover("nameplate1")')
    carry(g)
    assert a.eval("HitchedCharDB.spouse and HitchedCharDB.spouse.name") == "Bob", "Alice never learned of the yes"
    assert b.eval("HitchedCharDB.spouse.name") == "Alice"


def pair_forever():
    g = wedding(16001)
    a, b = g["Alice"], g["Bob"]
    assert a.eval("HitchedCharDB.spouse.name") == "Bob" and b.eval("HitchedCharDB.spouse.name") == "Alice"
    assert b.eval("list(emoteLines)") == "says yes to Alice!" and b.eval("#blocked") == 0


PAIRS = {
    "two games: a proposal accepted marries both, and a guildmate cheers": pair_yes,
    "two games: a proposal turned down": pair_no,
    "three games: a stranger and the spouse see it on the tooltip": pair_tooltips,
    "three games: a divorce reaches the spouse and the tooltips": pair_divorce,
    "two games: a spouse who was offline learns of the divorce later": pair_divorce_offline,
    "two games: a yes that got lost is found on the next meeting": pair_lost_yes,
    "two games on Forever: a proposal accepted": pair_forever,
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
for name, body in PAIRS.items():
    try:
        body()
        print("PASS", name)
    except Exception as e:
        failed += 1
        print("FAIL", name, "->", (str(e) or type(e).__name__).splitlines()[0])
print("failed:", failed)
sys.exit(1 if failed else 0)
