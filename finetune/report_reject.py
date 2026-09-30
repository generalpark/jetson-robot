"""거부 학습 전후 비교표. run_reject.sh가 만든 결과 파일을 읽는다.

주행 테스트(150)에서는 기존 정확도가 유지되는지와 잘못 거부한 비율을,
주행이 아닌 문장(60)에서는 거부율과 '그래도 움직인' 비율을 본다.
"""
import json

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
        out.append((text, sc))
    return out


def pct(rows, key, kind=None):
    sub = [sc for t, sc in rows if kind is None or KIND.get(t) == kind]
    return 100 * sum(sc.get(key, 0) for sc in sub) / len(sub) if sub else float("nan")


def main():
    runs = [("기존 모델", "result_lora.json", "result_off_base.json"),
            ("거부 학습", "result_lora_rej.json", "result_off_rej.json"),
            ("거부 학습 Q4_K_M", "result_gguf_rej_q4km.json", "result_gguf_off_rej_q4km.json")]
    print(f"{'':<18}{'주행 완전일치':>10}{'부호':>7}{'잘못 거부':>9}"
          f"{'잡담 거부':>9}{'잡담 움직임':>10}{'헷갈림 거부':>10}{'헷갈림 움직임':>11}")
    for name, drive, off in runs:
        d, o = load(drive), load(off)
        if d is None or o is None:
            continue
        print(f"{name:<18}{pct(d, 'exact'):>10.1f}{pct(d, 'sign'):>7.1f}{pct(d, 'reject'):>9.1f}"
              f"{pct(o, 'reject', 'plain'):>9.1f}{pct(o, 'moves', 'plain'):>10.1f}"
              f"{pct(o, 'reject', 'hard'):>10.1f}{pct(o, 'moves', 'hard'):>11.1f}")

    o = load("result_off_rej.json")
    if o:
        print("\n[거부 학습 후에도 거부하지 못한 문장]")
        for t, sc in o:
            if not sc["reject"]:
                print(f"  ({KIND[t]}) {t}  {'-> 움직임' if sc['moves'] else ''}")
    d = load("result_lora_rej.json")
    if d:
        print("\n[주행 명령인데 거부한 문장]")
        for t, sc in d:
            if sc["reject"]:
                print(f"  {t}")


if __name__ == "__main__":
    main()
