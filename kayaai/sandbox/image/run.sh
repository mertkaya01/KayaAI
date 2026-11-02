#!/bin/sh
# Kodu çalıştırır; çıktıyı /tmp'ye (64 MB tmpfs) yazar, ilk MAX_OUT baytını işaretlerle geri verir.
# Süre sınırı konteynerin İÇİNDE: aşılırsa 124 döner (dışarıdaki zaman aşımı yalnız yedek)
timeout --kill-after=2 "${TIME_LIMIT:-30}" python -I /in/main.py >/tmp/stdout 2>/tmp/stderr
ec=$?
head -c "${MAX_OUT:-65536}" /tmp/stdout
printf '\n@@KAYA_STDERR@@\n'
head -c "${MAX_OUT:-65536}" /tmp/stderr
printf '\n@@KAYA_EXIT@@%s\n' "$ec"
