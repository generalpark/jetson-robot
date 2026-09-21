"""Qwen2.5-0.5B-Instruct LoRA 파인튜닝 (Jetson Orin Nano 8GB).

8GB에서는 전체 파라미터 학습이 들어가지 않는다. LoRA로 어댑터만 학습해
학습 대상 파라미터를 1% 아래로 줄인다.

손실은 정답 JSON 부분에만 건다. 프롬프트까지 학습하면 모델이 질문을
따라 쓰게 되고, 정작 필요한 출력 형식은 덜 배운다.
"""
import argparse
import json
import os

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model
from transformers import (AutoModelForCausalLM, AutoTokenizer,
                          DataCollatorForSeq2Seq, Trainer, TrainingArguments)

SYSTEM = (
    "너는 로봇 주행 제어기다. 사용자의 주행 명령을 JSON 하나로만 변환한다.\n"
    '형식: {"linear": <m/s>, "angular": <rad/s>, "duration": <초>}\n'
    "linear는 전진이 양수, 후진이 음수. angular는 좌회전이 양수, 우회전이 음수.\n"
    "설명 없이 JSON만 출력한다."
)
IGNORE = -100


def build(tok, path, max_len):
    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    feats = []
    for r in rows:
        prompt = tok.apply_chat_template(
            [{"role": "system", "content": SYSTEM},
             {"role": "user", "content": r["instruction"]}],
            tokenize=False, add_generation_prompt=True)
        answer = r["output"] + tok.eos_token

        p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
        a_ids = tok(answer, add_special_tokens=False)["input_ids"]
        ids = (p_ids + a_ids)[:max_len]
        # 프롬프트 구간은 손실에서 제외한다
        labels = ([IGNORE] * len(p_ids) + a_ids)[:max_len]
        feats.append({"input_ids": ids, "labels": labels,
                      "attention_mask": [1] * len(ids)})
    return Dataset.from_list(feats)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="Qwen/Qwen2.5-0.5B-Instruct")
    ap.add_argument("--train", default="train.jsonl")
    ap.add_argument("--valid", default="valid.jsonl")
    ap.add_argument("--out", default="adapter")
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--bs", type=int, default=4)
    ap.add_argument("--accum", type=int, default=4)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=256)
    args = ap.parse_args()

    tok = AutoTokenizer.from_pretrained(args.base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        args.base, torch_dtype=torch.float16, device_map="cuda")
    model.config.use_cache = False
    model.enable_input_require_grads()

    lora = LoraConfig(
        r=args.rank, lora_alpha=args.rank * 2, lora_dropout=0.05,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"])
    model = get_peft_model(model, lora)

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"학습 파라미터 {trainable:,} / 전체 {total:,} = {trainable/total*100:.2f}%")

    ds_tr = build(tok, args.train, args.max_len)
    ds_va = build(tok, args.valid, args.max_len)
    print(f"학습 {len(ds_tr)}건 / 검증 {len(ds_va)}건")

    targs = TrainingArguments(
        output_dir=os.path.join(args.out, "_ckpt"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.bs,
        per_device_eval_batch_size=args.bs,
        gradient_accumulation_steps=args.accum,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        logging_steps=10,
        eval_strategy="epoch",
        save_strategy="no",
        fp16=True,
        report_to=[],
        gradient_checkpointing=True,
    )

    trainer = Trainer(
        model=model, args=targs,
        train_dataset=ds_tr, eval_dataset=ds_va,
        data_collator=DataCollatorForSeq2Seq(tok, padding=True, label_pad_token_id=IGNORE),
    )
    trainer.train()

    model.save_pretrained(args.out)
    tok.save_pretrained(args.out)
    print(f"\n어댑터 저장: {args.out}")
    print("GPU 최대 사용:", round(torch.cuda.max_memory_allocated() / 1024**3, 2), "GB")


if __name__ == "__main__":
    main()
