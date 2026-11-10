# battle-marker

Scans Steam background game recordings of Battlefield for highlight badges, like DOUBLE KILL or HEADSHOT, and adds them to the recording's Steam timeline as markers with their own icons.

## Setup

```
winget install UB-Mannheim.TesseractOCR
winget install Gyan.FFmpeg
uv sync
```

ffmpeg needs NVDEC support for GPU decoding. `ffmpeg -hide_banner -decoders | findstr cuvid` should list `hevc_cuvid`. Paths and thresholds live in `config.py`.

## Commands

```
uv run main.py sessions
uv run main.py scan [SESSION] [--from H:MM:SS] [--to H:MM:SS] [--cpu]
uv run main.py mark [SESSION] [--write] [--force]
uv run main.py dump [SESSION] --at H:MM:SS [--seconds 4]
```

`SESSION` is a `bg_*` folder name from `sessions` and defaults to the newest recording. All times are timeline times, the ones the Steam UI shows. `scan` logs every badge it reads to `output/`. `mark` turns that log into markers and only prints them unless `--write` is given. Close Steam before writing, because Steam rewrites the timeline file from memory.

Steam deletes older background recordings when new ones need the space. A recording has to be marked, clipped or exported before that happens.

## Choosing markers

`markers.json` decides which badges become markers and how they look. Editing it only needs a rerun of `mark`, not a new scan.

```json
{
  "name": "DOUBLE KILL",
  "match": "DOUBLE KILL",
  "source": "banner",
  "icon": "steam_2",
  "priority": 30,
  "enabled": true
}
```

| Field | Meaning |
|---|---|
| `name` | Marker title in Steam. Several badges merged into one marker are joined with " + ". |
| `match` | Text searched for in the badge, ignoring case and extra spaces. `KILL` also matches `KILL X2`. |
| `source` | `banner` for the ribbon above the stack (DOUBLE KILL, PAYBACK), `tag` for the boxed text below the name (KILL, HEADSHOT, DAMAGE ASSIST), or `any`. |
| `icon` | One of the icons below. |
| `priority` | Higher wins. When badges merge into one marker, the highest priority picks the icon. Steam also uses it to decide which icons to show in crowded parts of the timeline. |
| `enabled` | `false` keeps the rule in the file without using it. |

Badge texts seen so far include DOUBLE KILL, TRIPLE KILL, QUAD KILL, MARAUDER 5, PAYBACK and GUNSLINGER as banners, and KILL, KILL X2, HEADSHOT, DAMAGE ASSIST, EQUIPMENT DESTROYED, REVIVE, SQUAD REVIVE and SQUAD SUPPLY as tags. The scan log in `output/` lists every text it read.

## Timeline entry format

Steam stores markers in `gamerecordings\timelines\timeline_<appid><date>_<time>.json`. Times are milliseconds stored as strings. battle-marker writes entries like this one.

```json
{
  "id": "3",
  "time": "6716200",
  "type": "event",
  "icon": "steam_2",
  "priority": 30,
  "title": "KILL + DOUBLE KILL",
  "description": "battle-marker"
}
```

The type has to be `event`. Steam keeps any icon on a `usermarker` entry in the file but always draws the default marker icon for it. `gameevent` does not work either.

## Icons

These are Steam's built-in timeline icons, from the [Steamworks Timeline documentation](https://partner.steamgames.com/doc/features/timeline). Custom images are only available to a game's developer.

| | | | | |
|---|---|---|---|---|
| `steam_marker` | `steam_achievement` | `steam_attack` | `steam_bolt` | `steam_bookmark` |
| `steam_bug` | `steam_cart` | `steam_caution` | `steam_chat` | `steam_checkmark` |
| `steam_chest` | `steam_circle` | `steam_combat` | `steam_completed` | `steam_crown` |
| `steam_death` | `steam_defend` | `steam_diamond` | `steam_edit` | `steam_effect` |
| `steam_explosion` | `steam_fix` | `steam_flag` | `steam_gem` | `steam_group` |
| `steam_heart` | `steam_info` | `steam_invalid` | `steam_minus` | `steam_pair` |
| `steam_person` | `steam_plus` | `steam_purchase` | `steam_question` | `steam_ribbon` |
| `steam_screenshot` | `steam_scroll` | `steam_square` | `steam_star` | `steam_starburst` |
| `steam_timer` | `steam_transfer` | `steam_triangle` | `steam_trophy` | `steam_view` |
| `steam_x` | | | | |

Numbers from `steam_0` to `steam_99` draw that number, which suits multikills.
