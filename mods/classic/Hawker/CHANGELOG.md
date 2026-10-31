# Hawker changelog

## 0.2.1 (2026-10-31)

- Fixed an error when accepting the game's own confirmation popups, such as using a bind-on-use item like a mount. Hawker was blamed for the blocked action.

## 0.2.0 (2026-10-31)

- Presets: keep several named lists of lines, such as "enchants" and "portals". Your existing lines become a preset called "default".
- One preset is active. Plain `/hawk` and `add`, `list`, `remove` and `clear` use it. Each character remembers its own active preset.
- Name a preset to use it once: `/hawk portals`. Combine it with a channel in either order: `/hawk 2 portals`.
- `/hawk use <preset>` switches the active preset, and `/hawk presets` lists them.
- New window: `/hawk edit` shows a preset's lines as a notepad, one line per advert. Save, Revert, and pick, create, rename, delete or activate presets from the top bar.
- The window asks before throwing away unsaved changes, and keeps them if you close it.
- `/hawk help` lists every command. An unknown word now says so instead of showing help.
- From scripts, `Hawk(channel, preset)` takes an optional preset name.

## 0.1.0 (2026-10-25)

First release.

- Keep a list of advert lines with `/hawk add`, `/hawk list`, `/hawk remove <number>` and `/hawk clear`.
- `/hawk` says a random line from your list, never the same one twice in a row.
- Send to another channel with `/hawk yell`, `/hawk guild`, `/hawk party`, `/hawk raid`, `/hawk emote` or `/hawk officer`, or the short forms `y`, `g`, `p`, `ra`, `e` and `o`.
- Send to a numbered channel such as Trade with `/hawk 2`. Hawker tells you if you haven't joined that channel.
- Lines are saved across reloads and shared by every character on your account.
- Lines longer than the game's 255-character chat limit are refused when you add them.
- `/run Hawk()` works in macros too, with an optional channel such as `Hawk("guild")` or `Hawk(2)`.
