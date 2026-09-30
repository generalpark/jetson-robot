# 추론 최적화 측정 (Jetson Orin Nano 8GB)

대상: 자연어 주행명령 → ROS 2 Twist JSON 변환 모델 (Qwen2.5-0.5B + LoRA)
측정일: 2026-09-25 / CUDA 12.6.68, JetPack 6.2, MAXN_SUPER
조건: 배치 1 (실시간 제어 시나리오라 배칭 불가), 30샘플, 워밍업 후 측정

## 배경 — 왜 배치 1인가

주행 명령은 한 번에 하나씩 들어온다. 처리량보다 **요청당 지연**이 중요하고
배칭으로 숨길 수 없다. 그래서 throughput 벤치마크가 아니라 latency를 잰다.

## 결과

| 구성 | TTFT | E2E | tok/s | VRAM | 최대전류 |
|---|---|---|---|---|---|
| FP16 (LoRA 분리) | 165.8 ms | 4114.6 ms | 6.3 | 994 MB | 1688 mA |
| **+ LoRA 병합** | **87.0 ms** | **2094.1 ms** | **12.3** | 957 MB | 1768 mA |
| + GPU 클럭 고정 | 79.2 ms | 1918.4 ms | 13.4 | 957 MB | 2192 mA |

참고: 전류는 모듈 5V 쪽(`VDD_IN`, 약 4.95V)을 잰 값이다. 1688 mA ≈ 8.4 W.

## 관찰 1 — LoRA 병합은 사실상 공짜로 2배

```
속도 +96%   전력 +80 mA(+5%)   VRAM -37 MB
```

PEFT 어댑터는 매 forward마다 별도 matmul을 추가한다. 0.5B처럼 작은 모델에서는
base 연산 대비 이 오버헤드 비중이 커서, 가중치에 병합하는 것만으로 2배가 나왔다.

## 관찰 2 — 클럭 고정은 손해

```
GPU 306 MHz → 1020 MHz (3.3배)   →   처리량 +9%,  전력 +424 mA(+24%)
```

전력당 처리량으로 보면 오히려 나빠진다.

```
병합만      12.3 tok/s / 1768 mA = 0.0070   ← 최적
클럭 고정   13.4 tok/s / 2192 mA = 0.0061
```

424 mA(약 2 W)를 9% 성능에 쓰는 것은 맞는 거래가 아니다. 클럭은 원복했다.

## 관찰 3 — 병목은 GPU 연산이 아니다

클럭을 3.3배 올렸는데 9%만 개선됐다는 것은 **연산이 병목이 아니라는 증거**다.
0.5B는 GPU 입장에서 너무 작아, 토큰마다 발생하는 **커널 런치 오버헤드**가
지배적인 것으로 판단했다. 다음 실험은 이 가설을 직접 겨냥한다.

→ `torch.compile(mode="reduce-overhead")` + static KV cache = CUDA Graphs 캡처

## 관찰 4 — torch.compile은 환경 제약으로 실패했다

가설 자체는 유효했지만 이 보드에서는 실행할 수 없었다. 두 단계로 막혔다.

**1차 (`fullgraph=True`)** — dynamo가 추적 불가로 예외:

```
torch._dynamo.exc.Unsupported:
  ALL_ATTENTION_FUNCTIONS[self.config._attn_implementation]
```

transformers가 attention 구현을 런타임 딕셔너리 조회로 고르는데, dynamo가
이를 따라가지 못한다. graph break를 허용하지 않아 그대로 중단됐다.

**2차 (`fullgraph=False`)** — 진짜 원인이 드러남:

```
RuntimeError: Cannot find a working triton installation.
```

inductor 백엔드는 Triton으로 GPU 커널을 생성한다. Triton이 없으니 컴파일이
전혀 일어나지 않았고, `suppress_errors=True` 탓에 조용히 eager로 폴백했다.

| | TTFT | E2E | tok/s |
|---|---|---|---|
| 병합만 | 87.0 ms | 2094.1 ms | 12.3 |
| + compile(폴백) | 91.5 ms | 2257.9 ms | **11.4** |

**7% 느려졌다.** 컴파일 이득은 0인데 static cache와 고정 길이 패딩의
오버헤드만 남았기 때문이다. 최적화를 켰다고 빨라지는 게 아니라는 확인이다.

설치도 불가능했다.

```
torch           2.4.0 (NVIDIA Jetson 빌드, aarch64)
요구 triton     3.0.0
pypi 제공       3.5.0 이상만
```

torch를 올리려면 JetPack L4T 패키지를 건드려야 하는데, CUDA 파손 위험이
있어 55개 패키지를 `apt-mark hold` 해둔 상태다. 이 경로는 닫았다.

> 부수 확인: 컨테이너의 pip이 커스텀 인덱스(`jetson.webredirect.org`)를
> 가리키고 있어 `Name or service not known`으로 실패한다. DNS 문제로
> 보이지만 아니다. `PIP_INDEX_URL=https://pypi.org/simple`로 우회된다.

## 관찰 5 — llama.cpp로 병목을 확인 사살

Triton이 막혔을 뿐 진단은 유효했으므로, C++ 런타임으로 같은 병목을 쳤다.
llama.cpp를 CUDA(sm_87)로 빌드하고 병합 모델을 GGUF로 변환했다.

### 생성 속도 (llama-bench, tg32, 전 레이어 GPU)

| 런타임 | 생성 tok/s | 프롬프트 tok/s | 크기 |
|---|---|---|---|
| transformers FP16 | 6.3 | - | 994 MB |
| transformers + 병합 | 12.3 | - | 957 MB |
| llama.cpp F16 | **38.87** | 2747 | 942 MB |
| llama.cpp Q8_0 | **108.20** | 3618 | 501 MB |
| llama.cpp Q4_K_M | 104.93 | 3597 | 374 MB |

**같은 F16 가중치, 같은 GPU에서 12.3 → 38.87 (3.2배).** 연산도 정밀도도
동일하고 달라진 것은 런타임뿐이다. 이 3.2배가 Python 인터프리터와 커널 런치
오버헤드였다는 직접 증거이고, 관찰 3의 가설을 확정한다.

양자화 구간은 성격이 다르다. F16 942 MB → Q8_0 501 MB로 절반이 되자 속도가
2.8배가 됐다. **메모리 대역폭이 병목**이라는 뜻이다. 다만 Q4_K_M은 374 MB로
더 작은데도 오히려 느리다(104.93). 역양자화 연산 비용이 대역폭 이득을
넘어선 것으로, **줄일수록 빨라지는 구간이 아니다.**

### 정확도 (테스트셋 150개 전체, evaluate.py의 score() 그대로 재사용)

| | parse | schema | sign | exact | 요청 지연 |
|---|---|---|---|---|---|
| transformers (기준) | 100 | 100 | 86.0 | **74.7%** | 2094 ms |
| llama.cpp F16 | 100 | 100 | 86.7 | **74.7%** | 787 ms |
| llama.cpp Q8_0 | 100 | 100 | 85.3 | 74.0% | **405 ms** |
| llama.cpp Q4_K_M | 100 | 100 | 86.0 | 74.0% | 408 ms |

채점기를 새로 만들지 않고 기존 `score()`를 그대로 import했다. 다른 채점기를
쓰면 비교 자체가 무의미해지기 때문이다.

**F16 GGUF의 값 정확도가 74.7%로 기준과 소수점까지 일치한다**(부호는 86.0 → 86.7로 한 건 차이). 변환이 모델을 훼손하지
않았다는 확인이고, 이것이 맞아야 아래 양자화 비교가 의미를 가진다.

**양자화 손실은 0.7%p에 그쳤고, Q4_K_M(4비트)이 Q8_0(8비트)과 동일한
74.0%다.** 절반으로 더 줄였는데 정확도가 떨어지지 않았다. 출력이 짧은
구조화된 JSON이라 양자화 노이즈에 둔감한 것으로 보인다.

### 선택: Q4_K_M

| | Q8_0 | Q4_K_M |
|---|---|---|
| 정확도 | 74.0% | 74.0% (동일) |
| 지연 | 405 ms | 408 ms (+0.7%) |
| 크기 | 501 MB | **374 MB** |

지연 차이가 1% 미만이고 정확도가 같으므로 크기가 작은 쪽을 택한다.
로봇에는 카메라·SLAM이 함께 올라가므로 메모리 여유가 성능보다 값지다.

## 최종

```
transformers FP16     4114 ms   994 MB   74.7%
llama.cpp Q4_K_M       408 ms   374 MB   74.0%
                    ─────────────────────────────
                      10.1배     62% 감소   -0.7%p
```

명령 하나를 4.1초에 변환하던 것이 0.41초가 됐다. 정확도는 0.7%p를 내줬다.

## 전력에 대한 정정 (2026-09-30 최종)

초기에는 "학습 중 2616 mA에서 전원 차단"으로 적고, 이후 "지속 부하" 가설로 고쳤다. **둘 다 틀렸다.**

- 전류 센서(ina3221 ch1 `VDD_IN`)는 19V 입력이 아니라 **모듈 5V 쪽(약 4.95V)**이다. 2616 mA ≈ 13 W,
  3784 mA ≈ 19 W. 번들 어댑터(19V 2.37A, 45W)에 한참 못 미친다
- 학습 중 리셋의 실제 원인은 **메모리 고갈**이었다. PyTorch 캐싱 할당기가 5.6 GB까지 불어나 시스템 RAM이
  170 MB로 떨어졌다. 할당기 상한(60%)으로 해결했다. 상세는 [README](README.md)의 "학습 중 보드 리셋"

## 남은 것

- ~~데이터 양 스윕 200/400~~ 완료(README 참고)
- micro-ROS 노드에서 GGUF 추론 호출해 실제 제어 루프 지연 측정

## 재현

```bash
# 기준선
python3 benchmark.py --adapter adapter --n 30 --label fp16
# 병합
python3 benchmark.py --adapter adapter --merge --n 30 --label fp16_merged
# 컴파일
python3 benchmark.py --adapter adapter --merge --compile --n 30
```

전력은 `monitor.sh`가 1초 간격으로 append+sync 기록한다. 보드가 갑자기
꺼져도 직전 수치가 디스크에 남도록 한 것이다.
