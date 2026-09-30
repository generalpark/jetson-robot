"""거부 학습 전후 비교표. run_reject.sh가 만든 결과 파일을 읽는다.

주행 테스트(150)에서는 기존 정확도가 유지되는지와 잘못 거부한 비율을,
주행이 아닌 문장(60)에서는 거부율과 '그래도 움직인' 비율을 본다.
마지막 줄은 배포 경로처럼 정지어 규칙(infer.py의 STOP_RE)을 모델 앞에 둔 경우다.
"""
import json

from infer import STOP_RE

KIND = {json.loads(l)["instruction"]: json.loads(l)["kind"]
        for l in open("test_offtopic.jsonl", encoding="utf-8")}


def load(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
    except FileNotFoundError:
        return None
    # evaluate.py는 in/score, eval_gguf.py는 instruction/지표 평탄화로 저장한다
    out = []
    for s in d["samples"]:
        text = s.get("in") or s.get("instruction")
        sc = s.get("score") or {k: s[k] for k in ("sign", "exact", "reject", "moves")}
        out.append((text, sc, s["gold"]))
    return out


def with_stop_rule(rows):
    """정지어가 보이면 모델 출력 대신 정지 명령이 나간 것으로 다시 채점한다."""
    out = []
    for text, sc, gold in rows:
        if STOP_RE.search(text):
            is_stop = not gold.get("reject") and all(gold[k] == 0 for k in ("linear", "angular"))
            sc = {"sign": int(is_stop), "exact": int(is_stop and gold["duration"] == 0),
                  "reject": 0, "moves": 0}
        out.append((text, sc, gold))
    return out


def pct(rows, key, kind=None):
    sub = [sc for t, sc, _ in rows if kind is None or KIND.get(t) == kind]
    return 100 * sum(sc.get(key, 0) for sc in sub) / len(sub) if sub else float("nan")


def main():
    runs = [("기존 모델", "result_lora.json", "result_off_base.json", False),
            ("거부 학습", "result_lora_rej.json", "result_off_rej.json", False),
            ("거부 학습 Q4_K_M", "result_gguf_rej_q4km.json", "result_gguf_off_rej_q4km.json", False),
            ("  + 정지어 규칙", "result_gguf_rej_q4km.json", "result_gguf_off_rej_q4km.json", True)]
    print(f"{'':<18}{'주행 완전일치':>10}{'부호':>7}{'잘못 거부':>9}"
          f"{'잡담 거부':>9}{'잡담 움직임':>10}{'헷갈림 거부':>10}{'헷갈림 움직임':>11}")
    for name, drive, off, rule in runs:
        d, o = load(drive), load(off)
        if d is None or o is None:
            continue
        if rule:
            d, o = with_stop_rule(d), with_stop_rule(o)
        print(f"{name:<18}{pct(d, 'exact'):>10.1f}{pct(d, 'sign'):>7.1f}{pct(d, 'reject'):>9.1f}"
              f"{pct(o, 'reject', 'plain'):>9.1f}{pct(o, 'moves', 'plain'):>10.1f}"
              f"{pct(o, 'reject', 'hard'):>10.1f}{pct(o, 'moves', 'hard'):>11.1f}")

    o = load("result_off_rej.json")
    if o:
        print("\n[거부 학습 후에도 거부하지 못한 문장]")
        for t, sc, _ in o:
            if not sc["reject"]:
                print(f"  ({KIND[t]}) {t}  {'-> 움직임' if sc['moves'] else ''}")
    d = load("result_gguf_rej_q4km.json")
    if d:
        print("\n[주행 명령인데 거부한 문장 (Q4_K_M)]")
        for t, sc, _ in d:
            if sc["reject"]:
                print(f"  {t}  {'-> 정지어 규칙이 먼저 멈춤' if STOP_RE.search(t) else ''}")
        hits = [(t, g) for t, _, g in d if STOP_RE.search(t)]
        wrong = [t for t, g in hits if any(g[k] for k in ("linear", "angular"))]
        print(f"\n[정지어 규칙] 주행 테스트 150건 중 {len(hits)}건에 걸림, "
              f"그중 정지가 아닌 명령 {len(wrong)}건 {wrong}")


if __name__ == "__main__":
    main()
