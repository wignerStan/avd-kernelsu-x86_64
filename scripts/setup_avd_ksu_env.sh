#!/bin/bash
# ============================================================
# setup_avd_ksu_env.sh — One-shot provisioning of a rooted,
# KernelSU + Vector(LSPosed) + Google Play AVD environment.
#
# Prereqs:
#   - Android SDK emulator + system-images;android-35;google_apis_playstore;arm64-v8a
#   - gh CLI authenticated (for artifact download)
#   - Fork of leemikepop/avd-kernelsu-x86_64 with ksu_ref default v3.2.5
#
# Steps:
#   1. Build/replace kernel-ranchu with KSU kernel (Build ID matched)
#   2. Inject ksuinit into ramdisk (preserve bootconfig tail!)
#   3. Boot AVD, install KernelSU Manager, enable ADB Root
#   4. Install Zygisk Next + Vector, reboot, install Vector manager
# Usage: ./setup_avd_ksu_env.sh <avd_name> [ksu_build_artifact_dir]
# ============================================================
set -euo pipefail

AVD="${1:-Android35_GooglePlay}"
KSU_DIR="${2:-${KSU_DIR:-$HOME/avd_ksu}}"
SDK="${ANDROID_SDK_ROOT:-$HOME/Library/Android/sdk}"
ADB="$SDK/platform-tools/adb"
EMU="$SDK/emulator/emulator"
IMG="$SDK/system-images/android-35/google_apis_playstore/arm64-v8a"

log() { echo "[*] $*"; }

log "=== Step 0: verify AVD + image ==="
[ -d "$IMG" ] || { echo "ERROR: image dir missing: $IMG"; exit 1; }
"$EMU" -list-avds | grep -qx "$AVD" || { echo "ERROR: AVD $AVD not found"; exit 1; }

log "=== Step 1: deploy KernelSU kernel (kernel-ranchu) ==="
# Expects the leemikepop workflow artifact: Image.gz + build-info.txt
# (Build ID must equal the image's: 11987101 for android-35 6.6.30)
if [ ! -f "$KSU_DIR/Image.gz" ]; then
  echo "ERROR: $KSU_DIR/Image.gz not found. Build it via GH Actions:"
  echo "  gh workflow run build-gki.yml --repo wignerStan/avd-kernelsu-x86_64 \\"
  echo "      -f avd_target=a15-api35-6.6 -f ksu_ref=v3.2.5 -f ksu_variant=KernelSU -f arch=arm64"
  exit 1
fi
[ -f "$IMG/kernel-ranchu.orig" ] || cp "$IMG/kernel-ranchu" "$IMG/kernel-ranchu.orig"
cp "$KSU_DIR/Image.gz" "$IMG/kernel-ranchu"
log "kernel replaced (orig backed up as kernel-ranchu.orig)"

log "=== Step 2: inject ksuinit into ramdisk (keeps bootconfig tail!) ==="
# ksuinit v3.2.5 arm64 static binary
KSUINIT="$KSU_DIR/ksuinit"
[ -f "$KSUINIT" ] || { echo "ERROR: $KSUINIT missing"; exit 1; }
[ -f "$IMG/ramdisk.img.orig" ] || cp "$IMG/ramdisk.img" "$IMG/ramdisk.img.orig"
PY="${PYTHON:-python3}"
"$PY" "$KSU_DIR/inject_ksuinit.py" "$IMG/ramdisk.img.orig" "$KSUINIT" "$IMG/ramdisk.img"
log "ramdisk patched (orig backed up as ramdisk.img.orig)"

log "=== Step 3: boot AVD ==="
pkill -f qemu-system 2>/dev/null || true
sleep 2
nohup "$EMU" -avd "$AVD" -memory 4096 -cores 4 -gpu host \
  -no-snapshot -no-boot-anim -no-audio > /tmp/ksu_avd_setup.log 2>&1 &
timeout 180 "$ADB" wait-for-device
for i in $(seq 1 24); do
  [ "$("$ADB" -e shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ] && break
  sleep 10
done
log "AVD booted"

log "=== Step 4: verify KernelSU kernel + install Manager ==="
"$ADB" -e shell uname -r
"$ADB" -e install -r "$KSU_DIR/KernelSU_manager.apk"
"$ADB" -e shell am start -n me.weishu.kernelsu/.ui.MainActivity
sleep 8
log "Manager installed & launched (deploys ksud, enables adbd root)"

log "=== Step 5: enable ADB root / verify uid=0 ==="
"$ADB" -e shell "ksud -V"
"$ADB" -e shell id

log "=== Step 6: install Zygisk Next + Vector (LSPosed successor) ==="
"$ADB" -e push "$KSU_DIR/ZygiskNext.zip" /data/local/tmp/zygisk.zip
"$ADB" -e push "$KSU_DIR/Vector.zip" /data/local/tmp/vector.zip
"$ADB" -e shell "ksud module install /data/local/tmp/zygisk.zip"
"$ADB" -e shell "ksud module install /data/local/tmp/vector.zip"
log "modules installed, rebooting"
"$ADB" -e reboot
sleep 5
timeout 180 "$ADB" wait-for-device
for i in $(seq 1 24); do
  [ "$("$ADB" -e shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ] && break
  sleep 10
done
log "rebooted"

log "=== Step 7: install Vector manager + activate GMS/Play ==="
"$ADB" -e shell "cp /data/adb/modules/zygisk_vector/manager.apk /data/local/tmp/vm.apk"
"$ADB" -e pull /data/local/tmp/vm.apk "$KSU_DIR/vector_manager.apk"
"$ADB" -e install -r "$KSU_DIR/vector_manager.apk"
"$ADB" -e shell "pm enable com.google.android.gms"
"$ADB" -e shell "pm enable com.android.vending"
"$ADB" -e shell "am start -n org.matrix.vector.manager/.ui.MainActivity"
log "=== DONE. Verify: Vector=Active, adb root, Play Store works ==="
