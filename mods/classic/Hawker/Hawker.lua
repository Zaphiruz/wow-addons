-- Hawker: keep named lists (presets) of advert lines and say a random one.
--
--   /hawk                say a random line from the active preset
--   /hawk yell           same, in another channel: say yell emote guild officer
--                        party raid, short forms s y e g o p ra
--   /hawk 2              same, in numbered channel 2 (Trade in cities)
--   /hawk portals        same, from the preset called "portals"
--   /hawk 2 portals      channel and preset together, in either order
--   /hawk use portals    make "portals" the active preset
--   /hawk presets        list presets
--   /hawk edit           open the editing window
--   /hawk add <text>, list, remove <n>, clear   edit the active preset's lines
--
-- /run Hawk(channel, preset) does the same as /hawk; both arguments are optional.
--
-- Presets are shared by every character on the account (HawkerDB). Each
-- character remembers which preset is active for it (HawkerCharDB).

local ADDON = ...
local PREFIX = "|cffffcc00Hawker:|r "
local MAX_LEN = 255      -- longest chat message the game allows
local MAX_NAME_LEN = 24

local CHANNELS = {
  say = "SAY", s = "SAY",
  yell = "YELL", y = "YELL",
  emote = "EMOTE", e = "EMOTE",
  guild = "GUILD", g = "GUILD",
  officer = "OFFICER", o = "OFFICER",
  party = "PARTY", p = "PARTY",
  raid = "RAID", ra = "RAID",
}
local COMMANDS = { add = true, list = true, remove = true, clear = true, edit = true,
                   use = true, presets = true, help = true }

local db        -- HawkerDB: { presets = { { id, name, lines } }, nextId }
local char      -- HawkerCharDB: { active = preset id }
local lastIndex = {}   -- preset id -> index of the line said last
local refreshEditor = function() end  -- replaced once the window exists

local function say(fmt, ...)
  print(PREFIX .. format(fmt, ...))
end

---------------------------------------------------------------------------
-- Presets
---------------------------------------------------------------------------

local function presetById(id)
  for _, p in ipairs(db.presets) do
    if p.id == id then return p end
  end
end

local function findPreset(name)
  name = strtrim(tostring(name or "")):lower()
  for _, p in ipairs(db.presets) do
    if p.name:lower() == name then return p end
  end
end

local function activePreset()
  local p = presetById(char.active) or db.presets[1]
  char.active = p.id
  return p
end

local function newPreset(name)
  local p = { id = db.nextId, name = name, lines = {} }
  db.nextId = db.nextId + 1
  tinsert(db.presets, p)
  return p
end

-- Returns true, or false and a message for the player.
local function validName(name, exceptId)
  if name == "" then return false, "preset names can't be empty." end
  if not name:match("^[%w%-]+$") then
    return false, "preset names are one word of letters, numbers or dashes."
  end
  if not name:find("%a") then return false, "preset names need at least one letter." end
  if #name > MAX_NAME_LEN then
    return false, format("preset names can be at most %d characters.", MAX_NAME_LEN)
  end
  local lower = name:lower()
  if CHANNELS[lower] or COMMANDS[lower] then
    return false, format("%s is a channel or command word, so it can't be a preset name.", name)
  end
  local other = findPreset(name)
  if other and other.id ~= exceptId then
    return false, format("you already have a preset called %s.", other.name)
  end
  return true
end

local function plural(n, word)
  return format("%d %s%s", n, word, n == 1 and "" or "s")
end

---------------------------------------------------------------------------
-- Saying a line
---------------------------------------------------------------------------

-- Returns chat type and channel number, or nil and a message for the player.
local function resolveChannel(arg)
  if arg == nil or arg == "" then return "SAY" end
  local number = tonumber(arg)
  if number then
    if GetChannelName(number) == 0 then
      return nil, format("you're not in channel %d.", number)
    end
    return "CHANNEL", number
  end
  local chatType = CHANNELS[tostring(arg):lower()]
  if not chatType then
    return nil, format("unknown channel %s. Type /hawk help to see the channels.", tostring(arg))
  end
  return chatType
end

local function noLines(p)
  say("no lines yet in %s. Add one with /hawk add <text> or /hawk edit", p.name)
end

function Hawk(channel, preset)
  if not db then return end
  local chatType, target = resolveChannel(channel)
  if not chatType then say("%s", target) return end
  local p
  if preset ~= nil and preset ~= "" then
    p = findPreset(preset)
    if not p then say("no preset called %s.", tostring(preset)) return end
  else
    p = activePreset()
  end
  local n = #p.lines
  if n == 0 then noLines(p) return end
  local i = random(n)
  -- Don't say the same line twice in a row when there's a choice.
  if n > 1 and i == lastIndex[p.id] then
    i = i % n + 1
  end
  lastIndex[p.id] = i
  -- Forever (and modern clients) only have C_ChatInfo.SendChatMessage;
  -- Classic Era has the global.
  local send = (C_ChatInfo and C_ChatInfo.SendChatMessage) or SendChatMessage
  send(p.lines[i], chatType, nil, target)
end

---------------------------------------------------------------------------
-- Slash commands
---------------------------------------------------------------------------

local function add(text)
  local p = activePreset()
  text = strtrim(text or "")
  if text == "" then say("usage: /hawk add <text>") return end
  if #text > MAX_LEN then
    say("that line is too long: %d characters, the limit is %d.", #text, MAX_LEN)
    return
  end
  tinsert(p.lines, text)
  say("added line %d to %s.", #p.lines, p.name)
  refreshEditor()
end

local function list()
  local p = activePreset()
  if #p.lines == 0 then noLines(p) return end
  say("lines in %s:", p.name)
  for i, line in ipairs(p.lines) do
    print(format("  %d. %s", i, line))
  end
end

local function remove(arg)
  local p = activePreset()
  local i = tonumber(arg)
  if not i or not p.lines[i] then
    say("no line %s. Type /hawk list to see the numbers.", strtrim(arg or ""))
    return
  end
  local line = tremove(p.lines, i)
  lastIndex[p.id] = nil
  say("removed line %d: %s", i, line)
  refreshEditor()
end

local function clear()
  local p = activePreset()
  local n = #p.lines
  wipe(p.lines)
  lastIndex[p.id] = nil
  say("cleared %d lines from %s.", n, p.name)
  refreshEditor()
end

local function use(name)
  local p = findPreset(name)
  if not p then say("no preset called %s. Type /hawk presets to see them.", strtrim(name or "")) return end
  char.active = p.id
  say("%s is now active.", p.name)
  refreshEditor()
end

local function presets()
  local active = activePreset()
  say("presets:")
  for _, p in ipairs(db.presets) do
    print(format("  %s (%s)%s", p.name, plural(#p.lines, "line"), p == active and " - active" or ""))
  end
end

local function help()
  say("commands:")
  print("  /hawk  - say a random line from the active preset")
  print("  /hawk yell  - same, in another channel: say yell emote guild officer party raid")
  print("      short forms: s y e g o p ra")
  print("  /hawk 2  - same, in numbered channel 2 (Trade in cities)")
  print("  /hawk <preset>  - say a line from that preset, e.g. /hawk 2 portals")
  print("  /hawk use <preset>  - make a preset the active one")
  print("  /hawk presets  - list your presets")
  print("  /hawk edit  - open the window to edit presets")
  print("  /hawk add <text>  - add a line to the active preset")
  print("  /hawk list  - show the active preset's lines")
  print("  /hawk remove <number>  - remove one line")
  print("  /hawk clear  - remove all lines from the active preset")
end

-- "/hawk 2 portals": any mix of one channel and one preset.
local function sayFromWords(msg)
  local channel, preset
  for word in msg:gmatch("%S+") do
    if CHANNELS[word:lower()] or tonumber(word) then
      if channel then say("pick one channel at a time.") return end
      channel = word
    elseif findPreset(word) then
      if preset then say("pick one preset at a time.") return end
      preset = word
    else
      say("no channel or preset called %s. Type /hawk help for commands.", word)
      return
    end
  end
  Hawk(channel, preset)
end

---------------------------------------------------------------------------
-- Window (/hawk edit)
---------------------------------------------------------------------------

local editor
local editing   -- id of the preset shown in the window
local dirty = false


local function popupBox(dialog)
  return dialog.GetEditBox and dialog:GetEditBox() or dialog.editBox
end

-- Run fn now, or after the player agrees to throw away unsaved edits.
local function confirmDiscard(fn)
  if dirty then
    StaticPopup_Show("HAWKER_DISCARD", nil, nil, fn)
  else
    fn()
  end
end

-- Lines from the notepad, or nil plus the bad line's number and length.
local function parseLines(text)
  local lines, n = {}, 0
  for raw in (text .. "\n"):gmatch("(.-)\n") do
    n = n + 1
    local line = strtrim((raw:gsub("\r", "")))
    if line ~= "" then
      if #line > MAX_LEN then return nil, n, #line end
      tinsert(lines, line)
    end
  end
  return lines
end

local function setStatus(text, r, g, b)
  editor.status:SetText(text)
  editor.status:SetTextColor(r or 0.8, g or 0.8, b or 0.8)
end

local function updateHeader()
  local p = presetById(editing)
  local isActive = p == activePreset()
  editor.presetButton:SetText(p.name)
  editor.activeLabel:SetShown(isActive)
  editor.activeButton:SetShown(not isActive)
  editor.deleteButton:SetEnabled(#db.presets > 1)
end

-- Show a preset's saved lines in the notepad.
local function fill(id)
  local p = presetById(id or editing) or activePreset()
  editing = p.id
  editor.box:SetText(table.concat(p.lines, "\n"))
  dirty = false
  updateHeader()
  setStatus(format("One line per advert. %s.", plural(#p.lines, "line")))
end

local function save()
  local p = presetById(editing)
  local lines, badLine, length = parseLines(editor.box:GetText())
  if not lines then
    setStatus(format("Line %d is %d characters. The limit is %d.", badLine, length, MAX_LEN), 1, 0.3, 0.3)
    return
  end
  p.lines = lines
  lastIndex[p.id] = nil
  fill(p.id)
  setStatus(format("Saved %s.", plural(#lines, "line")), 0.4, 1, 0.4)
end

local function menuItem(i)
  local item = CreateFrame("Button", nil, editor.menu)
  item:SetSize(200, 18)
  item:SetPoint("TOPLEFT", 8, -8 - (i - 1) * 18)
  item:SetNormalFontObject("GameFontHighlightLeft")
  item:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
  item:SetScript("OnClick", function(self)
    editor.menu:Hide()
    local id = self.presetId
    if id ~= editing then confirmDiscard(function() fill(id) end) end
  end)
  return item
end

local function toggleMenu()
  local menu = editor.menu
  if menu:IsShown() then menu:Hide() return end
  local active = activePreset()
  for i, p in ipairs(db.presets) do
    local item = menu.items[i] or menuItem(i)
    menu.items[i] = item
    item.presetId, item.presetName = p.id, p.name
    item:SetText(format("%s  (%s)%s", p.name, plural(#p.lines, "line"), p == active and " - active" or ""))
    item:Show()
  end
  for i = #db.presets + 1, #menu.items do menu.items[i]:Hide() end
  menu:SetSize(216, #db.presets * 18 + 16)
  menu:Show()
end

local function button(name, text, width)
  local b = CreateFrame("Button", name, editor, "UIPanelButtonTemplate")
  b:SetSize(width, 22)
  b:SetText(text)
  return b
end

local function createEditor()
  editor = CreateFrame("Frame", "HawkerEditor", UIParent, "BasicFrameTemplateWithInset")
  editor:SetSize(540, 420)
  editor:SetPoint("CENTER")
  editor:SetFrameStrata("DIALOG")
  editor:SetClampedToScreen(true)
  editor:SetMovable(true)
  editor:EnableMouse(true)
  editor:RegisterForDrag("LeftButton")
  editor:SetScript("OnDragStart", editor.StartMoving)
  editor:SetScript("OnDragStop", editor.StopMovingOrSizing)
  editor.TitleText:SetText("Hawker")
  tinsert(UISpecialFrames, "HawkerEditor")

  -- Preset bar
  editor.presetButton = button("HawkerEditorPreset", "", 170)
  editor.presetButton:SetPoint("TOPLEFT", 12, -30)
  editor.presetButton:SetScript("OnClick", toggleMenu)

  editor.activeButton = button("HawkerEditorSetActive", "Set active", 84)
  editor.activeButton:SetPoint("LEFT", editor.presetButton, "RIGHT", 6, 0)
  editor.activeButton:SetScript("OnClick", function()
    char.active = editing
    updateHeader()
  end)
  editor.activeLabel = editor:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  editor.activeLabel:SetPoint("LEFT", editor.presetButton, "RIGHT", 10, 0)
  editor.activeLabel:SetText("Active")
  editor.activeLabel:SetTextColor(0.4, 1, 0.4)

  editor.deleteButton = button("HawkerEditorDelete", "Delete", 60)
  editor.deleteButton:SetPoint("TOPRIGHT", -12, -30)
  editor.deleteButton:SetScript("OnClick", function()
    local p = presetById(editing)
    StaticPopup_Show("HAWKER_DELETE", p.name, nil, p.id)
  end)
  editor.renameButton = button("HawkerEditorRename", "Rename", 66)
  editor.renameButton:SetPoint("RIGHT", editor.deleteButton, "LEFT", -4, 0)
  editor.renameButton:SetScript("OnClick", function()
    StaticPopup_Show("HAWKER_RENAME", presetById(editing).name, nil, editing)
  end)
  editor.newButton = button("HawkerEditorNew", "New", 54)
  editor.newButton:SetPoint("RIGHT", editor.renameButton, "LEFT", -4, 0)
  editor.newButton:SetScript("OnClick", function()
    confirmDiscard(function() StaticPopup_Show("HAWKER_NEW") end)
  end)

  local menu = CreateFrame("Frame", "HawkerEditorMenu", editor, "BackdropTemplate")
  menu:SetPoint("TOPLEFT", editor.presetButton, "BOTTOMLEFT", 0, -2)
  menu:SetFrameStrata("FULLSCREEN_DIALOG")
  if menu.SetBackdrop then
    menu:SetBackdrop({
      bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
      edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
      tile = true, tileSize = 16, edgeSize = 16,
      insets = { left = 4, right = 4, top = 4, bottom = 4 },
    })
    menu:SetBackdropColor(0, 0, 0, 0.95)
  end
  menu.items = {}
  menu:Hide()
  editor.menu = menu

  -- Notepad
  local scroll = CreateFrame("ScrollFrame", "HawkerEditorScroll", editor, "UIPanelScrollFrameTemplate")
  scroll:SetPoint("TOPLEFT", 14, -62)
  scroll:SetPoint("BOTTOMRIGHT", -34, 44)
  local box = CreateFrame("EditBox", "HawkerEditorBox", scroll)
  box:SetMultiLine(true)
  box:SetAutoFocus(false)
  box:SetFontObject(ChatFontNormal)
  box:SetMaxLetters(0)
  box:SetWidth(480)
  box:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
  box:SetScript("OnTextChanged", function(_, userInput)
    if userInput then
      dirty = true
      setStatus("Unsaved changes.", 1, 0.82, 0)
    end
  end)
  if ScrollingEdit_OnCursorChanged then
    box:SetScript("OnCursorChanged", ScrollingEdit_OnCursorChanged)
  end
  if ScrollingEdit_OnUpdate then
    box:SetScript("OnUpdate", function(self, elapsed) ScrollingEdit_OnUpdate(self, elapsed, scroll) end)
  end
  scroll:SetScrollChild(box)
  scroll:SetScript("OnSizeChanged", function(_, width) box:SetWidth(width) end)
  scroll:SetScript("OnMouseDown", function() box:SetFocus() end)
  editor.box = box

  -- Footer
  editor.saveButton = button("HawkerEditorSave", "Save", 80)
  editor.saveButton:SetPoint("BOTTOMRIGHT", -12, 12)
  editor.saveButton:SetScript("OnClick", save)
  editor.revertButton = button("HawkerEditorRevert", "Revert", 80)
  editor.revertButton:SetPoint("RIGHT", editor.saveButton, "LEFT", -4, 0)
  editor.revertButton:SetScript("OnClick", function() fill() end)
  editor.status = editor:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  editor.status:SetPoint("BOTTOMLEFT", 16, 18)
  editor.status:SetJustifyH("LEFT")

  editor:SetScript("OnShow", function()
    -- Keep unsaved edits if the window was closed with some.
    if dirty and presetById(editing) then updateHeader() else fill() end
  end)
  editor:SetScript("OnHide", function() menu:Hide() end)
  editor:Hide()
end

refreshEditor = function()
  if not (editor and editor:IsShown()) then return end
  if dirty and presetById(editing) then updateHeader() else fill() end
end

local function toggleEditor()
  if not editor then createEditor() end
  editor:SetShown(not editor:IsShown())
end

StaticPopupDialogs.HAWKER_DISCARD = {
  text = "Throw away your unsaved changes?",
  button1 = YES or "Yes",
  button2 = NO or "No",
  OnAccept = function(_, fn)
    dirty = false
    fn()
  end,
  timeout = 0, whileDead = true, hideOnEscape = true, preferredIndex = 3,
}

local function namePopup(text, onName)
  return {
    text = text,
    button1 = ACCEPT or "Accept",
    button2 = CANCEL or "Cancel",
    hasEditBox = true,
    maxLetters = MAX_NAME_LEN,
    OnShow = function(self, id)
      local box = popupBox(self)
      local p = id and presetById(id)
      box:SetText(p and p.name or "")
      box:HighlightText()
      box:SetFocus()
    end,
    OnAccept = function(self, id)
      local name = strtrim(popupBox(self):GetText() or "")
      local valid, problem = validName(name, id)
      if not valid then
        say("%s", problem)
        return true -- keep it open so the name can be fixed
      end
      onName(name, id)
      return false
    end,
    EditBoxOnEnterPressed = function(box) StaticPopup_OnClick(box:GetParent(), 1) end,
    EditBoxOnEscapePressed = function(box) box:GetParent():Hide() end,
    timeout = 0, whileDead = true, hideOnEscape = true, preferredIndex = 3,
  }
end

StaticPopupDialogs.HAWKER_NEW = namePopup("Name for the new preset\n(one word, letters, numbers or dashes):",
  function(name)
    local p = newPreset(name)
    fill(p.id)
    say("made preset %s. Type its lines and press Save.", name)
  end)

StaticPopupDialogs.HAWKER_RENAME = namePopup("New name for %s:", function(name, id)
  presetById(id).name = name
  updateHeader()
  say("renamed to %s. Macros that name the old preset need updating.", name)
end)

StaticPopupDialogs.HAWKER_DELETE = {
  text = "Delete the preset %s and all its lines?",
  button1 = YES or "Yes",
  button2 = NO or "No",
  OnAccept = function(_, id)
    if #db.presets <= 1 then return end
    for i, p in ipairs(db.presets) do
      if p.id == id then
        tremove(db.presets, i)
        say("deleted preset %s.", p.name)
        break
      end
    end
    lastIndex[id] = nil
    if char.active == id then char.active = db.presets[1].id end
    dirty = false
    fill(activePreset().id)
  end,
  timeout = 0, whileDead = true, hideOnEscape = true, preferredIndex = 3,
}

---------------------------------------------------------------------------
-- Slash command and loading
---------------------------------------------------------------------------

SLASH_HAWKER1 = "/hawk"
SlashCmdList.HAWKER = function(msg)
  if not db then
    say("didn't finish loading. Check BugSack for the error.")
    return
  end
  msg = strtrim(msg or "")
  local cmd, rest = msg:match("^(%S*)%s*(.-)$")
  cmd = cmd:lower()
  if cmd == "" then Hawk()
  elseif cmd == "add" then add(rest)
  elseif cmd == "list" then list()
  elseif cmd == "remove" then remove(rest)
  elseif cmd == "clear" then clear()
  elseif cmd == "use" then use(rest)
  elseif cmd == "presets" then presets()
  elseif cmd == "edit" then toggleEditor()
  elseif cmd == "help" then help()
  else sayFromWords(msg) end
end

local events = CreateFrame("Frame")
events:RegisterEvent("ADDON_LOADED")
events:SetScript("OnEvent", function(_, _, name)
  if name ~= ADDON then return end
  HawkerDB = HawkerDB or {}
  HawkerCharDB = HawkerCharDB or {}
  db, char = HawkerDB, HawkerCharDB
  db.presets = db.presets or {}
  db.nextId = db.nextId or 1
  if #db.presets == 0 then
    -- First run, or saved data from before presets: keep any old lines.
    local p = newPreset("default")
    p.lines = db.lines or {}
  end
  db.lines = nil
  activePreset()
end)
