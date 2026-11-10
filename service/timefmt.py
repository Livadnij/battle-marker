"""Timeline time as text, the H:MM:SS form Steam shows."""


def parse_time(value: str) -> float:
    seconds = 0.0
    for part in value.split(":"):
        seconds = seconds * 60 + float(part)
    return seconds


def fmt(seconds: float) -> str:
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{sign}{int(h)}:{int(m):02d}:{s:04.1f}"
