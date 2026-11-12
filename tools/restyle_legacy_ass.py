"""Re-style an old .ass (made before the Karaoke Mugen restyle) without re-running alignment.

Usage (from the repo root):
    python tools/restyle_legacy_ass.py "output/Old.ass" "output/New (KM style).ass" "Song title"

Reads the absolute syllable timings from the old file's \\k / \\kf tags and recompiles them
with ass_compiler.compile_ass (kara.moe style).
"""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from ass_compiler import compile_ass
from models import LyricLine, MoraTiming

src, dst, title = sys.argv[1:4]
def t(s):
    h, m, sec = s.split(":"); return int(h) * 3600 + int(m) * 60 + float(sec)
lines = []
for ln in open(src, encoding="utf-8-sig"):
    if not ln.startswith("Dialogue:"):
        continue
    f = ln.rstrip("\n").split(",", 9)
    cur = t(f[1]); morae = []
    for tag, cs, text in re.findall(r"\{\\(kf|ko|k|K)(\d+)\}([^{]*)", f[9]):
        d = int(cs) / 100
        if text:
            morae.append(MoraTiming(text, text, cur, cur + d))
        cur += d
    if morae:
        lines.append(LyricLine("".join(m.romaji for m in morae).strip(), morae[0].start_sec, morae[-1].end_sec, morae))
compile_ass(lines, title, dst)
print(len(lines), "lines ->", dst)
