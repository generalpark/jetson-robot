/*
 * 로봇 주행 제어기 - micro-ROS 노드
 *
 * ROS 2의 /cmd_vel(geometry_msgs/Twist)을 구독해 좌우 바퀴 PWM으로 바꾼다.
 * Jetson에서 micro-ROS Agent를 띄우면 이 보드가 ROS 2 노드로 참여한다.
 *
 *   [상위]  /cmd_vel  ->  micro-ROS Agent  --USB시리얼-->  ESP32  ->  BTS7960
 *   [하위]  /wheel_ticks <- 좌우 앞바퀴 엔코더 누적 카운트(Int32MultiArray [왼쪽, 오른쪽], 20 Hz)
 *
 * 안전장치는 시리얼 버전과 같다. 명령이 끊기면 스스로 멈춘다.
 * 상위가 죽었을 때 마지막 속도로 계속 달리는 것이 가장 위험하기 때문이다.
 */
#include <Arduino.h>
#include <micro_ros_platformio.h>
#include <rcl/rcl.h>
#include <rclc/rclc.h>
#include <rclc/executor.h>
#include <geometry_msgs/msg/twist.h>
#include <std_msgs/msg/int32_multi_array.h>
#include "driver/pcnt.h"

// --- 핀 배치 (시리얼 버전과 동일) ---
constexpr int L_RPWM = 25, L_LPWM = 26;
constexpr int R_RPWM = 32, R_LPWM = 33;
constexpr int LED    = 2;
// EN 핀은 펌웨어가 켠다. 점퍼선이 암-암뿐이라 3V3 한 핀을 VCC·R_EN·L_EN 여러 곳으로
// 나눌 수 없어서 EN을 GPIO에 하나씩 물렸다. 덕분에 부팅 중(초기화 전)에는 드라이버가 꺼져 있다.
constexpr int L_R_EN = 27, L_L_EN = 18;
constexpr int R_R_EN = 16, R_L_EN = 17;
// 오른쪽 드라이버의 로직 전원(VCC). 3V3 핀은 왼쪽 드라이버가 쓴다.
// 로직부(74HC244 + BTS7960 입력)는 수 mA 이하라 GPIO로 공급한다. 브레드보드가 생기면 3V3로 옮길 것
constexpr int R_VCC = 23;
constexpr int CH_L_R = 0, CH_L_L = 1, CH_R_R = 2, CH_R_L = 3, CH_LED = 4;
constexpr int PWM_FREQ = 20000, PWM_BITS = 8;

// --- 로봇 치수 ---
// JGA25-370 12V 170RPM + 65mm 바퀴 기준 이론 최고속도:
//   170 / 60 * pi * 0.065 = 0.578 m/s
// 무부하 회전수라 실제로는 더 낮다. 박스 섀시 바닥 실측: 0.2 m/s x 1.5 s 명령에 27 cm(90%)
constexpr float MAX_SPEED   = 0.50f;   // m/s
constexpr float WHEEL_BASE  = 0.24f;   // m, 좌우 바퀴 중심 간격(박스 섀시 실측)
// 4륜 스키드 조향은 제자리 회전에서 바퀴가 옆으로 미끄러져 덜 돈다.
// 실측(박스 섀시 10/7): 90도 명령에 45도(좌·우·좌 3회 같음). 속도 오차(90%)를 빼면 회전 효율 약 0.56
// 재보정(아크릴 2층 섀시 + Jetson + 보조배터리, 11/3): 0.56으로 90도 명령에 64.4도·67.5도(평균 65.9도)
// -> 비례로 0.41을 넣었더니 112.2도로 넘침(빨리 돌수록 덜 미끄러져 비례가 안 맞음)
// -> 두 점(1/0.56 -> 65.9도, 1/0.41 -> 112.2도)을 직선으로 이어 90도가 되는 0.47
constexpr float TURN_EFF    = 0.47f;
constexpr float TRACK_EFF   = WHEEL_BASE / TURN_EFF;   // 약 0.51 m, 바퀴 속도 계산에 쓰는 유효 간격
// 좌우 모터가 거울상으로 달려서 배선이 같으면 오른쪽이 거꾸로 돈다(섀시 장착 후 확인)
constexpr bool  INVERT_R    = true;

// --- 엔코더 (JGA25-370 홀, 11PPR x 감속 35, 4체배 -> 바퀴 한 바퀴 1540) ---
// 앞바퀴 좌우 하나씩. A·B는 입력 전용 핀, 엔코더 전원·GND는 GND 핀이 모자라 GPIO로 준다(수 mA).
// 손으로 앞으로 한 바퀴 돌린 실측(11/5): 오른쪽 +1552, 왼쪽 -1512 -> 왼쪽은 부호를 뒤집어 둘 다 앞으로 +.
struct Enc { pcnt_unit_t unit; int a, b, vcc, gnd; int sign; int32_t total; };
Enc enc_l = {PCNT_UNIT_1, 36, 39, 13, 14, -1, 0};   // 보드 표기 UP / NU
Enc enc_r = {PCNT_UNIT_0, 34, 35,  4, 15, +1, 0};
constexpr uint32_t TICKS_PERIOD_MS = 50;           // 20 Hz
// 거리 환산용(상위에서 씀): 카탈로그 65 mm로 계산하면 실제보다 4.5% 짧게 나왔다.
// 0.2 m/s x 1.5 s 주행(11/5): 줄자 왼쪽 30.0 / 오른쪽 29.7 cm, 엔코더(65 mm 기준) 28.7 / 28.4 cm
// -> 좌우 모두 1.045배 -> 유효 지름 67.9 mm (자로 잰 타이어 지름 약 67 mm와 맞음)
constexpr float WHEEL_DIAMETER = 0.0679f;          // m
constexpr float COUNTS_PER_REV = 11.0f * 35.0f * 4.0f;   // 1540, 손으로 한 바퀴 실측 1512~1552

constexpr uint32_t CMD_TIMEOUT_MS = 500;
volatile uint32_t last_cmd_ms = 0;
volatile bool stopped = true;

rcl_subscription_t sub_cmd_vel;
geometry_msgs__msg__Twist msg_in;
rcl_publisher_t pub_ticks;
std_msgs__msg__Int32MultiArray msg_ticks;
int32_t ticks_buf[2];
uint32_t last_ticks_ms = 0;
rclc_executor_t executor;
rclc_support_t support;
rcl_allocator_t allocator;
rcl_node_t node;

void applyMotor(int ch_fwd, int ch_rev, int duty) {
  duty = constrain(duty, -255, 255);
  if (duty >= 0) { ledcWrite(ch_rev, 0); ledcWrite(ch_fwd, duty); }
  else           { ledcWrite(ch_fwd, 0); ledcWrite(ch_rev, -duty); }
}

void driveStop() {
  applyMotor(CH_L_R, CH_L_L, 0);
  applyMotor(CH_R_R, CH_R_L, 0);
  ledcWrite(CH_LED, 0);
  stopped = true;
}

// Twist(선속도·각속도) -> 좌우 바퀴 속도. 차동 구동 변환.
void cmdVelCallback(const void *msgin) {
  const auto *m = (const geometry_msgs__msg__Twist *)msgin;
  float v = m->linear.x;      // m/s
  float w = m->angular.z;     // rad/s

  float v_l = v - w * TRACK_EFF / 2.0f;
  float v_r = v + w * TRACK_EFF / 2.0f;

  int duty_l = (int)(v_l / MAX_SPEED * 255.0f);
  int duty_r = (int)(v_r / MAX_SPEED * 255.0f);
  if (INVERT_R) duty_r = -duty_r;

  applyMotor(CH_L_R, CH_L_L, duty_l);
  applyMotor(CH_R_R, CH_R_L, duty_r);
  ledcWrite(CH_LED, min(255, max(abs(duty_l), abs(duty_r))));

  last_cmd_ms = millis();
  stopped = false;
}

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
  pcnt_set_filter_value(e.unit, 100);   // 80 MHz 기준 1.25 us 미만 잡음 무시
  pcnt_filter_enable(e.unit);
  pcnt_counter_pause(e.unit);
  pcnt_counter_clear(e.unit);
  pcnt_counter_resume(e.unit);
}

// 하드웨어 카운터는 16비트라 주기적으로 비우고 32비트에 누적한다.
// 최고속도(약 2.8바퀴/s = 4300카운트/s)에서도 50 ms 동안 수백 카운트라 넘칠 일이 없다.
void readEnc(Enc& e) {
  int16_t v = 0;
  pcnt_get_counter_value(e.unit, &v);
  pcnt_counter_clear(e.unit);
  e.total += e.sign * v;
}

void enableDrivers(bool on) {
  for (int pin : {L_R_EN, L_L_EN, R_R_EN, R_L_EN}) digitalWrite(pin, on ? HIGH : LOW);
}

void setup() {
  // 부팅 직후 EN이 떠 있지 않게 가장 먼저 LOW로 묶는다
  for (int pin : {L_R_EN, L_L_EN, R_R_EN, R_L_EN}) { pinMode(pin, OUTPUT); digitalWrite(pin, LOW); }
  setupEnc(enc_l);
  setupEnc(enc_r);
  pinMode(R_VCC, OUTPUT);
  digitalWrite(R_VCC, HIGH);

  ledcSetup(CH_L_R, PWM_FREQ, PWM_BITS); ledcAttachPin(L_RPWM, CH_L_R);
  ledcSetup(CH_L_L, PWM_FREQ, PWM_BITS); ledcAttachPin(L_LPWM, CH_L_L);
  ledcSetup(CH_R_R, PWM_FREQ, PWM_BITS); ledcAttachPin(R_RPWM, CH_R_R);
  ledcSetup(CH_R_L, PWM_FREQ, PWM_BITS); ledcAttachPin(R_LPWM, CH_R_L);
  ledcSetup(CH_LED, 1000, PWM_BITS);     ledcAttachPin(LED, CH_LED);
  driveStop();

  Serial.begin(115200);
  set_microros_serial_transports(Serial);
  delay(2000);

  allocator = rcl_get_default_allocator();
  rclc_support_init(&support, 0, NULL, &allocator);
  rclc_node_init_default(&node, "esp32_motor", "", &support);
  rclc_subscription_init_default(
      &sub_cmd_vel, &node,
      ROSIDL_GET_MSG_TYPE_SUPPORT(geometry_msgs, msg, Twist), "cmd_vel");
  rclc_publisher_init_best_effort(
      &pub_ticks, &node,
      ROSIDL_GET_MSG_TYPE_SUPPORT(std_msgs, msg, Int32MultiArray), "wheel_ticks");
  msg_ticks.data.data = ticks_buf;            // 동적 할당 없이 고정 버퍼 2칸
  msg_ticks.data.size = 2;
  msg_ticks.data.capacity = 2;
  msg_ticks.layout.dim.size = 0;
  msg_ticks.layout.dim.capacity = 0;
  msg_ticks.layout.data_offset = 0;

  rclc_executor_init(&executor, &support.context, 1, &allocator);
  rclc_executor_add_subscription(&executor, &sub_cmd_vel, &msg_in,
                                 &cmdVelCallback, ON_NEW_DATA);
  last_cmd_ms = millis();
  enableDrivers(true);   // PWM이 0인 상태에서 켠다 — 양쪽 LOW라 브레이크 상태
}

void loop() {
  rclc_executor_spin_some(&executor, RCL_MS_TO_NS(10));

  if (!stopped && millis() - last_cmd_ms > CMD_TIMEOUT_MS) {
    driveStop();   // 상위에서 명령이 끊겼다
  }

  if (millis() - last_ticks_ms >= TICKS_PERIOD_MS) {
    last_ticks_ms += TICKS_PERIOD_MS;
    readEnc(enc_l);
    readEnc(enc_r);
    ticks_buf[0] = enc_l.total;
    ticks_buf[1] = enc_r.total;
    rcl_publish(&pub_ticks, &msg_ticks, NULL);
  }
}
