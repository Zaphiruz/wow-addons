-- Minimal fake WoW API for exercising Downcast.lua outside the game.
M = { out = {}, timers = {}, events = {}, frames = {}, wraps = {},
      inCombat = false, cursor = nil, actions = {}, book = {}, class = "PRIEST",
      placeCount = 0, optionResult = "player" }

M.knownEvents = { ADDON_LOADED = true, PLAYER_ENTERING_WORLD = true, SPELLS_CHANGED = true,
  ACTIONBAR_SLOT_CHANGED = true, PLAYER_REGEN_ENABLED = true, PLAYER_REGEN_DISABLED = true }

function print(...) local t = {} for i = 1, select("#", ...) do t[#t+1] = tostring(select(i, ...)) end M.out[#M.out+1] = table.concat(t, " ") end
format = string.format
tinsert, tremove = table.insert, table.remove
function strtrim(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end
BOOKTYPE_SPELL = "spell"
UIParent = {}
SlashCmdList = {}

local function protectedCheck(f, what)
  if M.inCombat and f.secure then error("BLOCKED in combat: " .. what .. " on " .. tostring(f.name)) end
end

-- Plain UI widgets: the methods tests look at are real, anything else is a no-op.
local noop = function() end
local widgetMT = { __index = function() return noop end }
function M.widget(kind, name, parent)
  local w = setmetatable({ kind = kind, name = name, parent = parent, scripts = {}, shown = true,
                           enabled = true, text = "" }, widgetMT)
  function w:SetScript(s, fn) self.scripts[s] = fn end
  function w:GetScript(s) return self.scripts[s] end
  function w:HookScript(s, fn) self.hooks = self.hooks or {}; self.hooks[s] = fn end
  function w:SetText(t) self.text = t == nil and "" or tostring(t) end
  function w:GetText() return self.text end
  function w:Show() self.shown = true; if self.scripts.OnShow then self.scripts.OnShow(self) end end
  function w:Hide() self.shown = false; if self.scripts.OnHide then self.scripts.OnHide(self) end end
  function w:SetShown(v) if v then self:Show() else self:Hide() end end
  function w:IsShown() return self.shown end
  function w:Enable() self.enabled = true end
  function w:Disable() self.enabled = false end
  function w:SetEnabled(v) self.enabled = not not v end
  function w:IsEnabled() return self.enabled end
  function w:GetName() return self.name end
  function w:GetParent() return self.parent end
  function w:SetTexture(t) self.tex = t end
  function w:CreateFontString(n) return M.widget("FontString", n, self) end
  function w:CreateTexture(n) return M.widget("Texture", n, self) end
  function w:Click(button) if self.enabled and self.scripts.OnClick then self.scripts.OnClick(self, button or "LeftButton") end end
  -- Type into an edit box as the player would.
  function w:Type(t) self.text = t; if self.scripts.OnTextChanged then self.scripts.OnTextChanged(self, true) end end
  return w
end

function CreateFrame(kind, name, parent, template)
  local secure = template ~= nil and template:find("Secure") ~= nil
  local eventFrame = kind == "Frame" and template == nil and parent == nil
  if not secure and not eventFrame then
    local w = M.widget(kind, name, parent)
    if template and template:find("BasicFrameTemplate") then
      w.TitleText = M.widget("FontString", nil, w)
      w.CloseButton = M.widget("Button", nil, w)
    end
    if name then _G[name] = w end
    return w
  end
  local f = { name = name, attrs = {}, scripts = {}, secure = secure }
  function f:SetAttribute(k, v) protectedCheck(self, "SetAttribute " .. k); self.attrs[k] = v end
  function f:GetAttribute(k) return self.attrs[k] end
  function f:RegisterEvent(e)
    -- Classic Era 1.15.9 throws on events it doesn't have (seen in game).
    if not M.knownEvents[e] then error('Attempt to register unknown event "' .. e .. '"') end
    M.events[e] = M.events[e] or {}; table.insert(M.events[e], self)
  end
  function f:SetScript(s, fn) self.scripts[s] = fn end
  function f:GetName() return self.name end
  function f:HookScript(s, fn) self.hooks = self.hooks or {}; self.hooks[s] = fn end
  function f:RegisterForClicks(...) protectedCheck(self, "RegisterForClicks"); self.clicks = {...} end
  if secure and M.inCombat then error("BLOCKED: creating secure frame in combat") end
  if name then _G[name] = f end
  table.insert(M.frames, f)
  return f
end

function SecureHandlerWrapScript(frame, script, header, pre)
  protectedCheck(frame, "WrapScript")
  M.wraps[frame] = pre
end

function InCombatLockdown() return M.inCombat end
C_Timer = { After = function(d, fn) table.insert(M.timers, fn) end }
function M.runTimers()
  for _ = 1, 20 do
    if #M.timers == 0 then return end
    local t = M.timers; M.timers = {}
    for _, fn in ipairs(t) do fn() end
  end
end
function M.fire(event, ...)
  for _, f in ipairs(M.events[event] or {}) do f.scripts.OnEvent(f, event, ...) end
end

function UnitClass() return "x", M.class end

-- Spellbook: M.book = { {name=, rank=, id=}, ... } in one tab.
M.spellNames = {}
function M.learn(name, rank, id) table.insert(M.book, { name = name, rank = rank, id = id }); M.spellNames[id] = name end
function GetNumSpellTabs() return 1 end
function GetSpellTabInfo(tab) return "General", "", 0, #M.book end
function GetSpellBookItemName(i) local s = M.book[i]; if s then return s.name, s.rank and ("Rank " .. s.rank) or "" end end
function GetSpellBookItemInfo(i) local s = M.book[i]; if s then return "SPELL", s.id end end
function GetSpellInfo(id) return M.spellNames[id] end
function GetSpellSubtext(id) for _, s in ipairs(M.book) do if s.id == id then return s.rank and ("Rank " .. s.rank) or "" end end end
function GetCVarBool(name) return true end
M.harmful = { Smite = true }
M.passive = { ["Spiritual Guidance"] = true }
function IsHelpfulSpell(i) local s = M.book[i]; return s ~= nil and not M.harmful[s.name] and not M.passive[s.name] end
function IsPassiveSpell(i) local s = M.book[i]; return s ~= nil and M.passive[s.name] == true end

-- Action slots and cursor
function HasAction(slot) return M.actions[slot] ~= nil end
function GetActionInfo(slot) local a = M.actions[slot]; if a then return a.kind, a.id end end
-- Like the game: a spell on the cursor reports "spell", spellbook index, book type, spell ID.
function GetCursorInfo()
  local c = M.cursor
  if not c then return nil end
  if c.kind == "spell" then return "spell", c.index, c.book, c.id end
  return c.kind, c.id
end
function ClearCursor() M.cursor = nil end
function PickupSpellBookItem(i) if M.inCombat then error("BLOCKED PickupSpellBookItem in combat") end M.cursor = { kind = "spell", index = i, book = "spell", id = M.book[i].id } end
function GetSpellTexture(id) return "icon-" .. tostring(id) end
UISpecialFrames = {}
StaticPopupDialogs = {}
function StaticPopup_Show(which, a1, a2, data)
  local d = M.widget("Frame", "StaticPopup1", nil)
  d.which, d.data = which, data
  d.editBox = M.widget("EditBox", nil, d)
  function d:GetEditBox() return self.editBox end
  local info = StaticPopupDialogs[which]
  if info.OnShow then info.OnShow(d, data) end
  M.popup = d
  return d
end
function StaticPopup_OnClick(d, index)
  local info = StaticPopupDialogs[d.which]
  if index == 1 and info.OnAccept then
    if not info.OnAccept(d, d.data, d.data2) then d:Hide() end
  end
end
function PlaceAction(slot)
  if M.inCombat then error("BLOCKED PlaceAction in combat") end
  M.placeCount = M.placeCount + 1
  local old = M.actions[slot]; M.actions[slot] = M.cursor; M.cursor = old
  M.fire("ACTIONBAR_SLOT_CHANGED", slot)
end
function PickupAction(slot)
  if M.inCombat then error("BLOCKED PickupAction in combat") end
  M.cursor = M.actions[slot]; M.actions[slot] = nil
  M.fire("ACTIONBAR_SLOT_CHANGED", slot)
end

-- Blizzard's decision from SecureActionButton_OnClick (classic_era source).
function M.click(button, down, cvarKeyDown)
  local pre = M.wraps[button]
  local env = setmetatable({
    self = button, button = "LeftButton", down = down,
    SecureCmdOptionParse = function(rule) M.lastRule = rule; return M.optionResult end,
  }, { __index = _G })
  local fn = assert(loadstring(pre))
  setfenv(fn, env)
  fn()
  local useOnKeyDown = button.attrs.useOnKeyDown
  if useOnKeyDown == nil then useOnKeyDown = cvarKeyDown end
  local clickAction = (down and useOnKeyDown) or (not down and not useOnKeyDown)
  local hook = button.hooks and button.hooks.OnClick
  if hook then hook(button, "LeftButton", down) end
  if clickAction and button.attrs.type == "action" then
    return button.attrs.action or 1, button.attrs.unit
  end
  return nil
end

function M.slotOf(spellName)
  for slot = 1, 120 do
    local a = M.actions[slot]
    if a and a.kind == "spell" and M.spellNames[a.id] == spellName then return slot, a.id end
  end
end
