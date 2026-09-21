"""모터 제어 펌웨어 동작 확인.

드라이버·모터가 없는 상태에서 펌웨어 로직을 검증한다.
확인 항목은 세 가지다.
  1) 속도 명령이 그대로 반영되는가
  2) 정/역 전환이 되는가
  3) 명령이 끊기면 스스로 멈추는가 (타임아웃)
"""
import sys
import time

import serial

port = sys.argv[1] if len(sys.argv) > 1 else "COM3"

# 포트를 그냥 열면 DTR/RTS가 켜지면서 보드가 리셋되거나 부트 모드가 바뀐다.
# 둘 다 내린 상태로 연 뒤, RTS를 잠깐 올렸다 내려 의도적으로 한 번만 리셋한다.
ser = serial.Serial()
ser.port = port
ser.baudrate = 115200
ser.timeout = 1.5
ser.dtr = False
ser.rts = False
ser.open()

ser.rts = True      # EN을 내려 리셋
time.sleep(0.15)
ser.rts = False     # 놓으면 정상 부팅
time.sleep(2.0)     # 부팅 대기
ser.reset_input_buffer()


def send(cmd, wait=0.3):
    ser.write((cmd + "\n").encode())
    time.sleep(wait)
    out = []
    while ser.in_waiting:
        line = ser.readline().decode("utf-8", "replace").strip()
        if line:
            out.append(line)
    return out


print(f"[연결] {port} 115200\n")

print("1) 부팅 메시지")
ser.write(b"?\n")
time.sleep(0.5)
for l in send("?"):
    print("   ", l)

print("\n2) 속도 명령")
for cmd in ["L 200", "R 150", "L -120", "R -255"]:
    r = send(cmd)
    print(f"    {cmd:8s} -> {r}")

print("\n3) 범위 제한 (255를 넘겨본다)")
print(f"    L 999    -> {send('L 999')}")

print("\n4) 정지 명령")
print(f"    S        -> {send('S')}")

print("\n5) 타임아웃 확인 — 속도를 준 뒤 1초간 아무 명령도 보내지 않는다")
send("L 200")
print("    L 200 보냄, 대기...")
time.sleep(1.2)
out = []
while ser.in_waiting:
    line = ser.readline().decode("utf-8", "replace").strip()
    if line:
        out.append(line)
print(f"    자동 출력: {out}")
print(f"    상태 확인: {send('?')}")

print("\n6) 잘못된 명령")
print(f"    X        -> {send('X')}")

ser.close()
print("\n[완료]")
