#!/bin/bash
# ROS2 셸 진입 (토픽 확인, 테스트용)
# --ipc=host: 컨테이너끼리는 Fast DDS가 공유메모리로 통신하려 해서, 이게 없으면
# 토픽 목록은 보여도 메시지가 안 넘어온다 (echo가 조용함). 2026-10-01 확인
docker run -it --rm --net=host --ipc=host \
  -v ~/robot:/robot \
  dustynv/ros:humble-ros-base-l4t-r36.3.0 \
  bash -c 'source /opt/ros/humble/install/setup.bash; cd /robot; exec bash'
