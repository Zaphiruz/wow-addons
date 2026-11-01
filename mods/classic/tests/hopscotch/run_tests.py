"""Runs Hopscotch.lua against a small fake WoW API. Usage: python run_tests.py path/to/Hopscotch.lua"""
import pathlib
import sys
from lupa import lua51

ADDON = open(sys.argv[1], encoding="utf-8").read()
GUARD = (pathlib.Path(__file__).parent.parent / "guard_globals.lua").read_text(encoding="utf-8")

MOCK = r'''
out, events = {}, {}
function print(...) local t = {} for i = 1, select("#", ...) do t[#t+1] = tostring(select(i, ...)) end out[#out+1] = table.concat(t, " ") end
format, tinsert, tremove, wipe = string.format, table.insert, table.remove, function(t) for k in pairs(t) do t[k] = nil end return t end
function strtrim(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end
SlashCmdList = {}
UISpecialFrames = {}
StaticPopupDialogs = {}
RAID_CLASS_COLORS = { PRIEST = { r = 1, g = 1, b = 1 }, MAGE = { r = 0.4, g = 0.8, b = 0.9 } }

-- The player, as the movement code sees them.
player = { name = "Zaphiruz", realm = "Whitemane", class = "PRIEST",
           falling = false, swimming = false, dead = false, taxi = false,
           zone = "Elwynn Forest", instance = "none" }
function GetRealZoneText() return player.zone end
function IsInInstance() return player.instance ~= "none", player.instance end
-- Walk (or port) into another zone.
function goTo(zone, instance)
  player.zone, player.instance = zone, instance or "none"
  fire("ZONE_CHANGED_NEW_AREA")
end
function UnitName(u) if u == "player" then return player.name end end
function GetRealmName() return player.realm end
function UnitClass(u) if u == "player" then return player.class:sub(1, 1) .. player.class:sub(2):lower(), player.class end end
function IsFalling() return player.falling end
function IsSwimming() return player.swimming end
function UnitIsDeadOrGhost(u) return player.dead end
function UnitOnTaxi(u) return player.taxi end
now = 100
function GetTime() return now end
function time() return 1700000000 + math.floor(now) end

-- Timers run when the test moves the clock on with advance().
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

-- Guild, group and addon messages.
guild = true
group = {}          -- names of other group members
raid = false
sent = {}           -- addon messages this client sent
prefixes = {}
C_ChatInfo = {
  RegisterAddonMessagePrefix = function(p) prefixes[p] = true; return true end,
  SendAddonMessage = function(prefix, text, channel, target)
    assert(prefixes[prefix], "prefix not registered: " .. tostring(prefix))
    assert(#text <= 255, "message too long")
    table.insert(sent, { prefix = prefix, text = text, channel = channel, target = target })
  end,
}
function IsInGuild() return guild end
function IsInGroup() return #group > 0 end
function IsInRaid() return raid and #group > 0 end
function GetNumGroupMembers() return #group > 0 and #group + 1 or 0 end
local function inGroup(name) for _, n in ipairs(group) do if n == name then return true end end return false end
function UnitInParty(name) return not raid and inGroup(name) end
function UnitInRaid(name) if raid and inGroup(name) then return 1 end end
function Ambiguate(name, how) return (name:gsub("%-.*$", "")) end
-- Another player's Hopscotch sends us a message.
function hear(sender, text, channel)
  fire("CHAT_MSG_ADDON", "Hopscotch", text, channel, sender, sender)
end
function sentTo(channel, target)
  local t = {}
  for _, m in ipairs(sent) do
    if m.channel == channel and (target == nil or m.target == target) then t[#t+1] = m.text end
  end
  return t
end

-- The jump key binding calls these two.
function JumpOrAscendStart() end
function AscendStop() end
function hooksecurefunc(name, fn)
  local orig = _G[name]
  if type(orig) ~= "function" then error("hooksecurefunc(): " .. tostring(name) .. " is not a function") end
  _G[name] = function(...) orig(...) fn(...) end
end

-- UI widgets: the methods tests look at are real, anything else is a no-op.
local noop = function() end
local widgetMT = { __index = function() return noop end }
function widget(kind, name, parent)
  local w = setmetatable({ kind = kind, name = name, parent = parent, scripts = {}, shown = true,
                           enabled = true, text = "", points = {}, moving = false, checked = false }, widgetMT)
  function w:SetScript(s, fn) self.scripts[s] = fn end
  function w:GetScript(s) return self.scripts[s] end
  function w:SetText(t) self.text = t == nil and "" or tostring(t) end
  function w:GetText() return self.text end
  function w:GetStringWidth() return #self.text * 6 end
  function w:Show() self.shown = true; if self.scripts.OnShow then self.scripts.OnShow(self) end end
  function w:Hide() self.shown = false; if self.scripts.OnHide then self.scripts.OnHide(self) end end
  function w:SetShown(v) if v then self:Show() else self:Hide() end end
  function w:IsShown() return self.shown end
  function w:SetEnabled(v) self.enabled = not not v end
  function w:IsEnabled() return self.enabled end
  function w:GetParent() return self.parent end
  function w:CreateFontString(n) return widget("FontString", n, self) end
  function w:CreateTexture(n) return widget("Texture", n, self) end
  function w:SetTextColor(r, g, b) self.color = { r, g, b } end
  function w:SetChecked(v) self.checked = not not v end
  function w:GetChecked() return self.checked end
  function w:RegisterEvent(e) events[e] = self end
  function w:ClearAllPoints() self.points = {} end
  function w:SetPoint(p, rel, rp, x, y) table.insert(self.points, { p, rel, rp, x, y }) end
  function w:GetPoint(i) local p = self.points[i or 1]; if p then return p[1], p[2], p[3], p[4], p[5] end end
  function w:StartMoving() self.moving = true end
  function w:StopMovingOrSizing() self.moving = false end
  function w:Click()
    if not self.enabled then return end
    if self.kind == "CheckButton" then self.checked = not self.checked end
    if self.scripts.OnClick then self.scripts.OnClick(self, "LeftButton") end
  end
  -- Drag with the mouse to a new spot, as the player would.
  function w:Drag(point, x, y)
    if self.scripts.OnDragStart then self.scripts.OnDragStart(self, "LeftButton") end
    if self.moving then self:ClearAllPoints(); self:SetPoint(point, UIParent, point, x, y) end
    if self.scripts.OnDragStop then self.scripts.OnDragStop(self) end
  end
  return w
end
UIParent = widget("Frame", "UIParent")
GameTooltip = widget("GameTooltip", "GameTooltip")
GameTooltip.lines = {}
function GameTooltip:SetText(t) self.lines = { t } end
function GameTooltip:AddLine(t) table.insert(self.lines, t) end
function tooltip() return table.concat(GameTooltip.lines, "\n") end
function CreateFrame(kind, name, parent, template)
  local w = widget(kind, name, parent)
  if template and template:find("BasicFrameTemplate") then
    w.TitleText = widget("FontString", nil, w)
    w.CloseButton = widget("Button", nil, w)
  end
  if name then _G[name] = w end
  return w
end
function StaticPopup_Show(which, a1, a2, data)
  local info = StaticPopupDialogs[which]
  assert(info, "no popup " .. which)
  popup = { which = which, data = data, text = format(info.text, a1 or "", a2 or "") }
  return popup
end
-- Press a popup button: 1 = accept, 2 = cancel.
function press(d, index)
  local info = StaticPopupDialogs[d.which]
  if index == 1 and info.OnAccept then info.OnAccept(d, d.data, d.data2) end
  popup = nil
end

-- Game loop helpers.
function tick(dt)
  dt = dt or 0.05
  now = now + dt
  local f = events.PLAYER_LOGIN
  if f and f.scripts.OnUpdate then f.scripts.OnUpdate(f, dt) end
end
-- A normal hop: press jump, leave the ground, land, let go.
function hop()
  JumpOrAscendStart(); tick()
  player.falling = true; tick(); tick()
  player.falling = false; tick()
  AscendStop(); tick()
end

function fire(e, ...) local f = events[e]; if f then f.scripts.OnEvent(f, e, ...) end end
function login(saved)
  HopscotchDB = saved
  events = {}
  timers = {}  -- a reload stops the old session's timers
  assert(loadstring(ADDON_SRC, "Hopscotch.lua"))("Hopscotch")
  fire("ADDON_LOADED", "Hopscotch")
  fire("PLAYER_LOGIN")
end
function cmd(s) out = {}; SlashCmdList.HOPSCOTCH(s); return table.concat(out, "\n") end
function ok(c, m) if not c then error("FAIL: " .. m, 2) end end
function mine() return HopscotchDB.chars["Zaphiruz-Whitemane"] end
function win() return HopscotchWindow end
function shownRows(list)
  local t = {}
  for _, r in ipairs(list or win().rows) do if r:IsShown() then t[#t+1] = r end end
  return t
end
function playerRows() return shownRows(win().playerRows) end
function placesTab() if not (win() and win():IsShown()) then cmd("") end; win().tabs.places:Click() end
function where() return HopscotchCounter.where:IsShown() and HopscotchCounter.where:GetText() or nil end
function hops(n) for i = 1, n do hop() end end
function playersTab() if not (win() and win():IsShown()) then cmd("") end; win().tabs.players:Click() end
'''

SCENARIOS = {
# ---- counting ----
"first login starts this character at zero": r'''
  login(nil)
  ok(mine() and mine().jumps == 0, "entry made")
  ok(mine().name == "Zaphiruz" and mine().realm == "Whitemane" and mine().class == "PRIEST", "who")
  ok(HopscotchCounter:IsShown(), "counter shown")
  ok(HopscotchCounter.text:GetText():find("0$"), HopscotchCounter.text:GetText())
''',
"a hop off the ground counts once": r'''
  login(nil)
  hop()
  ok(mine().jumps == 1, "got " .. mine().jumps)
  ok(HopscotchCounter.text:GetText():find("1$"), "counter updates: " .. HopscotchCounter.text:GetText())
  hop(); hop()
  ok(mine().jumps == 3, "got " .. mine().jumps)
''',
"pressing again in the air does not count": r'''
  login(nil)
  JumpOrAscendStart(); tick(); player.falling = true; tick()
  AscendStop(); tick()
  JumpOrAscendStart(); tick(); AscendStop(); tick()
  JumpOrAscendStart(); tick(); AscendStop(); tick()
  player.falling = false; tick(); tick(); tick(); tick(); tick(); tick(); tick(); tick()
  ok(mine().jumps == 1, "only the first: got " .. mine().jumps)
''',
"holding jump to bunny-hop counts every landing and jump": r'''
  login(nil)
  JumpOrAscendStart(); tick()
  for i = 1, 4 do
    player.falling = true; tick(); tick(); tick()
    player.falling = false; tick()
  end
  AscendStop(); tick()
  ok(mine().jumps == 4, "got " .. mine().jumps)
''',
"walking off a ledge is not a jump": r'''
  login(nil)
  hop()
  for i = 1, 40 do tick() end
  player.falling = true; tick(); tick(); player.falling = false; tick()
  ok(mine().jumps == 1, "got " .. mine().jumps)
''',
"a press that never leaves the ground does not count": r'''
  login(nil)
  JumpOrAscendStart(); for i = 1, 10 do tick() end
  AscendStop(); tick()
  for i = 1, 20 do tick() end
  player.falling = true; tick(); player.falling = false; tick()
  ok(mine().jumps == 0, "rooted press then a fall: got " .. mine().jumps)
''',
"a lost key release can't make ledges count": r'''
  login(nil)
  JumpOrAscendStart(); tick(); player.falling = true; tick(); player.falling = false; tick()
  -- no AscendStop: the release went somewhere else
  for i = 1, 30 do tick() end
  player.falling = true; tick(); player.falling = false; tick()
  ok(mine().jumps == 1, "got " .. mine().jumps)
''',
"swimming up does not count": r'''
  login(nil)
  player.swimming = true
  JumpOrAscendStart(); tick(); player.falling = true; tick(); player.falling = false; AscendStop(); tick()
  ok(mine().jumps == 0, "got " .. mine().jumps)
''',
"dead, ghost and flight paths do not count": r'''
  login(nil)
  player.dead = true; hop(); player.dead = false
  player.taxi = true; hop(); player.taxi = false
  ok(mine().jumps == 0, "got " .. mine().jumps)
  hop(); ok(mine().jumps == 1, "alive again counts")
''',
"jumps carry over between sessions": r'''
  login({ chars = { ["Zaphiruz-Whitemane"] = { name = "Zaphiruz", realm = "Whitemane", class = "PRIEST", jumps = 41 } } })
  hop()
  ok(mine().jumps == 42, "got " .. mine().jumps)
''',
"big numbers get commas": r'''
  login({ chars = { ["Zaphiruz-Whitemane"] = { name = "Zaphiruz", realm = "Whitemane", class = "PRIEST", jumps = 1234566 } } })
  hop()
  ok(HopscotchCounter.text:GetText():find("1,234,567$"), HopscotchCounter.text:GetText())
''',
"no jump hook in this game version: loads, says so, counts nothing": r'''
  JumpOrAscendStart = nil
  login(nil)
  ok(table.concat(out, "\n"):find("can't see jumps"), table.concat(out, "\n"))
  ok(mine().jumps == 0, "nothing counted")
''',

# ---- counter ----
"counter can be dragged and remembers where": r'''
  login(nil)
  HopscotchCounter:Drag("TOPLEFT", 120, -300)
  local c = HopscotchDB.counter
  ok(c.point == "TOPLEFT" and c.x == 120 and c.y == -300, "saved")
  login(HopscotchDB)
  local p, _, rp, x, y = HopscotchCounter:GetPoint(1)
  ok(p == "TOPLEFT" and rp == "TOPLEFT" and x == 120 and y == -300, "restored")
''',
"locked counter can't be dragged": r'''
  login(nil)
  local p0, _, _, x0, y0 = HopscotchCounter:GetPoint(1)
  cmd("lock")
  HopscotchCounter:Drag("TOPLEFT", 5, -5)
  local p, _, _, x, y = HopscotchCounter:GetPoint(1)
  ok(p == p0 and x == x0 and y == y0, "didn't move")
  cmd("unlock")
  HopscotchCounter:Drag("TOPLEFT", 5, -5)
  ok(HopscotchDB.counter.x == 5, "moves once unlocked")
''',
"clicking the counter opens and closes the window": r'''
  login(nil)
  ok(not (win() and win():IsShown()), "starts closed")
  HopscotchCounter:Click()
  ok(win():IsShown(), "opened")
  HopscotchCounter:Click()
  ok(not win():IsShown(), "closed")
''',
"hide and show the counter, remembered": r'''
  login(nil)
  cmd("hide")
  ok(not HopscotchCounter:IsShown(), "hidden")
  login(HopscotchDB)
  ok(not HopscotchCounter:IsShown(), "still hidden after reload")
  cmd("")
  ok(win():IsShown(), "/hop still opens the window")
  cmd("show")
  ok(HopscotchCounter:IsShown(), "shown")
''',

# ---- window ----
"window lists every character, most jumps first, with the total": r'''
  login({ chars = {
    ["Bankalt-Whitemane"] = { name = "Bankalt", realm = "Whitemane", class = "MAGE", jumps = 1904 },
    ["Lowbie-Doomhowl"] = { name = "Lowbie", realm = "Doomhowl", class = "MAGE", jumps = 377 },
    ["Zaphiruz-Whitemane"] = { name = "Zaphiruz", realm = "Whitemane", class = "PRIEST", jumps = 4217 },
  } })
  hop()
  cmd("")
  local rows = shownRows()
  ok(#rows == 3, "3 rows, got " .. #rows)
  ok(rows[1].name:GetText():find("Zaphiruz") and rows[1].name:GetText():find("you"), "me first and marked: " .. rows[1].name:GetText())
  ok(rows[1].jumps:GetText() == "4,218", rows[1].jumps:GetText())
  ok(rows[2].name:GetText():find("Bankalt") and rows[2].name:GetText():find("Whitemane"), rows[2].name:GetText())
  ok(rows[3].name:GetText():find("Lowbie") and rows[3].jumps:GetText() == "377", "lowbie last")
  ok(rows[2].name.color[1] == 0.4, "class colour")
  ok(win().total:GetText() == "6,499", "total " .. win().total:GetText())
''',
"window follows new jumps while open": r'''
  login(nil); cmd("")
  hop(); hop()
  ok(shownRows()[1].jumps:GetText() == "2", "row")
  ok(win().total:GetText() == "2", "total")
''',
"remove another character after confirming": r'''
  login({ chars = {
    ["Bankalt-Whitemane"] = { name = "Bankalt", realm = "Whitemane", class = "MAGE", jumps = 10 },
    ["Zaphiruz-Whitemane"] = { name = "Zaphiruz", realm = "Whitemane", class = "PRIEST", jumps = 5 },
  } })
  cmd("")
  local rows = shownRows()
  ok(not rows[2].remove:IsShown(), "can't remove yourself")
  ok(rows[1].remove:IsShown(), "can remove others")
  rows[1].remove:Click()
  ok(popup and popup.text:find("Bankalt") and popup.text:find("10"), "asks: " .. (popup and popup.text or "none"))
  press(popup, 2)
  ok(HopscotchDB.chars["Bankalt-Whitemane"], "cancel keeps")
  shownRows()[1].remove:Click(); press(popup, 1)
  ok(not HopscotchDB.chars["Bankalt-Whitemane"], "removed")
  ok(#shownRows() == 1 and win().total:GetText() == "5", "list and total update")
''',
"window checkboxes lock and hide the counter": r'''
  login(nil); cmd("")
  ok(not win().lockBox:GetChecked() and win().showBox:GetChecked(), "start state")
  win().lockBox:Click()
  ok(HopscotchDB.counter.locked, "locked")
  win().showBox:Click()
  ok(not HopscotchCounter:IsShown() and HopscotchDB.counter.hidden, "hidden")
  cmd("show")
  ok(win().showBox:GetChecked(), "checkbox follows the command")
''',
"window closes with escape": r'''
  login(nil); cmd("")
  local found
  for _, n in ipairs(UISpecialFrames) do if n == "HopscotchWindow" then found = true end end
  ok(found, "in UISpecialFrames")
''',

# ---- sharing with other players ----
"login tells the guild and asks for theirs, after a short wait": r'''
  login({ chars = { ["Zaphiruz-Whitemane"] = { name = "Zaphiruz", realm = "Whitemane", class = "PRIEST", jumps = 40 },
                    ["Bankalt-Whitemane"] = { name = "Bankalt", realm = "Whitemane", class = "MAGE", jumps = 2 } } })
  ok(prefixes.Hopscotch, "prefix registered")
  ok(#sent == 0, "nothing straight away")
  advance(15)
  local g = sentTo("GUILD")
  ok(#g == 1 and g[1] == "1:SQ:40:42", "guild got " .. table.concat(g, ","))
''',
"not in a guild or group: sends nothing": r'''
  guild = false
  login(nil); advance(15)
  ok(#sent == 0, "sent " .. #sent)
''',
"login while grouped tells the group too": r'''
  group = { "Mirelle" }
  login(nil); advance(15)
  ok(#sentTo("PARTY") == 1 and sentTo("PARTY")[1] == "1:SQ:0:0", "party")
''',
"joining a group or raid tells it, once": r'''
  login(nil); advance(15); sent = {}
  group = { "Mirelle" }; fire("GROUP_ROSTER_UPDATE")
  ok(#sentTo("PARTY") == 1, "party told")
  fire("GROUP_ROSTER_UPDATE")
  ok(#sentTo("PARTY") == 1, "no repeat for a roster refresh")
  advance(20); raid = true; group = { "Mirelle", "Tobbin" }; fire("GROUP_ROSTER_UPDATE")
  ok(#sentTo("RAID") == 1 and sentTo("RAID")[1]:find("^1:SQ:"), "raid told")
''',
"a request gets an answer by whisper": r'''
  login({ chars = { ["Zaphiruz-Whitemane"] = { name = "Zaphiruz", realm = "Whitemane", class = "PRIEST", jumps = 7 } } })
  advance(15); sent = {}
  hear("Grimbolt-Whitemane", "1:SQ:9102:21540", "GUILD")
  local w = sentTo("WHISPER", "Grimbolt-Whitemane")
  ok(#w == 1 and w[1] == "1:S:7:7", "whispered back: " .. table.concat(w, ","))
  ok(#sentTo("GUILD") == 0, "guild not flooded")
  hear("Grimbolt-Whitemane", "1:Q", "WHISPER")
  ok(#sentTo("WHISPER") == 1, "no second answer straight away")
''',
"numbers we hear are remembered and listed": r'''
  login({ chars = { ["Zaphiruz-Whitemane"] = { name = "Zaphiruz", realm = "Whitemane", class = "PRIEST", jumps = 4218 },
                    ["Bankalt-Whitemane"] = { name = "Bankalt", realm = "Whitemane", class = "MAGE", jumps = 2281 } } })
  hear("Grimbolt-Whitemane", "1:S:9102:21540", "GUILD")
  hear("Mirelle-Whitemane", "1:S:2977:3310", "PARTY")
  local p = HopscotchDB.players["Grimbolt-Whitemane"]
  ok(p and p.name == "Grimbolt" and p.charJumps == 9102 and p.total == 21540, "stored")
  playersTab()
  local rows = playerRows()
  ok(#rows == 3, "3 rows with you, got " .. #rows)
  ok(rows[1].name:GetText():find("Grimbolt") and rows[1].name:GetText():find("guild"), rows[1].name:GetText())
  ok(rows[1].charJumps:GetText() == "9,102" and rows[1].total:GetText() == "21,540", "numbers")
  ok(rows[2].name:GetText():find("Zaphiruz") and rows[2].name:GetText():find("you"), "you second: " .. rows[2].name:GetText())
  ok(rows[2].total:GetText() == "6,499", "your total " .. rows[2].total:GetText())
  ok(rows[3].name:GetText():find("Mirelle") and rows[3].name:GetText():find("group"), "group third")
  ok(not win().rows[1]:IsShown() or not win().mineView:IsShown(), "my characters view hidden")
''',
"list shows how long ago we heard": r'''
  login(nil)
  hear("Tobbin-Whitemane", "1:S:1045:1045", "GUILD")
  advance(3 * 86400)
  playersTab()
  ok(playerRows()[1].name:GetText():find("3 days ago"), playerRows()[1].name:GetText())
  hear("Tobbin-Whitemane", "1:S:1046:1046", "GUILD")
  ok(playerRows()[1].name:GetText():find("just now"), "refreshes: " .. playerRows()[1].name:GetText())
''',
"guild and group filters": r'''
  login(nil)
  hear("Grimbolt-Whitemane", "1:S:10:10", "GUILD")
  hear("Mirelle-Whitemane", "1:S:20:20", "PARTY")
  hear("Stranger-Whitemane", "1:S:30:30", "WHISPER")
  group = { "Mirelle" }
  playersTab()
  ok(#playerRows() == 4, "all: " .. #playerRows())
  win().filters.guild:Click()
  local rows = playerRows()
  ok(#rows == 2 and rows[1].name:GetText():find("Grimbolt"), "guild + you")
  win().filters.group:Click()
  rows = playerRows()
  ok(#rows == 2 and rows[1].name:GetText():find("Mirelle"), "group + you")
  group = {}; fire("GROUP_ROSTER_UPDATE")
  ok(#playerRows() == 1, "left the group")
''',
"bad or foreign messages are ignored": r'''
  login(nil)
  hear("A-Whitemane", "1:S:abc:5", "GUILD")
  hear("B-Whitemane", "1:S:10:5", "GUILD")          -- character can't beat the account
  hear("C-Whitemane", "1:S:-1:5", "GUILD")
  hear("D-Whitemane", "2:S:1:1", "GUILD")           -- a future version
  hear("E-Whitemane", "1:S:1:99999999999", "GUILD")
  fire("CHAT_MSG_ADDON", "OtherAddon", "1:S:1:1", "GUILD", "F-Whitemane")
  local n = 0 for _ in pairs(HopscotchDB.players) do n = n + 1 end
  ok(n == 0, "stored " .. n)
''',
"our own messages are ignored": r'''
  login(nil); advance(15); sent = {}
  hear("Zaphiruz-Whitemane", "1:SQ:0:0", "GUILD")
  ok(next(HopscotchDB.players) == nil and #sent == 0, "ignored")
''',
"changed numbers are sent every minute, unchanged ones aren't": r'''
  login(nil); advance(15); sent = {}
  advance(61)
  ok(#sent == 0, "nothing new to send")
  hop(); hop()
  advance(61)
  local g = sentTo("GUILD")
  ok(#g == 1 and g[1] == "1:S:2:2", "update: " .. table.concat(g, ","))
''',
"sharing off: send nothing, answer nothing, still listen": r'''
  login(nil); playersTab()
  ok(win().shareBox:GetChecked(), "on by default")
  win().shareBox:Click()
  ok(HopscotchDB.share == false, "saved")
  advance(15); hop(); advance(61)
  hear("Grimbolt-Whitemane", "1:SQ:9:9", "GUILD")
  ok(#sent == 0, "sent " .. #sent)
  ok(HopscotchDB.players["Grimbolt-Whitemane"], "still listened")
''',
"players not heard from in 30 days are forgotten": r'''
  local old = time() - 31 * 86400
  login({ players = { ["Gone-Whitemane"] = { name = "Gone", charJumps = 1, total = 1, seen = old, guild = old },
                      ["Here-Whitemane"] = { name = "Here", charJumps = 1, total = 1, seen = time(), guild = time() } } })
  ok(not HopscotchDB.players["Gone-Whitemane"] and HopscotchDB.players["Here-Whitemane"], "pruned")
''',
"/hop compare asks one player and prints the answer": r'''
  login(nil)
  cmd("compare Grimbolt")
  local w = sentTo("WHISPER", "Grimbolt")
  ok(#w == 1 and w[1] == "1:Q", "asked")
  out = {}
  hear("Grimbolt-Whitemane", "1:S:9102:21540", "WHISPER")
  local o = table.concat(out, "\n")
  ok(o:find("Grimbolt") and o:find("9,102") and o:find("21,540"), o)
  ok(HopscotchDB.players["Grimbolt-Whitemane"].whisper, "listed as whisper")
  out = {}; advance(10)
  ok(#out == 0, "no timeout message after an answer")
''',
"/hop compare with no answer says so": r'''
  login(nil)
  cmd("compare nobody")
  out = {}; advance(6)
  ok(table.concat(out, "\n"):find("no answer from nobody"), table.concat(out, "\n"))
  local o = cmd("compare")
  ok(o:find("/hop compare <name>"), o)
''',

# ---- zones and dungeon runs ----
"jumps are counted per zone for each character": r'''
  login(nil)
  hops(3); goTo("Stormwind City"); hops(2)
  ok(mine().zones["Elwynn Forest"] == 3 and mine().zones["Stormwind City"] == 2, "zones")
  ok(mine().jumps == 5, "total still counts")
''',
"counter's second line: this zone since login": r'''
  login({ chars = { ["Zaphiruz-Whitemane"] = { name = "Zaphiruz", realm = "Whitemane", class = "PRIEST", jumps = 50,
                                               zones = { ["Elwynn Forest"] = 50 } } } })
  ok(where() == "Elwynn Forest  0", "starts at 0 this session: " .. tostring(where()))
  hops(2)
  ok(where() == "Elwynn Forest  2", tostring(where()))
  goTo("Stormwind City"); hop()
  ok(where() == "Stormwind City  1", tostring(where()))
  goTo("Elwynn Forest"); hop()
  ok(where() == "Elwynn Forest  3", "coming back keeps adding: " .. tostring(where()))
  login(HopscotchDB)
  ok(where() == "Elwynn Forest  0", "new session starts again: " .. tostring(where()))
''',
"location line setting: this visit, and off": r'''
  login(nil); cmd("")
  ok(win().locationButton:GetText():find("Since login"), win().locationButton:GetText())
  win().locationButton:Click()
  ok(HopscotchDB.counter.location == "visit" and win().locationButton:GetText():find("This visit"), "visit")
  hops(2); goTo("Stormwind City"); goTo("Elwynn Forest"); hop()
  ok(where() == "Elwynn Forest  1", "resets per visit: " .. tostring(where()))
  win().locationButton:Click()
  ok(HopscotchDB.counter.location == "off" and where() == nil, "off hides the line")
  win().locationButton:Click()
  ok(HopscotchDB.counter.location == nil and where() == "Elwynn Forest  3", "back to since login: " .. tostring(where()))
''',
"a dungeon run counts from entering to leaving": r'''
  login(nil); hops(5)
  goTo("The Deadmines", "party")
  ok(where() == "The Deadmines run  0", tostring(where()))
  hops(4)
  ok(where() == "The Deadmines run  4", tostring(where()))
  advance(30 * 60)
  goTo("Westfall"); out = {}
  advance(16 * 60)
  local o = table.concat(out, "\n")
  ok(o:find("The Deadmines run: 4 jumps in 30 min"), o)
  local r = HopscotchDB.runs[1]
  ok(r and r.dungeon == "The Deadmines" and r.jumps == 4 and r.char == "Zaphiruz", "run saved")
  local d = HopscotchDB.dungeons["The Deadmines"]
  ok(d.fewest == 4 and d.most == 4 and d.runs == 1, "record")
''',
"coming back within 15 minutes continues the run": r'''
  login(nil)
  goTo("The Deadmines", "party"); hops(3)
  goTo("Westfall"); advance(10 * 60); hop()
  goTo("The Deadmines", "party"); hops(2)
  ok(where() == "The Deadmines run  5", tostring(where()))
  ok(#HopscotchDB.runs == 0, "not finished")
''',
"entering another dungeon finishes the last run": r'''
  login(nil)
  goTo("The Deadmines", "party"); hops(3)
  goTo("Westfall"); out = {}
  goTo("Wailing Caverns", "party")
  ok(table.concat(out, "\n"):find("The Deadmines run: 3 jumps"), table.concat(out, "\n"))
  ok(where() == "Wailing Caverns run  0", tostring(where()))
''',
"a reload inside a dungeon keeps the run": r'''
  login(nil)
  goTo("The Deadmines", "party"); hops(3)
  advance(60)
  login(HopscotchDB); fire("ZONE_CHANGED_NEW_AREA")
  hop()
  ok(where() == "The Deadmines run  4", tostring(where()))
''',
"a run left long ago is finished at the next login": r'''
  login(nil)
  goTo("The Deadmines", "party"); hops(2)
  goTo("Westfall")
  local saved = HopscotchDB
  now = now + 3600
  out = {}
  login(saved)
  ok(table.concat(out, "\n"):find("The Deadmines run: 2 jumps"), table.concat(out, "\n"))
  ok(#HopscotchDB.runs == 1, "saved")
''',
"battlegrounds are not runs": r'''
  login(nil)
  goTo("Warsong Gulch", "pvp"); hops(2)
  ok(where() == "Warsong Gulch  2", tostring(where()))
  goTo("Ashenvale"); advance(20 * 60)
  ok(not HopscotchDB.runs[1], "no run")
''',
"fewest and most per dungeon, last 20 runs kept": r'''
  login(nil)
  for i = 1, 22 do
    goTo("The Deadmines", "party"); hops(i % 5 + 1)
    goTo("Westfall"); advance(16 * 60)
  end
  ok(#HopscotchDB.runs == 20, "kept " .. #HopscotchDB.runs)
  local d = HopscotchDB.dungeons["The Deadmines"]
  ok(d.fewest == 1 and d.most == 5 and d.runs == 22, "fewest " .. d.fewest .. " most " .. d.most .. " runs " .. d.runs)
''',
"Places tab: zones for this character or the account, and runs": r'''
  login({ chars = {
    ["Zaphiruz-Whitemane"] = { name = "Zaphiruz", realm = "Whitemane", class = "PRIEST", jumps = 30,
                               zones = { ["Elwynn Forest"] = 10, ["Stormwind City"] = 20 } },
    ["Bankalt-Whitemane"] = { name = "Bankalt", realm = "Whitemane", class = "MAGE", jumps = 50,
                              zones = { ["Elwynn Forest"] = 50 } } },
    dungeons = { ["The Deadmines"] = { fewest = 120, most = 300, runs = 3 } },
    runs = { { dungeon = "The Deadmines", char = "Zaphiruz", ended = time() - 2 * 86400, jumps = 214, seconds = 38 * 60 } } })
  placesTab()
  local z = shownRows(win().zoneRows)
  ok(#z == 2 and z[1].name:GetText():find("Stormwind City") and z[1].jumps:GetText() == "20", "this character")
  win().scopeButtons.account:Click()
  z = shownRows(win().zoneRows)
  ok(z[1].name:GetText():find("Elwynn Forest") and z[1].jumps:GetText() == "60", "account sums: " .. z[1].jumps:GetText())
  local r = shownRows(win().runRows)
  ok(#r == 1 and r[1].name:GetText():find("The Deadmines") and r[1].name:GetText():find("Zaphiruz")
     and r[1].name:GetText():find("2 days ago"), r[1] and r[1].name:GetText() or "no run row")
  ok(r[1].info:GetText():find("214") and r[1].info:GetText():find("38 min"), r[1].info:GetText())
  ok(r[1].name:GetText():find("fewest 120") and r[1].name:GetText():find("most 300"), "record on the run")
''',

# ---- jumps per hour ----
"time online is tracked per character and per zone": r'''
  login(nil)
  advance(20 * 60)
  goTo("Stormwind City")
  advance(10 * 60)
  fire("PLAYER_LOGOUT")
  ok(math.abs(mine().seconds - 1800) <= 1, "character " .. tostring(mine().seconds))
  ok(math.abs(mine().zoneSeconds["Elwynn Forest"] - 1200) <= 1, "elwynn " .. tostring(mine().zoneSeconds["Elwynn Forest"]))
  ok(math.abs(mine().zoneSeconds["Stormwind City"] - 600) <= 1, "stormwind")
''',
"session rate on the counter tooltip": r'''
  login(nil)
  hops(10); advance(30 * 60)
  HopscotchCounter.scripts.OnEnter(HopscotchCounter)
  ok(tooltip():find("This session: 10 jumps, 20 per hour"), tooltip())
''',
"rates hide until there's enough time to mean something": r'''
  login(nil)
  hops(10); advance(60)
  HopscotchCounter.scripts.OnEnter(HopscotchCounter)
  ok(tooltip():find("This session: 10 jumps") and not tooltip():find("per hour"), tooltip())
''',
"my characters tab shows each character's rate and the account's": r'''
  login({ chars = {
    -- 1,000 jumps from before time was tracked, then 600 in the hour since
    ["Zaphiruz-Whitemane"] = { name = "Zaphiruz", realm = "Whitemane", class = "PRIEST", jumps = 1600,
                               timedJumps = 600, seconds = 3600 },
    ["Bankalt-Whitemane"] = { name = "Bankalt", realm = "Whitemane", class = "MAGE", jumps = 100,
                              timedJumps = 100, seconds = 100 },
    ["Old-Whitemane"] = { name = "Old", realm = "Whitemane", class = "MAGE", jumps = 50 } } })
  cmd("")
  local rows = shownRows()
  ok(rows[1].jumps:GetText() == "1,600" and rows[1].rate:GetText() == "600/h", "rate " .. rows[1].rate:GetText())
  ok(rows[2].rate:GetText() == "", "too little time: '" .. rows[2].rate:GetText() .. "'")
  ok(rows[3].rate:GetText() == "", "no time yet")
  ok(win().totalRate:GetText() == "681/h", "account " .. win().totalRate:GetText())
  ok(win().session:GetText():find("This session: 0 jumps"), win().session:GetText())
''',
"jumps from before time was tracked don't inflate the rate": r'''
  login({ chars = { ["Zaphiruz-Whitemane"] = { name = "Zaphiruz", realm = "Whitemane", class = "PRIEST", jumps = 5000 } } })
  hops(10); advance(30 * 60)
  cmd("")
  ok(shownRows()[1].rate:GetText() == "20/h", "rate " .. shownRows()[1].rate:GetText())
''',
"places tab shows each zone's rate": r'''
  login({ chars = { ["Zaphiruz-Whitemane"] = { name = "Zaphiruz", realm = "Whitemane", class = "PRIEST", jumps = 60,
                    zones = { ["Elwynn Forest"] = 60 }, zoneSeconds = { ["Elwynn Forest"] = 1800 } } } })
  placesTab()
  local z = shownRows(win().zoneRows)[1]
  ok(z.jumps:GetText() == "60" and z.rate:GetText() == "120/h", "zone rate " .. z.rate:GetText())
''',
"each run shows its rate": r'''
  login(nil)
  goTo("The Deadmines", "party"); hops(50); advance(30 * 60)
  goTo("Westfall"); advance(16 * 60)
  placesTab()
  local r = shownRows(win().runRows)[1]
  local rate = tonumber(r.info:GetText():match("(%d+)/h"))
  ok(r.info:GetText():find("50 jumps, 30 min") and rate and rate >= 98 and rate <= 100, r.info:GetText())
''',

# ---- commands ----
"/hop help and unknown words": r'''
  login(nil)
  local o = cmd("help")
  ok(o:find("/hop lock") and o:find("/hop hide") and o:find("/hop compare"), o)
  o = cmd("banana")
  ok(o:find("banana") and o:find("/hop help"), o)
''',
"/hopscotch works too": r'''
  login(nil)
  ok(SLASH_HOPSCOTCH1 == "/hop" and SLASH_HOPSCOTCH2 == "/hopscotch", "slash names")
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
