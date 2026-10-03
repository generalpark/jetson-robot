#!/usr/bin/env bash
# 실험: 모델을 0.5B → 1.5B로 키우면 처음 보는 속도어("살살", "전속력으로")를 풀 수 있나?
# 데이터를 늘려도(어휘 확장), 확신도로 걸러도 안 됐다. 남은 가설은 "모델이 단어 뜻을 모른다"다.
# 0.5B 거부 학습(run_seeds.sh의 rej)과 같은 데이터·하이퍼파라미터·시드 3개로 비교한다.
# 다른 점: 배치 4×누적 4 → 1×누적 16 (유효 배치 16 동일), 할당기 상한 0.6 → 0.55.
#   처음 배치 2로 돌리자 가용 메모리가 약 200MB까지 떨어졌다(9/23 리셋 때 170MB). 멈추고 줄였다.
#   배치 1에서도 같아 Jetson 8GB에서는 중단했다(README). 더 큰 GPU에서 학습할 때 쓴다.
set -eu
cd /mnt/nvme/finetune/work
BIN=/mnt/nvme/llama.cpp/build/bin
BASE=Qwen/Qwen2.5-1.5B-Instruct

DOCKER_ARGS="--rm -e HF_HUB_DISABLE_PROGRESS_BARS=1 \
  -v /mnt/nvme/finetune/work:/work \
  -v /mnt/nvme/finetune/hf_cache:/mnt/nvme/finetune/hf_cache \
  -e PYTORCH_CUDA_ALLOC_CONF=garbage_collection_threshold:0.6 -w /work finetune:jetson"

# 가용 메모리가 바닥나면 보드가 통째로 리셋된다. 그 전에 컨테이너를 멈춘다
guard() {
  while sleep 1; do
    a=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
    if [ "$a" -lt 300 ]; then
      echo "[guard] MemAvailable ${a}MB — 컨테이너 중단"
      docker ps -q --filter ancestor=finetune:jetson | xargs -r docker stop -t 2 >/dev/null
    fi
  done
}
guard &
GUARD=$!
trap 'kill $GUARD 2>/dev/null' EXIT

for S in 1 2 3; do
  AD="adapter_1p5b_s${S}"
  echo "##### 1.5B seed=${S} #####"
  docker run ${DOCKER_ARGS} python3 train_lora.py --base "${BASE}" --seed "${S}" --bs 1 --accum 16 --mem-fraction 0.55 \
    --train train_rej.jsonl --valid valid_rej.jsonl --out "${AD}" --memlog "memlog_1p5b_s${S}.csv" \
    2>&1 | grep -E "학습 파라미터|train_runtime|어댑터 저장|GPU 최대|Error|error"
  for T in test test_offtopic; do
    docker run ${DOCKER_ARGS} python3 evaluate.py --mode lora --base "${BASE}" --adapter "${AD}" \
      --test "${T}.jsonl" --out "seed_rej1p5b_s${S}_rpdef_${T}.json" | grep -E "생성|완전일치|거부|움직이는"
  done
done

echo "##### 배포용 GGUF (seed 1) #####"
docker run ${DOCKER_ARGS} python3 save_merged.py --base "${BASE}" --adapter adapter_1p5b_s1 --out merged_1p5b
docker run --rm -e PYTHONPATH=/llamacpp/gguf-py -v /mnt/nvme/finetune/work:/work \
  -v /mnt/nvme/llama.cpp:/llamacpp -w /work finetune:jetson \
  python3 /llamacpp/convert_hf_to_gguf.py merged_1p5b --outfile drive_cmd_1p5b_f16.gguf --outtype f16 2>&1 | tail -1
"$BIN/llama-quantize" drive_cmd_1p5b_f16.gguf drive_cmd_1p5b_q4km.gguf Q4_K_M 2>&1 | tail -1
ls -la drive_cmd_rej_q4km.gguf drive_cmd_1p5b_q4km.gguf | awk '{printf "%-28s %5.0f MB\n", $9, $5/1048576}'

echo "##### 실사용 지연: 명령 간격 3초, 서버가 클럭 고정 (0.5B 거부 모델과 같은 조건) #####"
for M in drive_cmd_rej_q4km drive_cmd_1p5b_q4km; do
  setsid ~/robot/llama_server.sh "/mnt/nvme/finetune/work/${M}.gguf" > "server_lat_${M}.log" 2>&1 < /dev/null &
  for _ in $(seq 120); do curl -sf http://127.0.0.1:8080/health >/dev/null && break; sleep 1; done
  echo -n "${M}: "
  for t in "앞으로 천천히 3초 동안 가" "5초 동안 오른쪽으로 돌아" "뒤로 빠르게 2초" \
           "왼쪽으로 가면서 앞으로 가" "천천히 왼쪽으로 돌아" "7초 동안 직진으로 빠르게"; do
    sleep 3
    python3 infer.py --server http://127.0.0.1:8080/v1/chat/completions "$t" 2>&1 >/dev/null | grep -o '[0-9]* ms'
  done | tr '\n' ' '; echo
  free -m | awk 'NR==2{print "  used " $3 " MB"}'
  pkill -TERM -f "[l]lama_server\.sh"; sleep 3
done

echo "##### 비교 #####"
python3 report_seeds.py
echo DONE_1P5B
