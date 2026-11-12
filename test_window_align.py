import sys
import stable_whisper
from fast_lyrics import fetch_and_parse_lyrics

sys.stdout.reconfigure(encoding="utf-8")

# Fetch LRC lines with their timestamps
lrc_lines = fetch_and_parse_lyrics("サカナクション", "Ame(A)")
print(f"Loaded {len(lrc_lines)} LRC lines for Ame(A)")

model = stable_whisper.load_model("base", device="cuda")

for i in [12, 13, 14]:
    line = lrc_lines[i]
    prev_line = lrc_lines[i-1] if i > 0 else None
    next_line = lrc_lines[i+1] if i + 1 < len(lrc_lines) else None
    
    # Window: start slightly before LRC start, end at next line start or +8s
    w_start = max(0.0, line.start_sec - 0.5)
    w_end = (next_line.start_sec + 0.5) if next_line else (line.start_sec + 8.0)
    
    print(f"\n--- Testing Line {i+1}: '{line.original_text}' ---")
    print(f"LRC Window: {w_start:.2f}s -> {w_end:.2f}s (dur: {w_end - w_start:.2f}s)")
    
    # We can align just that audio slice!
    # But wait, stable_whisper can align the full audio with time range or we can slice audio
    # Let's see if stable_whisper supports segment alignment or audio slicing
