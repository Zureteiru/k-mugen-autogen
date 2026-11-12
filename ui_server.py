"""Local test UI for k-mugen-autogen.

Run:  .venv/bin/python ui_server.py   (Windows: .venv\\Scripts\\python.exe ui_server.py)  ->  http://127.0.0.1:8765
Standard library only (plus the project's own modules). Binds to localhost.
"""
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

DIRS = {
    "output": os.path.join(BASE, "output"),
    "downloads": os.path.join(BASE, "downloads"),
    "uploads": os.path.join(BASE, "uploads"),
}
MEDIA_EXT = {".mp4", ".mkv", ".webm", ".mov", ".m4a", ".mp3", ".wav", ".flac", ".ogg", ".opus"}
PY = next((p for p in (os.path.join(BASE, ".venv", "bin", "python"),            # macOS / Linux
                        os.path.join(BASE, ".venv", "Scripts", "python.exe"))  # Windows
           if os.path.exists(p)), sys.executable)

JOBS: dict[str, dict] = {}

# libass-in-the-browser (JASSUB) and the fonts the Karaoke Mugen style uses
VENDOR = os.path.join(BASE, "ui", "vendor", "jassub")
_WIN_FONTS = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
_FONT_CANDIDATES = {
    "arial.ttf": ["/System/Library/Fonts/Supplemental/Arial.ttf", os.path.join(_WIN_FONTS, "arial.ttf")],
    "arial-bold.ttf": ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", os.path.join(_WIN_FONTS, "arialbd.ttf")],
}
FONTS = {k: next(p for p in ps if os.path.isfile(p)) for k, ps in _FONT_CANDIDATES.items() if any(os.path.isfile(p) for p in ps)}
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("font/woff2", ".woff2")


def safe_path(kind: str, name: str) -> str | None:
    d = DIRS.get(kind)
    if not d or name != os.path.basename(name) or name.startswith("."):
        return None
    p = os.path.join(d, name)
    return p if os.path.isfile(p) else None


def list_files() -> dict:
    out = {}
    for kind, d in DIRS.items():
        items = []
        if os.path.isdir(d):
            for n in sorted(os.listdir(d)):
                p = os.path.join(d, n)
                if os.path.isfile(p) and not n.startswith("."):
                    items.append({"name": n, "size": os.path.getsize(p), "mtime": os.path.getmtime(p)})
        out[kind] = items
    return out


# ---------- offline helpers ----------
def api_romanize(text: str) -> dict:
    from japanese_utils import get_morae_for_text

    lines = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        morae = get_morae_for_text(raw)
        words, cur = [], []
        for m in morae:
            cur.append(m)
            if m["is_token_end"]:
                words.append(cur)
                cur = []
        if cur:
            words.append(cur)
        lines.append({"text": raw, "romaji": " ".join("".join(m["rom"] for m in w) for w in words), "morae": morae})
    return {"lines": lines}


def api_lrc_to_ass(lrc: str, title: str) -> dict:
    from ass_compiler import compile_ass
    from fast_lyrics import parse_lrc_text

    parsed = parse_lrc_text(lrc)
    if not parsed:
        return {"error": "No timestamped lines found. Expected lines like [00:12.34] text"}
    tmp = os.path.join(DIRS["uploads"], ".lrc_preview.ass")
    os.makedirs(DIRS["uploads"], exist_ok=True)
    content = compile_ass(parsed, title=title or "LRC preview", output_path=tmp)
    return {"ass": content, "lines": len(parsed)}


def run_tests() -> dict:
    r = subprocess.run([PY, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", "tests/"],
                       cwd=BASE, capture_output=True, text=True, timeout=300)
    return {"ok": r.returncode == 0, "output": r.stdout + r.stderr}


# ---------- pipeline job ----------
def start_job(p: dict) -> dict:
    source = (p.get("source") or "").strip()
    if not source:
        return {"error": "Source is required (URL or uploaded file)."}
    is_url = source.startswith(("http://", "https://", "www."))
    if not is_url:
        up = safe_path("uploads", os.path.basename(source)) or (source if os.path.isfile(source) else None)
        if not up:
            return {"error": f"Local file not found: {source}"}
        source = up
        if not (p.get("artist") and p.get("title")):
            return {"error": "Artist and title are required for local files."}
    cmd = [PY, "-u", "main.py", source, "--no-play"]
    for k in ("artist", "title"):
        if p.get(k):
            cmd += [f"--{k}", p[k]]
    jid = uuid.uuid4().hex[:8]
    if (p.get("lyrics") or "").strip():
        os.makedirs(DIRS["uploads"], exist_ok=True)
        lp = os.path.join(DIRS["uploads"], f"lyrics_{jid}.txt")
        with open(lp, "w", encoding="utf-8") as f:
            f.write(p["lyrics"])
        cmd += ["--lyrics-file", lp]
    if p.get("remove_vocals"):
        cmd.append("--remove-vocals")

    started = time.time()

    def finish(job):
        res = {"ass": None, "media": None}
        for kind, exts in (("output", {".ass"}), ("downloads", MEDIA_EXT)):
            d = DIRS[kind]
            if os.path.isdir(d):
                fresh = [(os.path.getmtime(os.path.join(d, n)), n) for n in os.listdir(d)
                         if os.path.splitext(n)[1].lower() in exts and os.path.getmtime(os.path.join(d, n)) >= started - 1]
                if fresh:
                    res["ass" if kind == "output" else "media"] = {"kind": kind, "name": max(fresh)[1]}
        if not res["media"] and not is_url:
            res["media"] = {"kind": "uploads", "name": os.path.basename(source)}
        if res["ass"] and res["media"]:
            mm = load_media_map()
            mm[res["ass"]["name"]] = f'{res["media"]["kind"]}/{res["media"]["name"]}'
            save_media_map(mm)
        return res

    return spawn(cmd, finish, jid)


def spawn(cmd: list[str], on_done=None, jid: str | None = None) -> dict:
    """Run a subprocess as a pollable job; on_done(job) returns the job's result."""
    jid = jid or uuid.uuid4().hex[:8]
    proc = subprocess.Popen(cmd, cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", bufsize=1)
    job = {"id": jid, "cmd": cmd[1:], "log": [], "status": "running", "proc": proc, "result": None}
    JOBS[jid] = job

    def pump():
        buf = ""
        while True:  # split on \r too, so ffmpeg / yt-dlp progress lines show up live
            ch = proc.stdout.read(1)
            if not ch:
                break
            if ch in "\r\n":
                if buf.strip():
                    job["log"].append(buf)
                buf = ""
            else:
                buf += ch
        if buf.strip():
            job["log"].append(buf)
        rc = proc.wait()
        try:
            job["result"] = on_done(job) if on_done else None
        except Exception as e:
            job["log"].append(f"[ui] post-processing failed: {e}")
        if job["status"] != "cancelled":
            job["status"] = "done" if rc == 0 else "failed"

    threading.Thread(target=pump, daemon=True).start()
    return {"id": jid}


# ---------- media helpers ----------
MAP_PATH = os.path.join(DIRS["output"], ".media_map.json")


def load_media_map() -> dict:
    try:
        with open(MAP_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_media_map(mm: dict) -> None:
    os.makedirs(DIRS["output"], exist_ok=True)
    with open(MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(mm, f, ensure_ascii=False, indent=1)


def probe(path: str) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {}
    r = subprocess.run([ffprobe, "-v", "error", "-show_entries", "stream=codec_type,codec_name", "-of", "json", path],
                       capture_output=True, text=True, timeout=30)
    try:
        streams = json.loads(r.stdout).get("streams", [])
    except ValueError:
        return {}
    return {s["codec_type"]: s["codec_name"] for s in streams if s.get("codec_type") in ("video", "audio")}


def start_transcode(kind: str, name: str) -> dict:
    src = safe_path(kind, name)
    ffmpeg = shutil.which("ffmpeg")
    if not src:
        return {"error": "file not found"}
    if not ffmpeg:
        return {"error": "ffmpeg is not on PATH"}
    os.makedirs(DIRS["uploads"], exist_ok=True)
    out_name = os.path.splitext(name)[0] + ".h264.mp4"
    out = os.path.join(DIRS["uploads"], out_name)
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-stats", "-i", src,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out]

    def done(job):
        if job["proc"].returncode == 0:
            mm = load_media_map()  # re-point subtitles that used the original file
            for k, v in mm.items():
                if v == f"{kind}/{name}":
                    mm[k] = f"uploads/{out_name}"
            save_media_map(mm)
            return {"media": {"kind": "uploads", "name": out_name}}
        return None

    return spawn(cmd, done)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # quiet
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def do_GET(self):
        u = urlparse(self.path)
        path = unquote(u.path)
        if path == "/":
            return self._serve(os.path.join(BASE, "ui", "index.html"))
        if path == "/api/files":
            return self._json({**list_files(), "media_map": load_media_map()})
        m = re.fullmatch(r"/api/probe/(\w+)/(.+)", path)
        if m:
            p = safe_path(m.group(1), m.group(2))
            return self._json(probe(p) if p else {"error": "not found"})
        m = re.fullmatch(r"/api/job/(\w+)", path)
        if m:
            job = JOBS.get(m.group(1))
            if not job:
                return self._json({"error": "unknown job"}, 404)
            since = int(parse_qs(u.query).get("since", ["0"])[0])
            return self._json({"status": job["status"], "log": job["log"][since:], "next": len(job["log"]),
                               "result": job["result"], "cmd": " ".join(job["cmd"])})
        m = re.fullmatch(r"/vendor/jassub/([\w.\-]+)", path)
        if m and m.group(1) in os.listdir(VENDOR):
            return self._serve(os.path.join(VENDOR, m.group(1)))
        m = re.fullmatch(r"/font/([\w.\-]+)", path)
        if m and m.group(1) in FONTS:
            return self._serve(FONTS[m.group(1)])
        m = re.fullmatch(r"/file/(\w+)/(.+)", path)
        if m:
            p = safe_path(m.group(1), m.group(2))
            if p:
                return self._serve(p)
        self.send_error(404)

    def do_POST(self):
        u = urlparse(self.path)
        try:
            if u.path == "/api/upload":
                name = os.path.basename(parse_qs(u.query).get("name", ["upload.bin"])[0]) or "upload.bin"
                name = re.sub(r"[^\w.\- ]", "_", name).lstrip(".") or "upload.bin"
                os.makedirs(DIRS["uploads"], exist_ok=True)
                with open(os.path.join(DIRS["uploads"], name), "wb") as f:
                    remaining = int(self.headers.get("Content-Length") or 0)
                    while remaining > 0:
                        chunk = self.rfile.read(min(1 << 20, remaining))
                        if not chunk:
                            break
                        f.write(chunk)
                        remaining -= len(chunk)
                return self._json({"name": name})
            body = json.loads(self._body() or b"{}")
            if u.path == "/api/romanize":
                return self._json(api_romanize(body.get("text", "")))
            if u.path == "/api/lrc-to-ass":
                return self._json(api_lrc_to_ass(body.get("lrc", ""), body.get("title", "")))
            if u.path == "/api/run":
                return self._json(start_job(body))
            if u.path == "/api/transcode":
                return self._json(start_transcode(body.get("kind", ""), body.get("name", "")))
            if u.path == "/api/tests":
                return self._json(run_tests())
            m = re.fullmatch(r"/api/cancel/(\w+)", u.path)
            if m and m.group(1) in JOBS:
                j = JOBS[m.group(1)]
                j["status"] = "cancelled"
                j["proc"].terminate()
                return self._json({"ok": True})
            self.send_error(404)
        except Exception as e:  # surface errors to the UI
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def _serve(self, path: str):
        if not os.path.isfile(path):
            return self.send_error(404)
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if path.endswith(".ass"):
            ctype = "text/plain; charset=utf-8"
        start, end, code = 0, size - 1, 200
        rng = self.headers.get("Range")
        if rng and (m := re.match(r"bytes=(\d*)-(\d*)", rng)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            elif m.group(2):
                start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            code = 206
        length = max(0, end - start + 1)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    port = int(os.environ.get("PORT", "8765"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"k-mugen-autogen test UI: http://127.0.0.1:{port}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
