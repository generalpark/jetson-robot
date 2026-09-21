#!/usr/bin/env bash
# 기준선 측정: 형식 지시만(zeroshot) / 예시 3개 제공(fewshot) / 학습 후(lora)
set -eu
cd /mnt/nvme/finetune/work

DOCKER_ARGS="--rm -e HF_HUB_DISABLE_PROGRESS_BARS=1 \
  -v /mnt/nvme/finetune/work:/work \
  -v /mnt/nvme/finetune/hf_cache:/mnt/nvme/finetune/hf_cache \
  -w /work finetune:jetson"

for m in "$@"; do
  echo "##### ${m} #####"
  if [ "${m}" = "lora" ]; then
    docker run ${DOCKER_ARGS} python3 evaluate.py --mode lora --adapter adapter --out "result_lora.json"
  else
    docker run ${DOCKER_ARGS} python3 evaluate.py --mode "${m}" --out "result_${m}.json"
  fi
done
echo DONE_ALL
