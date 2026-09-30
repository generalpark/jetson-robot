"""데이터 양에 따른 성능 변화를 정리한다.

같은 설정에서 학습 데이터 양만 바꿔 학습한 결과를 모아,
어느 지점부터 더 모아도 소용이 없는지 본다.
어휘를 넓힌 실험과 달리 이번에는 양만 바꾼다.
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import has_holdout

rows = []
for path in sorted(glob.glob("result_lora_*.json"),
                   key=lambda p: int(re.search(r"(\d+)", os.path.basename(p)).group(1))
                   if re.search(r"(\d+)", os.path.basename(p)) else 0):
    m = re.search(r"result_lora_(\d+)\.json", os.path.basename(path))
    if not m:
        continue                      # result_lora_rich.json 등은 건너뛴다
    n = int(m.group(1))
    d = json.load(open(path, encoding="utf-8"))
    s = d["samples"]
    seen = [r for r in s if not has_holdout(r["in"])]
    unseen = [r for r in s if has_holdout(r["in"])]
    pct = lambda xs, k: round(sum(r["score"][k] for r in xs) / len(xs) * 100, 1) if xs else 0
    rows.append({
        "n": n,
        "sign": d["metrics"]["sign"], "exact": d["metrics"]["exact"],
        "seen_exact": pct(seen, "exact"), "unseen_exact": pct(unseen, "exact"),
        "unseen_sign": pct(unseen, "sign"),
    })

if not rows:
    print("결과 파일이 없습니다.")
    sys.exit(1)

print(f"{'학습건수':>8}{'방향':>8}{'완전일치':>9} | {'학습어휘':>9}{'새어휘':>8}{'새어휘방향':>10}")
print("-" * 60)
for r in rows:
    print(f"{r['n']:>8}{r['sign']:>8.1f}{r['exact']:>9.1f} | "
          f"{r['seen_exact']:>9.1f}{r['unseen_exact']:>8.1f}{r['unseen_sign']:>10.1f}")

print("\n[증가폭]")
for a, b in zip(rows, rows[1:]):
    print(f"  {a['n']:>4} → {b['n']:>4}:  완전일치 {b['exact']-a['exact']:+.1f}%p, "
          f"새어휘 {b['unseen_exact']-a['unseen_exact']:+.1f}%p")
