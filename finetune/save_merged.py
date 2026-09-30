"""Write the LoRA-merged model to disk so llama.cpp can convert it to GGUF.

Loads on CPU: this only serializes weights, and keeping it off the GPU avoids
competing with anything else running on the board.
"""
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

BASE = "Qwen/Qwen2.5-0.5B-Instruct"
OUT = "merged_model"

tok = AutoTokenizer.from_pretrained(BASE)
model = AutoModelForCausalLM.from_pretrained(BASE, torch_dtype=torch.float16)
model = PeftModel.from_pretrained(model, "adapter")
model = model.merge_and_unload()
model.save_pretrained(OUT, safe_serialization=True)
tok.save_pretrained(OUT)
print("saved to", OUT)
