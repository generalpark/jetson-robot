#!/usr/bin/env bash
# 실험: 같은 설정을 시드만 바꿔 3번씩 학습하면 정확도가 얼마나 흔들리나?
# 거부 학습 후 완전일치 -3.4%p(74.7 → 71.3)가 편차 안인지 밖인지 가리려는 것.
# 평가는 반복 패널티 기본(1.1)과 끔(1.0) 두 조건으로 한다.
set -eu
cd /mnt/nvme/finetune/work

DOCKER_ARGS="--rm -e HF_HUB_DISABLE_PROGRESS_BARS=1 \
  -v /mnt/nvme/finetune/work:/work \
  -v /mnt/nvme/finetune/hf_cache:/mnt/nvme/finetune/hf_cache \
  -e PYTORCH_CUDA_ALLOC_CONF=garbage_collection_threshold:0.6 -w /work finetune:jetson"

for S in 1 2 3; do
  for C in base:train:valid rej:train_rej:valid_rej; do
    NAME="${C%%:*}"; REST="${C#*:}"; TR="${REST%%:*}"; VA="${REST#*:}"
    AD="adapter_seed_${NAME}_s${S}"
    echo "##### ${NAME} seed=${S} #####"
    docker run ${DOCKER_ARGS} python3 train_lora.py --seed "${S}" \
      --train "${TR}.jsonl" --valid "${VA}.jsonl" --out "${AD}" 2>&1 | grep -E "train_runtime|어댑터 저장"
    for RP in def 1.0; do
      OPT=""
      [ "$RP" = def ] || OPT="--repetition-penalty $RP"
      for T in test test_offtopic; do
        docker run ${DOCKER_ARGS} python3 evaluate.py --mode lora --adapter "${AD}" ${OPT} \
          --test "${T}.jsonl" --out "seed_${NAME}_s${S}_rp${RP}_${T}.json" | grep -E "완전일치|거부|움직이는"
      done
    done
  done
done
echo DONE_SEEDS
