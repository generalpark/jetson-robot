/*
 * 모터 제어 펌웨어 - BTS7960(IBT-2) 2채널 구동용
 *
 * BTS7960은 정/역을 PWM 두 핀으로 나눠 받는다(RPWM/LPWM).
 * 한쪽에 듀티를 주는 동안 반대쪽은 반드시 0이어야 한다.
 * 둘 다 0이 아니면 하이사이드와 로우사이드가 동시에 열려
 * 드라이버가 단락된다(shoot-through).
 *
 * 드라이버가 아직 없어 출력은 온보드 LED로 확인한다.
 * 핀 번호와 신호 규격은 실제 배선과 같게 두었으므로,
 * 드라이버가 오면 배선만 연결하면 된다.
 *
 * 시리얼 명령(115200)
 *   L <-255..255>   왼쪽 속도
 *   R <-255..255>   오른쪽 속도
 *   S               즉시 정지
 *   ?               상태 출력
 */
#include <Arduino.h>

// --- 핀 배치 (BTS7960 2개) ---
constexpr int L_RPWM = 25;   // 왼쪽 정방향
constexpr int L_LPWM = 26;   // 왼쪽 역방향
constexpr int R_RPWM = 32;   // 오른쪽 정방향
constexpr int R_LPWM = 33;   // 오른쪽 역방향
constexpr int LED    = 2;    // 온보드 LED (드라이버 대용 확인)
// PWM이 실제로 나가는지 확인하기 위한 입력 핀.
// GPIO25(L_RPWM)와 점퍼선으로 연결하면 보드가 자기 출력을 자기가 읽는다.
// 오실로스코프나 로직 애널라이저 없이 듀티를 검증하기 위한 것이다.
constexpr int VERIFY_IN = 34;   // 입력 전용 핀

// --- LEDC(ESP32 하드웨어 PWM) 채널 ---
constexpr int CH_L_R = 0, CH_L_L = 1, CH_R_R = 2, CH_R_L = 3, CH_LED = 4;
constexpr int PWM_FREQ = 20000;   // 20kHz - 가청대역 위. 모터 소음을 줄인다
constexpr int PWM_BITS = 8;       // 0~255

// --- 안전장치 ---
constexpr uint32_t CMD_TIMEOUT_MS = 500;   // 이 시간 명령이 없으면 정지
uint32_t last_cmd_ms = 0;
int speed_l = 0, speed_r = 0;
bool stopped_by_timeout = false;

void applyMotor(int ch_fwd, int ch_rev, int speed) {
  speed = constrain(speed, -255, 255);
  // 한쪽을 먼저 0으로 내린 뒤 반대쪽을 올린다. 순서가 바뀌면 순간적으로 양쪽이 살아난다
  if (speed >= 0) {
    ledcWrite(ch_rev, 0);
    ledcWrite(ch_fwd, speed);
  } else {
    ledcWrite(ch_fwd, 0);
    ledcWrite(ch_rev, -speed);
  }
}

void applyAll() {
  applyMotor(CH_L_R, CH_L_L, speed_l);
  applyMotor(CH_R_R, CH_R_L, speed_r);
  // 드라이버가 없으므로 두 바퀴 중 큰 쪽 세기를 LED 밝기로 보여준다
  ledcWrite(CH_LED, max(abs(speed_l), abs(speed_r)));
}

void stopAll(const char* why) {
  speed_l = speed_r = 0;
  applyAll();
  Serial.printf("STOP (%s)\n", why);
}

void verifyPwm() {
  // PWM 한 주기(20kHz = 50us)보다 훨씬 오래 표본을 모아
  // HIGH로 읽힌 비율을 센다. 샘플링이 PWM과 동기화돼 있지 않으므로
  // 표본이 충분하면 그 비율이 듀티에 수렴한다.
  Serial.println("duty,measured,expected,error");
  const int duties[] = {0, 32, 64, 96, 128, 160, 192, 224, 255};
  for (int d : duties) {
    ledcWrite(CH_L_L, 0);
    ledcWrite(CH_L_R, d);
    delay(80);                       // 출력이 안정될 때까지 기다린다
    const uint32_t N = 20000;
    uint32_t high = 0;
    for (uint32_t i = 0; i < N; i++) {
      if (digitalRead(VERIFY_IN)) high++;
    }
    float measured = (float)high / N;
    float expected = (float)d / 255.0f;
    Serial.printf("%d,%.4f,%.4f,%+.4f", d, measured, expected, measured - expected);
    Serial.println();
  }
  ledcWrite(CH_L_R, 0);
  Serial.println("verify_done");
}

void setup() {
  Serial.begin(115200);
  delay(200);
  pinMode(VERIFY_IN, INPUT);

  ledcSetup(CH_L_R, PWM_FREQ, PWM_BITS); ledcAttachPin(L_RPWM, CH_L_R);
  ledcSetup(CH_L_L, PWM_FREQ, PWM_BITS); ledcAttachPin(L_LPWM, CH_L_L);
  ledcSetup(CH_R_R, PWM_FREQ, PWM_BITS); ledcAttachPin(R_RPWM, CH_R_R);
  ledcSetup(CH_R_L, PWM_FREQ, PWM_BITS); ledcAttachPin(R_LPWM, CH_R_L);
  ledcSetup(CH_LED, 1000, PWM_BITS);     ledcAttachPin(LED, CH_LED);

  stopAll("boot");
  last_cmd_ms = millis();
  Serial.println("ready: L/R <-255..255>, S=stop, ?=status, V=verify PWM");
}

void handleLine(String line) {
  line.trim();
  if (!line.length()) return;
  char c = toupper(line[0]);

  if (c == 'S') { stopAll("command"); last_cmd_ms = millis(); return; }
  if (c == 'V') { verifyPwm(); last_cmd_ms = millis(); return; }
  if (c == '?') {
    Serial.printf("L=%d R=%d  timeout=%s  since_cmd=%lums\n",
                  speed_l, speed_r, stopped_by_timeout ? "Y" : "N",
                  millis() - last_cmd_ms);
    return;
  }
  if (c == 'L' || c == 'R') {
    int v = line.substring(1).toInt();
    if (c == 'L') speed_l = constrain(v, -255, 255);
    else          speed_r = constrain(v, -255, 255);
    applyAll();
    last_cmd_ms = millis();
    stopped_by_timeout = false;
    Serial.printf("OK L=%d R=%d\n", speed_l, speed_r);
    return;
  }
  Serial.println("ERR unknown command");
}

void loop() {
  while (Serial.available()) {
    static String buf;
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') { handleLine(buf); buf = ""; }
    else if (buf.length() < 32)   { buf += ch; }
  }

  // 명령이 끊기면 스스로 멈춘다.
  // 상위 제어기가 죽거나 USB가 빠져도 마지막 속도로 계속 달리지 않게 하기 위함이다.
  if (!stopped_by_timeout && (speed_l || speed_r) &&
      millis() - last_cmd_ms > CMD_TIMEOUT_MS) {
    stopped_by_timeout = true;
    stopAll("timeout");
  }
}
