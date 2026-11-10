"""HLS playlists over Steam's recording chunks, so a player can read them in place.

Every Steam chunk is a self-contained 3 second fMP4 fragment that starts with
a keyframe, and the init segment holds what all chunks share. That is the
layout HLS describes, so a playlist that lists the chunk files lets a player
seek straight to any chunk and read only that one file. Nothing is joined or
copied.

The playlists describe the chunks on disk at the moment they are written.
Steam keeps deleting the oldest chunks, so they are rebuilt every time a
recording is opened.
"""

from dataclasses import dataclass
from pathlib import Path

import config
from recording.mpd import VideoTrack, read_audio_track
from recording.session import Session


@dataclass(frozen=True)
class Playback:
    master: Path  # the playlist to give the player
    starts_at: float  # timeline time of player position 0
    length: float  # seconds of video in the playlist
    has_audio: bool


def _ref(path: Path) -> str:
    """How a chunk is written in a playlist.

    A plain absolute path with forward slashes, like E:/Steam/... on Windows.
    FFmpeg on Windows turns file:///E:/... into the path /E:/..., which does
    not exist, while it reads a drive letter path as a local file.
    """
    return path.resolve().as_posix()


def _chunks(session: Session, track: VideoTrack) -> list[int]:
    prefix = f"chunk-stream{track.representation_id}-"
    return sorted(int(p.stem.removeprefix(prefix)) for p in session.video_dir.glob(f"{prefix}*.m4s"))


def _media_playlist(session: Session, track: VideoTrack, numbers: list[int]) -> str:
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:7",
        f"#EXT-X-TARGETDURATION:{int(track.segment_seconds + 0.999)}",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        f"#EXT-X-MEDIA-SEQUENCE:{numbers[0]}",
        f'#EXT-X-MAP:URI="{_ref(session.video_dir / track.init_name)}"',
    ]
    previous = None
    for number in numbers:
        if previous is not None and number != previous + 1:
            lines.append("#EXT-X-DISCONTINUITY")  # a chunk is missing, time jumps here
        lines.append(f"#EXTINF:{track.segment_seconds:.3f},")
        lines.append(_ref(session.video_dir / track.chunk_name(number)))
        previous = number
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


def build_playback(session: Session) -> Playback | None:
    """Writes the playlists for a recording. None when no video is left on disk."""
    video = session.track
    video_numbers = _chunks(session, video)
    if not video_numbers:
        return None

    folder = config.OUTPUT_DIR / "playlists" / session.name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "video.m3u8").write_text(_media_playlist(session, video, video_numbers), encoding="utf-8")

    audio = read_audio_track(session.video_dir / "session.mpd")
    # Audio chunks share the video's numbering. Only numbers present in both are listed,
    # so the two playlists always cover the same time.
    audio_numbers = sorted(set(_chunks(session, audio)) & set(video_numbers)) if audio else []
    has_audio = bool(audio_numbers)

    master = ["#EXTM3U", "#EXT-X-VERSION:7"]
    codecs = video.codec
    if has_audio:
        (folder / "audio.m3u8").write_text(_media_playlist(session, audio, audio_numbers), encoding="utf-8")
        master.append('#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="game",NAME="Game",'
                      'DEFAULT=YES,AUTOSELECT=YES,URI="audio.m3u8"')
        codecs += f",{audio.codec}"
    stream_inf = f'#EXT-X-STREAM-INF:BANDWIDTH=40000000,RESOLUTION={video.width}x{video.height},CODECS="{codecs}"'
    if has_audio:
        stream_inf += ',AUDIO="game"'
    master += [stream_inf, "video.m3u8"]
    (folder / "master.m3u8").write_text("\n".join(master) + "\n", encoding="utf-8")

    return Playback(
        master=folder / "master.m3u8",
        starts_at=session.to_timeline(video.chunk_start(video_numbers[0])),
        length=len(video_numbers) * video.segment_seconds,
        has_audio=has_audio,
    )
