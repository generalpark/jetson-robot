"""눈으로 확인하는 데모. 온보드 LED 밝기가 PWM 듀티를 그대로 보여준다."""
import sys
import time

import serial

port = sys.argv[1] if len(sys.argv) > 1 else "COM3"
ser = serial.Serial()
ser.port, ser.baudrate, ser.timeout = port, 115200, 1.0
ser.dtr = ser.rts = False
ser.open()
ser.rts = True; time.sleep(0.15); ser.rts = False
time.sleep(2.0)
ser.reset_input_buffer()

def cmd(c):
    ser.write((c + "\n").encode())
    time.sleep(0.05)
    while ser.in_waiting:
        ser.readline()

print("1) 밝기 서서히 올리기 (0 -> 255)")
for v in range(0, 256, 5):
    cmd(f"L {v}")
    time.sleep(0.04)

print("2) 서서히 내리기 (255 -> 0)")
for v in range(255, -1, -5):
    cmd(f"L {v}")
    time.sleep(0.04)

print("3) 깜빡임 - 정방향/역방향 전환 (LED는 세기만 보이므로 둘 다 켜짐)")
for _ in range(6):
    cmd("L 255"); time.sleep(0.2)
    cmd("L -255"); time.sleep(0.2)

print("4) 타임아웃 확인 - 255를 주고 명령을 끊는다. 0.5초 뒤 LED가 꺼져야 한다")
cmd("L 255")
print("   ... 지금 켜져 있음")
time.sleep(1.5)
print("   ... 꺼졌나요?")

ser.write(b"?\n"); time.sleep(0.3)
while ser.in_waiting:
    print("   상태:", ser.readline().decode("utf-8", "replace").strip())

cmd("S")
ser.close()
print("\n[완료]")
