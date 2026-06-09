import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.deterministic_parser import DeterministicParser

def test():
    dp = DeterministicParser()
    path = "DDD/D_20250715_1849_Milan_Adalberto_I100000168598002.ddd"
    if not os.path.exists(path):
        print("File not found")
        return
    with open(path, "rb") as f:
        data = f.read()
    try:
        res = dp.parse(data, is_vu=False)
        print("Raw tags keys:")
        for k in sorted(res.get("raw_tags", {}).keys()):
            print(f"  {k}: {len(res['raw_tags'][k])} occurrences")
    except Exception:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test()
