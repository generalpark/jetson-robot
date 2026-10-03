"""Write the LoRA-merged model to disk so llama.cpp can convert it to GGUF.

Loads on CPU: this only serializes weights, and keeping it off the GPU avoids
competing with anything else running on the board.
"""
import argparse

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="Qwen/Qwen2.5-0.5B-Instruct")
ap.add_argument("--adapter", default="adapter")
ap.add_argument("--out", default="merged_model")
args = ap.parse_args()

tok = AutoTokenizer.from_pretrained(args.base)
model = AutoModelForCausalLM.from_pretrained(args.base, torch_dtype=torch.float16)
model = PeftModel.from_pretrained(model, args.adapter)
model = model.merge_and_unload()
model.save_pretrained(args.out, safe_serialization=True)
tok.save_pretrained(args.out)
print("saved to", args.out)
