#!/bin/bash
# ROS2 셸 진입 (토픽 확인, 테스트용)
docker run -it --rm --net=host \
  -v ~/robot:/robot \
  dustynv/ros:humble-ros-base-l4t-r36.3.0 \
  bash -c 'source /opt/ros/humble/install/setup.bash; cd /robot; exec bash'
