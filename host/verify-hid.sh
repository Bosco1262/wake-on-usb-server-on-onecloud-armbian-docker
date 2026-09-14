#!/bin/bash
# Write a single Enter report to /dev/hidg0 with Docker out of the picture, to
# verify the hardware link. It narrows the problem down to either «cable /
# gadget» or «container».
#
# Pass --lang en|zh-CN to force a language; otherwise the system locale is
# used, falling back to English.
#
# 不经过 Docker，直接向 /dev/hidg0 写一次 Enter 按键报文，验证硬件链路。
# 用来把问题范围缩小到「线/gadget」还是「容器」这一层。
#
# 可用 --lang en|zh-CN 指定语言；否则跟随系统语言，最后回退英文。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

. "${HERE}/i18n.sh"
i18n_init "$@"

DEV="${HID_DEVICE:-/dev/hidg0}"

if [ ! -e "$DEV" ]; then
  printf '%s%s\n' "$(t error.prefix)" "$(t verify.missing_device device="$DEV")" >&2
  exit 1
fi

echo "$(t verify.sending device="$DEV")"

# Report layout: [modifiers, reserved, key1..key6]. The NUL bytes are written
# straight out by printf; they must not be routed through a shell variable.
#
# 报文格式: [修饰键, 保留, key1..key6]，NUL 字节直接由 printf 写出（不能用变量中转）
printf '\x00\x00\x28\x00\x00\x00\x00\x00' > "$DEV"
sleep 0.06
printf '\x00\x00\x00\x00\x00\x00\x00\x00' > "$DEV"

echo "$(t verify.sent)"
echo "$(t verify.tips)"
