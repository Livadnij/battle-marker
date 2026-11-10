"""Steam's built-in timeline icons.

Source is the Steamworks Timeline documentation. Besides these names,
steam_0 to steam_99 draw a number.
"""

import re

NAMED_ICONS = [
    "steam_marker", "steam_achievement", "steam_attack", "steam_bolt", "steam_bookmark",
    "steam_bug", "steam_cart", "steam_caution", "steam_chat", "steam_checkmark",
    "steam_chest", "steam_circle", "steam_combat", "steam_completed", "steam_crown",
    "steam_death", "steam_defend", "steam_diamond", "steam_edit", "steam_effect",
    "steam_explosion", "steam_fix", "steam_flag", "steam_gem", "steam_group",
    "steam_heart", "steam_info", "steam_invalid", "steam_minus", "steam_pair",
    "steam_person", "steam_plus", "steam_purchase", "steam_question", "steam_ribbon",
    "steam_screenshot", "steam_scroll", "steam_square", "steam_star", "steam_starburst",
    "steam_timer", "steam_transfer", "steam_triangle", "steam_trophy", "steam_view",
    "steam_x",
]

_NUMBER_ICON = re.compile(r"steam_(\d{1,2})")


def is_valid_icon(name: str) -> bool:
    return name in NAMED_ICONS or _NUMBER_ICON.fullmatch(name) is not None
