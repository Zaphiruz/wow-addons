# WoW addons

## Never assign the game's globals

Addon code must never assign to a global the game owns, even with the same
value. This includes `StaticPopupDialogs = StaticPopupDialogs or {}`,
`UISpecialFrames = ...` and `SlashCmdList = ...`. The assignment taints the
global, and then Blizzard's own protected code that reads it is blocked and
blamed on the addon. This caused ADDON_ACTION_FORBIDDEN on bind-on-use
confirmations (`ConfirmBindOnUse`) and Logout in Downcast and Hawker 0.2.0.

- Adding a key is fine: `StaticPopupDialogs.MYADDON_X = {...}`,
  `SlashCmdList.MYADDON = fn`, `tinsert(UISpecialFrames, "MyFrame")`.
- Every global the addon creates starts with the addon's name, such as
  `DowncastEditor` or `SLASH_HAWKER1`. Keep everything else `local`.
- Each addon's tests load `mods/classic/tests/guard_globals.lua` after the mock,
  which makes reassigning a guarded global fail the tests. When an addon starts
  using another game global, add it to that file's list.

## Adding a new addon

Besides the addon folder, tests, changelog and logo, add its name to:

- the Addon dropdown in `.github/ISSUE_TEMPLATE/bug.yml` and `feature.yml`
- the `addons` list in `.github/workflows/issue-labels.yml`
- a GitHub label of the same name (`gh label create <Addon>`)
- the table in `README.md`
