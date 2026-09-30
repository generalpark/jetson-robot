#!/bin/bash
# 주행 명령 모델(Q4_K_M GGUF)을 llama-server로 상주시킨다.
# 모델을 한 번만 올려두고 명령마다 HTTP로 묻는다 — nl2cmdvel.sh가 여기에 붙는다.
# 사용법: ./llama_server.sh [GGUF]   (Ctrl+C 로 종료)
MODEL="${1:-/mnt/nvme/finetune/work/drive_cmd_q4km.gguf}"
BIN=/mnt/nvme/llama.cpp/build/bin/llama-server
DF=/sys/class/devfreq/17000000.gpu

if [ ! -e "$MODEL" ]; then
  echo "[!] $MODEL 없음. 있는 GGUF:"
  ls /mnt/nvme/finetune/work/*.gguf 2>/dev/null || echo "    (없음)"
  exit 1
fi

# 명령은 드문드문 온다. 요청 하나가 0.5초 안에 끝나 GPU 클럭이 306 MHz에서
# 올라오기 전에 끝나므로, 서버가 떠 있는 동안만 최저 클럭을 최대로 고정한다.
# 실측(2026-10-01): 응답 약 810 ms -> 420 ms, 대기 전력 +0.84 W. 종료 시 원복.
ORIG_MIN=$(cat "$DF/min_freq")
SRV=
cleanup() {
  [ -n "$SRV" ] && kill "$SRV" 2>/dev/null && wait "$SRV" 2>/dev/null
  echo "$ORIG_MIN" | sudo tee "$DF/min_freq" >/dev/null
  echo "[*] 종료. GPU 최저 클럭 원복: $ORIG_MIN Hz"
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP
cat "$DF/max_freq" | sudo tee "$DF/min_freq" >/dev/null

echo "[*] llama-server 시작: $MODEL -> http://127.0.0.1:8080 (GPU $(cat "$DF/min_freq") Hz 고정)"
# -ngl 99: 전 레이어 GPU. -c 2048: 평가(run_gguf_eval.sh)와 같은 설정
"$BIN" -m "$MODEL" -ngl 99 --host 127.0.0.1 --port 8080 -c 2048 &
SRV=$!
wait "$SRV"
