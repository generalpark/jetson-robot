#!/usr/bin/env bash
# 학습 중 전력·온도를 1초마다 파일에 남긴다.
# 보드가 갑자기 꺼지면 로그가 버퍼에 남은 채 사라지므로,
# 매 줄마다 즉시 디스크에 반영되도록 append 로 쓰고 sync 한다.
OUT="${1:-/mnt/nvme/finetune/work/power.log}"
echo "time,temp_mC,curr_mA" > "$OUT"
while true; do
  T=$(cat /sys/devices/virtual/thermal/thermal_zone0/temp 2>/dev/null)
  C=$(cat /sys/bus/i2c/drivers/ina3221/*/hwmon/hwmon*/curr1_input 2>/dev/null | head -1)
  echo "$(date +%H:%M:%S),${T},${C}" >> "$OUT"
  sync "$OUT"
  sleep 1
done
