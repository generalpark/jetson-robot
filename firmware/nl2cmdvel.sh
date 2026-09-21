#!/usr/bin/env bash
# 자연어 한 줄로 로봇을 움직인다. Jetson에서 실행.
#
#   "앞으로 천천히 3초 동안 가"
#        -> 파인튜닝 모델 -> {"linear":0.15,"angular":0.0,"duration":3.0}
#        -> ROS 2 /cmd_vel -> micro-ROS -> ESP32 -> 모터
#
# 준비: 다른 창에서 Agent 실행  ~/robot/uros_agent.sh /dev/ttyUSB0
set -eu

INSTRUCTION="${*:?사용법: ./nl2cmdvel.sh \"앞으로 천천히 가\"}"
WORK=/mnt/nvme/finetune/work
ROS_IMG="dustynv/ros:humble-ros-base-l4t-r36.3.0"

echo "[1/3] 명령 해석: ${INSTRUCTION}"
CMD_JSON=$(docker run --rm -e HF_HUB_DISABLE_PROGRESS_BARS=1 \
  -v "${WORK}":/work \
  -v /mnt/nvme/finetune/hf_cache:/mnt/nvme/finetune/hf_cache \
  -w /work finetune:jetson \
  python3 infer.py "${INSTRUCTION}" 2>/dev/null | tail -1)

echo "      -> ${CMD_JSON}"

LIN=$(echo "${CMD_JSON}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["linear"])')
ANG=$(echo "${CMD_JSON}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["angular"])')
DUR=$(echo "${CMD_JSON}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["duration"])')

echo "[2/3] /cmd_vel 발행: linear=${LIN} angular=${ANG} (${DUR}초)"
# 펌웨어가 500ms 무명령이면 멈추므로 주기적으로 계속 보내야 한다.
docker run --rm --net=host "${ROS_IMG}" bash -c "
  source /opt/ros/humble/install/setup.bash
  timeout ${DUR} ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/Twist \
    '{linear: {x: ${LIN}}, angular: {z: ${ANG}}}'
" || true

echo "[3/3] 명령 종료. 펌웨어 타임아웃으로 자동 정지한다."
