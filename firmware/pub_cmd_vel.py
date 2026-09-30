"""/cmd_vel을 정확히 duration초 동안 10 Hz로 보내고, 끝나면 정지 명령을 보낸다.

`timeout N ros2 topic pub`은 ROS 기동 시간(약 1초)까지 N초에 포함돼
실제 주행이 짧아진다. 여기서는 구독자(ESP32)와 연결된 뒤부터 시간을 잰다.
끝에 0을 보내는 이유: 안 보내면 펌웨어 타임아웃(500 ms)까지 마지막 명령으로 계속 간다.

사용: python3 pub_cmd_vel.py <linear> <angular> <duration>
"""
import sys
import time

import rclpy
from geometry_msgs.msg import Twist

RATE_HZ = 10
MATCH_TIMEOUT_S = 3.0


def twist(lin, ang):
    m = Twist()
    m.linear.x = lin
    m.angular.z = ang
    return m


def main():
    lin, ang, dur = (float(v) for v in sys.argv[1:4])
    rclpy.init()
    node = rclpy.create_node("nl2cmdvel")
    pub = node.create_publisher(Twist, "cmd_vel", 10)

    # 연결 전에 보낸 메시지는 버려진다. 구독자가 잡힐 때까지 기다린다.
    t0 = time.monotonic()
    while pub.get_subscription_count() == 0:
        if time.monotonic() - t0 > MATCH_TIMEOUT_S:
            print("[!] /cmd_vel 구독자 없음 — Agent와 ESP32 연결 확인", file=sys.stderr)
            sys.exit(1)
        time.sleep(0.05)

    msg, n = twist(lin, ang), 0
    start = time.monotonic()
    while time.monotonic() - start < dur:
        pub.publish(msg)
        n += 1
        time.sleep(1.0 / RATE_HZ)
    for _ in range(3):
        pub.publish(twist(0.0, 0.0))
        time.sleep(0.05)
    print(f"      {n}회 발행, {time.monotonic() - start:.2f}초 후 정지 명령")

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
