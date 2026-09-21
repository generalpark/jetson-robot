"""학습한 어댑터로 자연어 명령 한 줄을 제어 명령(JSON)으로 바꾼다.

평가용(evaluate.py)과 달리 한 건만 처리하고 JSON만 출력한다.
셸에서 받아 ROS 2로 넘기기 위해서다.
"""
import argparse
import json
import re
import sys

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

SYSTEM = (
    "너는 로봇 주행 제어기다. 사용자의 주행 명령을 JSON 하나로만 변환한다.\n"
    '형식: {"linear": <m/s>, "angular": <rad/s>, "duration": <초>}\n'
    "linear는 전진이 양수, 후진이 음수. angular는 좌회전이 양수, 우회전이 음수.\n"
    "설명 없이 JSON만 출력한다."
)
JSON_RE = re.compile(r"\{[^{}]*\}", re.S)
KEYS = ("linear", "angular", "duration")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instruction", nargs="+")
    ap.add_argument("--base", default="Qwen/Qwen2.5-0.5B-Instruct")
    ap.add_argument("--adapter", default="adapter")
    args = ap.parse_args()
    text = " ".join(args.instruction)

    tok = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForCausalLM.from_pretrained(
        args.base, torch_dtype=torch.float16, device_map="cuda")
    from peft import PeftModel
    model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()

    prompt = tok.apply_chat_template(
        [{"role": "system", "content": SYSTEM},
         {"role": "user", "content": text}],
        tokenize=False, add_generation_prompt=True)
    enc = tok(prompt, return_tensors="pt").to("cuda")
    with torch.no_grad():
        gen = model.generate(**enc, max_new_tokens=64, do_sample=False,
                             pad_token_id=tok.eos_token_id or tok.pad_token_id)
    out = tok.decode(gen[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)

    m = JSON_RE.search(out)
    if not m:
        print(json.dumps({"error": "JSON을 찾지 못함", "raw": out.strip()[:200]},
                         ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    try:
        cmd = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        print(json.dumps({"error": str(e), "raw": m.group(0)}, ensure_ascii=False),
              file=sys.stderr)
        sys.exit(1)

    # 로봇에 넘기기 전에 형식을 확인한다. 값이 빠진 채로 내려가면
    # 상위에서 0으로 읽혀 의도하지 않게 움직일 수 있다.
    missing = [k for k in KEYS if k not in cmd]
    if missing:
        print(json.dumps({"error": f"누락된 키: {missing}", "raw": cmd},
                         ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    print(json.dumps(cmd, ensure_ascii=False))


if __name__ == "__main__":
    main()
