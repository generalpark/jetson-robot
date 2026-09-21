#!/usr/bin/env bash
# micro-ROS 연결 확인. Jetson에서 실행한다.
#
# 준비: ESP32를 Jetson USB에 연결하고, 다른 창에서 Agent를 띄워둔다.
#   ~/robot/uros_agent.sh /dev/ttyUSB0
set -eu

ROS_IMG="dustynv/ros:humble-ros-base-l4t-r36.3.0"
run_ros() {
  docker run --rm --net=host "${ROS_IMG}" \
    bash -c "source /opt/ros/humble/install/setup.bash; $1"
}

echo "===== 1) 노드 목록 ====="
run_ros "ros2 node list" || echo "  (노드 없음 - Agent가 떠 있는지, ESP32가 붙었는지 확인)"

echo
echo "===== 2) 토픽 목록 ====="
run_ros "ros2 topic list"

echo
echo "===== 3) cmd_vel 구독자 확인 ====="
run_ros "ros2 topic info /cmd_vel"

echo
echo "===== 4) 전진 명령 (linear.x=0.3, 2초) ====="
run_ros "timeout 2 ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/Twist \
  '{linear: {x: 0.3}, angular: {z: 0.0}}'" || true
echo "  -> LED가 중간 밝기로 켜졌어야 한다"

echo
echo "===== 5) 제자리 회전 (angular.z=1.0, 2초) ====="
run_ros "timeout 2 ros2 topic pub -r 10 /cmd_vel geometry_msgs/msg/Twist \
  '{linear: {x: 0.0}, angular: {z: 1.0}}'" || true
echo "  -> 좌우 바퀴가 반대 방향. LED는 세기만 보인다"

echo
echo "===== 6) 타임아웃 확인 ====="
echo "  명령 발행을 멈춘 뒤 0.5초 안에 LED가 꺼져야 한다"
sleep 2
echo "  -> 꺼졌는가?"

echo
echo "[완료]"
