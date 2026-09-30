#!/bin/bash
# /cmd_vel 브릿지 상주 — nl2cmdvel.sh가 127.0.0.1:8765로 명령을 넘긴다.
# 명령마다 ROS 컨테이너를 띄우던 약 2초를 없앤다. (Ctrl+C 로 종료)
# --ipc=host: 컨테이너끼리 Fast DDS 공유메모리로 통신하므로 필요 (ros2sh.sh 참고)
FW="${FW:-/mnt/nvme/firmware}"

echo "[*] cmd_vel 브릿지 시작: 127.0.0.1:8765 -> /cmd_vel"
exec docker run --rm --init --name cmd_bridge --net=host --ipc=host \
  -v "$FW":/fw \
  dustynv/ros:humble-ros-base-l4t-r36.3.0 \
  bash -c 'source /opt/ros/humble/install/setup.bash >/dev/null; exec python3 /fw/cmd_vel_bridge.py'
