"""학습에 나온 표현과 나오지 않은 표현을 나눠서 정확도를 비교한다.

검증 손실이 0에 가까워도 실제 성능은 다를 수 있다. 검증셋은 학습과 같은
어휘를 쓰기 때문이다. 테스트셋에만 넣어둔 표현(holdout)을 기준으로 나눠
보면 모델이 규칙을 익혔는지 어휘를 외웠는지 구분할 수 있다.
"""
import json
import sys

HOLDOUT = ["살살", "전속력으로", "앞쪽으로", "뒤쪽으로", "좌측으로", "우측으로",
           "꺾어", "세워", "가봐"]
KEYS = ("parse", "schema", "sign", "exact")


def has_holdout(text):
    return any(w in text for w in HOLDOUT)


def agg(rows, key):
    sub = [r for r in rows if has_holdout(r["in"]) == (key == "unseen")]
    if not sub:
        return None
    return {"n": len(sub),
            **{k: round(sum(r["score"][k] for r in sub) / len(sub) * 100, 1) for k in KEYS}}


def main():
    modes = sys.argv[1:] or ["zeroshot", "fewshot", "lora"]
    print(f"{'모드':<10}{'구간':<22}{'건수':>5}{'파싱':>8}{'스키마':>8}{'부호':>8}{'완전일치':>9}")
    print("-" * 72)
    rowsets = {}
    for m in modes:
        try:
            d = json.load(open(f"result_{m}.json", encoding="utf-8"))
        except FileNotFoundError:
            continue
        rowsets[m] = d["samples"]
        for key, label in [("seen", "학습에 나온 표현"), ("unseen", "학습에 없던 표현")]:
            a = agg(d["samples"], key)
            if a:
                print(f"{m:<10}{label:<20}{a['n']:>5}{a['parse']:>8.1f}{a['schema']:>8.1f}"
                      f"{a['sign']:>8.1f}{a['exact']:>9.1f}")
        print("-" * 72)

    if "lora" in rowsets:
        bad = [r for r in rowsets["lora"] if not r["score"]["exact"]]
        un = [r for r in bad if has_holdout(r["in"])]
        print(f"\nLoRA 오답 {len(bad)}건 중 학습에 없던 표현이 {len(un)}건 "
              f"({len(un)/max(len(bad),1)*100:.0f}%)")
        print("\n[오답 예시]")
        for r in bad[:6]:
            mark = "새 표현" if has_holdout(r["in"]) else "기존 표현"
            print(f"  ({mark}) {r['in']}")
            print(f"     정답 {json.dumps(r['gold'], ensure_ascii=False)}")
            print(f"     생성 {json.dumps(r['pred'], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
