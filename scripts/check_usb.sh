#!/bin/bash
# ESP32가 인식됐는지 확인
echo "=== USB 시리얼 장치 ==="
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || echo "  없음"
echo
echo "=== USB 장치 목록 ==="
lsusb | grep -iE "cp210|ch34|silicon|espressif|wch" || echo "  ESP32로 보이는 장치 없음"
echo
echo "=== 커널 인식 로그 (최근) ==="
dmesg 2>/dev/null | grep -iE "cp210|ch34|ttyUSB|ttyACM" | tail -5 || echo "  (권한 없음 - sudo dmesg 로 확인)"
