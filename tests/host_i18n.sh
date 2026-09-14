#!/bin/bash
# Host-script localisation checks: normalisation, precedence, catalog
# completeness and the language each script actually prints.
#
# 宿主脚本多语言检查：归一化、优先级、消息目录完整性，以及脚本实际输出的语言。
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
PROJ="$(cd "${HERE}/.." && pwd)"
pass=0
fail=0
ok() { echo "PASS  $1"; pass=$((pass + 1)); }
bad() { echo "FAIL  $1"; fail=$((fail + 1)); }

. "${PROJ}/host/i18n.sh"

echo "== 归一化 =="
for pair in "en:en" "EN:en" "en-US:en" "en_GB:en" "zh:zh-CN" "zh-CN:zh-CN" \
            "zh_cn:zh-CN" "zh-Hans-CN:zh-CN" "zh-TW:zh-CN" "fr:" "de-DE:" ":";
do
  raw="${pair%%:*}"
  want="${pair#*:}"
  got="$(i18n_normalize "$raw")"
  [ "$got" = "$want" ] && ok "normalize('$raw') = '$want'" || bad "normalize('$raw') = '$got'，应为 '$want'"
done

echo
echo "== 优先级：--lang > 继承 > 系统语言 > 英文 =="

lang_of() {
  local loc="$1"
  shift
  ( LC_ALL="" LC_MESSAGES="" LANG="$loc" HID_I18N_LANG="" i18n_init "$@"; printf '%s' "$HID_I18N_LANG" )
}

expect() {
  local name="$1" want="$2" got="$3"
  [ "$got" = "$want" ] && ok "$name = $want" || bad "$name = '$got'，应为 '$want'"
}

expect "系统语言 de 回落英文" "en" "$(lang_of de_DE.UTF-8)"
expect "系统语言 zh_CN" "zh-CN" "$(lang_of zh_CN.UTF-8)"
expect "系统语言 C" "en" "$(lang_of C)"
expect "系统语言为空" "en" "$(lang_of '')"
expect "--lang 覆盖系统语言" "zh-CN" "$(lang_of de_DE.UTF-8 --lang zh-CN)"
expect "--lang=... 形式" "en" "$(lang_of zh_CN.UTF-8 --lang=en)"
expect "非法 --lang 回落系统语言" "zh-CN" "$(lang_of zh_CN.UTF-8 --lang fr)"
expect "--lang 归一化" "zh-CN" "$(lang_of '' --lang zh_Hans)"
# 曾经的死循环：--lang 缺少取值时 shift 2 不移动位置
expect "--lang 缺参数不挂起" "en" "$(lang_of '' --lang)"
expect "--lang=空值不挂起" "en" "$(lang_of '' --lang=)"

expect "LC_ALL 优先于 LANG" "zh-CN" \
  "$( ( LC_ALL=zh_CN.UTF-8 LANG=de_DE.UTF-8 HID_I18N_LANG="" i18n_init; printf '%s' "$HID_I18N_LANG" ) )"
expect "继承的 HID_I18N_LANG 优先于系统语言" "en" \
  "$( ( LC_ALL="" LANG=zh_CN.UTF-8 HID_I18N_LANG=en i18n_init; printf '%s' "$HID_I18N_LANG" ) )"
expect "--lang 优先于继承值" "zh-CN" \
  "$( ( LC_ALL="" LANG=de_DE.UTF-8 HID_I18N_LANG=en i18n_init --lang zh-CN; printf '%s' "$HID_I18N_LANG" ) )"

echo
echo "== 消息表完整性 =="
placeholders() { printf '%s' "$1" | grep -o '{[a-z]*}' | sort | tr '\n' ' '; }

missing=""
identical=""
mismatch=""
for key in "${!HID_MSG_EN[@]}"; do
  if [ -z "${HID_MSG_ZH[$key]:-}" ]; then
    missing="$missing $key"
    continue
  fi
  [ "${HID_MSG_EN[$key]}" != "${HID_MSG_ZH[$key]}" ] || identical="$identical $key"
  [ "$(placeholders "${HID_MSG_EN[$key]}")" = "$(placeholders "${HID_MSG_ZH[$key]}")" ] \
    || mismatch="$mismatch $key"
done

[ -z "$missing" ] && ok "中文表覆盖全部 ${#HID_MSG_EN[@]} 个键" || bad "中文表缺键:$missing"
[ -z "$identical" ] && ok "两语言文案确实不同" || bad "两语言文案相同:$identical"
[ -z "$mismatch" ] && ok "两语言占位符一致" || bad "占位符不一致:$mismatch"

expect "t 在 zh-CN 下取中文" "已绑定 UDC: c9040000.usb" \
  "$( ( HID_I18N_LANG=zh-CN; t setup.bound udc=c9040000.usb ) )"
expect "t 在 en 下取英文" "Bound to UDC: c9040000.usb" \
  "$( ( HID_I18N_LANG=en; t setup.bound udc=c9040000.usb ) )"
expect "未知键回显键名" "no.such.key" "$( ( HID_I18N_LANG=en; t no.such.key ) )"
expect "多行消息展开为多行" "2" \
  "$( ( HID_I18N_LANG=zh-CN; t setup.wakeup_missing ) | grep -c '^' )"

echo
echo "== 脚本实际输出 =="
check_lang() {
  case "$3" in
    *"$2"*) ok "$1" ;;
    *) bad "$1 —— 实际输出: $(printf '%s' "$3" | head -1)" ;;
  esac
}

out_zh="$(HID_DEVICE=/nonexistent bash "${PROJ}/host/verify-hid.sh" --lang zh-CN 2>&1)"
out_en="$(HID_DEVICE=/nonexistent bash "${PROJ}/host/verify-hid.sh" --lang en 2>&1)"
check_lang "verify-hid.sh --lang zh-CN" "错误" "$out_zh"
check_lang "verify-hid.sh --lang en" "Error" "$out_en"

out_loc="$(LC_ALL= LANG=zh_CN.UTF-8 HID_DEVICE=/nonexistent bash "${PROJ}/host/verify-hid.sh" 2>&1)"
check_lang "verify-hid.sh 跟随系统语言" "错误" "$out_loc"

out_loc2="$(LC_ALL= LANG=de_DE.UTF-8 HID_DEVICE=/nonexistent bash "${PROJ}/host/verify-hid.sh" 2>&1)"
check_lang "verify-hid.sh 未知系统语言回落英文" "Error" "$out_loc2"

fifo=$(mktemp -u)
mkfifo "$fifo"
cat "$fifo" > /dev/null &
reader=$!
exec 3> "$fifo"
sleep 0.3
out_ok="$(HID_DEVICE="$fifo" bash "${PROJ}/host/verify-hid.sh" --lang zh-CN 2>&1)"
sleep 0.3
exec 3>&-
wait $reader
check_lang "verify-hid.sh 成功路径中文" "已发送" "$out_ok"
rm -f "$fifo"

out_setup_zh="$(bash "${PROJ}/host/setup-hid-gadget.sh" --lang zh-CN 2>&1)"
out_setup_en="$(bash "${PROJ}/host/setup-hid-gadget.sh" --lang en 2>&1)"
check_lang "setup-hid-gadget.sh --lang zh-CN" "错误" "$out_setup_zh"
check_lang "setup-hid-gadget.sh --lang en" "Error" "$out_setup_en"

echo
echo "通过 $pass 项，失败 $fail 项"
exit $([ "$fail" -eq 0 ] && echo 0 || echo 1)
