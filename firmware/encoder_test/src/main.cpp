// 엔코더 시험: 좌우 앞 모터 엔코더(JGA25-370 홀, 11PPR x 감속 35)
//   오른쪽 앞: 노랑 A -> 34, 초록 B -> 35, 파랑 전원 -> GPIO4 HIGH, 검정 GND -> GPIO15 LOW
//   왼쪽 앞:   노랑 A -> 36(보드 표기 UP), 초록 B -> 39(보드 표기 NU), 파랑 -> GPIO13 HIGH, 검정 -> GPIO14 LOW
//   34·35·36·39는 입력 전용 핀(내부 풀업 없음) — 엔코더 기판 출력이 3.3V에서 바로 읽혀서 문제없었다(11/5)
//   GND 핀이 모자라 GPIO를 전원·GND로 쓴다. 홀 센서는 수 mA라 GPIO로 충분하다.
// ESP32 하드웨어 펄스 카운터(PCNT)로 A·B 양쪽 에지를 모두 세는 4체배: 바퀴 한 바퀴 = 11 x 35 x 4 = 1540
#include <Arduino.h>
#include "driver/pcnt.h"

struct Enc { pcnt_unit_t unit; int a, b, vcc, gnd; const char* name; int64_t total; };
Enc enc[] = {
  {PCNT_UNIT_0, 34, 35, 4, 15, "R", 0},
  {PCNT_UNIT_1, 36, 39, 13, 14, "L", 0},
};
constexpr int DRIVER_EN[] = {27, 18, 16, 17};   // 시험 중 모터 드라이버는 꺼 둔다
constexpr float COUNTS_PER_REV = 11.0f * 35.0f * 4.0f;

void setupEnc(Enc& e) {
  pinMode(e.gnd, OUTPUT); digitalWrite(e.gnd, LOW);
  pinMode(e.vcc, OUTPUT); digitalWrite(e.vcc, HIGH);
  pinMode(e.a, INPUT); pinMode(e.b, INPUT);

  pcnt_config_t c = {};
  c.unit = e.unit; c.counter_h_lim = 32767; c.counter_l_lim = -32768;
  c.channel = PCNT_CHANNEL_0; c.pulse_gpio_num = e.a; c.ctrl_gpio_num = e.b;
  c.pos_mode = PCNT_COUNT_DEC; c.neg_mode = PCNT_COUNT_INC;
  c.lctrl_mode = PCNT_MODE_REVERSE; c.hctrl_mode = PCNT_MODE_KEEP;
  pcnt_unit_config(&c);
  c.channel = PCNT_CHANNEL_1; c.pulse_gpio_num = e.b; c.ctrl_gpio_num = e.a;
  c.pos_mode = PCNT_COUNT_INC; c.neg_mode = PCNT_COUNT_DEC;
  pcnt_unit_config(&c);
  pcnt_set_filter_value(e.unit, 100);   // 80MHz 기준 1.25us 미만 잡음 무시
  pcnt_filter_enable(e.unit);
  pcnt_counter_pause(e.unit);
  pcnt_counter_clear(e.unit);
  pcnt_counter_resume(e.unit);
}

void setup() {
  for (int p : DRIVER_EN) { pinMode(p, OUTPUT); digitalWrite(p, LOW); }
  for (auto& e : enc) setupEnc(e);
  delay(50);
  Serial.begin(115200);
  delay(200);
  Serial.println("ENC_TEST start");
}

void loop() {
  for (auto& e : enc) {
    int16_t v = 0;
    pcnt_get_counter_value(e.unit, &v);
    pcnt_counter_clear(e.unit);           // 16비트라 100ms마다 비우고 64비트에 누적
    e.total += v;
    Serial.printf("%s total=%lld rev=%.3f A=%d B=%d  ", e.name, (long long)e.total,
                  e.total / COUNTS_PER_REV, digitalRead(e.a), digitalRead(e.b));
  }
  Serial.println();
  delay(100);
}
