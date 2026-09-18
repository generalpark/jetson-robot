#!/bin/bash
# micro-ROS Agent 실행 - ESP32와 시리얼(USB)로 통신
# 사용법: ./uros_agent.sh [장치]   (기본 /dev/ttyUSB0)
DEV="${1:-/dev/ttyUSB0}"

if [ ! -e "$DEV" ]; then
  echo "[!] $DEV 없음. 연결된 USB 시리얼 장치:"
  ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || echo "    (없음 - ESP32가 연결됐는지 확인)"
  exit 1
fi

echo "[*] micro-ROS Agent 시작: $DEV (Ctrl+C 로 종료)"
docker run -it --rm \
  --net=host \
  --device "$DEV":"$DEV" \
  microros/micro-ros-agent:humble \
  serial -D "$DEV" -b 115200 -v6
