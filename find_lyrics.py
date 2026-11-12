import sys
import syncedlyrics

sys.stdout.reconfigure(encoding="utf-8")

queries = [
    "RADWIMPS Hyperventilation",
    "RADWIMPS ハイパーベンチレイション",
    "Hyperventilation RADWIMPS",
    "ハイパーベンチレイション",
    "RADWIMPS hyper ventilation",
]

for q in queries:
    res = syncedlyrics.search(q)
    if res:
        print(f"FOUND for query: '{q}'\n")
        print(res[:300])
        with open("hyperventilation.lrc", "w", encoding="utf-8") as f:
            f.write(res)
        break
    else:
        print(f"Not found: '{q}'")
