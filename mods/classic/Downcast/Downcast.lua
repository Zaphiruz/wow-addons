-- Downcast
--
-- Casting a spell from an action slot makes the game drop to the best rank
-- the target can take. Casting by name (/cast) does not: it fails with
-- "Target is too low level". Downcast keeps each chosen spell's top rank in a
-- hidden action slot and gives it a button your macros can /click:
--
--   /click DowncastRenew
--
-- At the moment of the click, a secure snippet picks the unit
-- (mouseover, then friendly target, then you), so it works in combat.

local ADDON = ...
local PREFIX = "|cff66ccffDowncast:|r "
local UNIT_RULE = "[@mouseover,help,nodead] mouseover; [help,nodead] target; player"
local BOOK = BOOKTYPE_SPELL or "spell"
local MAX_SLOT = 120
local MAX_KEY_LEN = 24

local PRIEST_DEFAULTS = {
  { key = "Renew",      spell = "Renew" },
  { key = "Fort",       spell = "Power Word: Fortitude" },
  { key = "Shield",     spell = "Power Word: Shield" },
  { key = "Spirit",     spell = "Divine Spirit" },
  { key = "ShadowProt", spell = "Shadow Protection" },
}

local db                 -- DowncastCharDB once loaded
local buttons = {}       -- frame name -> secure button
local status = {}        -- entry -> text for /downcast
local label = {}         -- entry -> short state for the window ("Rank 5", "not learned")
local iconOf = {}        -- entry -> spell icon texture
local refreshEditor = function() end  -- replaced once the window exists
local worldReady = false
local syncQueued = false
local pendingCombat = false
local debugOn = false

local function say(fmt, ...)
  print(PREFIX .. format(fmt, ...))
end

---------------------------------------------------------------------------
-- Secure buttons
---------------------------------------------------------------------------

local header = CreateFrame("Frame", "DowncastHeader", UIParent, "SecureHandlerBaseTemplate")

-- Runs in the restricted environment on every click, in or out of combat.
-- useOnKeyDown is matched to the click we got, so a plain "/click X" (a
-- release) and "/click X LeftButton 1" (a press) both cast exactly once.
local CLICK_SNIPPET = [=[
  local unit = SecureCmdOptionParse(self:GetAttribute("downcast-unitrule"))
  self:SetAttribute("unit", unit or "player")
  self:SetAttribute("useOnKeyDown", down and true or false)
]=]

local function buttonName(e)
  return "Downcast" .. e.key
end

local function getButton(e)
  local name = buttonName(e)
  local b = buttons[name]
  if not b then
    if InCombatLockdown() then return nil end
    b = CreateFrame("Button", name, UIParent, "SecureActionButtonTemplate")
    b:RegisterForClicks("AnyUp", "AnyDown")
    b:SetAttribute("downcast-unitrule", UNIT_RULE)
    SecureHandlerWrapScript(b, "OnClick", header, CLICK_SNIPPET)
    -- Read-only report after each click, only when /downcast debug is on.
    b:HookScript("OnClick", function(self, _, down)
      if not debugOn then return end
      local slot = self:GetAttribute("action")
      local holds = ""
      if slot then
        local kind, id = GetActionInfo(slot)
        if kind == "spell" then
          local sub = GetSpellSubtext and GetSpellSubtext(id)
          holds = format(" holds %s (%s)", GetSpellInfo(id) or "?", (sub and sub ~= "") and sub or "?")
        else
          holds = " holds " .. tostring(kind)
        end
      end
      say("%s click: down=%s unit=%s type=%s slot=%s%s useOnKeyDown=%s",
        self:GetName(), tostring(down), tostring(self:GetAttribute("unit")),
        tostring(self:GetAttribute("type")), tostring(slot), holds,
        tostring(self:GetAttribute("useOnKeyDown")))
    end)
    buttons[name] = b
  end
  return b
end

-- With no "action" attribute Blizzard's button falls back to slot 1, so a
-- button that isn't ready must have no type at all.
local function disable(b)
  b:SetAttribute("type", nil)
  b:SetAttribute("action", nil)
end

---------------------------------------------------------------------------
-- Spellbook and action slots
---------------------------------------------------------------------------

-- Highest known rank: spellbook index, proper name, rank number, spell ID.
local function topRank(spellName)
  local want = spellName:lower()
  local bestIndex, bestName, bestRank
  for tab = 1, GetNumSpellTabs() do
    local _, _, offset, numSpells = GetSpellTabInfo(tab)
    for i = offset + 1, offset + numSpells do
      local name, subtext = GetSpellBookItemName(i, BOOK)
      if name and name:lower() == want then
        local rank = tonumber(subtext and subtext:match("%d+")) or 0
        if not bestRank or rank >= bestRank then
          bestIndex, bestName, bestRank = i, name, rank
        end
      end
    end
  end
  if not bestIndex then return nil end
  local _, spellID = GetSpellBookItemInfo(bestIndex, BOOK)
  return bestIndex, bestName, bestRank, spellID
end

-- True if the slot holds any rank of this spell.
local function slotHolds(slot, spellName)
  local kind, id = GetActionInfo(slot)
  if kind ~= "spell" or not id then return false end
  local name = GetSpellInfo(id)
  return name ~= nil and name:lower() == spellName:lower()
end

local function slotClaimed(slot, except)
  for _, e in ipairs(db.spells) do
    if e ~= except and e.slot == slot then return true end
  end
  return false
end

local function freeSlot(except)
  for slot = MAX_SLOT, 1, -1 do
    if not HasAction(slot) and not slotClaimed(slot, except) then return slot end
  end
end

local function ownsSlot(slot)
  if slot == 0 then return true end
  for _, e in ipairs(db.spells) do
    if e.slot == slot then return true end
  end
  return false
end

---------------------------------------------------------------------------
-- Keeping slots and buttons up to date (out of combat only)
---------------------------------------------------------------------------

local function syncEntry(e)
  local b = getButton(e)
  if not b then return end

  local index, name, rank, spellID = topRank(e.spell)
  if not index then
    disable(b)
    status[e] = "not in your spellbook"
    label[e], iconOf[e] = "not learned", nil
    return
  end
  e.spell = name
  iconOf[e] = GetSpellTexture and GetSpellTexture(spellID)
  label[e] = "not ready"

  local slot = e.slot
  if not (slot and slotHolds(slot, name)) then
    -- Our old slot is gone or something else is in it now. Never overwrite it.
    slot = freeSlot(e)
    if not slot then
      disable(b)
      e.slot = nil
      status[e] = "no empty action slot to use"
      return
    end
  end

  local kind, current = GetActionInfo(slot)
  if not (kind == "spell" and current == spellID) then
    ClearCursor()
    PickupSpellBookItem(index, BOOK)
    PlaceAction(slot)
    ClearCursor()
    kind, current = GetActionInfo(slot)
  end
  if not (kind == "spell" and current == spellID) then
    disable(b)
    status[e] = "could not place it in an action slot"
    return
  end

  e.slot = slot
  b:SetAttribute("type", "action")
  b:SetAttribute("action", slot)
  status[e] = rank > 0 and format("ready, top rank %d", rank) or "ready"
  label[e] = rank > 0 and format("Rank %d", rank) or "ready"
end

local queueSync

local function sync()
  syncQueued = false
  if not (db and worldReady) then return end
  if InCombatLockdown() then
    pendingCombat = true
    return
  end
  if GetCursorInfo() then
    -- Don't drop whatever the player is dragging. Try again shortly.
    queueSync(1)
    return
  end
  pendingCombat = false
  for _, e in ipairs(db.spells) do syncEntry(e) end
  refreshEditor()
end

queueSync = function(delay)
  if syncQueued then return end
  syncQueued = true
  C_Timer.After(delay or 0.1, sync)
end

---------------------------------------------------------------------------
-- Slash command
---------------------------------------------------------------------------

local function findEntry(key)
  key = strtrim(key or ""):lower()
  if key == "" then return nil end
  local bare = key:match("^downcast(.+)$")
  for i, e in ipairs(db.spells) do
    local k = e.key:lower()
    if k == key or k == bare then return e, i end
  end
end

local function help()
  say("commands:")
  print("  /downcast  - list your buttons and the /click line for each")
  print("  /downcast edit  - open the Downcast window")
  print("  /downcast spells  - list spells in your spellbook worth adding")
  print("  /downcast add <spell name>  - add a spell, e.g. /downcast add Abolish Disease")
  print("  /downcast add <spell name> as <ButtonName>  - pick a shorter button name")
  print("  /downcast remove <ButtonName>  - remove a button")
  print("  /downcast rename <ButtonName> <NewName>  - rename a button")
  print("  /downcast debug  - print what each click does, for troubleshooting")
end

local function list()
  if #db.spells == 0 then
    say("no spells yet. Add one with /downcast add <spell name>")
    return
  end
  say("put these lines in your macros:")
  for _, e in ipairs(db.spells) do
    print(format("  /click %s  -  %s (%s)", buttonName(e), e.spell, status[e] or "waiting"))
  end
  if pendingCombat then say("changes will apply when combat ends.") end
end

local function entryForSpell(name)
  for _, e in ipairs(db.spells) do
    if e.spell:lower() == name:lower() then return e end
  end
end

-- Spells worth a button: castable on others, with more than one rank.
-- Returns a sorted list of { name = , rank = }.
local function candidates()
  local best, names = {}, {}
  for tab = 1, GetNumSpellTabs() do
    local _, _, offset, numSpells = GetSpellTabInfo(tab)
    for i = offset + 1, offset + numSpells do
      local name, subtext = GetSpellBookItemName(i, BOOK)
      local rank = tonumber(subtext and subtext:match("%d+"))
      local helpful = (not IsHelpfulSpell) or IsHelpfulSpell(i, BOOK)
      local passive = IsPassiveSpell and IsPassiveSpell(i, BOOK)
      if name and rank and helpful and not passive then
        if not best[name] then names[#names + 1] = name end
        best[name] = math.max(best[name] or 0, rank)
      end
    end
  end
  table.sort(names)
  local list = {}
  for _, name in ipairs(names) do
    if best[name] >= 2 then list[#list + 1] = { name = name, rank = best[name] } end
  end
  return list
end

local function spells()
  local list = candidates()
  for i, c in ipairs(list) do
    if i == 1 then say("spells you can cast on others that have more than one rank:") end
    local added = entryForSpell(c.name)
    print(format("  %s (rank %d)%s", c.name, c.rank,
      added and (", added as " .. buttonName(added)) or ""))
  end
  if #list == 0 then
    say("no spells in your spellbook that you cast on others have more than one rank yet.")
  else
    say("add one with /downcast add <spell name>")
  end
end

local function validKey(key)
  if key:match("^%a%w*$") and #key <= MAX_KEY_LEN then return true end
  say("button names must start with a letter, use only letters and numbers, and be at most %d long.", MAX_KEY_LEN)
  return false
end

-- Each of these returns true when it changed something.
local function add(args)
  local spell, key = args:match("^(.-)%s+[Aa][Ss]%s+(%S+)$")
  spell = strtrim(spell or args)
  if spell == "" then
    say("usage: /downcast add <spell name> [as <ButtonName>]")
    return false
  end
  key = key or (spell:gsub("[^%w]", ""))
  if not validKey(key) then return false end
  if InCombatLockdown() then say("can't add spells in combat.") return false end
  if GetCursorInfo() then say("drop what's on your cursor first.") return false end
  if findEntry(key) then say("you already have a button called %s.", "Downcast" .. key) return false end
  local existing = entryForSpell(spell)
  if existing then
    say("%s is already covered by %s.", existing.spell, buttonName(existing))
    return false
  end

  local index, name = topRank(spell)
  local e = { key = key, spell = name or spell }
  tinsert(db.spells, e)
  syncEntry(e)
  say("added. Use this line in your macro: /click %s", buttonName(e))
  if not index then
    say("%s isn't in your spellbook. Check the spelling. It will start working once you learn it.", spell)
  end
  return true
end

local function removeEntry(e)
  if InCombatLockdown() then say("can't remove spells in combat.") return false end
  if GetCursorInfo() then say("drop what's on your cursor first.") return false end
  if e.slot and slotHolds(e.slot, e.spell) then
    ClearCursor()
    PickupAction(e.slot)
    ClearCursor()
  end
  local b = buttons[buttonName(e)]
  if b then disable(b) end
  for i, other in ipairs(db.spells) do
    if other == e then tremove(db.spells, i) break end
  end
  status[e], label[e], iconOf[e] = nil, nil, nil
  say("removed %s. Macros that click it will do nothing now.", buttonName(e))
  return true
end

local function remove(args)
  local e = findEntry(args)
  if not e then say("no button called %s. Type /downcast to see your buttons.", strtrim(args)) return false end
  return removeEntry(e)
end

local function rename(e, newKey)
  newKey = strtrim(newKey or "")
  local bare = newKey:match("^[Dd]owncast(%w+)$")
  if bare then newKey = bare end
  if not validKey(newKey) then return false end
  if InCombatLockdown() then say("can't rename buttons in combat.") return false end
  local other = findEntry(newKey)
  if other and other ~= e then say("you already have a button called %s.", "Downcast" .. newKey) return false end
  if newKey == e.key then return true end
  local old = buttons[buttonName(e)]
  if old then disable(old) end
  e.key = newKey
  syncEntry(e)
  say("renamed. Use this line in your macros now: /click %s", buttonName(e))
  return true
end

local function renameCommand(args)
  local old, new = strtrim(args or ""):match("^(%S+)%s+(%S+)$")
  if not old then say("usage: /downcast rename <ButtonName> <NewName>") return false end
  local e = findEntry(old)
  if not e then say("no button called %s. Type /downcast to see your buttons.", old) return false end
  return rename(e, new)
end

---------------------------------------------------------------------------
-- Window (/downcast edit)
---------------------------------------------------------------------------

local editor
local ROW_HEIGHT = 28
local QUESTION_ICON = "Interface\\Icons\\INV_Misc_QuestionMark"

StaticPopupDialogs = StaticPopupDialogs or {}

local function popupBox(dialog)
  return dialog.GetEditBox and dialog:GetEditBox() or dialog.editBox
end

StaticPopupDialogs.DOWNCAST_RENAME = {
  text = "New button name for %s\n(letters and numbers only):",
  button1 = ACCEPT or "Accept",
  button2 = CANCEL or "Cancel",
  hasEditBox = true,
  maxLetters = MAX_KEY_LEN,
  OnShow = function(self, e)
    local box = popupBox(self)
    box:SetText(e.key)
    box:HighlightText()
    box:SetFocus()
  end,
  OnAccept = function(self, e)
    if rename(e, popupBox(self):GetText()) then
      refreshEditor()
      return false
    end
    return true -- keep it open so the name can be fixed
  end,
  EditBoxOnEnterPressed = function(box) StaticPopup_OnClick(box:GetParent(), 1) end,
  EditBoxOnEscapePressed = function(box) box:GetParent():Hide() end,
  timeout = 0,
  whileDead = true,
  hideOnEscape = true,
  preferredIndex = 3,
}

local function receiveDrag()
  local kind, index, book, spellID = GetCursorInfo()
  if kind ~= "spell" then return end
  if InCombatLockdown() then say("can't add spells in combat.") return end
  local name = (spellID and GetSpellInfo(spellID)) or (index and GetSpellBookItemName(index, book or BOOK))
  ClearCursor()
  if name and add(name) then refreshEditor() end
end

local function createRow(i)
  local row = CreateFrame("Frame", nil, editor.content)
  row:SetSize(500, ROW_HEIGHT)
  row:SetPoint("TOPLEFT", 0, -(i - 1) * ROW_HEIGHT)

  row.icon = row:CreateTexture(nil, "ARTWORK")
  row.icon:SetSize(22, 22)
  row.icon:SetPoint("LEFT", 2, 0)

  row.name = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  row.name:SetPoint("LEFT", row.icon, "RIGHT", 6, 0)
  row.name:SetWidth(128)
  row.name:SetJustifyH("LEFT")

  -- Read-only text box so the /click line can be selected and copied.
  row.copy = CreateFrame("EditBox", nil, row, "InputBoxTemplate")
  row.copy:SetSize(172, 20)
  row.copy:SetPoint("LEFT", row.name, "RIGHT", 10, 0)
  row.copy:SetAutoFocus(false)
  row.copy:SetScript("OnTextChanged", function(self, userInput)
    if userInput then
      self:SetText(self.value or "")
      self:HighlightText()
    end
  end)
  row.copy:SetScript("OnEditFocusGained", function(self) self:HighlightText() end)
  row.copy:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
  row.copy:SetScript("OnEnterPressed", function(self) self:ClearFocus() end)

  row.rank = row:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  row.rank:SetPoint("LEFT", row.copy, "RIGHT", 8, 0)
  row.rank:SetWidth(66)
  row.rank:SetJustifyH("LEFT")

  row.remove = CreateFrame("Button", nil, row, "UIPanelButtonTemplate")
  row.remove:SetSize(24, 20)
  row.remove:SetPoint("RIGHT", 0, 0)
  row.remove:SetText("X")
  row.remove:SetScript("OnClick", function(self)
    local e = self:GetParent().entry
    if e and removeEntry(e) then refreshEditor() end
  end)

  row.rename = CreateFrame("Button", nil, row, "UIPanelButtonTemplate")
  row.rename:SetSize(64, 20)
  row.rename:SetPoint("RIGHT", row.remove, "LEFT", -4, 0)
  row.rename:SetText("Rename")
  row.rename:SetScript("OnClick", function(self)
    local e = self:GetParent().entry
    if e then StaticPopup_Show("DOWNCAST_RENAME", buttonName(e), nil, e) end
  end)
  return row
end

local function menuItem(i)
  local item = CreateFrame("Button", nil, editor.menu)
  item:SetSize(220, 18)
  item:SetPoint("TOPLEFT", 8, -8 - (i - 1) * 18)
  item:SetNormalFontObject("GameFontHighlightLeft")
  item:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
  item:SetScript("OnClick", function(self)
    editor.menu:Hide()
    if add(self.spell) then refreshEditor() end
  end)
  return item
end

local function toggleMenu()
  local menu = editor.menu
  if menu:IsShown() then menu:Hide() return end
  local list = {}
  for _, c in ipairs(candidates()) do
    if not entryForSpell(c.name) then list[#list + 1] = c end
  end
  for i, c in ipairs(list) do
    menu.items[i] = menu.items[i] or menuItem(i)
    menu.items[i]:SetText(format("%s (rank %d)", c.name, c.rank))
    menu.items[i].spell = c.name
    menu.items[i]:Show()
  end
  for i = #list + 1, #menu.items do menu.items[i]:Hide() end
  menu.empty:SetShown(#list == 0)
  menu:SetSize(236, math.max(#list, 1) * 18 + 16)
  menu:Show()
end

local function createEditor()
  editor = CreateFrame("Frame", "DowncastEditor", UIParent, "BasicFrameTemplateWithInset")
  editor:SetSize(560, 340)
  editor:SetPoint("CENTER")
  editor:SetFrameStrata("DIALOG")
  editor:SetClampedToScreen(true)
  editor:SetMovable(true)
  editor:EnableMouse(true)
  editor:RegisterForDrag("LeftButton")
  editor:SetScript("OnDragStart", editor.StartMoving)
  editor:SetScript("OnDragStop", editor.StopMovingOrSizing)
  editor:SetScript("OnReceiveDrag", receiveDrag)
  editor:SetScript("OnMouseUp", receiveDrag)
  editor.TitleText:SetText("Downcast")
  tinsert(UISpecialFrames, "DowncastEditor")

  local scroll = CreateFrame("ScrollFrame", "DowncastEditorScroll", editor, "UIPanelScrollFrameTemplate")
  scroll:SetPoint("TOPLEFT", 12, -32)
  scroll:SetPoint("BOTTOMRIGHT", -32, 44)
  -- The scroll area takes the mouse, so it needs the drop handler too.
  scroll:SetScript("OnReceiveDrag", receiveDrag)
  scroll:SetScript("OnMouseUp", receiveDrag)
  editor.content = CreateFrame("Frame", nil, scroll)
  editor.content:SetSize(500, 1)
  scroll:SetScrollChild(editor.content)
  editor.rows = {}

  editor.addButton = CreateFrame("Button", "DowncastEditorAdd", editor, "UIPanelButtonTemplate")
  editor.addButton:SetSize(120, 22)
  editor.addButton:SetPoint("BOTTOMLEFT", 12, 12)
  editor.addButton:SetText("Add spell...")
  editor.addButton:SetScript("OnClick", toggleMenu)

  editor.note = editor:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  editor.note:SetPoint("LEFT", editor.addButton, "RIGHT", 10, 0)
  editor.note:SetJustifyH("LEFT")

  local menu = CreateFrame("Frame", "DowncastEditorMenu", editor, "BackdropTemplate")
  menu:SetPoint("BOTTOMLEFT", editor.addButton, "TOPLEFT", 0, 2)
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
  menu.empty = menu:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  menu.empty:SetPoint("TOPLEFT", 10, -10)
  menu.empty:SetText("Nothing new to add. Spells need more than one rank.")
  menu:Hide()
  editor.menu = menu

  editor:SetScript("OnShow", function() refreshEditor() end)
  editor:SetScript("OnHide", function() menu:Hide() end)
  editor:Hide()
end

refreshEditor = function()
  if not (editor and editor:IsShown()) then return end
  local locked = InCombatLockdown()
  for i, e in ipairs(db.spells) do
    local row = editor.rows[i] or createRow(i)
    editor.rows[i] = row
    row.entry = e
    row.icon:SetTexture(iconOf[e] or QUESTION_ICON)
    row.name:SetText(e.spell)
    row.copy.value = "/click " .. buttonName(e)
    row.copy:SetText(row.copy.value)
    row.copy:SetCursorPosition(0)
    local text = label[e] or "not ready"
    row.rank:SetText(text)
    if text:match("^Rank") or text == "ready" then
      row.rank:SetTextColor(0.4, 1, 0.4)
    else
      row.rank:SetTextColor(0.6, 0.6, 0.6)
    end
    row.rename:SetEnabled(not locked)
    row.remove:SetEnabled(not locked)
    row:Show()
  end
  for i = #db.spells + 1, #editor.rows do
    editor.rows[i].entry = nil
    editor.rows[i]:Hide()
  end
  editor.content:SetHeight(math.max(1, #db.spells * ROW_HEIGHT))
  editor.addButton:SetEnabled(not locked)
  if locked then
    editor.menu:Hide()
    editor.note:SetText("Changes are locked during combat.")
  elseif #db.spells == 0 then
    editor.note:SetText("No spells yet. Drag one from your spellbook here.")
  else
    editor.note:SetText("Drag a spell from your spellbook here to add it.")
  end
end

local function toggleEditor()
  if not editor then createEditor() end
  editor:SetShown(not editor:IsShown())
end

SLASH_DOWNCAST1 = "/downcast"
SlashCmdList.DOWNCAST = function(msg)
  if not db then
    say("didn't finish loading, so it can't run. Check BugSack or /console scriptErrors 1 for the error.")
    return
  end
  local cmd, rest = strtrim(msg or ""):match("^(%S*)%s*(.-)$")
  cmd = cmd:lower()
  if cmd == "" or cmd == "list" then list()
  elseif cmd == "spells" then spells()
  elseif cmd == "debug" then
    debugOn = not debugOn
    say("debug %s.%s", debugOn and "on" or "off", debugOn
      and format(" Cast-on-key-press setting is %s. Each click will print a line.", tostring(GetCVarBool("ActionButtonUseKeyDown")))
      or "")
  elseif cmd == "edit" then toggleEditor()
  elseif cmd == "add" then if add(rest) then refreshEditor() end
  elseif cmd == "remove" then if remove(rest) then refreshEditor() end
  elseif cmd == "rename" then if renameCommand(rest) then refreshEditor() end
  else help() end
end

---------------------------------------------------------------------------
-- Events
---------------------------------------------------------------------------

local events = CreateFrame("Frame")
-- SPELLS_CHANGED also covers learning a new rank. Each registration is
-- guarded: the game throws on event names it doesn't have, and one bad name
-- must never stop the rest of the addon from loading.
for _, event in ipairs({ "ADDON_LOADED", "PLAYER_ENTERING_WORLD", "SPELLS_CHANGED",
                         "ACTIONBAR_SLOT_CHANGED", "PLAYER_REGEN_ENABLED", "PLAYER_REGEN_DISABLED" }) do
  if not pcall(events.RegisterEvent, events, event) then
    say("this game version has no %s event. Please report it.", event)
  end
end
events:SetScript("OnEvent", function(_, event, arg1)
  if event == "ADDON_LOADED" then
    if arg1 ~= ADDON then return end
    DowncastCharDB = DowncastCharDB or {}
    db = DowncastCharDB
    db.spells = db.spells or {}
    if not db.seeded then
      db.seeded = true
      local _, class = UnitClass("player")
      if class == "PRIEST" then
        for _, d in ipairs(PRIEST_DEFAULTS) do
          tinsert(db.spells, { key = d.key, spell = d.spell })
        end
      end
    end
  elseif not db then
    return
  elseif event == "PLAYER_ENTERING_WORLD" then
    -- Action bar contents are only reliable from here on.
    worldReady = true
    queueSync()
  elseif event == "PLAYER_REGEN_ENABLED" then
    if pendingCombat then queueSync() end
    refreshEditor()
  elseif event == "PLAYER_REGEN_DISABLED" then
    refreshEditor()
  elseif event == "ACTIONBAR_SLOT_CHANGED" then
    if ownsSlot(arg1) then queueSync() end
  else
    queueSync()
  end
end)
