"""확신도로 틀린 답을 골라낼 수 있나 — 되묻기(답하지 않기) 분석.

틀린 38건은 전부 처음 보는 어휘에서 나왔다. 모델이 그 값을 고를 때 확률이 낮았다면,
기준 아래에서는 움직이지 않고 되물으면 된다. 재학습 없이 되는지 본다.

확신도 = 출력한 숫자 토큰들의 확률 중 최솟값 (min_value)
  숫자 하나라도 헷갈렸으면 명령 전체를 믿지 않는다는 뜻이다.
  보조로 전체 토큰 최솟값(min_all), 숫자 토큰의 1·2위 확률 차(margin)도 본다.
  주 지표는 결과를 보기 전에 min_value로 정했다 — 여러 개 중 좋은 걸 고르면 테스트에 맞추는 셈이다.

기준(τ)은 테스트가 아니라 검증셋(valid_rej, 학습과 같은 분포)에서 정한다.
"검증셋 정답의 99%(또는 95%)는 통과시키는 값"이다. 테스트에서 고르면 결과가 부풀려진다.

run_logprobs.sh가 만든 lp_<모델>_rp<패널티>_<셋>.json을 읽는다.
"""
import json
import math
import re
import sys

from analyze import has_holdout

NUM = re.compile(r"^\s*-?[\d.]+$|^\s*-$")


def conf(tokens):
    ps = [math.exp(lp) for _, lp, _ in tokens]
    num = [(math.exp(lp), top) for tok, lp, top in tokens if NUM.match(tok)]
    min_value = min((p for p, _ in num), default=1.0)
    margins = []
    for p, top in num:
        probs = sorted((math.exp(x[1]) for x in top), reverse=True)
        margins.append(probs[0] - (probs[1] if len(probs) > 1 else 0.0))
    return {"min_value": min_value, "min_all": min(ps, default=1.0),
            "margin": min(margins, default=1.0)}


def load(path):
    rows = []
    for s in json.load(open(path, encoding="utf-8"))["samples"]:
        rows.append({"text": s["instruction"], "exact": s["exact"], "sign": s["sign"],
                     "reject": s["reject"], "moves": s["moves"],
                     "gold_reject": bool(s["gold"].get("reject")),
                     **conf(s.get("tokens") or [])})
    return rows


def auroc(pos, neg):
    """정답(pos)의 확신도가 오답(neg)보다 높을 확률. 0.5면 구분 못 함."""
    if not pos or not neg:
        return float("nan")
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def quantile(xs, q):
    xs = sorted(xs)
    return xs[max(0, min(len(xs) - 1, int(math.floor(q * (len(xs) - 1)))))]


def report(model, rp, key="min_value"):
    try:
        test = load(f"lp_{model}_rp{rp}_test.json")
        valid = load(f"lp_{model}_rp{rp}_valid_rej.json")
    except FileNotFoundError:
        return
    drive_valid = [r for r in valid if not r["gold_reject"]]
    ok_valid = [r[key] for r in drive_valid if r["exact"]]
    print(f"\n===== {model} rp={rp}  확신도={key} =====")
    print(f"검증셋 주행 {len(drive_valid)}건 중 정답 {len(ok_valid)}건, 정답 확신도 최솟값 {min(ok_valid):.3f}")

    for grp, sub in (("전체", test), ("학습 어휘", [r for r in test if not has_holdout(r["text"])]),
                     ("처음 보는 어휘", [r for r in test if has_holdout(r["text"])])):
        pos = [r[key] for r in sub if r["exact"]]
        neg = [r[key] for r in sub if not r["exact"]]
        print(f"  {grp:<10} {len(sub):>3}건  정답 {len(pos):>3}  오답 {len(neg):>3}  "
              f"AUROC {auroc(pos, neg):.3f}  (정답 중앙값 {quantile(pos, .5) if pos else float('nan'):.3f}, "
              f"오답 중앙값 {quantile(neg, .5) if neg else float('nan'):.3f})")

    print(f"  {'기준':<22}{'답함':>6}{'정확(답한 것 중)':>14}{'잘못 움직임':>11}{'부호 틀림':>9}{'되물은 오답':>11}{'되물은 정답':>11}")
    base = (None, "되묻기 없음")
    for q, label in (base, (0.01, "검증 정답 99% 통과"), (0.05, "검증 정답 95% 통과")):
        tau = -1.0 if q is None else quantile(ok_valid, q)
        ans = [r for r in test if r[key] >= tau]
        abst = [r for r in test if r[key] < tau]
        wrong_move = sum(1 for r in ans if r["moves"] and not r["exact"])
        sign_wrong = sum(1 for r in ans if r["moves"] and not r["sign"])
        caught = sum(1 for r in abst if not r["exact"])
        lost = sum(1 for r in abst if r["exact"])
        acc = 100 * sum(r["exact"] for r in ans) / len(ans) if ans else float("nan")
        name = label if q is None else f"{label} (τ={tau:.3f})"
        print(f"  {name:<22}{len(ans):>6}{acc:>13.1f}%{wrong_move:>11}{sign_wrong:>9}{caught:>11}{lost:>11}")
        if q is not None:
            unseen = [r for r in test if has_holdout(r["text"])]
            seen = [r for r in test if not has_holdout(r["text"])]
            print(f"    되물은 비율: 학습 어휘 {sum(r[key] < tau for r in seen)}/{len(seen)}, "
                  f"처음 보는 어휘 {sum(r[key] < tau for r in unseen)}/{len(unseen)}")


def main():
    for model in ("rej", "base"):
        for rp in ("1.0", "def"):
            report(model, rp)
    if "--all" in sys.argv:
        for model, rp in (("rej", "def"), ("rej", "1.0"), ("base", "def")):
            for key in ("min_all", "margin"):
                report(model, rp, key)


if __name__ == "__main__":
    main()
