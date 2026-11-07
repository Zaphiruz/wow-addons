-- Run after a mock has set up the game's globals. Assigning one of the game's
-- own tables from addon code taints it, and then the game's protected code that
-- reads it gets blocked (for example the bind-on-use confirmation popup).
-- Reading these tables and adding keys to them is fine; replacing them is not.
local owned = {}
for _, name in ipairs({ "StaticPopupDialogs", "UISpecialFrames", "SlashCmdList", "UIParent", "GameTooltip" }) do
  owned[name] = rawget(_G, name)
  rawset(_G, name, nil)
end
setmetatable(_G, {
  __index = owned,
  __newindex = function(t, k, v)
    if owned[k] ~= nil then error("addon assigned the game's global " .. k .. " (this taints it)", 2) end
    rawset(t, k, v)
  end,
})
