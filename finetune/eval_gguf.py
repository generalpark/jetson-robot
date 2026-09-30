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

from evaluate import build_messages, extract, score

KEYS = ("parse", "schema", "sign", "exact")


def query(url, messages, max_tokens=64, timeout=120):
    body = json.dumps({
        "messages": messages,
        "temperature": 0.0,
        "top_k": 1,
        "max_tokens": max_tokens,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080/v1/chat/completions")
    ap.add_argument("--test", default="test.jsonl")
    ap.add_argument("--label", default="gguf")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.test, encoding="utf-8")]

    totals = {k: 0 for k in KEYS}
    samples, lat = [], []
    for r in rows:
        t0 = time.perf_counter()
        text = query(args.url, build_messages(r["instruction"], "lora"))
        lat.append((time.perf_counter() - t0) * 1000)
        pred = extract(text)
        gold = json.loads(r["output"])
        s = score(pred, gold)
        for k in KEYS:
            totals[k] += s[k]
        samples.append({"instruction": r["instruction"], "gold": gold,
                        "pred": pred, "raw": text, **s})

    n = len(rows)
    res = {
        "label": args.label,
        "n": n,
        "parse": round(100 * totals["parse"] / n, 1),
        "schema": round(100 * totals["schema"] / n, 1),
        "sign": round(100 * totals["sign"] / n, 1),
        "exact": round(100 * totals["exact"] / n, 1),
        "req_ms_mean": round(sum(lat) / n, 1),
    }
    print(json.dumps(res, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"summary": res, "samples": samples}, f,
                      ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
