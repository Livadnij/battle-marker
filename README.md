# battle-marker

Scans Steam background game recordings of Battlefield for highlight badges, like DOUBLE KILL or HEADSHOT, and adds them to the recording's Steam timeline as markers with their own icons.

## Setup

```
winget install UB-Mannheim.TesseractOCR
winget install Gyan.FFmpeg
uv sync
```

ffmpeg needs NVDEC support for GPU decoding. `ffmpeg -hide_banner -decoders | findstr cuvid` should list `hevc_cuvid`. Paths and thresholds live in `config.py`.

## Window

```
uv run app.py
```

The first screen lists every recording Steam still has, with a preview, the game, start time, length of the video still on disk, and whether it was scanned. Games other than Battlefield 6 are shown as unsupported. Double-click a recording to open it.

The recording screen plays the video with sound, with a timeline that has a tick for every badge the scan found. Badges picked by a rule are orange, the rest are grey, and the list on the right shows all of them the same way, with the marker icon in front of each picked one. Picked badges show their Steam icon from `icons/` above the timeline. Steam's number icons have no image files and are drawn as text. The timeline shows 10 minutes at a time. The wheel zooms around the cursor, Shift+wheel or the scrollbar under it scrolls, and while playing it follows the playhead. Hovering shows a preview frame and the name of a badge under the cursor. Click a badge to jump to it, drag the timeline to seek, Space plays and pauses, and the arrow keys skip 5 seconds. Scan and Write markers are on the right. If Steam is running, Write markers waits and writes as soon as Steam closes. Start Steam afterwards to see the markers.

The player reads Steam's chunk files in place through HLS playlists in `output/playlists/`, which are rebuilt each time a recording is opened. The same `master.m3u8` also opens in VLC or mpv.

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

Rules... on the recordings screen decides which badges become markers and how they look. Changing rules never needs a new scan. Every badge a rule picks becomes its own marker, placed where its first matching text appeared. A KILL that turns into a DOUBLE KILL with a HEADSHOT tag is one badge, so it is one marker.

| Field | Meaning |
|---|---|
| On | Unticked keeps the rule without using it. |
| Name | Marker title in Steam. When several rules match texts on the same badge, their names are joined with " + ". |
| Match text | Text searched for in the badge, ignoring case and extra spaces. `KILL` also matches `KILL X2`. |
| Source | `banner` for the ribbon above the stack (DOUBLE KILL, PAYBACK), `tag` for the boxed text below the name (KILL, HEADSHOT, DAMAGE ASSIST, SUPPLY), `life` for DEATH, DOWNED and REVIVED, or `any` for banner and tag. |
| Icon | One of Steam's icons, listed below. |
| Priority | Higher wins. When several rules match one badge, the highest priority picks the icon. Steam also uses it to decide which icons to show in crowded parts of the timeline. |

Below the rules is every badge text your scans have read, how often, and which rule picks it. Double-click a text, or select it and press Add as rule, to start a rule from it.

## Deaths, downs and revives

A scan also watches for the downed screen, found by its round heartbeat button, and the deploy screen, found by its row of class icons. A revive keeps the same life going, so the rules Death, Downed and Revived mark these moments.

| Text | When |
|---|---|
| DEATH | You went down and the deploy screen followed. The marker sits where you went down. Without a down first, it sits where the deploy screen showed. |
| DOWNED | You went down and got revived. |
| REVIVED | The moment that down ended. |

A down counts as a revive when the deploy screen does not show within 60 seconds after it, long enough for a detour through the loadout screen. The deploy screen at the start of a match is no death, it only counts after a badge or a down showed you were alive. Badges are not looked for while the deploy screen shows. Older scans have no deaths until they are scanned again.

## Scanning speed

A scan splits the recording into parts, 3 by default, and scans them at the same time, each with its own ffmpeg. One ffmpeg uses only part of the GPU's video decoders. Raise or lower the count in Settings and watch the Video Decode graph in Task Manager. Recordings shorter than a minute per part get fewer parts. Each part starts a few seconds early and finishes the badge it is following past its end, so badges on the seams are found once and whole.

ffmpeg and Tesseract always end with battle-marker. On Windows the app runs inside a job object that Windows closes when the app ends, even after a crash or when it is killed in Task Manager, and that ends every program it started.

## Settings and storage

Settings... holds the Steam recordings folder, the ffmpeg and Tesseract paths, GPU decoding, how many parts are scanned at once, how close an existing timeline entry skips a new marker, and how far markers are moved earlier.

Settings, rules and scan results are kept in `battle-marker.db`, a SQLite file in the project folder. The first start imports `markers.json`, the scan logs in `output/` and `output/app_names.json` into it. Those files are not read after that and can be deleted. Detection constants that belong to the templates stay in `config.py`.

## Tests

```
uv run pytest
```

The suite takes a few seconds and needs no recording and no ffmpeg. Every test works on its own temporary database, so your settings, rules and scans are never touched. The tests that read text from real screen crops, and one scan test, need Tesseract and are skipped without it. The crops live in `tests/frames/` and have player names blacked out.

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
