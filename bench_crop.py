"""Times a scan of the same stretch with the old and the new crop. Run it with `uv run bench_crop.py`.

Nothing is saved, the database and the timelines stay as they are. Each
crop runs twice, alternating, so the second pair reads chunks from the disk
cache like the first pair's second half did.
"""

import time

import config
import service.scan as scan
from service.sessions import list_sessions
from storage.settings import get_settings

# Recording to time. None takes the newest Battlefield recording with video.
SESSION_NAME = None
# Video stretch to scan, seconds after the first chunk Steam still has.
SKIP_SECONDS = 60
SCAN_SECONDS = 300
ROUNDS = 2

CROPS = {
    "old crop": config.BADGE_ONLY_ROI,
    "new crop": config.ROI,
}


def main() -> None:
    infos = [i for i in list_sessions() if i.supported and i.covers_from is not None]
    if SESSION_NAME is not None:
        infos = [i for i in infos if i.name == SESSION_NAME]
    if not infos:
        raise SystemExit("No Battlefield recording with video found.")
    info = max(infos, key=lambda i: i.name.split("_", 2)[-1])
    session = info.session
    start = session.to_video(info.covers_from) + SKIP_SECONDS
    end = start + SCAN_SECONDS

    scan.save_scan = lambda *args, **kwargs: None  # timing only, keep the stored results
    print(f"{session.name}, video {start:.0f}s to {end:.0f}s, "
          f"{get_settings().scan_parts} parts, {'GPU' if get_settings().gpu_decoding else 'CPU'}")

    results: dict[str, list[float]] = {name: [] for name in CROPS}
    for round_number in range(1, ROUNDS + 1):
        for name, roi in CROPS.items():
            config.ROI = roi
            began = time.perf_counter()
            result = scan.scan_session(session, start=start, end=end, gpu=get_settings().gpu_decoding)
            elapsed = time.perf_counter() - began
            results[name].append(elapsed)
            print(f"  round {round_number}, {name}: {elapsed:.1f}s, "
                  f"{result.video_seconds / elapsed:.1f}x realtime, {len(result.appearances)} badges", flush=True)

    old, new = min(results["old crop"]), min(results["new crop"])
    print(f"Best times: old {old:.1f}s, new {new:.1f}s. The new crop is {100 * (new / old - 1):+.0f}%.")


if __name__ == "__main__":
    main()
