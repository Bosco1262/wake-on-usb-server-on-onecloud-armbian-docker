#!/bin/bash
# Host-script structure checks: syntax, raw NUL bytes, report descriptor,
# argument handling, and the message-substitution edge cases.
#
# 宿主脚本的结构检查：语法、NUL 字节、报告描述符、参数处理，以及消息替换的
# 边界情况。
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
PROJ="$(cd "${HERE}/.." && pwd)"
pass=0
fail=0
ok() { echo "PASS  $1"; pass=$((pass + 1)); }
bad() { echo "FAIL  $1"; fail=$((fail + 1)); }

echo "== bash -n 语法检查 =="
for f in i18n.sh setup-hid-gadget.sh teardown-hid-gadget.sh verify-hid.sh; do
  if bash -n "${PROJ}/host/${f}" 2>/dev/null; then ok "bash -n $f"; else bad "bash -n $f"; fi
done

echo
echo "== printf 写 NUL 字节 =="
n=$(printf '\x00\x00\x28\x00\x00\x00\x00\x00' | wc -c | tr -d ' ')
[ "$n" = "8" ] && ok "按下报文 8 字节" || bad "按下报文 $n 字节"

hex=$(printf '\x00\x00\x28\x00\x00\x00\x00\x00' | od -An -tx1 | tr -d ' \n')
[ "$hex" = "0000280000000000" ] && ok "报文字节内容 $hex" || bad "报文字节内容 $hex"

echo
echo "== verify-hid.sh 实际写入（用 FIFO 模拟字符设备，避开 > 截断干扰）=="
fifo=$(mktemp -u)
out=$(mktemp)
mkfifo "$fifo"
cat "$fifo" > "$out" &
reader=$!
exec 3> "$fifo"
sleep 0.3
HID_DEVICE="$fifo" bash "${PROJ}/host/verify-hid.sh" --lang en > /dev/null 2>&1
sleep 0.3
exec 3>&-
wait $reader
size=$(wc -c < "$out" | tr -d ' ')
[ "$size" = "16" ] && ok "写出 16 字节（8 按下 + 8 释放）" || bad "写出 $size 字节"
hex=$(od -An -tx1 "$out" | tr -d ' \n')
[ "$hex" = "00002800000000000000000000000000" ] && ok "字节内容正确" || bad "字节内容 $hex"
rm -f "$fifo" "$out"

echo
echo "== report_desc 拼接与写入 =="
eval "$(grep '^HID_REPORT_DESC' "${PROJ}/host/setup-hid-gadget.sh")"
desc=$(mktemp)
printf '%b' "$HID_REPORT_DESC" > "$desc"
DESC_SIZE="$(wc -c < "$desc" | tr -d ' ')"
[ "$DESC_SIZE" -eq 63 ] && ok "report_desc 63 字节" || bad "report_desc $DESC_SIZE 字节"
head_hex=$(od -An -tx1 -N6 "$desc" | tr -d ' \n')
[ "$head_hex" = "05010906a101" ] && ok "描述符开头 $head_hex" || bad "描述符开头 $head_hex"
tail_hex=$(od -An -tx1 -j62 -N1 "$desc" | tr -d ' \n')
[ "$tail_hex" = "c0" ] && ok "描述符结尾 c0" || bad "描述符结尾 $tail_hex"
rm -f "$desc"

echo
echo "== 无 configfs 时 setup 脚本优雅报错 =="
out=$(bash "${PROJ}/host/setup-hid-gadget.sh" --lang en 2>&1)
if echo "$out" | grep -q "^Error"; then
  ok "提前失败并给出可读错误信息"
  echo "      -> $(echo "$out" | grep '^Error' | head -1)"
else
  bad "没有按预期报错：$out"
fi

echo
echo "== teardown 脚本正常退出 =="
bash "${PROJ}/host/teardown-hid-gadget.sh" --lang en > /dev/null 2>&1
[ $? -eq 0 ] && ok "退出码为 0" || bad "退出码非 0"

echo
echo "== 消息替换的边界情况 =="
. "${PROJ}/host/i18n.sh"
HID_I18N_LANG=en

# bash 5.2 起替换串里的 & 会被展开成匹配内容，必须被挡住
got="$(t setup.bound udc='A&B')"
[ "$got" = "Bound to UDC: A&B" ] && ok "取值里的 & 原样保留" || bad "取值里的 & 被改写：$got"

got="$(t setup.bound udc='{udc}')"
[ "$got" = "Bound to UDC: {udc}" ] && ok "占位符只替换一次" || bad "占位符被反复替换：$got"

got="$(t setup.no_udc)"
case "$got" in
  *"{name}"*) bad "多行消息残留未替换占位符" ;;
  *"peripheral"*) ok "多行消息正常取到" ;;
  *) bad "多行消息异常：$got" ;;
esac

echo
echo "== 取值里的转义不被解释（printf %s 而非 %b）=="
out=$(HID_DEVICE='/dev/hidg0\cTAIL' bash "${PROJ}/host/verify-hid.sh" --lang en 2>&1)
case "$out" in
  *TAIL*) ok "设备路径里的 \\c 不再截断输出" ;;
  *) bad "输出被截断：$out" ;;
esac

echo
echo "通过 $pass 项，失败 $fail 项"
exit $([ "$fail" -eq 0 ] && echo 0 || echo 1)
