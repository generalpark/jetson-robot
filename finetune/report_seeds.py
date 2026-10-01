"""시드 반복 결과 집계. run_seeds.sh가 만든 seed_<조건>_s<시드>_rp<패널티>_<셋>.json을 읽는다.

조건(기존 / 거부 학습) × 반복 패널티(기본 1.1 / 끔 1.0)마다 시드 3개의 평균과 표준편차를 낸다.
"""
import json
import statistics as st

from analyze import has_holdout

SEEDS = (1, 2, 3)


def metrics(cond, seed, rp):
    d = json.load(open(f"seed_{cond}_s{seed}_rp{rp}_test.json", encoding="utf-8"))["samples"]
    o = json.load(open(f"seed_{cond}_s{seed}_rp{rp}_test_offtopic.json", encoding="utf-8"))["samples"]
    pct = lambda rows, k: 100 * sum(r["score"][k] for r in rows) / len(rows)
    seen = [r for r in d if not has_holdout(r["in"])]
    unseen = [r for r in d if has_holdout(r["in"])]
    return {"완전일치": pct(d, "exact"), "학습 어휘": pct(seen, "exact"),
            "처음 보는 어휘": pct(unseen, "exact"), "부호": pct(d, "sign"),
            "잘못 거부": pct(d, "reject"), "비주행 거부": pct(o, "reject"),
            "비주행 움직임": pct(o, "moves")}


def main():
    cols = ["완전일치", "학습 어휘", "처음 보는 어휘", "부호", "잘못 거부", "비주행 거부", "비주행 움직임"]
    print(f"{'조건':<14}" + "".join(f"{c:>14}" for c in cols))
    for cond, name in (("base", "기존"), ("rej", "거부 학습")):
        for rp in ("def", "1.0"):
            runs = [metrics(cond, s, rp) for s in SEEDS]
            cells = []
            for c in cols:
                xs = [r[c] for r in runs]
                cells.append(f"{st.mean(xs):6.1f} ±{st.stdev(xs):4.1f}")
            print(f"{name + ' rp=' + rp:<14}" + "".join(f"{x:>14}" for x in cells))
            print(f"{'':<14}" + "".join(f"{'/'.join(f'{r[c]:.1f}' for r in runs):>14}" for c in cols))


if __name__ == "__main__":
    main()
