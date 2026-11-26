# Stop SLAM + simulation launches and any Windows-side Webots left behind.
stopgrp() { local f="$BRIDGE/$1.pgid"; [ -f "$f" ] || return 0; local PG=$(cat "$f"); kill -INT -"$PG" 2>/dev/null
  for i in $(seq 1 20); do kill -0 -"$PG" 2>/dev/null || break; sleep 1; done
  kill -0 -"$PG" 2>/dev/null && { kill -TERM -"$PG"; sleep 4; }; kill -0 -"$PG" 2>/dev/null && kill -KILL -"$PG"; rm -f "$f"; echo "stopped $1"; }
stopgrp slam; stopgrp sim; sleep 2
for im in webots-bin.exe webotsw.exe webots.exe; do taskkill.exe /IM $im /F >/dev/null 2>&1 && echo "killed Windows $im"; done
sleep 2
echo "remaining Windows webots: $(tasklist.exe 2>/dev/null | grep -ic webots)"
