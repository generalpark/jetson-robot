#!/usr/bin/env bash
# Build llama.cpp with CUDA for Jetson Orin (sm_87).
# -j 3 on purpose: CUDA kernel compilation is memory hungry and the board
# only has 8 GB shared between CPU and GPU. -j 6 risks the OOM killer.
cd /mnt/nvme/llama.cpp
export PATH=/usr/local/cuda/bin:$PATH

bash /mnt/nvme/finetune/work/monitor.sh /mnt/nvme/finetune/work/power_build.log &
MON=$!

cmake -B build \
  -DGGML_CUDA=ON \
  -DCMAKE_CUDA_ARCHITECTURES=87 \
  -DLLAMA_CURL=OFF \
  -DCMAKE_BUILD_TYPE=Release > /mnt/nvme/llama.cpp/cmake.log 2>&1
CFG=$?
echo "configure exit=$CFG"
tail -5 /mnt/nvme/llama.cpp/cmake.log

if [ $CFG -eq 0 ]; then
  cmake --build build --config Release -j 3 > /mnt/nvme/llama.cpp/build.log 2>&1
  RC=$?
  echo "build exit=$RC"
  tail -15 /mnt/nvme/llama.cpp/build.log
else
  RC=$CFG
fi

kill $MON 2>/dev/null
echo "=== binaries ==="
ls build/bin/ 2>/dev/null | grep -E "llama-(cli|bench|quantize)" || echo "(none)"
echo "EXIT=$RC"
echo DONE_BUILD
