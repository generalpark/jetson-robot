#!/usr/bin/env bash
# 자연어 한 줄로 로봇을 움직인다. Jetson에서 실행.
#
#   "앞으로 천천히 3초 동안 가"
#        -> 파인튜닝 모델(llama-server, Q4_K_M) -> {"linear":0.15,"angular":0.0,"duration":3.0}
#        -> ROS 2 /cmd_vel -> micro-ROS -> ESP32 -> 모터
#
# 준비: 다른 창 두 개에서
#   ~/robot/uros_agent.sh /dev/ttyUSB0
#   ~/robot/llama_server.sh
set -eu

INSTRUCTION="${*:?사용법: ./nl2cmdvel.sh \"앞으로 천천히 가\"}"
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK=/mnt/nvme/finetune/work
LLAMA=http://127.0.0.1:8080
ROS_IMG="dustynv/ros:humble-ros-base-l4t-r36.3.0"

if ! curl -sf "${LLAMA}/health" >/dev/null; then
  echo "[!] llama-server가 떠 있지 않다. 다른 창에서 ~/robot/llama_server.sh 실행" >&2
  exit 1
fi

echo "[1/3] 명령 해석: ${INSTRUCTION}"
CMD_JSON=$(python3 "${WORK}/infer.py" --server "${LLAMA}/v1/chat/completions" "${INSTRUCTION}")

echo "      -> ${CMD_JSON}"

read -r LIN ANG DUR < <(echo "${CMD_JSON}" | python3 -c \
  'import json,sys; c=json.load(sys.stdin); print(c["linear"], c["angular"], c["duration"])')

echo "[2/3] /cmd_vel 발행: linear=${LIN} angular=${ANG} (${DUR}초)"
# 펌웨어가 500ms 무명령이면 멈추므로 주기적으로 계속 보내야 한다 — pub_cmd_vel.py 참고
docker run --rm --net=host --ipc=host -v "${HERE}":/fw "${ROS_IMG}" bash -c "
  source /opt/ros/humble/install/setup.bash >/dev/null
  python3 /fw/pub_cmd_vel.py ${LIN} ${ANG} ${DUR}
"

echo "[3/3] 명령 종료."
