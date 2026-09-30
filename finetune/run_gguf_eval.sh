#!/usr/bin/env bash
# Serve each GGUF in turn and score it with the original test set.
cd /mnt/nvme/finetune/work
BIN=/mnt/nvme/llama.cpp/build/bin

for M in q8_0 q4km f16; do
  echo "===== $M ====="
  $BIN/llama-server -m drive_cmd_${M}.gguf -ngl 99 --host 127.0.0.1 --port 8080 \
      -c 2048 > server_${M}.log 2>&1 &
  SRV=$!
  python3 -c "
import urllib.request, time, sys
for _ in range(120):
    try:
        urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)
        print('server ready'); sys.exit(0)
    except Exception:
        time.sleep(1)
print('server TIMEOUT'); sys.exit(1)
"
  docker run --rm --network host -v /mnt/nvme/finetune/work:/work -w /work \
    finetune:jetson python3 eval_gguf.py \
      --url http://127.0.0.1:8080/v1/chat/completions \
      --label "$M" --out "result_gguf_${M}.json" 2>&1 | tail -12
  kill $SRV 2>/dev/null
  wait $SRV 2>/dev/null
done
echo DONE_EVAL
