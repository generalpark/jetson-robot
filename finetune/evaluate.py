"""제어 명령 생성 성능 측정.

세 가지를 같은 기준으로 잰다.
  zeroshot  형식만 지시 (프롬프트로 될지 먼저 확인)
  fewshot   예시 3개 제공 (프롬프트만으로 어디까지 되는지)
  lora      LoRA 학습 후

학습을 한 쪽이 유리하도록 프롬프트를 다르게 주지 않는다. 시스템 프롬프트는 모두 동일하다.
"""
import argparse
import json
import re
import time

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

SYSTEM = (
    "너는 로봇 주행 제어기다. 사용자의 주행 명령을 JSON 하나로만 변환한다.\n"
    '형식: {"linear": <m/s>, "angular": <rad/s>, "duration": <초>}\n'
    "linear는 전진이 양수, 후진이 음수. angular는 좌회전이 양수, 우회전이 음수.\n"
    "설명 없이 JSON만 출력한다."
)

FEWSHOT = [
    ("앞으로 천천히 가", '{"linear": 0.15, "angular": 0.0, "duration": 3.0}'),
    ("5초 동안 오른쪽으로 돌아", '{"linear": 0.0, "angular": -0.72, "duration": 5.0}'),
    ("멈춰", '{"linear": 0.0, "angular": 0.0, "duration": 0.0}'),
]

JSON_RE = re.compile(r"\{[^{}]*\}", re.S)
KEYS = ("linear", "angular", "duration")


def build_messages(instruction, mode):
    msgs = [{"role": "system", "content": SYSTEM}]
    if mode == "fewshot":
        for q, a in FEWSHOT:
            msgs.append({"role": "user", "content": q})
            msgs.append({"role": "assistant", "content": a})
    msgs.append({"role": "user", "content": instruction})
    return msgs


def extract(text):
    m = JSON_RE.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def score(pred, gold, tol=0.02):
    r = {"parse": 0, "schema": 0, "sign": 0, "exact": 0}
    if pred is None:
        return r
    r["parse"] = 1
    if not all(k in pred and isinstance(pred[k], (int, float)) and not isinstance(pred[k], bool)
               for k in KEYS):
        return r
    r["schema"] = 1
    sign = lambda v: (v > 1e-9) - (v < -1e-9)
    if all(sign(pred[k]) == sign(gold[k]) for k in ("linear", "angular")):
        r["sign"] = 1
    if all(abs(pred[k] - gold[k]) <= tol for k in KEYS):
        r["exact"] = 1
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="Qwen/Qwen2.5-0.5B-Instruct")
    ap.add_argument("--mode", choices=["zeroshot", "fewshot", "lora"], required=True)
    ap.add_argument("--adapter", default=None, help="mode=lora일 때 어댑터 경로")
    ap.add_argument("--test", default="test.jsonl")
    ap.add_argument("--out", default=None)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    tok = AutoTokenizer.from_pretrained(args.base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "left"

    model = AutoModelForCausalLM.from_pretrained(
        args.base, torch_dtype=torch.float16, device_map="cuda")
    if args.mode == "lora":
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()

    rows = [json.loads(l) for l in open(args.test, encoding="utf-8")]
    if args.limit:
        rows = rows[: args.limit]

    totals = {"parse": 0, "schema": 0, "sign": 0, "exact": 0}
    samples, lat = [], []
    BS = 16
    for i in range(0, len(rows), BS):
        chunk = rows[i:i + BS]
        texts = [tok.apply_chat_template(build_messages(r["instruction"], args.mode),
                                         tokenize=False, add_generation_prompt=True)
                 for r in chunk]
        enc = tok(texts, return_tensors="pt", padding=True).to("cuda")
        t0 = time.perf_counter()
        with torch.no_grad():
            gen = model.generate(**enc, max_new_tokens=64, do_sample=False,
                                 pad_token_id=tok.pad_token_id)
        torch.cuda.synchronize()
        lat.append((time.perf_counter() - t0) / len(chunk))

        for r, g in zip(chunk, gen):
            out = tok.decode(g[enc["input_ids"].shape[1]:], skip_special_tokens=True)
            pred = extract(out)
            gold = json.loads(r["output"])
            s = score(pred, gold)
            for k in totals:
                totals[k] += s[k]
            samples.append({"in": r["instruction"], "gold": gold,
                            "pred": pred, "raw": out.strip()[:160], "score": s})
        print(f"  {min(i+BS, len(rows))}/{len(rows)}", flush=True)

    n = len(rows)
    res = {"mode": args.mode, "n": n,
           "metrics": {k: round(v / n * 100, 1) for k, v in totals.items()},
           "sec_per_sample": round(sum(lat) / len(lat), 3)}

    print("\n=== 결과 ===")
    print(f"모드: {args.mode}   샘플: {n}개   생성 {res['sec_per_sample']}초/건")
    m = res["metrics"]
    print(f"  JSON 파싱 성공   {m['parse']:5.1f}%")
    print(f"  스키마 일치      {m['schema']:5.1f}%")
    print(f"  방향(부호) 정확  {m['sign']:5.1f}%")
    print(f"  값 완전일치      {m['exact']:5.1f}%")
    print("\n[출력 예시]")
    for s in samples[:5]:
        print(f"  {s['in']}")
        print(f"    정답 {json.dumps(s['gold'], ensure_ascii=False)}")
        print(f"    생성 {s['raw']}")

    if args.out:
        res["samples"] = samples
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(f"\n저장: {args.out}")


if __name__ == "__main__":
    main()
