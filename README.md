# Jetson ROS2 Robot

사람이 말로 준 주행 명령을 **로봇 안의 언어모델**이 제어 명령으로 바꾸고, **ESP32가 모터를 돌리는** 로봇을
부품 선정부터 펌웨어 · 모델 학습 · 엣지 추론 최적화까지 직접 만든 기록입니다.
연산은 Jetson Orin Nano, 실시간 제어는 MCU로 나눴습니다.

> 🚧 2026-10-01 기준 — 제어부 · 모델 · 추론 최적화 완료, 문장 → ESP32 경로 연결 확인. 조립 · 실주행 전

---

## 한눈에

| 영역 | 결과 | 자세히 |
|---|---|---|
| **펌웨어** | BTS7960 단락 방지 순서 강제, 500ms 무명령 시 자동 정지, 20kHz PWM을 계측 장비 없이 검증 (최대 오차 **1.25%p**) | [firmware/](firmware/README.md) |
| **모델 학습** | 자연어 → ROS 2 Twist JSON. 값 정확도 few-shot **2.0% → LoRA 74.7%** (전체 파라미터의 1.75%만 학습) | [finetune/](finetune/README.md) |
| **안전** | "오늘 날씨 어때"에도 움직이던 문제. 거부 학습으로 주행 아닌 문장 60건 중 움직임 **57~100% → 0%**, 학습 어휘 정확도 100% 유지 | [finetune/](finetune/README.md#주행이-아닌-문장-거부-2026-10-01) |
| **평가 설계** | 검증 손실 0.000027이지만 학습 어휘 **100%** vs 미학습 어휘 **49.3%**. 오답 38건 전부 미학습 어휘 | [finetune/](finetune/README.md) |
| **엣지 추론** | **4,115ms → 408ms (10.1배)**, 모델 942 → 374MB, 정확도 −0.7%p. 병목 4개를 측정으로 하나씩 제거 | [BENCHMARK](finetune/BENCHMARK.md) |
| **경로 통합** | 문장 → ESP32 수신까지 실측. 드문드문 오는 요청은 GPU 클럭이 안 올라 **810 → 420ms**(서버 동작 중에만 클럭 고정). 주행 시간이 ROS 기동 시간만큼 짧아지던 버그 수정. 상주 브릿지로 **2.5 → 0.6초**, 달리는 중 정지 0.17초 | [BENCHMARK](finetune/BENCHMARK.md#실제-주행-경로에서-2026-10-01) |
| **장애 진단** | 학습 중 무로그 재부팅. 전원 가설을 측정으로 기각하고, PyTorch 캐시 팽창(5.6GB)이 원인임을 찾아 해결 | [finetune/](finetune/README.md#학습-중-보드-리셋--원인은-메모리였다) |

---

## 전체 흐름

```
 "앞으로 천천히 3초 동안 가"
          │
          ▼   Jetson Orin Nano 8GB
 ┌───────────────────────────────┐
 │ Qwen2.5-0.5B + LoRA           │  → {"linear": 0.15, "angular": 0.0, "duration": 3.0}
 │ llama.cpp Q4_K_M (상주 서버)  │
 └───────────────────────────────┘
          │  ROS 2 /cmd_vel (geometry_msgs/Twist)
          ▼
   micro-ROS Agent ──USB 시리얼──▶ ESP32 ──PWM 20kHz──▶ BTS7960 ×2 ──▶ DC 모터 ×4
```

`firmware/nl2cmdvel.sh` 한 줄로 이 경로 전체가 실행됩니다. 모델과 ROS 노드가 모두 상주해,
문장 입력부터 ESP32가 첫 명령을 받기까지 **0.6초**(처음 연결했을 때 2.2~2.7초)입니다.
"멈춰" 같은 정지어는 모델을 거치지 않고 **0.17초** 만에 진행 중인 명령을 덮어씁니다.

---

## 시스템 구조

```
┌─────────────────────────┐        ┌──────────────────────┐
│  Jetson Orin Nano 8GB   │        │   ESP32 DevKitC      │
│                         │ USB    │                      │
│  · ROS2 Humble          │◄──────►│  · micro-ROS Client  │
│  · 명령 해석 (언어모델)   │ serial │  · PWM 모터 제어      │
│  · micro-ROS Agent      │115200  │  · 무명령 시 자동 정지 │
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
같은 이유로 `torch.compile`에 필요한 Triton을 맞추려 PyTorch를 올리지 않고, C++ 런타임(llama.cpp)으로 우회했습니다.

### 학습 중 메모리 상한
Jetson에는 전용 VRAM이 없어 GPU가 시스템 RAM을 나눠 씁니다. PyTorch 캐싱 할당기를 그대로 두면
학습 중 5.6GB까지 불어나 OS가 멈췄습니다. 학습 스크립트는 기본으로 할당기에 상한(60%)을 겁니다.

### 전력 모드
`nvpmodel -m 2` (MAXN_SUPER)로 설정해 CPU 1.73GHz / GPU 1020MHz를 사용합니다.

### 시리얼 권한
ESP32(CP2102) 인식을 위해 `cp210x` 드라이버 로드를 확인하고, 사용자를 `dialout` 그룹에 추가해 `sudo` 없이 시리얼에 접근하도록 했습니다.

---

## 저장소 구조

```
firmware/    ESP32 펌웨어 — 시리얼 단독 테스트용(motor_ctrl), micro-ROS 노드(motor_uros),
             자연어 → /cmd_vel 스크립트(nl2cmdvel.sh)
finetune/    데이터 생성 · LoRA 학습 · 평가 · 추론 최적화 · 진단 스크립트, 측정 기록
scripts/     Jetson 쪽 USB 확인, micro-ROS Agent, 명령 해석 서버(llama-server), ROS 2 셸
```

## 스크립트

| 스크립트 | 용도 |
|---|---|
| `scripts/check_usb.sh` | ESP32(USB 시리얼) 인식 확인 — 장치 노드, `lsusb`, 커널 로그를 한 번에 |
| `scripts/uros_agent.sh` | micro-ROS Agent 실행 (컨테이너) |
| `scripts/llama_server.sh` | 명령 해석 모델(Q4_K_M) 상주. 떠 있는 동안만 GPU 최저 클럭 고정, 종료 시 원복 |
| `scripts/cmd_bridge.sh` | `/cmd_vel` 브릿지 상주. 명령을 로컬 TCP로 받아 10 Hz 발행, 새 명령이 진행 중 명령을 덮어씀 |
| `scripts/ros2sh.sh` | ROS2 셸 진입 — 토픽 확인용 |

### 통신 검증 순서

```bash
./scripts/check_usb.sh          # /dev/ttyUSB0 인식 확인
./scripts/uros_agent.sh         # 터미널 A — Agent 대기
./scripts/ros2sh.sh             # 터미널 B
  └─ ros2 topic list            # ESP32가 만든 토픽이 보이면 성공
```

> micro-ROS Agent 옵션은 `--dev`가 아니라 **`-D`** 입니다. 문서마다 다르게 적혀 있어 실행이 안 되는 원인이 됩니다.

> ESP32는 **부팅할 때 한 번만** Agent에 접속합니다. Agent를 먼저 띄운 뒤 ESP32의 EN(리셋) 버튼을 누르세요.

### 자연어 주행

```bash
./scripts/uros_agent.sh                           # 터미널 A — Agent (띄운 뒤 ESP32 리셋)
./scripts/llama_server.sh                         # 터미널 B — 명령 해석 서버
./scripts/cmd_bridge.sh                           # 터미널 C — /cmd_vel 브릿지
./firmware/nl2cmdvel.sh "앞으로 천천히 2초 동안 가"   # 터미널 D
./firmware/nl2cmdvel.sh "멈춰"                     # 달리는 중에도 바로 정지
```

---

## 환경

| | |
|---|---|
| L4T | R36.4.3 (JetPack 6.2) |
| 커널 | 5.15.148-tegra |
| CUDA | 12.6 |
| PyTorch | 2.4.0 (NVIDIA Jetson 빌드, 컨테이너) |
| llama.cpp | CUDA 빌드, `sm_87` |
| ROS2 | Humble |
| micro-ROS Agent | `microros/micro-ros-agent:humble` |
| ROS2 이미지 | `dustynv/ros:humble-ros-base-l4t-r36.3.0` |

---

## 진행 상황

- [x] Jetson 개발 환경 구축 (JetPack 6.2, NVMe 이전, 패키지 고정)
- [x] micro-ROS Agent 컨테이너 구동, 시리얼 드라이버·권한 설정
- [x] 하드웨어 사양 선정
- [x] ESP32 펌웨어 — PWM 모터 제어, 드라이버 단락 방지, 통신 단절 시 정지, PWM 자가검증
- [x] micro-ROS `/cmd_vel` 구독 · 차동 구동 변환
- [x] 자연어 → 제어 명령 모델 학습 · 평가 (LoRA), 데이터 양 스윕
- [x] 엣지 추론 최적화 (llama.cpp Q4, 10.1배)
- [x] 학습 중 보드 리셋 원인 규명 · 해결 (메모리)
- [ ] 구동부 조립 · 실주행 (부품 입고 완료)
- [ ] 엔코더 인터럽트 카운트 → 오도메트리 발행
- [x] llama.cpp 추론을 `/cmd_vel` 경로에 연결, 문장 → ESP32 수신 실측
- [x] 주행이 아닌 문장 거부 학습 (배포 모델 교체), 정지어는 규칙으로 먼저 처리
- [x] 상주 `/cmd_vel` 브릿지 — 문장 → ESP32 0.6초, 달리는 중 정지
- [ ] 카메라 · IMU 연동
- [ ] SLAM / 경로계획
