#!/bin/bash
# Audio diagnostics for the custom R36S device tree.
# Run from the Tools menu with headphones UNPLUGGED. Plays a tone on each
# playback path and writes what the kernel reports to audio_diag.log next to
# this script.

LOG="/roms/tools/audio_diag.log"
TTY="/dev/tty1"
sudo chmod 666 "$TTY" 2>/dev/null

say() { printf '%s\n' "$*" | tee -a "$LOG" > "$TTY"; }

tone() {
  if command -v speaker-test >/dev/null 2>&1; then
    timeout 4 speaker-test -t sine -f 660 -c 2 -l 1
  else
    head -c 529200 /dev/urandom | aplay -q -f S16_LE -r 44100 -c 2
  fi
}

printf '\033c' > "$TTY"
: > "$LOG"
say "Audio diagnostics (headphones should be unplugged)"

{
  echo "== date"; date
  echo "== model"; tr -d '\0' < /proc/device-tree/model; echo
  echo "== boot.ini dtb"; grep dtb /boot/boot.ini
  echo "== codec node props"; ls /proc/device-tree/i2c@ff180000/pmic@20/codec/
  echo "== hp-det-gpio"; hexdump -C "/proc/device-tree/rk817-sound/simple-audio-card,hp-det-gpio"
  echo "== cards"; cat /proc/asound/cards
  echo "== amixer contents"; amixer contents
  echo "== input devices"; cat /proc/bus/input/devices
  echo "== gpio"; sudo cat /sys/kernel/debug/gpio
  echo "== dmesg audio"; dmesg | grep -i -E "rk817|codec|jack|playback path|spk|asoc|simple-audio|hp-det"
} >> "$LOG" 2>&1

ORIG="$(amixer get 'Playback Path' 2>/dev/null | grep -oP "Item0: '\K\w+")"
n=0
for path in SPK HP SPK_HP; do
  n=$((n + 1))
  say ""
  say "TEST $n: path $path - listen for a short tone"
  {
    echo "-- test $n: path $path"
    amixer set 'Playback Path' "$path"
    sleep 1
    sudo grep -E "gpio-(103|86) " /sys/kernel/debug/gpio
    tone
  } >> "$LOG" 2>&1
  sleep 1
done

amixer -q set 'Playback Path' "${ORIG:-SPK}" >> "$LOG" 2>&1
{ echo "== dmesg tail"; dmesg | tail -40; } >> "$LOG" 2>&1
sync

say ""
say "Done. Note which TEST numbers played through the speaker."
sleep 10
