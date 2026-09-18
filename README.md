# Jetson ROS2 Robot

Jetson Orin Nano와 ESP32를 결합한 자율주행 로봇 제작 기록.
**연산은 Jetson, 실시간 제어는 MCU**로 분리하는 구조를 직접 구성하고 검증하는 과정을 담았습니다.

> 🚧 진행 중 — 개발 환경 구축과 통신 계층 검증 완료, 구동부 부품 입고 대기 (2026-09 기준)

---

## 시스템 구조

```
┌─────────────────────────┐        ┌──────────────────────┐
│  Jetson Orin Nano 8GB   │        │   ESP32 DevKitC      │
│                         │ USB    │                      │
│  · ROS2 Humble          │◄──────►│  · micro-ROS Client  │
│  · 인지 / 경로계획       │ serial │  · PWM 모터 제어      │
│  · micro-ROS Agent      │115200  │  · 엔코더 인터럽트     │
└─────────────────────────┘        └──────────────────────┘
         │                                    │
    카메라 / IMU                        모터 드라이버 ×2
                                              │
                                        DC 모터 ×4 (엔코더)
```

**왜 분리했는가** — 모터 PWM 제어와 엔코더 펄스 카운트는 수 μs 단위의 응답이 필요한데, 리눅스 유저스페이스는 이를 보장하지 못합니다. 실시간성이 필요한 루프는 MCU에 두고, Jetson은 인지·판단만 담당하도록 역할을 나눴습니다. 두 계층은 micro-ROS로 이어져 ROS2 토픽으로 통신합니다.

---

## 하드웨어 구성과 선정 근거

| 부품 | 선정 | 근거 |
|---|---|---|
| **연산** | Jetson Orin Nano 8GB | 온디바이스 추론을 위한 GPU 필요 |
| **MCU** | ESP32 DevKitC (WROOM-32D, CP2102) | micro-ROS 지원 확인. **WROOM-32U는 외부안테나형, ESP32-P4는 micro-ROS 미지원**이라 제외 |
| **모터** | JGA25-370 12V 170RPM, 엔코더 내장 ×4 | 홀 엔코더 11PPR × 감속비 35 = **바퀴 1회전당 385펄스**. 오도메트리 분해능 확보 |
| **드라이버** | BTS7960 (IBT-2) ×2 | 좌/우 각 2모터 병렬 구동 |
| **카메라** | IMX219 120° **22핀** | Orin Nano는 22핀 CSI. 15핀 모듈은 변환 케이블이 추가로 필요 |
| **IMU** | MPU6050 | 자세 추정 |

### 전원 설계

모터와 연산 장치의 전원을 **물리적으로 분리**했습니다.

- **모터계** — 12V 18650 3S2P (BMS 내장)
- **연산계** — USB-PD 파워뱅크 + PD 트리거 케이블

분리한 이유는 두 가지입니다. 첫째, 모터 기동 시 순간 전류가 크게 흘러 연산 장치의 전압이 흔들립니다. 둘째, **대부분의 파워뱅크는 2포트를 동시에 쓰면 출력이 5V로 강등**되는데, Jetson은 9~20V 입력을 요구하므로 한 배터리에서 둘 다 뽑으면 부팅 자체가 불안정해집니다.

---

## 셋업 과정에서 해결한 것

### Docker 데이터 경로를 NVMe로 이전
jetson-containers 이미지는 개당 10~15GB입니다. 64GB microSD로는 두 개도 못 올립니다.
NVMe SSD를 `/mnt/nvme`로 마운트하고 Docker `data-root`를 그쪽으로 옮겼습니다. `default-runtime`을 `nvidia`로 지정해 컨테이너에서 GPU를 바로 쓸 수 있게 했습니다.

### L4T 패키지 버전 고정
`apt upgrade`가 `nvidia-l4t-*` 패키지를 건드리면 CUDA 환경이 깨지고 부팅이 안 되는 사례가 보고돼 있습니다.
관련 패키지 55개를 `apt-mark hold`로 잠갔습니다. 일반 패키지 설치는 그대로 가능합니다.

### 전력 모드
`nvpmodel -m 2` (MAXN_SUPER)로 설정해 CPU 1.73GHz / GPU 1020MHz를 사용합니다.

### 시리얼 권한
ESP32(CP2102) 인식을 위해 `cp210x` 드라이버 로드를 확인하고, 사용자를 `dialout` 그룹에 추가해 `sudo` 없이 시리얼에 접근하도록 했습니다.

---

## 스크립트

| 스크립트 | 용도 |
|---|---|
| `scripts/check_usb.sh` | ESP32(USB 시리얼) 인식 확인 — 장치 노드, `lsusb`, 커널 로그를 한 번에 |
| `scripts/uros_agent.sh` | micro-ROS Agent 실행 (컨테이너) |
| `scripts/ros2sh.sh` | ROS2 셸 진입 — 토픽 확인용 |

### 통신 검증 순서

```bash
./scripts/check_usb.sh          # /dev/ttyUSB0 인식 확인
./scripts/uros_agent.sh         # 터미널 A — Agent 대기
./scripts/ros2sh.sh             # 터미널 B
  └─ ros2 topic list            # ESP32가 만든 토픽이 보이면 성공
```

> micro-ROS Agent 옵션은 `--dev`가 아니라 **`-D`** 입니다. 문서마다 다르게 적혀 있어 실행이 안 되는 원인이 됩니다.

---

## 환경

| | |
|---|---|
| L4T | R36.4.3 (JetPack 6.2) |
| 커널 | 5.15.148-tegra |
| CUDA | 12.6 |
| ROS2 | Humble |
| micro-ROS Agent | `microros/micro-ros-agent:humble` |
| ROS2 이미지 | `dustynv/ros:humble-ros-base-l4t-r36.3.0` |

---

## 진행 상황

- [x] Jetson 개발 환경 구축 (JetPack 6.2, NVMe 이전, 패키지 고정)
- [x] micro-ROS Agent 컨테이너 구동 확인
- [x] 시리얼 드라이버·권한 설정
- [x] 하드웨어 사양 선정
- [ ] ESP32 펌웨어 — PWM 모터 제어, 엔코더 인터럽트 카운트
- [ ] 오도메트리 발행
- [ ] 카메라·IMU 연동
- [ ] SLAM / 경로계획
