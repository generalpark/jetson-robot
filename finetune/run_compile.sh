#!/usr/bin/env bash
# torch.compile + static cache benchmark. Compilation can take several
# minutes, so this is meant to be launched detached with its output tee'd.
cd /mnt/nvme/finetune/work
bash monitor.sh /mnt/nvme/finetune/work/power_compile.log &
MON=$!
docker run --rm \
  -e HF_HUB_DISABLE_PROGRESS_BARS=1 \
  -e TORCHINDUCTOR_CACHE_DIR=/work/.inductor \
  -v /mnt/nvme/finetune/work:/work \
  -v /mnt/nvme/finetune/hf_cache:/mnt/nvme/finetune/hf_cache \
  -w /work finetune:jetson \
  python3 benchmark.py --adapter adapter --merge --compile --n 30 \
    --label fp16_merged_compiled --out bench_compiled.json
RC=$?
kill $MON 2>/dev/null
echo "EXIT=$RC"
echo "DONE_COMPILE"
