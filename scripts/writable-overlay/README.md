# writable-overlay

KSU module that tries to make the EROFS read-only `/system` appear
writable by overlaying an `overlayfs` on top of it. Writes go to
`/data/adb/writable-overlay/upper/` and survive reboots.

## Files

| file | when it runs |
|------|--------------|
| `post-fs-data.sh` | early boot (KSU module) — best chance to overmount `/` |
| `service.sh` | late boot (KSU module) — re-apply if lost + drop a marker |
| `post-boot.sh` | manual use from `adb shell` (or automation) |

## Verdict on AVD

**On AVD (erofs read-only `/`):**

```
mount -t overlay overlay -o lowerdir=/,upperdir=...,workdir=... / \
      → mount: Invalid argument
```

Reason:
- `/` is a dm-block-device (254:0) mounting erofs read-only.
- Kernel refuses to overmount a dm block device after the initial mount
  has settled. Even from init's mount namespace in post-fs-data.
- erofs has no `remount,rw` support, so you can't convert it first.

So this module does **NOT** turn a playstore erofs AVD into a writable
system. Confirmed by direct test (Android 15 userdebug AVD, KSU 32525):
both post-fs-data.sh and service.sh attempted the
mount and both failed with `rc=255 / Invalid argument`.

What **does** work on AVD:
- `mount -t overlay overlay -o lowerdir=/,upperdir=...,workdir=... \
  /mnt/scratch/merged` — overlay over a *new* mount point on tmpfs
  (already verified in a prior test — OVERLAY_OK). Useful
  for ad-hoc writes if your working dir is `/mnt/scratch/merged`,
  but does NOT make `/system` itself writable.

To make `/system` actually writable on AVD you need one of:
1. A system image that uses ext4 (or f2fs) with the dm-verity hashtree
   disabled and AVB disabled. `aosp_default` images are already ext4
   + userdebug + writable after `adb root` + `adb remount`. Use that.
2. Or, for playstore-style GMS on a writable system: build AOSP+MindTheGapps
   via `ponces/treble_aosp` fork (we verified the manifest), with
   GSI_FILE_SYSTEM_TYPE := ext4 — but that needs a self-hosted runner
   with 400 GB disk (not feasible on this machine).

## How to use anyway

For automation / CI / non-emulator (e.g. a phone with Magisk/KSU):

```bash
# push standalone script (no module install required)
adb push writable-overlay/post-boot.sh /data/local/tmp/
adb shell su -c 'sh /data/local/tmp/post-boot.sh'

# or as a real module
adb push writable-overlay.zip /sdcard/
adb shell su -c 'ksud module install /sdcard/writable-overlay.zip'
adb reboot    # post-fs-data.sh runs automatically
```

## Where the writes live

* `/data/adb/writable-overlay/upper/` — your files
* `/data/adb/writable-overlay/work/` — overlayfs internal
* `/data/adb/writable-overlay/overlay.log` — mount attempts
* `/data/adb/writable-overlay/postboot.log` — manual-run log