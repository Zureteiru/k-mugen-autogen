import argparse
import logging
import os
import re
import shutil
import subprocess
import sys

import yt_dlp

from aligner import force_align_japanese, isolate_vocals
from ass_compiler import compile_ass
from fast_lyrics import fetch_and_parse_lyrics, parse_lrc_text
from models import LyricLine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("k-mugen-autogen")


def is_url(source: str) -> bool:
    """Check if the provided source string is a network URL."""
    return source.startswith(("http://", "https://", "ftp://", "www."))


def _launch_mpv(mpv_cmd: list[str]) -> None:
    """Launch the mpv player and wait for it to exit."""
    subprocess.run(mpv_cmd, check=True)


def _find_mpv_binary() -> str | None:
    """Return the path to mpv found on PATH, or None."""
    return shutil.which("mpv")


def _safe_filename(s: str) -> str:
    """Replace characters that are invalid in file names and strip trailing dots/spaces."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", s)
    return s.rstrip(". ")


def download_video_yt_dlp(source: str, output_dir: str = "./downloads") -> tuple[str, dict]:
    """Download video from a URL using yt-dlp, returning (path, info); local files return (abspath, {})."""
    if not is_url(source):
        if not os.path.exists(source):
            raise FileNotFoundError(f"Local video file does not exist: {source}")
        return os.path.abspath(source), {}

    os.makedirs(output_dir, exist_ok=True)
    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": os.path.join(output_dir, "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": False,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(source, download=True)
        return ydl.prepare_filename(info), info


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="k-mugen-autogen",
        description="Generate Karaoke Mugen-style word-synced Romaji .ass subtitles from YouTube URLs or local audio.",
    )
    parser.add_argument(
        "source",
        help="YouTube URL or local file path to audio/video",
    )
    parser.add_argument(
        "--artist",
        default=None,
        help="Artist name, e.g., 'Sakanaction' (taken from the URL metadata if omitted)",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Song title, e.g., 'Shin Takarajima' (taken from the URL metadata if omitted)",
    )
    parser.add_argument(
        "--lyrics-file",
        default=None,
        help="Optional path to a plain .txt file with Japanese lyrics (fallback for forced alignment)",
    )
    parser.add_argument(
        "--remove-vocals",
        action="store_true",
        help="Download audio, isolate vocal/instrumental stems, and play instrumental track in mpv",
    )
    parser.add_argument(
        "--no-play",
        action="store_true",
        help="Skip launching mpv player (background generation mode)",
    )

    args = parser.parse_args()

    if not is_url(args.source) and (not args.artist or not args.title):
        parser.error("--artist and --title are required for local files")

    logger.info("Preparing media from source...")
    media_path, info = download_video_yt_dlp(args.source, output_dir="./downloads")

    args.artist = args.artist or info.get("artist") or info.get("uploader")
    args.title = args.title or info.get("track") or info.get("title")
    if not args.artist or not args.title:
        parser.error("--artist and --title could not be read from the URL metadata; pass them explicitly")

    logger.info(f"Processing '{args.artist} - {args.title}' from source: {args.source}")

    lines: list[LyricLine] | None = None
    vocal_stem_path: str | None = None
    inst_stem_path: str | None = None

    # Step 1: Obtain lyrics text
    raw_lyrics_text = None
    fallback_lines: list[LyricLine] | None = None

    if args.lyrics_file:
        logger.info(f"Using provided lyrics file: {args.lyrics_file}")
        if not os.path.exists(args.lyrics_file):
            logger.error(f"Provided --lyrics-file does not exist: {args.lyrics_file}")
            sys.exit(1)
        with open(args.lyrics_file, "r", encoding="utf-8") as f:
            file_content = f.read().strip()
        if "[" in file_content and re.search(r"\[\d{1,2}:\d{2}", file_content):
            logger.info("Detected LRC format in --lyrics-file. Parsing guide timestamps...")
            fallback_lines = parse_lrc_text(file_content)
            if fallback_lines:
                raw_lyrics_text = "\n".join(l.original_text for l in fallback_lines)
                logger.info(f"Parsed {len(fallback_lines)} lyric lines from LRC file.")
            else:
                raw_lyrics_text = file_content
        else:
            raw_lyrics_text = file_content
    else:
        logger.info("Step 1: Attempting to fetch online lyrics...")
        fetched = fetch_and_parse_lyrics(args.artist, args.title)
        if fetched:
            raw_lyrics_text, fallback_lines = fetched
            if fallback_lines:
                logger.info(f"Successfully retrieved lyrics text ({len(fallback_lines)} lines).")
            else:
                logger.info("Retrieved unsynced lyrics text (no timestamps).")

    if not raw_lyrics_text:
        logger.error(
            f"Could not find lyrics for '{args.artist} - {args.title}' "
            "and no --lyrics-file was provided. Cannot proceed."
        )
        sys.exit(1)

    if args.remove_vocals:
        logger.info("Step 2b: Preparing instrumental stem for vocal removal...")
        logger.info(f"Running stem isolation on {media_path}...")
        vocal_stem_path, inst_stem_path = isolate_vocals(media_path, output_dir="./stems")
        align_target = vocal_stem_path
    else:
        align_target = media_path

    logger.info("Step 2c: Running forced alignment with Whisper on media for exact syllable sync...")
    try:
        lines = force_align_japanese(align_target, raw_lyrics_text, lrc_guide_lines=fallback_lines)
    except Exception as e:
        logger.exception(f"Forced alignment failed ({e}). Falling back to LRC timing...")
        lines = fallback_lines

    if not lines:
        logger.error("Failed to generate or align lyric lines.")
        sys.exit(1)

    logger.info(f"Successfully obtained {len(lines)} synced lyric lines.")

    # Step 3: Compile ASS subtitles
    output_dir = "./output"
    os.makedirs(output_dir, exist_ok=True)
    ass_path = os.path.join(output_dir, _safe_filename(f"{args.artist} - {args.title}") + ".ass")
    logger.info(f"Step 3: Compiling ASS subtitle file to: {ass_path}")
    compile_ass(lines, title=args.title, output_path=ass_path)
    logger.info("ASS compilation complete.")

    mpv_bin = _find_mpv_binary()
    norm_ass_path = os.path.abspath(ass_path).replace("\\", "/")

    # Step 4: Launch mpv
    if args.no_play:
        logger.info("Step 4: --no-play flag is set. Skipping mpv launch. Generation complete!")
        logger.info(f"Generated ASS subtitle file: {ass_path}")
        return

    if mpv_bin is None:
        logger.warning("mpv was not found on PATH. Skipping playback.")
        logger.info(f"Generated ASS subtitle file: {ass_path}")
        return

    logger.info("Step 4: Launching mpv player...")
    mpv_cmd = [
        mpv_bin,
        "--force-window=immediate",
        "--ontop",
        "--focus-on=open",
        "--autofit=1280x720",
        "--geometry=50%:50%",
        "--border=yes",
        "--window-minimized=no",
        "--hwdec=auto-safe",
        f"--title=k-mugen: {args.artist} - {args.title}",
        f"--sub-file={norm_ass_path}",
    ]

    if inst_stem_path:
        norm_play_audio = os.path.abspath(inst_stem_path).replace("\\", "/")
        mpv_cmd.append(f"--audio-file={norm_play_audio}")

    norm_video_path = os.path.abspath(media_path).replace("\\", "/")
    mpv_cmd.append(norm_video_path)

    logger.info(f"Executing: {' '.join(mpv_cmd)}")

    try:
        _launch_mpv(mpv_cmd)
    except FileNotFoundError:
        logger.warning(
            "mpv is not installed or not found on PATH. Subtitles have been generated successfully:"
        )
        logger.info(f"  Subtitle file: {ass_path}")
        logger.info(f"To play manually, install mpv and run:\n  {' '.join(mpv_cmd)}")
    except subprocess.CalledProcessError as e:
        logger.error(f"mpv exited with returncode {e.returncode}")


if __name__ == "__main__":
    main()
