"""학습한 모델로 자연어 명령 한 줄을 제어 명령(JSON)으로 바꾼다.

평가용(evaluate.py)과 달리 한 건만 처리하고 JSON만 출력한다.
셸에서 받아 ROS 2로 넘기기 위해서다.

두 가지 방식으로 돌 수 있다.
  --server URL  상주 중인 llama-server(Q4_K_M GGUF)에 묻는다. 실주행용.
                표준 라이브러리만 쓰므로 컨테이너 없이 호스트 python3로 돈다.
  (기본)        transformers로 베이스 + LoRA 어댑터를 매번 올린다. 비교·검증용.
"""
import argparse
import json
import math
import re
import sys
import time
import urllib.request

SYSTEM = (
    "너는 로봇 주행 제어기다. 사용자의 주행 명령을 JSON 하나로만 변환한다.\n"
    '형식: {"linear": <m/s>, "angular": <rad/s>, "duration": <초>}\n'
    "linear는 전진이 양수, 후진이 음수. angular는 좌회전이 양수, 우회전이 음수.\n"
    "설명 없이 JSON만 출력한다."
)
JSON_RE = re.compile(r"\{[^{}]*\}", re.S)
KEYS = ("linear", "angular", "duration")
# 학습 데이터의 duration은 0~10초다. 그 밖의 값은 모델이 잘못 읽은 것으로 본다.
MAX_DURATION = 10.0


def messages(text):
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": text}]


def generate_server(text, url):
    # eval_gguf.py와 같은 조건(샘플링 끔)이어야 평가 정확도가 그대로 유지된다.
    body = json.dumps({
        "messages": messages(text),
        "temperature": 0.0,
        "top_k": 1,
        "max_tokens": 64,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]


def generate_local(text, base, adapter):
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(base)
    model = AutoModelForCausalLM.from_pretrained(
        base, torch_dtype=torch.float16, device_map="cuda")
    model = PeftModel.from_pretrained(model, adapter)
    model.eval()

    prompt = tok.apply_chat_template(
        messages(text), tokenize=False, add_generation_prompt=True)
    enc = tok(prompt, return_tensors="pt").to("cuda")
    with torch.no_grad():
        gen = model.generate(**enc, max_new_tokens=64, do_sample=False,
                             pad_token_id=tok.eos_token_id or tok.pad_token_id)
    return tok.decode(gen[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)


def fail(msg, raw):
    print(json.dumps({"error": msg, "raw": raw}, ensure_ascii=False), file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instruction", nargs="+")
    ap.add_argument("--server", default=None,
                    help="llama-server 주소 (예: http://127.0.0.1:8080/v1/chat/completions)")
    ap.add_argument("--base", default="Qwen/Qwen2.5-0.5B-Instruct")
    ap.add_argument("--adapter", default="adapter")
    args = ap.parse_args()
    text = " ".join(args.instruction)

    t0 = time.perf_counter()
    if args.server:
        out = generate_server(text, args.server)
    else:
        out = generate_local(text, args.base, args.adapter)
    ms = (time.perf_counter() - t0) * 1000

    m = JSON_RE.search(out)
    if not m:
        fail("JSON을 찾지 못함", out.strip()[:200])
    try:
        cmd = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        fail(str(e), m.group(0))

    # 로봇에 넘기기 전에 형식을 확인한다. 값이 빠진 채로 내려가면
    # 상위에서 0으로 읽혀 의도하지 않게 움직일 수 있다.
    missing = [k for k in KEYS if k not in cmd]
    if missing:
        fail(f"누락된 키: {missing}", cmd)
    bad = [k for k in KEYS
           if isinstance(cmd[k], bool) or not isinstance(cmd[k], (int, float))
           or not math.isfinite(cmd[k])]
    if bad:
        fail(f"숫자가 아닌 값: {bad}", cmd)
    if not 0 <= cmd["duration"] <= MAX_DURATION:
        fail(f"duration이 0~{MAX_DURATION:g}초 밖", cmd)

    print(f"[infer] {ms:.0f} ms", file=sys.stderr)
    print(json.dumps({k: cmd[k] for k in KEYS}, ensure_ascii=False))


if __name__ == "__main__":
    main()
