# Hawker changelog

## 0.1.0 (2026-10-25)

First release.

- Keep a list of advert lines with `/hawk add`, `/hawk list`, `/hawk remove <number>` and `/hawk clear`.
- `/hawk` says a random line from your list, never the same one twice in a row.
- Send to another channel with `/hawk yell`, `/hawk guild`, `/hawk party`, `/hawk raid`, `/hawk emote` or `/hawk officer`, or the short forms `y`, `g`, `p`, `ra`, `e` and `o`.
- Send to a numbered channel such as Trade with `/hawk 2`. Hawker tells you if you haven't joined that channel.
- Lines are saved across reloads and shared by every character on your account.
- Lines longer than the game's 255-character chat limit are refused when you add them.
- `/run Hawk()` works in macros too, with an optional channel such as `Hawk("guild")` or `Hawk(2)`.
