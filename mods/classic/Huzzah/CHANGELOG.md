# Huzzah changelog

## 0.1.1 (2026-11-10)

- Emotes now name the person who leveled up, such as "Yourname cheers for Bob!". The game only aims emotes at your target, so if they're your target you do the real emote, and otherwise Huzzah sends an emote line with their name in it.

## 0.1.0 (2026-11-10)

- Cheers someone on when they level up: an emote aimed at them and a message, a moment after the ding.
- Four kinds of level-up, each with its own on/off switch, emote and message: group members (party or raid chat), guildmates (guild chat), strangers nearby (a whisper) and your own (guild chat).
- Messages can use {name} and {level}. Leave the emote as None or the message empty to skip it.
- Settings are in Options > AddOns > Huzzah, or type `/huzzah`. `/huzzah test` shows what each would do without sending anything.
- Group members are seen right away. Guildmates elsewhere are noticed when the guild list refreshes, so that can come a minute or so late. Strangers are only seen while targeted, moused over or showing a nameplate.
- Works on Classic Era and World of Warcraft: Forever.
