# battle-marker

Scans Steam background recordings of Battlefield 6 for in-game badges (DOUBLE KILL, HEADSHOT, SUPPLY and so on) and for deaths, downs and revives, then writes them into the recording's Steam timeline as markers with Steam's own icons. Owner is Anton (Tony), a React and Node developer who knows Python basics.

- Window `uv run app.py`, CLI `uv run main.py sessions|scan|mark|dump`.
- Windows 11, Python 3.12 with uv, RTX 5080, ffmpeg with NVDEC (`hevc_cuvid`), Tesseract from UB Mannheim.
- Recordings are 3840x2160 HEVC at about 60 fps under `E:\Steam\gamerecordings`.
- `README.md` is the user-facing manual. Keep it in sync when behaviour changes.

## Working with Anton

- For multi-step work, outline the plan first and wait for his OK. After each major step, say briefly what was done and what is next.
- Before deleting, overwriting or renaming a file he did not ask about, show what will change and wait. Do not touch files outside the project unless he asks.
- Answers short and direct. He wants opinions and open disagreement, not agreement.
- Verify before claiming. Read the code, run it, measure on real recordings. Detection thresholds come from measured score distributions, never from guesses.
- Long commands get short timeouts and a visible outcome. He got angry once waiting on commands that were failing silently.
- New scripts take settings as constants at the top of the file, not CLI arguments. `main.py` keeps its existing commands.
- Writing style in docs, comments and messages is complete sentences without colons, semicolons or em dashes.
- At the end of a task, list every file created or changed.
- Git work happens on a branch. Commit when he asks or when a step he approved is done and tested. `icons/` is gitignored on purpose, those are Steam's images.

## Layout

- `config.py` holds paths, setting defaults and every detection constant, each with how it was measured.
- `recording/` is about Steam's files. `session.py` finds recordings and converts video time to timeline time. `mpd.py` reads `session.mpd`. `timeline.py` loads and saves timeline JSON. `apps.py` looks up game names.
- `decode/reader.py` runs ffmpeg on contiguous chunk runs, fed through stdin, and yields cropped BGR frames at `SAMPLE_FPS`.
- `detect/` works on single frames. `detector.py` matches badge templates, `ocr.py` reads banner and tag text, `life.py` checks for the downed and deploy screens.
- `events/` works across frames. `tracker.py` groups frames into badge appearances and confirms texts, `life.py` turns screens into deaths, downs and revives, `rules.py` matches texts to marker rules, `highlights.py` makes one highlight per appearance.
- `markers/` plans and writes timeline entries, with backups. `icons.py` lists Steam's 46 icon names.
- `storage/` is SQLite (`battle-marker.db`, WAL, one connection per operation, `PRAGMA user_version` migrations in `db.py`). Settings, rules, scans with their badges and sightings, and cached game names.
- `service/` is the layer both the CLI and the window call. Never let `ui/` or `main.py` reach past it into the lower packages for real work.
- `ui/` is PySide6. A stacked window with the recordings list (`recordings_screen.py`) and the player screen (`recording_screen.py`), Rules and Settings dialogs, workers in QThreads (`workers.py`), and `player/` with the timeline bar, hover preview and icon drawing.
- `child_processes.py` puts the app into a Windows job object at startup, so ffmpeg and Tesseract die with it even after a crash.
- `bench_crop.py` times a scan with the old and the new crop without saving anything.

## Steam recordings

- `video\bg_<appid>_<YYYYMMDD>_<HHMMSS>\` holds `session.mpd`, `init-stream0/1.m4s` and `chunk-stream0/1-NNNNN.m4s`. Stream 0 is video, 1 is audio. Each chunk is 3 s of fMP4 starting with a keyframe, and chunk N starts at (N-1)*3 s of video time.
- `timelines\timeline_<appid><date>_<time>.json` holds markers. Times are milliseconds stored as strings. An empty list is written as `"entries": {}`.
- The timeline file name time is earlier than the video folder time. The difference (19 or 23 s so far) is the offset between video time and the timeline time Steam shows. `Session.to_timeline` and `to_video` convert.
- Only `"type": "event"` shows a custom icon. `usermarker` and `gameevent` always show the default pin.
- Steam keeps timelines in memory and rewrites them while running. Markers are written only with Steam closed, and Steam has to be started again to show them.
- Steam deletes old recordings, timelines included, when it needs space.

## Detection

- The crop (`ROI`) is 1516x780 at (500, 1100) in 4K. Badge positions are in ROI pixels. Growing it from 1250x550 cost nothing measurable, because the GPU decodes whole frames either way.
- Badges are found by NCC template matches (`templates/`). `tag_edge` or `score_zero` above 0.75 means a badge is present. Text is read only when its element matches at 0.9 or more, because fade frames give garbage OCR.
- The banner box is read at its drawn position. Tag rows are read box by box, so multi-box rows like SQUAD SUPPLY | EQUIPMENT DESTROYED work.
- The tag row sits at y 404 for badges with a skull or revive icon, 332 for skull-less badges with a player name, 274 for ones with neither. The tag box snaps to the nearest row.
- A text counts after 2 identical reads in one appearance. Text is re-read only when the bright pixels in its box change, since tag boxes are see-through and the scene moves behind them.
- No fuzzy matching. Anton accepts about 1 misread in 255.

## Deaths, downs and revives

- Downed screen is a white ring (centre 1420, 598, radius 78 in ROI pixels) around the heartbeat button. Score is the share of the ring brighter than its outside and near white. Downed frames score 0.5 to 1.0, nothing else went above 0.3 on a whole 30 min recording.
- Deploy screen is the class icon row, matched on Sobel edges against `deploy_icons.png` so a white selected box does not matter. Deploy frames score 0.98 to 1.0, everything else under 0.3.
- A down followed by the deploy screen within 60 s is DEATH, marked at the down. Otherwise it is DOWNED at the down plus REVIVED where it ended. The 60 s covers a detour through the loadout screen, which hides the class row.
- A deploy screen without a down is a death only if a badge or a down showed the player alive since the last spawn, so the deploy screen at match start does not count.
- Badges are not checked while the deploy screen shows. They are still read while downed, because assists show up then.
- Events are stored as appearances with one sighting of kind `life`. Migration 2 added the rules Death, Downed and Revived with source `life`.

## Scanning

- A scan is split into parts (`scan_parts`, default 3), each with its own ffmpeg, detector and trackers, in threads. This took Video Decode on the 5080 from about 30% to 99% and gave about 19x realtime.
- Each part decodes 2 chunks early and runs past its end until nothing that started inside is still open. It keeps only what started in its own stretch. A 3-part scan found the same badges as a single pass.
- Starting the decode at a different chunk can shift sampled frames by one, so a badge may differ by a frame between scans. That is not a seam bug.
- Cancel and errors stop every part and kill its ffmpeg. A cancelled scan saves what it covered and keeps older results elsewhere.

## Gotchas

- FFmpeg on Windows reads `file:///E:/...` as `/E:/...`. HLS playlists list chunks as plain `E:/...` paths.
- Qt's FFmpeg cannot open `session.mpd`. Playback goes through HLS playlists over the chunk files in `output/playlists/<recording>/`.
- A QThread worker must not be released inside its own finished signal. Release it with `QTimer.singleShot(0, ...)`.
- The Steam check (`tasklist`) and every child process use `CREATE_NO_WINDOW`, otherwise a console window flashes.
- SQL keywords cannot be column names. Columns are `pattern`, `time_offset`, `video_start` and `video_end`.
- A Rules dialog that rebuilt its whole table on every edit took 2.3 s per checkbox. Update only what changed.

## Testing

- Test detection on real recordings and look at the frames. Dump frames with `main.py dump` or ffmpeg on single chunks (`init-stream0.m4s` plus one chunk through stdin).
- For a threshold, compute the score on every keyframe of a long recording and check that the two groups have a clear gap.
- For scan changes, compare against a single pass on the same stretch. For speed, use `bench_crop.py` or the timings a scan prints per part.
- UI tests can run offscreen (`QT_QPA_PLATFORM=offscreen`) with a copy of the database.

## Status on 2026-11-11

- `main` is at `36e1c6d`. The branch `death-detection` adds the bigger crop, death detection, skull-less tag reading and the new badge table.
- Not yet checked on Anton's machine. Rescan `bg_2807960_20261108_215340` and expect deaths near video 1721 s and 1760 s and a revived down at video 1977.6 s. Kill the app in Task Manager mid-scan and check no `ffmpeg.exe` is left.
- `output/_probe/` holds thumbnails from the death research and can be deleted once Anton agrees. `markers.json` and `output/bg_*.json` are only the old import source.
- Anton keeps a project note and session history in his Obsidian vault "My Second Brain", under `Efforts/Projects/battle-marker/` and `AIOS/History/`.
