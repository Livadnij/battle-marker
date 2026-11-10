"""Project constants. Detection tuning and file locations live here.

Settings a user changes, like the Steam folder or the ffmpeg path, are kept
in the database and edited in the Settings dialog. The DEFAULT_ values below
are what they start as.
"""

from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent

# ---- database and files ----------------------------------------------------

DB_FILE = PROJECT_DIR / "battle-marker.db"
TEMPLATES_DIR = PROJECT_DIR / "templates"
OUTPUT_DIR = PROJECT_DIR / "output"
BACKUP_DIR = PROJECT_DIR / "backups"
# Recording previews shown in the window.
THUMBNAILS_DIR = OUTPUT_DIR / "thumbnails"
THUMBNAIL_WIDTH = 240

# Files from before the database. They are imported once, the first time the
# database is created, and not read again after that.
LEGACY_MARKERS_FILE = PROJECT_DIR / "markers.json"
LEGACY_APP_NAMES_FILE = OUTPUT_DIR / "app_names.json"
LEGACY_SCAN_LOGS_DIR = OUTPUT_DIR

# ---- defaults for the user settings ----------------------------------------

# Steam writes video/, timelines/ and clips/ under this folder.
DEFAULT_RECORDINGS_ROOT = Path(r"E:\Steam\gamerecordings")
# ffmpeg executable. Needs a build with NVDEC (hevc_cuvid) for GPU decoding.
DEFAULT_FFMPEG = "ffmpeg"
# Tesseract executable. Default install path of the UB Mannheim Windows build.
DEFAULT_TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
DEFAULT_GPU_DECODING = True
# A recording is scanned as this many parts at once, each with its own ffmpeg.
DEFAULT_SCAN_PARTS = 3
# A new marker is skipped when an existing timeline entry is this close.
DEFAULT_DEDUP_SECONDS = 3.0
# Marker is placed this many seconds before the badge appeared.
DEFAULT_LEAD_SECONDS = 0.0

# ---- games -----------------------------------------------------------------

# Games whose badges the templates and OCR were built for. Other recordings
# are listed but can't be scanned. The name here is shown as is.
SUPPORTED_APPS = {"2807960": "Battlefield 6"}

# ---- detection, tied to the templates ---------------------------------------

SOURCE_SIZE = (3840, 2160)
# Region of a 3840x2160 frame that gets analysed, as (left, top, right, bottom).
# The badge stack is right-aligned near x 1500 and grows leftward, so the box
# leaves a lot of room on the left and above the banner row. It reaches down
# and right far enough for the heartbeat button of the downed screen and the
# first class icons of the deploy screen. The GPU decodes the whole frame
# either way, the size only changes how much is copied back.
ROI = (500, 1100, 2016, 1880)
# The region before the downed and deploy screens were added, kept for bench_crop.py.
BADGE_ONLY_ROI = (500, 1100, 1750, 1650)

# Frames analysed per second of video. Badges stay on screen about 2.5 s.
SAMPLE_FPS = 5

# Sub-regions inside the ROI, as (left, top, right, bottom) in ROI pixels.
# Each template is searched inside its region, so small shifts are tolerated.
REGIONS = {
    # Right end of a tag box. Searched over the whole stack height, because
    # badges without a skull or revive icon draw their tag row higher.
    "tag_edge": (974, 260, 1022, 486),
    "banner_bars": (954, 158, 1022, 240),   # striped bars right of the ribbon icon
    "score_zero": (1100, 276, 1200, 352),   # last "0" of the score, has a dark halo
    "headshot_tag": (796, 398, 1016, 482),  # the whole HEADSHOT box
}
# Text areas handed to OCR.
BANNER_TEXT_BOX = (0, 165, 840, 235)  # white ribbon box, grows leftward
TAG_TEXT_BOX = (250, 405, 1010, 475)  # KILL, HEADSHOT, KILL x2, OFFENSIVE
# Rows where tag_edge matches, measured. 404 for badges with an icon, where
# the tag sits in TAG_TEXT_BOX, 332 with a player name and no icon, 274 with
# neither. The box moves to the row nearest the match, so a match that
# wobbles by a pixel does not count as new text.
TAG_ROW_TOPS = (404, 332, 274)

# Template match thresholds (normalised cross-correlation, -1..1).
# Measured on real frames. Badge frames score 0.9 to 1.0, frames without a
# badge stay under 0.55.
PRESENCE_THRESHOLD = 0.75  # tag_edge or score_zero
BANNER_THRESHOLD = 0.75
HEADSHOT_THRESHOLD = 0.80
# Text is only read once its element matches this well. Fade-in and fade-out
# frames score lower and give garbage OCR.
READABLE_THRESHOLD = 0.90

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

# ---- downed and deploy screens ---------------------------------------------

# Heartbeat button of the downed screen, as (centre x, centre y, radius) in
# ROI pixels. It stays a ring while a teammate revives you, dashed then.
DOWNED_RING = (1420, 598, 78)
# Share of the ring that has to be drawn white against its outside. Downed
# frames score 0.5 to 1.0, a 30 minute recording had nothing else above 0.3.
DOWNED_THRESHOLD = 0.35
# Class icon row of the deploy screen, matched on its edges so it does not
# matter which class box is white. Template from deploy_icons.png, searched
# in this area of the ROI.
DEPLOY_REGION = (1146, 646, 1434, 780)
# Deploy screens score 0.98 to 1.0, everything else under 0.3.
DEPLOY_THRESHOLD = 0.6
# Consecutive samples a downed or deploy screen needs before it counts.
LIFE_CONFIRM_SAMPLES = 2
# The downed button may vanish this long, behind the scoreboard or a flash,
# without ending the down.
DOWNED_GAP_SECONDS = 4
# A down is a death when the deploy screen shows within this long after it
# ends, and a revive otherwise. Long enough for a detour through the loadout
# screen, which hides the class row.
DEATH_WAIT_SECONDS = 60
