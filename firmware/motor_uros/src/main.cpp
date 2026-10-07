/*
 * 로봇 주행 제어기 - micro-ROS 노드
 *
 * ROS 2의 /cmd_vel(geometry_msgs/Twist)을 구독해 좌우 바퀴 PWM으로 바꾼다.
 * Jetson에서 micro-ROS Agent를 띄우면 이 보드가 ROS 2 노드로 참여한다.
 *
 *   [상위]  /cmd_vel  ->  micro-ROS Agent  --USB시리얼-->  ESP32  ->  BTS7960
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

// --- 핀 배치 (시리얼 버전과 동일) ---
constexpr int L_RPWM = 25, L_LPWM = 26;
constexpr int R_RPWM = 32, R_LPWM = 33;
constexpr int LED    = 2;
// EN 핀은 펌웨어가 켠다. 점퍼선이 암-암뿐이라 3V3 한 핀을 VCC·R_EN·L_EN 여러 곳으로
// 나눌 수 없어서 EN을 GPIO에 하나씩 물렸다. 덕분에 micro-ROS 연결 전에는 드라이버가 꺼져 있다.
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
// 실측: 90도 명령에 45도(좌·우·좌 3회 같음). 속도 오차(90%)를 빼면 회전 효율 약 0.56
constexpr float TURN_EFF    = 0.56f;
constexpr float TRACK_EFF   = WHEEL_BASE / TURN_EFF;   // 약 0.43 m, 바퀴 속도 계산에 쓰는 유효 간격
// 좌우 모터가 거울상으로 달려서 배선이 같으면 오른쪽이 거꾸로 돈다(섀시 장착 후 확인)
constexpr bool  INVERT_R    = true;

constexpr uint32_t CMD_TIMEOUT_MS = 500;
volatile uint32_t last_cmd_ms = 0;
volatile bool stopped = true;

rcl_subscription_t sub_cmd_vel;
geometry_msgs__msg__Twist msg_in;
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

void enableDrivers(bool on) {
  for (int pin : {L_R_EN, L_L_EN, R_R_EN, R_L_EN}) digitalWrite(pin, on ? HIGH : LOW);
}

void setup() {
  // 부팅 직후 EN이 떠 있지 않게 가장 먼저 LOW로 묶는다
  for (int pin : {L_R_EN, L_L_EN, R_R_EN, R_L_EN}) { pinMode(pin, OUTPUT); digitalWrite(pin, LOW); }
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
}
