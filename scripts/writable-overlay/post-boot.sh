#!/system/bin/sh
#
# writable-overlay — post-boot.sh  (standalone, manual / automation use)
#
# Use this INSTEAD of the KernelSU module when you don't want to install
# a module, e.g. from an automation/CI script right after boot:
#
#     adb shell sh /data/local/tmp/writable-overlay/post-boot.sh
#
# What it does:
#   1. Mounts an overlay on / so the EROFS read-only system is writable.
#   2. Writes go to /data/adb/writable-overlay/upper and survive reboots.
#   3. Idempotent: safe to run every boot; skips if already mounted.
#   4. Sets SELinux permissive for the mount window, restores after.
#
# Requires: root (adb root) + overlay fs in kernel (emulator has it).

UPPER=/data/adb/writable-overlay/upper
WORK=/data/adb/writable-overlay/work
LOG=/data/adb/writable-overlay/postboot.log

echo "=== post-boot $(date) ===" >> "$LOG"

[ "$(id -u)" = "0" ] || { echo "need root" >> "$LOG"; exit 1; }

mkdir -p "$UPPER" "$WORK"

# Already mounted?
if grep " / " /proc/mounts | grep -q overlay; then
    echo "already mounted, skip" >> "$LOG"
    # still verify writability marker
    touch /system/.writable_marker && echo "marker ok" >> "$LOG"
    exit 0
fi

setenforce 0 2>/dev/null

mount -t overlay overlay \
      -o "lowerdir=/,upperdir=$UPPER,workdir=$WORK" / >> "$LOG" 2>&1
rc=$?

if [ $rc -eq 0 ]; then
    chcon -R u:object_r:system_file:s0 "$UPPER" >> "$LOG" 2>&1 || true
    touch /system/.writable_marker && echo "WRITABLE: marker created" >> "$LOG"
else
    echo "mount FAILED rc=$rc" >> "$LOG"
    setenforce 1 2>/dev/null
    exit 1
fi

setenforce 1 2>/dev/null
echo "done, selinux=$(getenforce)" >> "$LOG"
exit 0
