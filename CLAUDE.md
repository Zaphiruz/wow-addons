# WoW addons

World of Warcraft Classic Era addons (Bushel, Downcast, Hawker, Hopscotch, Huzzah), released to
CurseForge and GitHub from this one repository. The README covers the layout
and release commands for people; this file is how we work on it.

## The game

- Classic Era, client 1.15.9, `## Interface: 11509`. Installed at
  `D:\Battle.net\Games\World of Warcraft\_classic_era_`.
- Each `mods/classic/<Addon>` folder is junction-linked into the game's
  `Interface\AddOns`, so edits and newly linked addons show up after `/reload`.
  Remove a link with `cmd /c rmdir <link>`, never `Remove-Item` (it can delete
  the files the link points to).
- In-game errors are caught by BugGrabber/BugSack and saved to
  `WTF\Account\<account>\SavedVariables\!BugGrabber.lua` after `/reload` or logout.
- Look up Blizzard's own UI code in the `classic_era` branch of
  https://github.com/Gethe/wow-ui-source before relying on an event, function
  or template. Names differ from retail, and a wrong one can break loading.

### Forever

- World of Warcraft: Forever is a separate client at
  `D:\Battle.net\Games\World of Warcraft\_forever_`, version 1.60.1,
  `## Interface: 16001`. Its UI is built on modern retail code (12.1), so check
  APIs against the `forever` branch of wow-ui-source, not `classic_era`.
- Bushel, Hawker, Hopscotch and Huzzah support both games from one folder:
  `## Interface: 11509, 16001`. Downcast is Classic Era only.
- All four are junction-linked into `_forever_\Interface\AddOns` as well.
- Differences that matter so far: chat is `C_ChatInfo.SendChatMessage` (no
  global `SendChatMessage`), and addon chat started from a macro is blocked
  during instance encounters. Prefer the modern name and fall back to the
  Classic one: `(C_ChatInfo and C_ChatInfo.SendChatMessage) or SendChatMessage`.
- Forever adds "secret values": some API results can't be read by addons in
  restricted moments. Check a function's documentation for `Secret*` flags
  before using its results.

## How we build a change

1. **Agree on it first.** Ask what the player wants to see or do, then describe
   the change back (with a quick mockup for anything on screen) and wait for a
   yes before writing code. Mark guesses as guesses.
2. **Tests first.** Each addon has mock-game tests in
   `mods/classic/tests/<addon>/run_tests.py`: the real addon Lua runs against a
   small fake WoW API through Python `lupa` (Lua 5.1). Write the scenario, see it
   fail, then write the addon code.
3. **Run everything:** `python mods/classic/tools/run_tests.py` (or one addon by
   name). Needs `pip install lupa pyyaml pillow`; a venv in `$TEMP/luaenv` has them.
4. **Test in game.** The mock can't show timing, taint or how the client really
   behaves. After `/reload`, the player tries it. Anything uncertain gets a
   `/<cmd> debug` that prints what the addon sees, so the player can send it.
5. **Fix bugs from the cause.** Read the full error, trace it in Blizzard's
   source, add a test that fails for that reason, then fix it.

Mock widgets answer any missing field with a no-op function, which is truthy.
Give the mock a real starting value for every field the addon reads
(`moving = false`, `checked = false`), or the test passes for the wrong reason.

## Addon code rules

### Never assign the game's globals

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

### Other rules

- Register events with `pcall`. An unknown event name throws and stops the
  whole addon loading (`LEARNED_SPELL_IN_TAB` doesn't exist in 1.15.9).
- If loading failed, the slash command says so ("didn't finish loading")
  instead of doing nothing.
- Saved data: `<Addon>DB` is shared by the account, `<Addon>CharDB` is per
  character. Migrate old shapes on load instead of dropping them.
- Nothing that changes action bars or secure frames runs in combat. Defer it
  until `PLAYER_REGEN_ENABLED` and tell the player it's waiting.
- `/<cmd> help` lists every command. An unknown word says so and points to help.
- Chat lines are capped at 255 characters; refuse longer ones when they're added.

### Classic Era behaviour we verified in game

- Buffs and HoTs cast by name (`/cast`) fail on low-level targets ("Target is
  too low level"). Cast from an action slot, the client picks the highest rank
  that can land. Downcast is built on this.
- A failed "too low level" cast still triggers the global cooldown, so a second
  `/cast` in the same macro can't be a fallback.
- A bare `/click Button` sends a key release. Secure action buttons ignore it
  unless `useOnKeyDown` is set to match `down` in a WrapScript pre-snippet.
- The restricted environment has no `UnitLevel` or `UnitIsUnit`, and macro
  conditionals have no level check.
- The jump key calls `JumpOrAscendStart` on press and `AscendStop` on release;
  `hooksecurefunc` on both is safe. A real hop is `IsFalling()` turning true
  just after a press.

## Releasing

1. Bump `## Version:` in the `.toc`.
2. Add `## <version> (<date>)` at the top of the addon's `CHANGELOG.md`. Write
   for players: what changed for them, in plain words, one bullet each.
3. Commit, push `main`, then push a tag `<Addon>/v<version>`.

The release workflow checks the tag against the `.toc` and changelog, runs that
addon's tests, builds the zip, uploads it to CurseForge, then makes the GitHub
release. Watch the run and report the CurseForge file id and release link.

If a GitHub release for the tag already exists, the workflow skips the upload:
that version was released by hand. For a first version uploaded by hand on
CurseForge, create the GitHub release with `gh release create` (pass the full
commit SHA to `--target`) instead of pushing the tag.

## Adding a new addon

1. Check the name is free with CurseForge's WoW addon search.
2. Add the addon folder, tests, `CHANGELOG.md`, and a 400x400 logo drawn by
   `mods/classic/tools/<addon>_logo.py` with the shared `badge.py` style.
3. Junction-link it into the game and have the player try it.
4. Write a CurseForge summary and description for the player to paste. The
   player creates the project, uploads 0.1.0 by hand, and sets the Issues
   tracker to External with
   `https://github.com/Zaphiruz/wow-addons/issues/new/choose`.
5. Put the project ID in the `.toc`: `## X-Curse-Project-ID: <id>`.
6. Add the addon's name to:
   - the Addon dropdown in `.github/ISSUE_TEMPLATE/bug.yml` and `feature.yml`
   - the `addons` list in `.github/workflows/issue-labels.yml`
   - a GitHub label of the same name (`gh label create <Addon>`)
   - the table in `README.md`

## Git

- Commit and push only when asked. Work happens on `main`.
- The repository is public. The repo-local git email is the GitHub no-reply
  address on purpose; never commit with a personal email, and keep tokens and
  account names out of files. The CurseForge token lives only in the
  `CF_API_TOKEN` repository secret, which the player sets.
