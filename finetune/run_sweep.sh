#!/usr/bin/env bash
# 학습 데이터를 몇 건까지 모아야 하는지 확인한다.
# 같은 설정으로 데이터 양만 바꿔 학습하고 같은 테스트셋으로 측정한다.
set -eu
cd /mnt/nvme/finetune/work

DOCKER_ARGS="--rm -e HF_HUB_DISABLE_PROGRESS_BARS=1 \
  -v /mnt/nvme/finetune/work:/work \
  -v /mnt/nvme/finetune/hf_cache:/mnt/nvme/finetune/hf_cache \
  -w /work finetune:jetson"

for n in "$@"; do
  echo "##### train=${n} #####"
  head -n "${n}" train.jsonl > "train_${n}.jsonl"
  docker run ${DOCKER_ARGS} python3 train_lora.py \
    --train "train_${n}.jsonl" --out "adapter_${n}"
  docker run ${DOCKER_ARGS} python3 evaluate.py \
    --mode lora --adapter "adapter_${n}" --out "result_lora_${n}.json"
done
echo DONE_SWEEP
