#!/usr/bin/env bash
# LoRA 학습. 인자는 train_lora.py로 그대로 넘어간다.
set -eu
cd /mnt/nvme/finetune/work
docker run --rm -e HF_HUB_DISABLE_PROGRESS_BARS=1 \
  -v /mnt/nvme/finetune/work:/work \
  -v /mnt/nvme/finetune/hf_cache:/mnt/nvme/finetune/hf_cache \
  -w /work finetune:jetson \
  python3 train_lora.py "$@"
echo DONE_TRAIN
