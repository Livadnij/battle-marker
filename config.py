"""Project-wide settings. Paths and thresholds live here, nothing else does."""

from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent

# Steam writes video/, timelines/ and clips/ under this folder.
RECORDINGS_ROOT = Path(r"E:\Steam\gamerecordings")

# ffmpeg executable. Needs a build with NVDEC (hevc_cuvid) for GPU decoding.
FFMPEG = "ffmpeg"

# Badge region in a 3840x2160 frame, as (left, top, right, bottom).
# The badge stack is right-aligned near x 1500 and grows leftward,
# so the box leaves a lot of room on the left and above the banner row.
SOURCE_SIZE = (3840, 2160)
ROI = (500, 1100, 1750, 1650)

# Frames analysed per second of video. Badges stay on screen about 2.5 s.
SAMPLE_FPS = 5

# Sub-regions inside the ROI, as (left, top, right, bottom) in ROI pixels.
# Each template is searched inside its region, so small shifts are tolerated.
REGIONS = {
    "tag_edge": (974, 394, 1022, 486),      # right end of the KILL / HEADSHOT box
    "banner_bars": (954, 158, 1022, 240),   # striped bars right of the ribbon icon
    "score_zero": (1100, 276, 1200, 352),   # last "0" of the score, has a dark halo
    "headshot_tag": (796, 398, 1016, 482),  # the whole HEADSHOT box
}
# Text areas handed to OCR.
BANNER_TEXT_BOX = (0, 165, 840, 235)  # white ribbon box, grows leftward
TAG_TEXT_BOX = (250, 405, 1010, 475)  # KILL, HEADSHOT, KILL x2, OFFENSIVE

# Template match thresholds (normalised cross-correlation, -1..1).
# Measured on real frames. Badge frames score 0.9 to 1.0, frames without a
# badge stay under 0.55.
PRESENCE_THRESHOLD = 0.75  # tag_edge or score_zero
BANNER_THRESHOLD = 0.75
HEADSHOT_THRESHOLD = 0.80
# Text is only read once its element matches this well. Fade-in and fade-out
# frames score lower and give garbage OCR.
READABLE_THRESHOLD = 0.90

# Tesseract executable. Default install path of the UB Mannheim Windows build.
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# A badge counts as present after this many consecutive positive samples.
CONFIRM_SAMPLES = 2
# Samples a badge may drop out for without ending the appearance.
GAP_TOLERANCE = 2

# A text area is re-read with OCR when its pixels change by more than this
# mean absolute difference (0..255). Catches DOUBLE KILL turning into GUNSLINGER.
TEXT_CHANGE_THRESHOLD = 12.0
# The same text has to be read this many times in one appearance to count.
# A single odd read during an animation is dropped.
TEXT_CONFIRM_READS = 2

# Qualifying sightings closer than this merge into one highlight marker.
HIGHLIGHT_MERGE_SECONDS = 6.0
# A new marker is skipped when an existing timeline entry is this close.
MARKER_DEDUP_SECONDS = 3.0
# Marker is placed this many seconds before the badge appeared.
MARKER_LEAD_SECONDS = 0.0

# Which badges become markers and which icon each one gets.
MARKERS_FILE = PROJECT_DIR / "markers.json"

TEMPLATES_DIR = PROJECT_DIR / "templates"
OUTPUT_DIR = PROJECT_DIR / "output"
BACKUP_DIR = PROJECT_DIR / "backups"
