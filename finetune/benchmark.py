"""Measure inference latency and memory of the fine-tuned model on Jetson.

Reports time-to-first-token, end-to-end latency, throughput and peak VRAM.
Batch size is 1 on purpose: the target is a real-time control loop, where
per-request latency matters and batching is not available.

Runs inside the finetune:jetson container.
"""
import argparse
import json
import statistics
import time

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from evaluate import build_messages


def load_model(base, adapter, dtype, merge=False, compile_fwd=False):
    tok = AutoTokenizer.from_pretrained(base)
    tok.padding_side = "left"  # decoder-only: pad on the left or generation breaks
    model = AutoModelForCausalLM.from_pretrained(
        base, torch_dtype=dtype, device_map="cuda")
    if adapter and adapter.lower() != "none":
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter)
        if merge:
            # Fold LoRA weights into the base matrices so the adapter's
            # extra matmuls disappear from every forward pass.
            model = model.merge_and_unload()
    model.eval()
    if compile_fwd:
        # A static KV cache gives generate() fixed-shape tensors, which is what
        # lets reduce-overhead capture CUDA Graphs and drop the per-token
        # kernel-launch cost that the clock experiment showed is the bottleneck.
        # fullgraph=True fails here: transformers resolves attention via
        # ALL_ATTENTION_FUNCTIONS[cfg._attn_implementation], a dict lookup
        # dynamo cannot trace. Allow graph breaks and fall back to eager for
        # the parts it still cannot handle.
        import torch._dynamo
        torch._dynamo.config.suppress_errors = True
        model.generation_config.cache_implementation = "static"
        model.forward = torch.compile(model.forward, mode="reduce-overhead",
                                      fullgraph=False)
    return tok, model


def timed_generate(tok, model, text, max_new_tokens, pad_len=0):
    if pad_len:
        enc = tok([text], return_tensors="pt", padding="max_length",
                  max_length=pad_len, truncation=True).to("cuda")
    else:
        enc = tok([text], return_tensors="pt").to("cuda")
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    with torch.no_grad():
        gen = model.generate(**enc, max_new_tokens=max_new_tokens,
                             do_sample=False, pad_token_id=tok.pad_token_id)
    torch.cuda.synchronize()
    dt = time.perf_counter() - t0
    return dt, int(gen.shape[1] - enc["input_ids"].shape[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="Qwen/Qwen2.5-0.5B-Instruct")
    ap.add_argument("--adapter", default="adapter")
    ap.add_argument("--test", default="test.jsonl")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--label", default="fp16")
    ap.add_argument("--merge", action="store_true",
                    help="merge LoRA into base weights before timing")
    ap.add_argument("--compile", action="store_true",
                    help="torch.compile + static cache (CUDA Graphs)")
    ap.add_argument("--pad-len", type=int, default=0,
                    help="0 = auto (longest prompt) when --compile is set")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.test, encoding="utf-8")][:args.n]

    t0 = time.perf_counter()
    tok, model = load_model(args.base, args.adapter, torch.float16, args.merge,
                            args.compile)
    load_s = time.perf_counter() - t0

    texts = [tok.apply_chat_template(build_messages(r["instruction"], "lora"),
                                     tokenize=False, add_generation_prompt=True)
             for r in rows]

    pad_len = args.pad_len
    if args.compile and not pad_len:
        # Varying prompt length would retrigger compilation on every sample.
        pad_len = max(len(tok(t)["input_ids"]) for t in texts)
    print("pad_len =", pad_len, flush=True)

    # First CUDA calls compile kernels and are not representative. With
    # torch.compile the first calls also pay the full compilation cost.
    warm = args.warmup if not args.compile else max(args.warmup, 6)
    for i in range(warm):
        timed_generate(tok, model, texts[i % len(texts)], 1, pad_len)
        timed_generate(tok, model, texts[i % len(texts)], 64, pad_len)
    print("warmup done", flush=True)

    torch.cuda.reset_peak_memory_stats()
    ttft, full, toks = [], [], []
    for t in texts:
        dt1, _ = timed_generate(tok, model, t, 1, pad_len)
        ttft.append(dt1 * 1000)
        dt, n = timed_generate(tok, model, t, 64, pad_len)
        full.append(dt * 1000)
        toks.append(n)

    res = {
        "label": args.label,
        "adapter": args.adapter,
        "merged": args.merge,
        "compiled": args.compile,
        "samples": len(texts),
        "load_s": round(load_s, 2),
        "ttft_ms_mean": round(statistics.mean(ttft), 1),
        "ttft_ms_p50": round(statistics.median(ttft), 1),
        "e2e_ms_mean": round(statistics.mean(full), 1),
        "e2e_ms_p50": round(statistics.median(full), 1),
        "e2e_ms_min": round(min(full), 1),
        "e2e_ms_max": round(max(full), 1),
        "new_tokens_mean": round(statistics.mean(toks), 1),
        "tokens_per_s": round(sum(toks) / (sum(full) / 1000), 1),
        "peak_vram_mb": round(torch.cuda.max_memory_allocated() / 1048576, 1),
    }
    print(json.dumps(res, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
