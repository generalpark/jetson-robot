"""카메라로 앞 바닥을 보고, 가까이 물체가 있으면 전진을 막는다. Jetson에서 실행.

    python3 obstacle_guard.py              # cam_stream.py(8090)와 cmd_vel 브릿지(8765)가 떠 있어야 한다
    python3 obstacle_guard.py --debug      # /tmp/guard_debug.jpg에 판단 근거를 그려 1초마다 저장

방식 — 단안 카메라 바닥 경계(Ulrich & Nourbakhsh 2000의 외형 기반 장애물 검출을 단순화):
  1. 시작할 때 화면 맨 아래 띠(로봇 바로 앞 바닥)의 색 평균·분산(Lab)을 '바닥'으로 기억한다
     -> 시작 순간에는 바로 앞이 비어 있어야 한다
  2. 매 프레임, 로봇 폭에 해당하는 가운데 통로에서 바닥 색에서 많이 벗어난 픽셀을 찾는다
     (처음엔 HSV 히스토그램을 썼는데 나뭇결·조명 차이로 바닥 곳곳이 물체로 잡혀 바꿨다. --method hist로 남겨 둠)
  3. 열마다 아래에서 위로 올라가며 '바닥 아님'이 연속으로 나오는 첫 지점 = 그 열의 장애물 밑변
  4. 밑변이 정지선보다 아래면 가까운 것. 정지선은 전진 속도에 따라 움직인다:
     목표 30cm + (속도 x 0.17초 + 속도^2 x 0.91)만큼 먼 곳 — 처음엔 속도 비례(0.2초)로 했는데
     0.3m/s에서 23cm에 서서 제동 거리(속도 제곱) 항을 더했다. 거리는 (y - 수평선) = k / 거리로 환산
     (--fixed면 화면 높이 74% 고정, 11/4 실측으로 몸통 앞 약 30cm)
  5. 가까운 열이 통로의 일정 비율 이상이고 3프레임 연속이면 막고, 6프레임 연속 비면 푼다

막으면 브릿지가 달리던 전진을 끊고 새 전진을 거절한다. 회전·후진은 된다.
가드가 죽으면 막힌 상태는 그대로 남는다(안전한 쪽). 풀려 있을 때 죽으면 보호가 없다.
"""
import argparse
import json
import socket
import time
import urllib.request

import cv2
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--snapshot", default="http://127.0.0.1:8090/snapshot.jpg")
ap.add_argument("--stop-y", type=float, default=0.74, help="(--fixed일 때) 정지선(화면 높이 비율)")
ap.add_argument("--fixed", action="store_true", help="속도와 상관없이 --stop-y 고정 정지선 사용")
ap.add_argument("--target", type=float, default=30.0, help="멈춘 뒤 앞에 남길 거리(cm)")
ap.add_argument("--lag", type=float, default=0.17, help="정지 반응 지연(s): 더 가는 거리 = v*lag + v^2*brake")
ap.add_argument("--brake", type=float, default=0.91, help="제동 계수(s^2/m). 11/5 실측: 0.15m/s 4.6cm, 0.3m/s 13.3cm 더 감 -> lag 0.17, brake 0.91")
ap.add_argument("--horizon", type=float, default=0.347, help="바닥 수평선 높이(화면 비율, 11/4 실측)")
ap.add_argument("--k", type=float, default=12.4, help="바닥 거리 환산 상수: 거리(cm) = k / (y - horizon). 30cm->0.75, 20cm->0.98 실측으로 맞춤")
ap.add_argument("--corridor", type=float, default=0.45, help="가운데 통로 폭(화면 폭 비율)")
ap.add_argument("--min-cols", type=float, default=0.12, help="통로 열 중 이 비율 이상이 가까우면 장애물")
ap.add_argument("--thresh", type=float, default=0.15, help="(hist) 바닥 히스토그램 역투영 값이 이보다 낮으면 '바닥 아님'")
ap.add_argument("--method", choices=["lab", "hist"], default="lab", help="lab: 바닥 색 평균·분산에서 벗어난 정도(기본) / hist: HSV 히스토그램")
ap.add_argument("--dist", type=float, default=4.0, help="(lab) 바닥 색에서 이 표준편차 이상 벗어나면 '바닥 아님'")
ap.add_argument("--ref", type=float, default=0.20, help="시작 때 바닥으로 기억할 맨 아래 띠의 높이(화면 비율)")
ap.add_argument("--run", type=int, default=6, help="'바닥 아님'이 위로 몇 픽셀 연속이어야 물체로 보나(작은 잡티 무시)")
ap.add_argument("--hz", type=float, default=10.0)
ap.add_argument("--debug", action="store_true")
args = ap.parse_args()

W, H = 320, 180            # 판단은 축소 영상으로 — 1280x720이면 느리다


def grab():
    with urllib.request.urlopen(args.snapshot, timeout=2) as r:
        buf = np.frombuffer(r.read(), np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    return cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)


def send(obj):
    s = socket.create_connection(("127.0.0.1", 8765), timeout=1)
    s.sendall((json.dumps(obj) + "\n").encode())
    reply = s.makefile().readline().strip()
    s.close()
    return reply


x0 = int(W * (1 - args.corridor) / 2)
x1 = W - x0
def stop_line(v):
    """전진 속도 v(m/s)일 때의 정지선 y(픽셀). 빨리 달릴수록 정지가 늦으므로 선을 먼 쪽(위)으로 올린다.
    바닥 위 물체의 밑변 높이 y와 거리 d는 (y - 수평선) = k / d 관계(카메라 높이 고정, 바닥 평면)."""
    if args.fixed:
        return int(H * args.stop_y)
    v = max(v, 0.0)
    d = args.target + 100.0 * (v * args.lag + v * v * args.brake)   # cm. 제동 거리는 속도 제곱에 비례
    return int(H * (args.horizon + args.k / d))


def bridge_speed():
    try:
        return float(json.loads(send({"status": True})).get("linear", 0.0))
    except Exception:
        return 0.0


y_stop = stop_line(0.0)

# 1. 바닥 기억: 맨 아래 8% 띠, 통로 부분
first = grab()
hsv0 = cv2.cvtColor(first, cv2.COLOR_BGR2HSV)
ref = hsv0[int(H * (1 - args.ref)):, x0:x1]
hist = cv2.calcHist([ref], [0, 1], None, [18, 16], [0, 180, 0, 256])
cv2.normalize(hist, hist, 0, 255, cv2.NORM_MINMAX)   # calcBackProject는 히스토그램 값을 그대로 픽셀값(0~255)으로 쓴다
# lab: 나뭇결·조명 차이로 색이 조금씩 흔들려도 같은 바닥으로 보도록 평균·공분산(마할라노비스 거리)을 쓴다.
# 밝기(L)는 그림자에 크게 흔들리므로 절반만 반영한다
L_W = 0.5
def lab_feat(bgr):
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    lab[..., 0] *= L_W
    return lab
f0 = lab_feat(first)[int(H * (1 - args.ref)):, x0:x1].reshape(-1, 3)
mu = f0.mean(axis=0)
icov = np.linalg.inv(np.cov(f0, rowvar=False) + np.eye(3) * 4.0)   # 분산이 너무 작으면 작은 흔들림도 물체로 보므로 바닥값을 더한다
print(f"[guard] 바닥 기억 완료. 통로 x={x0}~{x1}, 정지선 y={y_stop}/{H}", flush=True)
print("[guard] 브릿지:", send({"block": False}), flush=True)

blocked = False
near_streak = clear_streak = 0
last_dbg = 0.0
period = 1.0 / args.hz

while True:
    t = time.monotonic()
    try:
        img = grab()
    except Exception as e:                       # 카메라 서버가 잠깐 끊겨도 죽지 않는다
        print("[guard] 프레임 실패:", e, flush=True)
        time.sleep(0.5)
        continue

    if args.method == "lab":
        d = lab_feat(cv2.GaussianBlur(img, (5, 5), 0)) - mu
        m2 = np.einsum("hwi,ij,hwj->hw", d, icov, d)
        notfloor = (m2 > args.dist ** 2).astype(np.uint8)
    else:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        floor = cv2.calcBackProject([hsv], [0, 1], hist, [0, 180, 0, 256], 1).astype(np.float32) / 255.0
        floor = cv2.GaussianBlur(floor, (5, 5), 0)
        notfloor = (floor < args.thresh).astype(np.uint8)
    notfloor = cv2.medianBlur(notfloor, 5)
    notfloor = cv2.morphologyEx(notfloor, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    # 3. 열마다 아래에서 위로: '바닥 아님'이 run 픽셀 연속인 첫 지점(가장 아래 y)
    bottoms = np.full(x1 - x0, -1, np.int32)
    col = notfloor[:, x0:x1]
    # 위로 run개 연속 합 — 아래쪽부터 찾기 쉽게 세로 누적합 사용
    cs = np.cumsum(col[::-1, :], axis=0)          # 뒤집어서 아래가 0번
    runs = cs[args.run:, :] - cs[:-args.run, :]   # [k, c] = 아래서 k~k+run 구간의 합
    hit = runs >= args.run
    any_hit = hit.any(axis=0)
    first_k = np.argmax(hit, axis=0)
    bottoms[any_hit] = (H - 1 - first_k[any_hit])
    v = bridge_speed()
    y_stop = stop_line(v)
    near_cols = int(np.sum(bottoms >= y_stop))
    near = near_cols >= args.min_cols * (x1 - x0)

    near_streak = near_streak + 1 if near else 0
    clear_streak = 0 if near else clear_streak + 1
    if not blocked and near_streak >= 3:
        blocked = True
        print(f"[guard] 앞에 물체 — 정지 ({near_cols}열, v={v:.2f}m/s, 정지선 y={y_stop})", send({"block": True}), flush=True)
    elif blocked and clear_streak >= 6:
        blocked = False
        print("[guard] 비었음 — 해제", send({"block": False}), flush=True)

    if args.debug and t - last_dbg > 1.0:
        last_dbg = t
        dbg = img.copy()
        dbg[notfloor > 0] = (0.5 * dbg[notfloor > 0] + [0, 0, 127]).astype(np.uint8)
        cv2.rectangle(dbg, (x0, 0), (x1, H - 1), (255, 255, 0), 1)
        cv2.line(dbg, (0, y_stop), (W - 1, y_stop), (0, 255, 255), 1)
        for i, b in enumerate(bottoms):
            if b >= 0:
                cv2.circle(dbg, (x0 + i, int(b)), 0, (0, 0, 255) if b >= y_stop else (0, 255, 0), -1)
        cv2.putText(dbg, "BLOCK" if blocked else "clear", (5, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 0, 255) if blocked else (0, 255, 0), 1)
        cv2.imwrite("/tmp/guard_debug.jpg", dbg)

    time.sleep(max(0.0, period - (time.monotonic() - t)))
