#!/usr/bin/env bash
# 실험: 학습 데이터의 양은 그대로 두고 어휘 다양성만 늘리면,
#       여전히 학습에 없는 표현에 강해지는가?
# 테스트셋(test.jsonl)은 바꾸지 않는다. 같은 자로 재야 비교가 된다.
set -eu
cd /mnt/nvme/finetune/work

DOCKER_ARGS="--rm -e HF_HUB_DISABLE_PROGRESS_BARS=1 \
  -v /mnt/nvme/finetune/work:/work \
  -v /mnt/nvme/finetune/hf_cache:/mnt/nvme/finetune/hf_cache \
  -w /work finetune:jetson"

echo "##### 어휘 확장 데이터 생성 (양은 800건 그대로) #####"
python3 gen_data.py --rich --tag _rich --out .

echo "##### 학습 #####"
docker run ${DOCKER_ARGS} python3 train_lora.py \
  --train train_rich.jsonl --valid valid_rich.jsonl --out adapter_rich

echo "##### 평가 (테스트셋은 기존 것 그대로) #####"
docker run ${DOCKER_ARGS} python3 evaluate.py \
  --mode lora --adapter adapter_rich --test test.jsonl --out result_lora_rich.json

echo DONE_RICH
