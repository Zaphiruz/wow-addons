"""Runs Hawker.lua against a small fake WoW API. Usage: python run_tests.py path/to/Hawker.lua"""
import sys
from lupa import lua51

ADDON = open(sys.argv[1], encoding="utf-8").read()
import pathlib
GUARD = (pathlib.Path(__file__).parent.parent / "guard_globals.lua").read_text(encoding="utf-8")

MOCK = r'''
out, said, events = {}, {}, {}
function print(...) local t = {} for i = 1, select("#", ...) do t[#t+1] = tostring(select(i, ...)) end out[#out+1] = table.concat(t, " ") end
format, tinsert, tremove, wipe = string.format, table.insert, table.remove, function(t) for k in pairs(t) do t[k] = nil end return t end
function strtrim(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end
SlashCmdList = {}
UISpecialFrames = {}
StaticPopupDialogs = {}
rolls = {}
function random(n) local r = table.remove(rolls, 1) or 1; assert(r >= 1 and r <= n, "roll out of range"); return r end
function SendChatMessage(msg, chan, lang, target)
  said[#said+1] = chan .. (target and ("(" .. target .. ")") or "") .. ": " .. msg
end
joined = { [1] = "General - Elwynn Forest", [2] = "Trade - City" }
function GetChannelName(id) if joined[id] then return id, joined[id] end return 0, nil end

-- UI widgets: the methods tests look at are real, anything else is a no-op.
local noop = function() end
local widgetMT = { __index = function() return noop end }
function widget(kind, name, parent)
  local w = setmetatable({ kind = kind, name = name, parent = parent, scripts = {}, shown = true,
                           enabled = true, text = "" }, widgetMT)
  function w:SetScript(s, fn) self.scripts[s] = fn end
  function w:GetScript(s) return self.scripts[s] end
  function w:SetText(t) self.text = t == nil and "" or tostring(t) end
  function w:GetText() return self.text end
  function w:Show() self.shown = true; if self.scripts.OnShow then self.scripts.OnShow(self) end end
  function w:Hide() self.shown = false; if self.scripts.OnHide then self.scripts.OnHide(self) end end
  function w:SetShown(v) if v then self:Show() else self:Hide() end end
  function w:IsShown() return self.shown end
  function w:SetEnabled(v) self.enabled = not not v end
  function w:Enable() self.enabled = true end
  function w:Disable() self.enabled = false end
  function w:IsEnabled() return self.enabled end
  function w:GetParent() return self.parent end
  function w:CreateFontString(n) return widget("FontString", n, self) end
  function w:CreateTexture(n) return widget("Texture", n, self) end
  function w:SetTextColor(r, g, b) self.color = { r, g, b } end
  function w:Click() if self.enabled and self.scripts.OnClick then self.scripts.OnClick(self, "LeftButton") end end
  -- Type into an edit box as the player would.
  function w:Type(t) self.text = t; if self.scripts.OnTextChanged then self.scripts.OnTextChanged(self, true) end end
  return w
end
function CreateFrame(kind, name, parent, template)
  if kind == "Frame" and not parent and not template then
    local f = { scripts = {} }
    function f:RegisterEvent(e) events[e] = self end
    function f:SetScript(s, fn) self.scripts[s] = fn end
    return f
  end
  local w = widget(kind, name, parent)
  if template and template:find("BasicFrameTemplate") then
    w.TitleText = widget("FontString", nil, w)
    w.CloseButton = widget("Button", nil, w)
  end
  if name then _G[name] = w end
  return w
end
function StaticPopup_Show(which, a1, a2, data)
  local d = widget("Frame", "StaticPopup1", nil)
  d.which, d.data, d.arg1 = which, data, a1
  d.editBox = widget("EditBox", nil, d)
  function d:GetEditBox() return self.editBox end
  local info = StaticPopupDialogs[which]
  assert(info, "no popup " .. which)
  if info.OnShow then info.OnShow(d, data) end
  popup = d
  return d
end
-- Press a popup button: 1 = accept, 2 = cancel.
function press(d, index)
  local info = StaticPopupDialogs[d.which]
  if index == 1 and info.OnAccept then
    if not info.OnAccept(d, d.data, d.data2) then d:Hide() end
  elseif index == 2 then
    if info.OnCancel then info.OnCancel(d, d.data) end
    d:Hide()
  end
  popup = nil
end
StaticPopup_OnClick = press

function load(saved, charSaved)
  HawkerDB, HawkerCharDB = saved, charSaved
  events = {}
  assert(loadstring(ADDON_SRC, "Hawker.lua"))("Hawker")
  local f = events.ADDON_LOADED
  f.scripts.OnEvent(f, "ADDON_LOADED", "Hawker")
end
function cmd(s) out = {}; SlashCmdList.HAWKER(s); return table.concat(out, "\n") end
function ok(c, m) if not c then error("FAIL: " .. m, 2) end end
function ed() return HawkerEditor end
-- Make a preset through the window, as the player would.
function makePreset(name, text)
  if not (ed() and ed():IsShown()) then cmd("edit") end
  ed().newButton:Click()
  popup.editBox:SetText(name)
  press(popup, 1)
  if text then ed().box:Type(text); ed().saveButton:Click() end
end
function pickPreset(name)
  ed().presetButton:Click()
  for _, item in ipairs(ed().menu.items) do
    if item:IsShown() and item.presetName == name then item:Click() return end
  end
  error("no preset " .. name .. " in the dropdown")
end
'''

SCENARIOS = {
# ---- lines and channels (from before presets) ----
"add, list, and say a random line": r'''
  load(nil)
  local o = cmd("add free bracer enchants to make your water taste better")
  ok(o:find("added line 1"), o)
  cmd("add struggling to kill your foes? free bracer enchants to help you out")
  cmd("add   a free buff with every free enchant  ")
  o = cmd("list")
  ok(o:find("1%. free bracer enchants to make your water taste better"), o)
  ok(o:find("3%. a free buff with every free enchant\n?") and not o:find("enchant  "), "trimmed: " .. o)
  rolls = {2}
  cmd("")
  ok(said[1] == "SAY: struggling to kill your foes? free bracer enchants to help you out", tostring(said[1]))
''',
"on Forever, chat goes through C_ChatInfo.SendChatMessage": r'''
  local classic = SendChatMessage
  SendChatMessage = nil   -- Forever has no global SendChatMessage
  C_ChatInfo = { SendChatMessage = function(msg, chan, lang, target) classic(msg, chan, lang, target) end }
  load(nil); cmd("add hello forever")
  cmd("guild")
  ok(said[1] == "GUILD: hello forever", tostring(said[1]))
''',
"Hawk() works from /run": r'''
  load(nil); cmd("add hello there")
  Hawk()
  ok(said[1] == "SAY: hello there", tostring(said[1]))
''',
"never repeats the same line twice in a row": r'''
  load(nil); cmd("add one"); cmd("add two"); cmd("add three")
  rolls = {1, 1, 2}
  Hawk(); Hawk()
  ok(said[1] == "SAY: one" and said[2] ~= "SAY: one", table.concat(said, " | "))
''',
"one line can repeat": r'''
  load(nil); cmd("add only")
  Hawk(); Hawk()
  ok(said[1] == "SAY: only" and said[2] == "SAY: only", table.concat(said, " | "))
''',
"clear removes everything": r'''
  load(nil); cmd("add one"); cmd("add two")
  local o = cmd("clear"); ok(o:find("cleared 2 lines"), o)
  o = cmd("list"); ok(o:find("no lines yet"), o)
  o = cmd(""); ok(o:find("no lines yet") and #said == 0, o)
''',
"remove one line": r'''
  load(nil); cmd("add one"); cmd("add two"); cmd("add three")
  local o = cmd("remove 2"); ok(o:find('removed line 2: two'), o)
  o = cmd("list"); ok(o:find("1%. one") and o:find("2%. three") and not o:find("two"), o)
  o = cmd("remove 9"); ok(o:find("no line 9"), o)
''',
"lines survive a reload": r'''
  load(nil); cmd("add keep me")
  load(HawkerDB, HawkerCharDB)
  local o = cmd("list"); ok(o:find("1%. keep me"), o)
''',
"rejects empty and too-long lines": r'''
  load(nil)
  local o = cmd("add"); ok(o:find("usage"), o)
  o = cmd("add " .. string.rep("x", 256)); ok(o:find("too long"), o)
  o = cmd("list"); ok(o:find("no lines yet"), o)
''',
"help lists commands": r'''
  load(nil)
  local o = cmd("help")
  ok(o:find("/hawk add") and o:find("/hawk yell") and o:find("/hawk edit") and o:find("/hawk use"), o)
''',
"unknown word says so": r'''
  load(nil); cmd("add hi")
  local o = cmd("frobnicate")
  ok(o:find("no channel or preset called frobnicate") and o:find("/hawk help") and #said == 0, o)
''',
"channel words and short forms": r'''
  load(nil); cmd("add hi")
  cmd("yell"); cmd("GUILD"); cmd("g"); cmd("p"); cmd("raid"); cmd("e"); cmd("o"); cmd("s")
  local want = { "YELL: hi", "GUILD: hi", "GUILD: hi", "PARTY: hi", "RAID: hi", "EMOTE: hi", "OFFICER: hi", "SAY: hi" }
  for i, w in ipairs(want) do ok(said[i] == w, i .. ": " .. tostring(said[i])) end
''',
"numbered channel": r'''
  load(nil); cmd("add wts enchants")
  cmd("2")
  ok(said[1] == "CHANNEL(2): wts enchants", tostring(said[1]))
  local o = cmd("5")
  ok(#said == 1 and o:find("not in channel 5"), o)
''',
"Hawk() takes a channel too": r'''
  load(nil); cmd("add hi")
  Hawk("guild"); Hawk(2); Hawk()
  ok(said[1] == "GUILD: hi" and said[2] == "CHANNEL(2): hi" and said[3] == "SAY: hi", table.concat(said, " | "))
''',
"bad channel from /run says so": r'''
  load(nil); cmd("add hi")
  out = {}; Hawk("whisper")
  ok(#said == 0 and table.concat(out):find("unknown channel"), table.concat(out))
''',

# ---- presets ----
"old saved lines become the default preset": r'''
  load({ lines = { "one", "two" } })
  ok(HawkerDB.lines == nil, "old list moved")
  local o = cmd("presets")
  ok(o:find("default") and o:find("2 lines") and o:find("active"), o)
  Hawk()
  ok(said[1] == "SAY: one", tostring(said[1]))
''',
"fresh install has an empty default preset": r'''
  load(nil)
  local o = cmd("presets"); ok(o:find("default") and o:find("0 lines"), o)
''',
"say from a named preset without switching": r'''
  load(nil); cmd("add enchant line")
  makePreset("portals", "port to Darnassus\nport to Ironforge")
  cmd("portals")
  ok(said[1] == "SAY: port to Darnassus", tostring(said[1]))
  cmd("")
  ok(said[2] == "SAY: enchant line", "active preset unchanged: " .. tostring(said[2]))
  cmd("2 portals"); cmd("PORTALS yell")
  ok(said[3] == "CHANNEL(2): port to Ironforge", tostring(said[3]))
  ok(said[4] == "YELL: port to Darnassus", tostring(said[4]))
  Hawk("guild", "portals")
  ok(said[5] == "GUILD: port to Ironforge", tostring(said[5]))
''',
"two channels or two presets is an error": r'''
  load(nil); cmd("add hi"); makePreset("lfg", "lf healer")
  local o = cmd("yell guild"); ok(#said == 0 and o:find("one channel"), o)
  o = cmd("lfg default"); ok(#said == 0 and o:find("one preset"), o)
''',
"use switches the active preset": r'''
  load(nil); cmd("add enchant line"); makePreset("portals", "port to Darnassus")
  local o = cmd("use Portals"); ok(o:find("portals is now active"), o)
  cmd(""); ok(said[1] == "SAY: port to Darnassus", tostring(said[1]))
  cmd("add port to Exodar?")
  o = cmd("list"); ok(o:find("2%. port to Exodar%?"), "add goes to the active preset: " .. o)
  o = cmd("use nope"); ok(o:find("no preset called nope"), o)
''',
"active preset is per character": r'''
  load(nil); cmd("add enchant line"); makePreset("portals", "port"); cmd("use portals")
  local account = HawkerDB
  load(account, nil)   -- a different character, same account
  cmd(""); ok(said[1] == "SAY: enchant line", "new character starts on the first preset: " .. tostring(said[1]))
''',
"no-repeat is tracked per preset": r'''
  load(nil); cmd("add a1"); cmd("add a2")
  makePreset("b", "b1\nb2")
  rolls = {1, 1, 1}
  Hawk(); Hawk(nil, "b"); Hawk()
  ok(said[1] == "SAY: a1" and said[2] == "SAY: b1" and said[3] == "SAY: a2", table.concat(said, " | "))
''',
"preset name rules": r'''
  load(nil); cmd("edit")
  for _, bad in ipairs({ "guild", "2", "add", "two words", "Default", "yell", "edit", "" }) do
    ed().newButton:Click(); popup.editBox:SetText(bad)
    out = {}; local d = popup; press(d, 1)
    ok(#HawkerDB.presets == 1 and table.concat(out) ~= "", "refused with a message: " .. bad)
  end
  makePreset("lfg-2")
  ok(cmd("presets"):find("lfg%-2"), "dashes and digits allowed")
''',

# ---- window ----
"edit window shows the active preset": r'''
  load({ lines = { "one", "two" } })
  cmd("edit")
  ok(ed():IsShown() and ed().box:GetText() == "one\ntwo", "box: " .. ed().box:GetText())
  ok(ed().presetButton:GetText():find("default"), ed().presetButton:GetText())
  ok(ed().activeLabel:IsShown() and not ed().activeButton:IsShown(), "shows it's active")
  local found = false
  for _, n in ipairs(UISpecialFrames) do if n == "HawkerEditor" then found = true end end
  ok(found, "Escape closes it")
  cmd("edit"); ok(not ed():IsShown(), "toggles closed")
''',
"save replaces the lines": r'''
  load(nil); cmd("edit")
  ed().box:Type("  first  \r\n\r\nsecond\n\n third\n")
  ed().saveButton:Click()
  local o = cmd("list")
  ok(o:find("1%. first") and o:find("2%. second") and o:find("3%. third") and not o:find("4%."), o)
  ok(ed().status:GetText():find("Saved 3 lines"), ed().status:GetText())
''',
"too-long line blocks save": r'''
  load(nil); cmd("add keep"); cmd("edit")
  ed().box:Type("ok line\n" .. string.rep("x", 300))
  ed().saveButton:Click()
  ok(ed().status:GetText():find("Line 2") and ed().status:GetText():find("300"), ed().status:GetText())
  ok(cmd("list"):find("1%. keep"), "lines unchanged")
''',
"revert restores": r'''
  load(nil); cmd("add keep"); cmd("edit")
  ed().box:Type("changed")
  ed().revertButton:Click()
  ok(ed().box:GetText() == "keep", ed().box:GetText())
''',
"switching with unsaved edits asks first": r'''
  load(nil); cmd("add a"); makePreset("b", "bee")
  pickPreset("default")
  ok(ed().box:GetText() == "a", "editing default: " .. ed().box:GetText())
  ed().box:Type("a changed")
  pickPreset("b")
  ok(popup and popup.which == "HAWKER_DISCARD", "asks")
  press(popup, 2)
  ok(ed().box:GetText() == "a changed", "cancel keeps the edits")
  pickPreset("b")
  press(popup, 1)
  ok(ed().box:GetText() == "bee", "accept switches: " .. ed().box:GetText())
  ok(cmd("list"):find("1%. a\n?") , "discarded edit was not saved")
''',
"set active from the window": r'''
  load(nil); cmd("add a"); makePreset("b", "bee")
  ok(ed().activeButton:IsShown() and not ed().activeLabel:IsShown(), "b is not active yet")
  ed().activeButton:Click()
  ok(ed().activeLabel:IsShown(), "now active")
  cmd(""); ok(said[1] == "SAY: bee", tostring(said[1]))
''',
"rename a preset": r'''
  load(nil); cmd("add a")
  cmd("edit")
  ed().renameButton:Click()
  ok(popup.editBox:GetText() == "default", "starts with old name")
  popup.editBox:SetText("enchants"); press(popup, 1)
  ok(ed().presetButton:GetText():find("enchants"), ed().presetButton:GetText())
  cmd("enchants"); ok(said[1] == "SAY: a", "new name works")
  cmd(""); ok(said[2] == "SAY: a", "still active")
  local o = cmd("default"); ok(o:find("no channel or preset called default"), o)
''',
"delete a preset": r'''
  load(nil); cmd("add a"); makePreset("b", "bee")
  ed().activeButton:Click()          -- b active
  ed().deleteButton:Click()
  ok(popup and popup.which == "HAWKER_DELETE", "asks to confirm")
  press(popup, 1)
  local o = cmd("presets")
  ok(not o:find("\n  b ") and o:find("default"), o)
  cmd(""); ok(said[1] == "SAY: a", "another preset became active")
  ok(ed().box:GetText() == "a", "window moved to a remaining preset")
  ok(not ed().deleteButton:IsEnabled(), "can't delete the last preset")
''',
"closing keeps unsaved edits": r'''
  load(nil); cmd("add a"); cmd("edit")
  ed().box:Type("half written")
  cmd("edit"); cmd("edit")
  ok(ed().box:GetText() == "half written", ed().box:GetText())
''',
"window follows /hawk add": r'''
  load(nil); cmd("add a"); cmd("edit")
  cmd("add b")
  ok(ed().box:GetText() == "a\nb", ed().box:GetText())
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
