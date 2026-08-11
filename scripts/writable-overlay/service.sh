#!/system/bin/sh
#
# writable-overlay — service.sh
# Runs after boot (late_start). Responsibilities:
#   - Re-verify the overlay is still mounted (some OEM init re-mounts /).
#   - Restore SELinux to enforcing now that the mount window is done.
#   - Drop a marker file so you can confirm writability.
#
MODDIR=${0%/*}

UPPER=/data/adb/writable-overlay/upper
WORK=/data/adb/writable-overlay/work
LOG=/data/adb/writable-overlay/overlay.log

echo "=== service $(date) ===" >> "$LOG"

# 1) If overlay got lost (e.g. remount of /), re-apply it.
if ! (grep " / " /proc/mounts | grep -q overlay); then
    setenforce 0 2>/dev/null
    mount -t overlay overlay \
          -o "lowerdir=/,upperdir=$UPPER,workdir=$WORK" / >> "$LOG" 2>&1
    echo "re-mounted overlay rc=$?" >> "$LOG"
fi

# 2) Write test marker (goes to upper, persists across reboots).
if touch /system/.writable_marker 2>/dev/null; then
    echo "WRITABLE marker created" >> "$LOG"
else
    echo "marker FAILED (still read-only?)" >> "$LOG"
fi

# 3) Restore enforcing.
setenforce 1 2>/dev/null
echo "selinux restored: $(getenforce)" >> "$LOG"

exit 0
