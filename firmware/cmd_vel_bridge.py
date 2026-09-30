"""상주 /cmd_vel 브릿지. 명령마다 ROS를 새로 띄우던 비용(약 2초)을 없앤다.

로컬 TCP(127.0.0.1:8765)로 JSON 한 줄을 받아 /cmd_vel로 내보낸다.
  {"linear": 0.15, "angular": 0.0, "duration": 2.0}   -> 2초 동안 10 Hz, 끝나면 정지
  {"linear": 0.0,  "angular": 0.0, "duration": 0.0}   -> 즉시 정지

새 명령은 진행 중인 명령을 바로 덮어쓴다. 예전 방식은 스크립트가 주행 시간만큼
붙잡혀 있어 달리는 중에 "멈춰"를 보낼 수 없었다.
응답: {"ok": true, "subscribers": <구독자 수>}  — 0이면 ESP32가 붙어 있지 않다는 뜻이다.
"""
import json
import socket
import threading
import time

import rclpy
from geometry_msgs.msg import Twist

HOST, PORT = "127.0.0.1", 8765
RATE_HZ = 10
TICK_S = 0.02        # 새 명령은 다음 틱(최대 20 ms)에 첫 발행
STOP_REPEAT = 3      # 정지는 몇 번 보낸다. 한 번은 유실될 수 있다
MAX_DURATION = 10.0


class Bridge:
    def __init__(self, node):
        self.node = node
        self.pub = node.create_publisher(Twist, "cmd_vel", 10)
        self.lock = threading.Lock()
        self.lin = self.ang = 0.0
        self.until = 0.0          # 이 시각까지 현재 명령을 보낸다
        self.next_pub = 0.0
        self.stops_left = 0
        node.create_timer(TICK_S, self.tick)

    def set(self, lin, ang, dur):
        now = time.monotonic()
        with self.lock:
            if dur > 0 and (lin or ang):
                self.lin, self.ang, self.until = lin, ang, now + dur
                self.stops_left = STOP_REPEAT
            else:
                self.until = 0.0
                self.stops_left = STOP_REPEAT
            self.next_pub = now

    def tick(self):
        now = time.monotonic()
        with self.lock:
            if now < self.next_pub:
                return
            # now가 아니라 예정 시각에 더한다. now 기준이면 틱(20 ms)만큼씩 밀려 9 Hz가 된다
            self.next_pub += 1.0 / RATE_HZ
            if self.next_pub < now:        # 크게 밀렸으면 다시 맞춘다
                self.next_pub = now + 1.0 / RATE_HZ
            if now < self.until:
                lin, ang = self.lin, self.ang
            elif self.stops_left > 0:
                self.stops_left -= 1
                lin = ang = 0.0
            else:
                return
        m = Twist()
        m.linear.x, m.angular.z = float(lin), float(ang)
        self.pub.publish(m)


def serve(bridge):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(4)
    while True:
        conn, _ = srv.accept()
        with conn:
            try:
                cmd = json.loads(conn.makefile("r", encoding="utf-8").readline())
                lin, ang, dur = (float(cmd[k]) for k in ("linear", "angular", "duration"))
                if not 0 <= dur <= MAX_DURATION:
                    raise ValueError(f"duration {dur}")
                bridge.set(lin, ang, dur)
                reply = {"ok": True, "subscribers": bridge.pub.get_subscription_count()}
            except Exception as e:           # 잘못된 입력은 거절만 하고 계속 돈다
                reply = {"ok": False, "error": str(e)}
            conn.sendall((json.dumps(reply) + "\n").encode("utf-8"))


def main():
    rclpy.init()
    node = rclpy.create_node("cmd_vel_bridge")
    bridge = Bridge(node)
    threading.Thread(target=serve, args=(bridge,), daemon=True).start()
    print(f"[bridge] {HOST}:{PORT} -> /cmd_vel", flush=True)
    rclpy.spin(node)


if __name__ == "__main__":
    main()
