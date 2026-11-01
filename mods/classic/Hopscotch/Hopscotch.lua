-- Hopscotch: counts every hop off the ground, per character and for the account.
local ADDON = ...

local db, me          -- HopscotchDB, and this character's entry in it
local counter, window
local refreshWindow = function() end  -- replaced once the window exists
local debugging = false

local function say(fmt, ...) print("|cff66ccffHopscotch|r: " .. format(fmt, ...)) end
local function dbg(fmt, ...) if debugging then say("|cff999999" .. fmt .. "|r", ...) end end

local function commas(n)
  local s = tostring(math.floor(n)):reverse():gsub("(%d%d%d)", "%1,"):reverse()
  return (s:gsub("^,", ""))
end

local function charKey(name, realm) return name .. "-" .. realm end

---------------------------------------------------------------------------
-- Counting
--
-- The jump key calls JumpOrAscendStart on press and AscendStop on release.
-- A press only counts if the player then leaves the ground soon after, so
-- presses in mid-air, presses while rooted and swimming upward don't count.
-- Holding the key bunny-hops, and each new take-off while held counts too.
---------------------------------------------------------------------------
local TAKEOFF_WINDOW = 0.3  -- seconds after a press in which leaving the ground counts
local HELD_TIMEOUT = 0.6    -- on the ground this long means the key isn't held any more

local held, pressedAt, falling, groundedFor = false, -math.huge, false, 0

local function updateCounter()
  if not counter then return end
  counter.text:SetText("|cffffd200Jumps|r  " .. commas(me.jumps))
  counter:SetWidth(counter.text:GetStringWidth() + 24)
end

local function countJump()
  me.jumps = me.jumps + 1
  updateCounter()
  refreshWindow()
end

local function canCount()
  return not IsSwimming() and not UnitIsDeadOrGhost("player") and not UnitOnTaxi("player")
end

local function onPress()
  held, pressedAt, groundedFor = true, GetTime(), 0
  dbg("jump pressed (in the air: %s)", tostring(falling))
end

local function onRelease() held = false end

local function onUpdate(_, elapsed)
  local nowFalling = IsFalling() and true or false
  if nowFalling and not falling then
    local recent = GetTime() - pressedAt <= TAKEOFF_WINDOW
    if (held or recent) and canCount() then
      countJump()
      dbg("hop %d", me.jumps)
    else
      dbg("left the ground without a jump")
    end
  end
  if nowFalling then
    groundedFor = 0
  else
    groundedFor = groundedFor + elapsed
    if held and groundedFor > HELD_TIMEOUT then held = false end
  end
  falling = nowFalling
end

---------------------------------------------------------------------------
-- On-screen counter
---------------------------------------------------------------------------
local function savePosition()
  local point, _, relPoint, x, y = counter:GetPoint(1)
  if not point then return end
  db.counter.point, db.counter.relPoint = point, relPoint
  db.counter.x, db.counter.y = math.floor(x + 0.5), math.floor(y + 0.5)
end

local function placeCounter()
  local c = db.counter
  counter:ClearAllPoints()
  counter:SetPoint(c.point or "TOP", UIParent, c.relPoint or c.point or "TOP", c.x or 0, c.y or -120)
end

local function setCounterShown(shown)
  db.counter.hidden = not shown or nil
  counter:SetShown(shown)
  refreshWindow()
end

local function setLocked(locked)
  db.counter.locked = locked or nil
  refreshWindow()
end

local toggleWindow

local function buildCounter()
  counter = CreateFrame("Button", "HopscotchCounter", UIParent, "BackdropTemplate")
  counter:SetSize(90, 24)
  counter:SetFrameStrata("MEDIUM")
  counter:SetClampedToScreen(true)
  counter:SetMovable(true)
  counter:EnableMouse(true)
  counter:RegisterForDrag("LeftButton")
  counter:RegisterForClicks("LeftButtonUp")
  if counter.SetBackdrop then
    counter:SetBackdrop({
      bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
      edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
      tile = true, tileSize = 16, edgeSize = 12,
      insets = { left = 3, right = 3, top = 3, bottom = 3 },
    })
    counter:SetBackdropColor(0, 0, 0, 0.6)
    counter:SetBackdropBorderColor(0.6, 0.6, 0.6, 0.8)
  end
  counter.text = counter:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  counter.text:SetPoint("CENTER")

  counter:SetScript("OnDragStart", function(self)
    if not db.counter.locked then self:StartMoving() end
  end)
  counter:SetScript("OnDragStop", function(self)
    self:StopMovingOrSizing()
    savePosition()
  end)
  counter:SetScript("OnClick", function() toggleWindow() end)
  counter:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_BOTTOM")
    GameTooltip:SetText("Hopscotch")
    GameTooltip:AddLine("Click to see every character's jumps.", 1, 1, 1)
    if not db.counter.locked then GameTooltip:AddLine("Drag to move.", 1, 1, 1) end
    GameTooltip:Show()
  end)
  counter:SetScript("OnLeave", function() GameTooltip:Hide() end)

  placeCounter()
  updateCounter()
  counter:SetShown(not db.counter.hidden)
end

---------------------------------------------------------------------------
-- Window
---------------------------------------------------------------------------
local ROW_HEIGHT = 22

StaticPopupDialogs.HOPSCOTCH_REMOVE = {
  text = "Remove %s from Hopscotch?\nTheir %s jumps come off the account total.",
  button1 = REMOVE or "Remove",
  button2 = CANCEL or "Cancel",
  OnAccept = function(_, key)
    if db and key and db.chars[key] ~= me then
      db.chars[key] = nil
      refreshWindow()
    end
  end,
  timeout = 0,
  whileDead = true,
  hideOnEscape = true,
  preferredIndex = 3,
}

local function displayName(e) return e.name .. " - " .. e.realm end

local function sortedChars()
  local list = {}
  for key, e in pairs(db.chars) do list[#list + 1] = { key = key, entry = e } end
  table.sort(list, function(a, b)
    if a.entry.jumps ~= b.entry.jumps then return a.entry.jumps > b.entry.jumps end
    return a.key < b.key
  end)
  return list
end

local function makeRow(parent, i)
  local row = CreateFrame("Frame", nil, parent)
  row:SetHeight(ROW_HEIGHT)
  row:SetPoint("TOPLEFT", 0, -(i - 1) * ROW_HEIGHT)
  row:SetPoint("RIGHT", parent, "RIGHT", 0, 0)

  row.name = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  row.name:SetPoint("LEFT", 4, 0)
  row.name:SetJustifyH("LEFT")

  row.remove = CreateFrame("Button", nil, row, "UIPanelButtonTemplate")
  row.remove:SetSize(22, 18)
  row.remove:SetPoint("RIGHT", -2, 0)
  row.remove:SetText("X")
  row.remove:SetScript("OnClick", function(self)
    local r = self:GetParent()
    if r.key then StaticPopup_Show("HOPSCOTCH_REMOVE", displayName(r.entry), commas(r.entry.jumps), r.key) end
  end)

  row.jumps = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  row.jumps:SetPoint("RIGHT", row.remove, "LEFT", -8, 0)
  row.jumps:SetJustifyH("RIGHT")
  return row
end

local function checkbox(name, label, anchorTo, x, onClick)
  local box = CreateFrame("CheckButton", name, window, "UICheckButtonTemplate")
  box:SetSize(24, 24)
  box:SetPoint("BOTTOMLEFT", anchorTo, "BOTTOMLEFT", x, 10)
  local text = box:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  text:SetPoint("LEFT", box, "RIGHT", 2, 1)
  text:SetText(label)
  box:SetScript("OnClick", function(self) onClick(self:GetChecked() and true or false) end)
  return box
end

local function buildWindow()
  window = CreateFrame("Frame", "HopscotchWindow", UIParent, "BasicFrameTemplateWithInset")
  window:SetSize(320, 360)
  window:SetPoint("CENTER")
  window:SetFrameStrata("DIALOG")
  window:SetClampedToScreen(true)
  window:SetMovable(true)
  window:EnableMouse(true)
  window:RegisterForDrag("LeftButton")
  window:SetScript("OnDragStart", window.StartMoving)
  window:SetScript("OnDragStop", window.StopMovingOrSizing)
  window.TitleText:SetText("Hopscotch")
  tinsert(UISpecialFrames, "HopscotchWindow")

  local scroll = CreateFrame("ScrollFrame", "HopscotchWindowScroll", window, "UIPanelScrollFrameTemplate")
  scroll:SetPoint("TOPLEFT", 12, -32)
  scroll:SetPoint("BOTTOMRIGHT", -32, 76)
  local content = CreateFrame("Frame", nil, scroll)
  content:SetSize(270, 1)
  scroll:SetScrollChild(content)
  window.content = content
  window.rows = {}

  local totalLabel = window:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  totalLabel:SetPoint("BOTTOMLEFT", 16, 48)
  totalLabel:SetText("Account total")
  window.total = window:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  window.total:SetPoint("BOTTOMRIGHT", -40, 48)

  window.lockBox = checkbox("HopscotchWindowLock", "Lock counter", window, 12, setLocked)
  window.showBox = checkbox("HopscotchWindowShow", "Show counter", window, 150, setCounterShown)

  window:SetScript("OnShow", function() refreshWindow() end)
  window:Hide()
end

refreshWindow = function()
  if not (window and window:IsShown()) then return end
  local list, total = sortedChars(), 0
  for i, item in ipairs(list) do
    local e = item.entry
    total = total + e.jumps
    local row = window.rows[i] or makeRow(window.content, i)
    window.rows[i] = row
    row.key, row.entry = item.key, e
    local label = e.name .. " |cff808080- " .. e.realm .. "|r"
    if e == me then label = label .. " |cff66ccff(you)|r" end
    row.name:SetText(label)
    local color = RAID_CLASS_COLORS and RAID_CLASS_COLORS[e.class or ""]
    if color then row.name:SetTextColor(color.r, color.g, color.b) else row.name:SetTextColor(1, 1, 1) end
    row.jumps:SetText(commas(e.jumps))
    row.remove:SetShown(e ~= me)
    row:Show()
  end
  for i = #list + 1, #window.rows do window.rows[i]:Hide() end
  window.content:SetHeight(math.max(1, #list * ROW_HEIGHT))
  window.total:SetText(commas(total))
  window.lockBox:SetChecked(db.counter.locked and true or false)
  window.showBox:SetChecked(not db.counter.hidden)
end

toggleWindow = function()
  if not window then buildWindow() end
  if window:IsShown() then window:Hide() else window:Show() end
end

---------------------------------------------------------------------------
-- Commands
---------------------------------------------------------------------------
local HELP = {
  "/hop  -  open or close the window with every character's jumps",
  "/hop show  /  /hop hide  -  show or hide the on-screen counter",
  "/hop lock  /  /hop unlock  -  stop or allow dragging the counter",
  "/hop debug  -  print each jump press, to check what counts",
}

SLASH_HOPSCOTCH1 = "/hop"
SLASH_HOPSCOTCH2 = "/hopscotch"
SlashCmdList.HOPSCOTCH = function(msg)
  if not (db and me and counter) then
    say("didn't finish loading. Try /reload, and check for errors.")
    return
  end
  local word = strtrim(msg or ""):lower()
  if word == "" then
    toggleWindow()
  elseif word == "show" or word == "hide" then
    setCounterShown(word == "show")
  elseif word == "lock" or word == "unlock" then
    setLocked(word == "lock")
    say(word == "lock" and "counter locked." or "counter unlocked. Drag it anywhere.")
  elseif word == "debug" then
    debugging = not debugging
    say("debug %s.", debugging and "on" or "off")
  elseif word == "help" then
    for _, line in ipairs(HELP) do say(line) end
  else
    say("no command called %s. Type /hop help for commands.", word)
  end
end

---------------------------------------------------------------------------
-- Startup
---------------------------------------------------------------------------
local events = CreateFrame("Frame")
events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("PLAYER_LOGIN")
events:SetScript("OnEvent", function(self, event, arg1)
  if event == "ADDON_LOADED" and arg1 == ADDON then
    HopscotchDB = HopscotchDB or {}
    db = HopscotchDB
    db.chars = db.chars or {}
    db.counter = db.counter or {}
  elseif event == "PLAYER_LOGIN" then
    local name, realm = UnitName("player"), GetRealmName()
    local key = charKey(name, realm)
    me = db.chars[key] or { jumps = 0 }
    me.name, me.realm = name, realm
    me.class = select(2, UnitClass("player"))
    me.jumps = me.jumps or 0
    db.chars[key] = me

    buildCounter()
    local hooked = pcall(hooksecurefunc, "JumpOrAscendStart", onPress)
    pcall(hooksecurefunc, "AscendStop", onRelease)
    if hooked then
      self:SetScript("OnUpdate", onUpdate)
    else
      say("can't see jumps in this game version, so nothing will be counted.")
    end
  end
end)
