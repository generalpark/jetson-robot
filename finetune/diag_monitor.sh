#!/usr/bin/env bash
# High-rate crash diagnostics: every 0.2 s, append + sync, so the last
# samples survive a sudden reset. Columns: all readable thermal zones,
# VDD_IN voltage/current (module 5V side), CPU_GPU_CV and SOC rail current,
# GPU clock, available memory.
OUT="${1:-/mnt/nvme/finetune/work/diag.log}"
H=/sys/bus/i2c/drivers/ina3221/1-0040/hwmon/hwmon1
G=/sys/devices/platform/bus@0/17000000.gpu/devfreq/17000000.gpu/cur_freq
T=/sys/devices/virtual/thermal
echo "time,cpu_mC,gpu_mC,soc0_mC,soc1_mC,soc2_mC,tj_mC,vin_mV,iin_mA,icpugpu_mA,isoc_mA,gpu_MHz,memavail_MB" > "$OUT"
while true; do
  ts=$(date +%H:%M:%S.%N | cut -c1-12)
  temps=""
  for z in 0 1 5 6 7 8; do temps="$temps,$(cat $T/thermal_zone$z/temp 2>/dev/null)"; done
  g=$(cat $G 2>/dev/null); g=$(( ${g:-0} / 1000000 ))
  m=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
  echo "$ts$temps,$(cat $H/in1_input),$(cat $H/curr1_input),$(cat $H/curr2_input),$(cat $H/curr3_input),$g,$m" >> "$OUT"
  sync "$OUT"
  sleep 0.2
done
