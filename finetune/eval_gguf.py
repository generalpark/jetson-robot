"""Score a llama.cpp GGUF build against the same test set as evaluate.py.

Reuses build_messages/extract/score from evaluate.py so the numbers are
directly comparable to the transformers runs -- a different scorer would
make the comparison meaningless.

Talks to llama-server over its OpenAI-compatible endpoint. Sampling is
disabled (temperature 0, top_k 1) to match do_sample=False on the
transformers side.
"""
import argparse
import json
import time
import urllib.request

from evaluate import METRICS as KEYS, build_messages, extract, score


def query(url, messages, max_tokens=64, timeout=120, extra=None):
    """(생성 텍스트, 토큰별 logprob 목록 또는 None)"""
    body = {
        "messages": messages,
        "temperature": 0.0,
        "top_k": 1,
        "max_tokens": max_tokens,
        "stream": False,
    }
    body.update(extra or {})
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        c = json.loads(r.read().decode("utf-8"))["choices"][0]
    lp = c.get("logprobs") or {}
    toks = [[t["token"], t["logprob"], [[x["token"], x["logprob"]] for x in t.get("top_logprobs", [])]]
            for t in lp.get("content") or []] or None
    return c["message"]["content"], toks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080/v1/chat/completions")
    ap.add_argument("--test", default="test.jsonl")
    ap.add_argument("--label", default="gguf")
    ap.add_argument("--out", default=None)
    # 지정하지 않으면 서버 기본값을 쓴다. llama-server는 GGUF에 담긴 모델 권장 설정
    # (Qwen2.5: repeat_penalty 1.1)을 기본값으로 가져온다. 1.0이면 순수 그리디
    ap.add_argument("--repeat-penalty", type=float, default=None)
    ap.add_argument("--logprobs", type=int, default=0, help="토큰별 상위 N개 logprob 저장")
    args = ap.parse_args()
    extra = {}
    if args.repeat_penalty is not None:
        extra["repeat_penalty"] = args.repeat_penalty
    if args.logprobs:
        extra.update(logprobs=True, top_logprobs=args.logprobs)

    rows = [json.loads(l) for l in open(args.test, encoding="utf-8")]

    totals = {k: 0 for k in KEYS}
    samples, lat = [], []
    for r in rows:
        t0 = time.perf_counter()
        text, toks = query(args.url, build_messages(r["instruction"], "lora"), extra=extra)
        lat.append((time.perf_counter() - t0) * 1000)
        pred = extract(text)
        gold = json.loads(r["output"])
        s = score(pred, gold)
        for k in KEYS:
            totals[k] += s[k]
        samples.append({"instruction": r["instruction"], "gold": gold,
                        "pred": pred, "raw": text, **s,
                        **({"tokens": toks} if toks else {})})

    n = len(rows)
    res = {
        "label": args.label,
        "n": n,
        **{k: round(100 * totals[k] / n, 1) for k in KEYS},
        "req_ms_mean": round(sum(lat) / n, 1),
    }
    print(json.dumps(res, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"summary": res, "samples": samples}, f,
                      ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
