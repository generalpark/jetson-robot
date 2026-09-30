#!/usr/bin/env bash
# 실험: 주행이 아닌 문장을 거부하도록 학습하면, 주행 정확도를 잃지 않고
#       "오늘 날씨 어때"에 움직이는 문제를 없앨 수 있는가?
# 주행 데이터 800건과 테스트셋 150건은 그대로 두고 거부 문장만 더한다.
set -eu
cd /mnt/nvme/finetune/work
BIN=/mnt/nvme/llama.cpp/build/bin

DOCKER_ARGS="--rm -e HF_HUB_DISABLE_PROGRESS_BARS=1 \
  -v /mnt/nvme/finetune/work:/work \
  -v /mnt/nvme/finetune/hf_cache:/mnt/nvme/finetune/hf_cache \
  -e PYTORCH_CUDA_ALLOC_CONF=garbage_collection_threshold:0.6 -w /work finetune:jetson"

echo "##### 데이터: 주행 800 + 거부 문장, 거부 평가셋 #####"
python3 gen_data.py --reject 200 --tag _rej --out .
cmp -s test.jsonl test_rej.jsonl && echo "테스트셋 동일 확인"

echo "##### 기준선: 기존 어댑터가 주행이 아닌 문장에 어떻게 반응하나 #####"
docker run ${DOCKER_ARGS} python3 evaluate.py \
  --mode lora --adapter adapter --test test_offtopic.jsonl --out result_off_base.json

echo "##### 학습 #####"
docker run ${DOCKER_ARGS} python3 train_lora.py \
  --train train_rej.jsonl --valid valid_rej.jsonl --out adapter_rej

echo "##### 평가: 주행 테스트 150 / 주행 아닌 문장 60 #####"
docker run ${DOCKER_ARGS} python3 evaluate.py \
  --mode lora --adapter adapter_rej --test test.jsonl --out result_lora_rej.json
docker run ${DOCKER_ARGS} python3 evaluate.py \
  --mode lora --adapter adapter_rej --test test_offtopic.jsonl --out result_off_rej.json

echo "##### 배포용 GGUF (Q4_K_M) #####"
docker run ${DOCKER_ARGS} python3 save_merged.py --adapter adapter_rej --out merged_model_rej
docker run --rm -e PYTHONPATH=/llamacpp/gguf-py -v /mnt/nvme/finetune/work:/work \
  -v /mnt/nvme/llama.cpp:/llamacpp -w /work finetune:jetson \
  python3 /llamacpp/convert_hf_to_gguf.py merged_model_rej \
  --outfile drive_cmd_rej_f16.gguf --outtype f16 2>&1 | tail -2
$BIN/llama-quantize drive_cmd_rej_f16.gguf drive_cmd_rej_q4km.gguf Q4_K_M 2>&1 | tail -1

echo "##### GGUF 평가 #####"
$BIN/llama-server -m drive_cmd_rej_q4km.gguf -ngl 99 --host 127.0.0.1 --port 8081 \
  -c 2048 > server_rej.log 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT
for _ in $(seq 120); do curl -sf http://127.0.0.1:8081/health >/dev/null && break; sleep 1; done
for T in test:rej_q4km test_offtopic:off_rej_q4km; do
  docker run --rm --network host -v /mnt/nvme/finetune/work:/work -w /work finetune:jetson \
    python3 eval_gguf.py --url http://127.0.0.1:8081/v1/chat/completions \
    --test "${T%%:*}.jsonl" --label "${T#*:}" --out "result_gguf_${T#*:}.json" | tail -12
done

echo "##### 비교 #####"
python3 report_reject.py
echo DONE_REJECT
