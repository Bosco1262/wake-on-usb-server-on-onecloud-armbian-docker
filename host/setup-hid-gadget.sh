#!/bin/bash
# Idempotently create the USB HID keyboard gadget and bind it to the UDC.
# Requires CONFIG_USB_CONFIGFS / CONFIG_USB_CONFIGFS_F_HID, and dwc2 running
# in peripheral/otg mode (i.e. /sys/class/udc/ is not empty).
#
# Pass --lang en|zh-CN to force a language; otherwise the system locale is
# used, falling back to English.
#
# 幂等地创建 USB HID 键盘 gadget 并绑定到 UDC。
# 前置条件：内核启用 CONFIG_USB_CONFIGFS / CONFIG_USB_CONFIGFS_F_HID，
# 且 dwc2 处于 peripheral/otg 模式（即 /sys/class/udc/ 非空）。
#
# 可用 --lang en|zh-CN 指定语言；否则跟随系统语言，最后回退英文。
set -euo pipefail

GADGET_NAME="${GADGET_NAME:-hidwake}"
G="/sys/kernel/config/usb_gadget/${GADGET_NAME}"
HERE="$(cd "$(dirname "$0")" && pwd)"

. "${HERE}/i18n.sh"
i18n_init "$@"

log() { printf '%s\n' "$*"; }
die() { printf '%s%s\n' "$(t error.prefix)" "$*" >&2; exit 1; }

# The 63-byte standard keyboard report descriptor: 8 modifier bits, one
# reserved byte, 6 key codes, plus the 5-bit LED output report. Matches
# Documentation/usb/gadget_hid.rst.
#
# 63 字节标准键盘报告描述符：8 个修饰键位 + 保留字节 + 6 个按键码
# + 5 位 LED 输出报表。与内核 Documentation/usb/gadget_hid.rst 一致。
HID_REPORT_DESC='\x05\x01\x09\x06\xa1\x01\x05\x07\x19\xe0\x29\xe7\x15\x00\x25\x01'
HID_REPORT_DESC+='\x75\x01\x95\x08\x81\x02\x95\x01\x75\x08\x81\x03\x95\x05\x75\x01'
HID_REPORT_DESC+='\x05\x08\x19\x01\x29\x05\x91\x02\x95\x01\x75\x03\x91\x03\x95\x06'
HID_REPORT_DESC+='\x75\x08\x15\x00\x25\x65\x05\x07\x19\x00\x29\x65\x81\x00\xc0'

modprobe libcomposite 2>/dev/null || true

if ! grep -q ' /sys/kernel/config ' /proc/mounts; then
  mount -t configfs none /sys/kernel/config || die "$(t setup.mount_failed)"
fi

[ -d /sys/kernel/config/usb_gadget ] || die "$(t setup.no_configfs)"

if [ -d "$G" ]; then
  if [ -n "$(cat "$G/UDC" 2>/dev/null)" ]; then
    log "$(t setup.already_bound name="$GADGET_NAME")"
    exit 0
  fi
  log "$(t setup.stale_gadget)"
  "${HERE}/teardown-hid-gadget.sh" || true
fi

UDC="$(ls /sys/class/udc/ 2>/dev/null | head -n1 || true)"
if [ -z "$UDC" ]; then
  die "$(t setup.no_udc)"
fi

mkdir -p "$G"
cd "$G"

echo 0x1d6b > idVendor
echo 0x0104 > idProduct
echo 0x0100 > bcdDevice
echo 0x0200 > bcdUSB

mkdir -p strings/0x409
echo "WAKE0001"          > strings/0x409/serialnumber
echo "WankeCloud"        > strings/0x409/manufacturer
echo "HID Wake Keyboard" > strings/0x409/product

mkdir -p configs/c.1/strings/0x409
echo "HID Wake" > configs/c.1/strings/0x409/configuration
echo 120        > configs/c.1/MaxPower

# Advertise remote wakeup capability (0x80 bus powered + 0x20 remote wakeup).
# This only tells the host that the device may wake it; actually sending the
# resume signal still needs kernel support. Older kernels may not expose this
# attribute at all, hence the guard.
#
# 声明 remote wakeup 能力（0x80 总线供电 + 0x20 远程唤醒）。
# 这只告诉主机「本设备可以唤醒你」，真正发出 resume 信号还需要内核支持，
# 老内核可能根本没有这个属性，所以加保护。
if [ -f configs/c.1/bmAttributes ]; then
  echo 0xa0 > configs/c.1/bmAttributes
else
  log "$(t setup.no_bmattributes)"
fi

mkdir -p functions/hid.usb0
echo 1 > functions/hid.usb0/subclass
echo 1 > functions/hid.usb0/protocol
echo 8 > functions/hid.usb0/report_length
printf '%b' "$HID_REPORT_DESC" > functions/hid.usb0/report_desc

DESC_SIZE="$(wc -c < functions/hid.usb0/report_desc)"
[ "$DESC_SIZE" -eq 63 ] || die "$(t setup.bad_report_desc size="$DESC_SIZE")"

ln -sf functions/hid.usb0 configs/c.1/

echo "$UDC" > UDC
log "$(t setup.bound udc="$UDC")"

for _ in $(seq 1 30); do
  [ -e /dev/hidg0 ] && break
  sleep 0.1
done
[ -e /dev/hidg0 ] || die "$(t setup.no_hidg)"
log "$(t setup.ready)"

if [ -e /sys/module/usb_f_hid/parameters/wakeup_on_write ]; then
  log "$(t setup.wakeup_ok)"
else
  log "$(t setup.wakeup_missing)"
fi
