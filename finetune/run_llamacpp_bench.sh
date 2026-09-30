#!/usr/bin/env bash
# Quantize the GGUF and benchmark F16 / Q8_0 / Q4_K_M on the GPU.
cd /mnt/nvme/finetune/work
BIN=/mnt/nvme/llama.cpp/build/bin
export PATH=/usr/local/cuda/bin:$PATH

bash monitor.sh /mnt/nvme/finetune/work/power_llamacpp.log &
MON=$!

echo "=== quantize Q8_0 ==="
$BIN/llama-quantize drive_cmd_f16.gguf drive_cmd_q8_0.gguf Q8_0 2>&1 | tail -2
echo "=== quantize Q4_K_M ==="
$BIN/llama-quantize drive_cmd_f16.gguf drive_cmd_q4km.gguf Q4_K_M 2>&1 | tail -2

echo "=== sizes ==="
ls -la drive_cmd_*.gguf | awk '{printf "%-26s %6.0f MB\n", $9, $5/1048576}'

echo "=== bench (pp128 / tg32, all layers on GPU) ==="
$BIN/llama-bench \
  -m drive_cmd_f16.gguf \
  -m drive_cmd_q8_0.gguf \
  -m drive_cmd_q4km.gguf \
  -p 128 -n 32 -ngl 99 -r 5 2>&1 | tail -20

kill $MON 2>/dev/null
echo DONE_BENCH
