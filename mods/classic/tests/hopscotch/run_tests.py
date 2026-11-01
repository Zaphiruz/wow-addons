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
           falling = false, swimming = false, dead = false, taxi = false }
function UnitName(u) if u == "player" then return player.name end end
function GetRealmName() return player.realm end
function UnitClass(u) if u == "player" then return player.class:sub(1, 1) .. player.class:sub(2):lower(), player.class end end
function IsFalling() return player.falling end
function IsSwimming() return player.swimming end
function UnitIsDeadOrGhost(u) return player.dead end
function UnitOnTaxi(u) return player.taxi end
now = 100
function GetTime() return now end

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
  assert(loadstring(ADDON_SRC, "Hopscotch.lua"))("Hopscotch")
  fire("ADDON_LOADED", "Hopscotch")
  fire("PLAYER_LOGIN")
end
function cmd(s) out = {}; SlashCmdList.HOPSCOTCH(s); return table.concat(out, "\n") end
function ok(c, m) if not c then error("FAIL: " .. m, 2) end end
function mine() return HopscotchDB.chars["Zaphiruz-Whitemane"] end
function win() return HopscotchWindow end
function shownRows()
  local t = {}
  for _, r in ipairs(win().rows) do if r:IsShown() then t[#t+1] = r end end
  return t
end
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

# ---- commands ----
"/hop help and unknown words": r'''
  login(nil)
  local o = cmd("help")
  ok(o:find("/hop lock") and o:find("/hop hide"), o)
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
