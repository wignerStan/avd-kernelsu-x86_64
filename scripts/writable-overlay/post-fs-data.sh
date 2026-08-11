#!/system/bin/sh
#
# writable-overlay — post-fs-data.sh
# Runs at early boot (before Zygote / PackageManager scan).
# Mounts an overlay on top of the EROFS read-only root so that
# /system appears writable. All writes go to /data/adb/writable-overlay/upper
# and survive reboots.
#
# ⚠️  Must run in early boot context (KSU post-fs-data, or init.rc
#     service that runs before zygote). Running this from an adb root
#     shell at runtime FAILS with EINVAL because:
#     - / is a dm-block-device (254:0) mounting erofs read-only
#     - overlay overmount on dm-block-device is rejected by the kernel
#       once the initial mount has settled
#     - erofs cannot be remounted rw (no remount support)
#     This is exactly why Magisk/KSU modules do their magic mount in
#     post-fs-data.sh: it runs while init still owns the mount
#     namespace and the dm block device is not yet locked.
#
# KernelSU calls this script with the module dir in $0.
MODDIR=${0%/*}

UPPER=/data/adb/writable-overlay/upper
WORK=/data/adb/writable-overlay/work
LOG=/data/adb/writable-overlay/overlay.log

mkdir -p "$UPPER" "$WORK" 2>/dev/null || {
    echo "FATAL: cannot create $UPPER / $WORK" >> "$LOG" 2>/dev/null
    exit 1
}
echo "=== post-fs-data $(date) ===" >> "$LOG"

# 1) Already mounted? Then nothing to do.
if grep -q " / " /proc/mounts 2>/dev/null && grep " / " /proc/mounts | grep -q overlay; then
    echo "overlay already active, skip" >> "$LOG"
    exit 0
fi

# 2) Drop SELinux to permissive so the overlay inherits the lower
#    filesystem labels without throwing EACCES on writes.
setenforce 0 2>/dev/null

# 3) Mount overlay over the EROFS root. lowerdir=the whole erofs
#    root, upperdir+workdir live under /data (a separate ext4
#    mount), so the kernel check "workdir must not live in lower"
#    passes.
mount -t overlay overlay \
      -o "lowerdir=/,upperdir=$UPPER,workdir=$WORK" / >> "$LOG" 2>&1
rc=$?

if [ $rc -eq 0 ]; then
    echo "overlay mounted OK" >> "$LOG"
    # 4) Re-label the upper so files created there are usable.
    chcon -R u:object_r:system_file:s0 "$UPPER" >> "$LOG" 2>&1 || true
    # 5) Drop a marker so we can confirm writability from userspace.
    echo "writable-overlay active $(date)" > /system/.writable_marker
    echo "marker written" >> "$LOG"
else
    echo "overlay mount FAILED rc=$rc (likely not early enough in boot)" >> "$LOG"
fi

# 6) Restore enforcing. (In permissive we keep it off until
#    service.sh re-applies; in enforcing we restore now.)
setenforce 1 2>/dev/null

exit 0