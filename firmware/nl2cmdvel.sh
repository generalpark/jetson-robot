#!/usr/bin/env bash
# 자연어 한 줄로 로봇을 움직인다. Jetson에서 실행.
#
#   "앞으로 천천히 3초 동안 가"
#        -> 파인튜닝 모델(llama-server, Q4_K_M) -> {"linear":0.15,"angular":0.0,"duration":3.0}
#        -> cmd_vel 브릿지 -> ROS 2 /cmd_vel -> micro-ROS -> ESP32 -> 모터
#
# 준비: 다른 창에서
#   ~/robot/uros_agent.sh /dev/ttyUSB0
#   ~/robot/llama_server.sh
#   ~/robot/cmd_bridge.sh      (없으면 명령마다 ROS를 띄우는 느린 경로로 간다)
#
# 정지어("멈춰", "세워" 등)는 모델을 거치지 않으므로 llama-server가 없어도 멈춘다.
# 브릿지 경로에서는 명령을 넘기고 바로 끝난다. 달리는 중에 다음 명령("멈춰")을 보내면 덮어쓴다.
set -eu

INSTRUCTION="${*:?사용법: ./nl2cmdvel.sh \"앞으로 천천히 가\"}"
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK=/mnt/nvme/finetune/work
LLAMA=http://127.0.0.1:8080
ROS_IMG="dustynv/ros:humble-ros-base-l4t-r36.3.0"

echo "[1/2] 명령 해석: ${INSTRUCTION}"
RC=0
CMD_JSON=$(python3 "${WORK}/infer.py" --server "${LLAMA}/v1/chat/completions" "${INSTRUCTION}") || RC=$?
if [ "${RC}" -eq 2 ]; then
  echo "      -> 주행 명령이 아니라서 움직이지 않는다."
  exit 0
fi
[ "${RC}" -eq 0 ] || exit "${RC}"
echo "      -> ${CMD_JSON}"

REPLY=$(python3 -c '
import socket, sys
s = socket.create_connection(("127.0.0.1", 8765), timeout=1)
s.sendall((sys.argv[1] + "\n").encode())
print(s.makefile().readline().strip())
' "${CMD_JSON}" 2>/dev/null) || REPLY=""

if [ -n "${REPLY}" ]; then
  echo "[2/2] 브릿지로 전달: ${REPLY}"
  case "${REPLY}" in
    *'"subscribers": 0'*) echo "      [!] /cmd_vel 구독자 없음 — Agent와 ESP32 연결 확인" >&2 ;;
  esac
  exit 0
fi

# 브릿지가 없을 때: 명령마다 ROS 컨테이너를 띄운다 (약 2초 더 걸린다)
read -r LIN ANG DUR < <(echo "${CMD_JSON}" | python3 -c \
  'import json,sys; c=json.load(sys.stdin); print(c["linear"], c["angular"], c["duration"])')
echo "[2/2] 브릿지 없음 — 느린 경로로 /cmd_vel 발행: linear=${LIN} angular=${ANG} (${DUR}초)"
# 펌웨어가 500ms 무명령이면 멈추므로 주기적으로 계속 보내야 한다 — pub_cmd_vel.py 참고
docker run --rm --net=host --ipc=host -v "${HERE}":/fw "${ROS_IMG}" bash -c "
  source /opt/ros/humble/install/setup.bash >/dev/null
  python3 /fw/pub_cmd_vel.py ${LIN} ${ANG} ${DUR}
"
