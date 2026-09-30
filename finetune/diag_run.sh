#!/usr/bin/env bash
# Run the pending data-size sweep under full diagnostics.
cd /mnt/nvme/finetune/work
cat /proc/sys/kernel/random/boot_id > diag_bootid.txt
bash diag_monitor.sh /mnt/nvme/finetune/work/diag.log &
MON=$!
( sudo dmesg -w --time-format iso >> kern_live.log 2>&1 & DM=$!; while kill -0 $DM 2>/dev/null; do sync kern_live.log; sleep 1; done ) &
KSYNC=$!
echo "start $(date +%T)" > diag_status.txt; sync diag_status.txt
bash run_sweep.sh 200 400 > diag_sweep.log 2>&1
RC=$?
echo "sweep exit=$RC $(date +%T)" >> diag_status.txt
kill $MON $KSYNC 2>/dev/null; sudo pkill -f "dmesg -w" 2>/dev/null
echo "DONE_DIAG" >> diag_status.txt; sync diag_status.txt
