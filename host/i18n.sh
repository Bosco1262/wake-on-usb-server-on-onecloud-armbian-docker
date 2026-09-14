#!/bin/bash
# Message catalog and language resolution shared by the host-side scripts.
#
# Priority: a --lang flag, then an inherited HID_I18N_LANG, then the system
# locale (LC_ALL / LC_MESSAGES / LANG), then English.
#
# Usage: source this file, call `i18n_init "$@"`, then use
# `t <key> [name=value ...]`.
#
# 宿主脚本共用的消息目录与语言解析。
#
# 优先级：--lang 参数 > 继承来的 HID_I18N_LANG > 系统语言环境
# （LC_ALL / LC_MESSAGES / LANG）> 英文保底。
#
# 用法：先 source 本文件，调用 i18n_init "$@"，然后用
# `t <key> [名字=值 ...]`。

# bash 5.2 expands `&` in a replacement into the matched text, which would
# mangle a device path containing `&`.
#
# bash 5.2 会把替换串里的 `&` 展开成匹配内容，含 `&` 的设备路径会被改写。
shopt -u patsub_replacement 2>/dev/null || true

# Normalise a language tag: any zh variant becomes zh-CN, any en variant
# becomes en, everything else is empty.
#
# 归一化语言标签：任何 zh 变体都归到 zh-CN，任何 en 变体归到 en，其余返回空。
i18n_normalize() {
  local tag
  tag="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]' | tr '_' '-')"
  case "$tag" in
    en | en-*) printf 'en' ;;
    zh | zh-*) printf 'zh-CN' ;;
    *) printf '' ;;
  esac
}

i18n_init() {
  local flag=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --lang=*) flag="${1#--lang=}"; shift ;;
      # `shift 2` refuses to move when the value is missing, which would spin
      # this loop forever, so consume the argument explicitly.
      #
      # 缺少取值时 `shift 2` 不会移动位置，会让本循环空转，因此显式逐个消费。
      --lang)
        if [ $# -ge 2 ]; then
          flag="$2"
          shift 2
        else
          shift
        fi
        ;;
      *) shift ;;
    esac
  done

  local lang=""
  lang="$(i18n_normalize "$flag")"
  [ -n "$lang" ] || lang="$(i18n_normalize "${HID_I18N_LANG:-}")"
  [ -n "$lang" ] || lang="$(i18n_normalize "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}")"
  [ -n "$lang" ] || lang="en"

  # Exported so that a script calling another script passes the choice down.
  #
  # 导出后，脚本调用另一个脚本时能把语言选择传下去。
  HID_I18N_LANG="$lang"
  export HID_I18N_LANG
}

declare -A HID_MSG_EN=(
  [error.prefix]="Error: "

  [setup.mount_failed]="Could not mount configfs."
  [setup.no_configfs]="No usb_gadget directory in configfs; the kernel lacks CONFIG_USB_CONFIGFS."
  [setup.already_bound]="gadget {name} already exists and is bound to a UDC, skipping."
  [setup.stale_gadget]="Found an unbound leftover gadget; cleaning it up first."
  [setup.no_udc]="/sys/class/udc/ is empty: dwc2 is not in peripheral mode.\n      This is the only hardware prerequisite on the Wanke Cloud; see \"Step 0\" in the README.\n      Note: do not apt upgrade the kernel or the device tree, that breaks OTG."
  [setup.no_bmattributes]="Note: this kernel does not expose configs/c.1/bmAttributes; skipping the remote wakeup capability advertisement."
  [setup.bad_report_desc]="report_desc was written as {size} bytes, expected 63."
  [setup.bound]="Bound to UDC: {udc}"
  [setup.no_hidg]="The gadget is bound but /dev/hidg0 was not created."
  [setup.ready]="/dev/hidg0 is ready"
  [setup.wakeup_ok]="This kernel supports wakeup_on_write, so signal mode can send a real remote wakeup."
  [setup.wakeup_missing]="Note: this kernel has no wakeup_on_write patch, so signal mode degrades to sending an empty report;\n      waking from S4/S5 will then depend on the target's BIOS supporting USB keyboard wake."

  [teardown.cleaned]="gadget {name} cleaned up"

  [verify.missing_device]="{device} does not exist; run setup-hid-gadget.sh first"
  [verify.sending]="Sending one Enter (usage 0x28) to {device}; watch whether the target wakes up..."
  [verify.sent]="Sent. If the target does not react:"
  [verify.tips]="  1. Make sure the A-to-A cable is in the Wanke Cloud's OTG port (the one next to the HDMI)\n  2. Make sure USB keyboard wake is enabled in the target's BIOS or OS\n  3. cat /sys/class/udc/*/state — only configured means the target has recognised this device"
)

declare -A HID_MSG_ZH=(
  [error.prefix]="错误: "

  [setup.mount_failed]="无法挂载 configfs"
  [setup.no_configfs]="configfs 中没有 usb_gadget 目录，内核缺少 CONFIG_USB_CONFIGFS"
  [setup.already_bound]="gadget {name} 已存在且已绑定 UDC，跳过"
  [setup.stale_gadget]="发现未绑定的残留 gadget，先清理再重建"
  [setup.no_udc]="/sys/class/udc/ 为空：dwc2 未进入 peripheral 模式。\n      这是玩客云上唯一的硬件前提，请先按 README 的「步骤 0」解决 OTG 模式。\n      注意：不要 apt upgrade 内核/设备树，否则 OTG 会失效。"
  [setup.no_bmattributes]="提示: 本内核未暴露 configs/c.1/bmAttributes，跳过远程唤醒能力声明"
  [setup.bad_report_desc]="report_desc 写入 {size} 字节，应为 63"
  [setup.bound]="已绑定 UDC: {udc}"
  [setup.no_hidg]="gadget 已绑定但 /dev/hidg0 未生成"
  [setup.ready]="/dev/hidg0 就绪"
  [setup.wakeup_ok]="内核支持 wakeup_on_write：signal 模式可发出真正的远程唤醒信号"
  [setup.wakeup_missing]="提示: 内核无 wakeup_on_write 补丁，signal 模式将降级为仅发空报文；\n      S4/S5 唤醒将依赖目标机 BIOS 的 USB 键盘唤醒支持。"

  [teardown.cleaned]="gadget {name} 已清理"

  [verify.missing_device]="{device} 不存在，请先运行 setup-hid-gadget.sh"
  [verify.sending]="向 {device} 发送一次 Enter（usage 0x28），请观察目标机是否被唤醒..."
  [verify.sent]="已发送。若目标机无反应："
  [verify.tips]="  1. 确认 USB 双公线接在玩客云靠近 HDMI 的 OTG 口\n  2. 确认目标机 BIOS/系统里开启了 USB 键盘唤醒\n  3. cat /sys/class/udc/*/state，configured 才说明被控机已识别本设备"
)

# Look a key up in the selected catalog and substitute {name} placeholders.
#
# Only the template's own \n is expanded, and that happens before the values
# are substituted, so a value containing a backslash (or \c, which would
# truncate printf %b output) is always printed literally.
#
# 在选定语言的目录里查键，并替换 {name} 占位符。
#
# 只展开模板自身的 \n，且在做取值替换之前完成，因此取值里的反斜杠（例如会让
# printf %b 截断输出的 \c）始终按字面输出。
t() {
  local key="$1"
  shift
  local text=""
  if [ "${HID_I18N_LANG:-en}" = "zh-CN" ]; then
    text="${HID_MSG_ZH[$key]:-}"
  fi
  [ -n "$text" ] || text="${HID_MSG_EN[$key]:-$key}"

  text="${text//\\n/$'\n'}"

  local pair
  for pair in "$@"; do
    text="${text//\{${pair%%=*}\}/${pair#*=}}"
  done
  printf '%s' "$text"
}
