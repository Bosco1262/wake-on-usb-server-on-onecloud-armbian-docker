#!/bin/bash
# Unbind and remove the gadget. configfs requires rmdir-ing the layers in order.
#
# Pass --lang en|zh-CN to force a language; otherwise the system locale is
# used, falling back to English.
#
# 解绑并删除 gadget。configfs 必须按顺序逐层 rmdir。
#
# 可用 --lang en|zh-CN 指定语言；否则跟随系统语言，最后回退英文。
set -uo pipefail

GADGET_NAME="${GADGET_NAME:-hidwake}"
G="/sys/kernel/config/usb_gadget/${GADGET_NAME}"
HERE="$(cd "$(dirname "$0")" && pwd)"

. "${HERE}/i18n.sh"
i18n_init "$@"

if [ ! -d "$G" ]; then
  exit 0
fi

echo "" > "$G/UDC" 2>/dev/null || true
rm -f "$G/configs/c.1/hid.usb0" 2>/dev/null || true
rmdir "$G/configs/c.1/strings/0x409" 2>/dev/null || true
rmdir "$G/configs/c.1" 2>/dev/null || true
rmdir "$G/functions/hid.usb0" 2>/dev/null || true
rmdir "$G/strings/0x409" 2>/dev/null || true
rmdir "$G" 2>/dev/null || true

printf '%s\n' "$(t teardown.cleaned name="$GADGET_NAME")"
