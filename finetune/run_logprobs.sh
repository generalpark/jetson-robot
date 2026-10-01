#!/usr/bin/env bash
# 확신도 분석용 데이터 수집. GGUF(Q4_K_M) 두 개 × 반복 패널티 두 조건 × 평가셋 세 개.
# 토큰별 상위 5개 logprob을 결과 파일에 남긴다 — analyze_confidence.py가 읽는다.
#   rp=def : 서버 기본값. GGUF에 담긴 Qwen 권장 설정이라 repeat_penalty 1.1
#   rp=1.0 : 순수 그리디
# valid_rej는 학습과 같은 분포라, 확신도 기준선을 여기서 정하고 테스트에 그대로 쓴다.
set -eu
cd /mnt/nvme/finetune/work
BIN=/mnt/nvme/llama.cpp/build/bin
PORT=8083

for M in rej:drive_cmd_rej_q4km base:drive_cmd_q4km; do
  NAME="${M%%:*}"
  "$BIN/llama-server" -m "${M#*:}.gguf" -ngl 99 --host 127.0.0.1 --port $PORT -c 2048 \
    > "server_lp_${NAME}.log" 2>&1 &
  SRV=$!
  for _ in $(seq 120); do curl -sf http://127.0.0.1:$PORT/health >/dev/null && break; sleep 1; done
  for RP in def 1.0; do
    OPT=""
    [ "$RP" = def ] || OPT="--repeat-penalty $RP"
    for T in test test_offtopic valid_rej; do
      echo "== ${NAME} rp=${RP} ${T}"
      docker run --rm --network host -v /mnt/nvme/finetune/work:/work -w /work finetune:jetson \
        python3 eval_gguf.py --url http://127.0.0.1:$PORT/v1/chat/completions \
        --test "${T}.jsonl" --label "${NAME}_rp${RP}_${T}" --logprobs 5 ${OPT} \
        --out "lp_${NAME}_rp${RP}_${T}.json" | grep -E '"(exact|sign|reject|moves)"' | tr -d '\n '
      echo
    done
  done
  kill $SRV; wait $SRV 2>/dev/null || true
done
echo DONE_LP
