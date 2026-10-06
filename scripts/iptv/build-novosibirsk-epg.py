#!/usr/bin/env python3
import gzip, re, shutil, urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
M3U = ROOT / "extras/iptv/novosibirsk-lampa.m3u"
OUT = ROOT / "extras/iptv/novosibirsk-lampa.xml.gz"
EPG_URL = "https://iptvx.one/EPG_LITE"

SOURCE = {
"НСК 49":"49kanal","ОТС":"ots","8 канал Новосибирск":"8kanal-novosibirsk","Афонтово":"afontovo-kr",
"Первый канал":"pervy","Россия 1":"rossia1","НТВ":"ntv","Пятый канал":"5kanal-ru","Россия К":"kultura","Россия 24":"rossia-24",
"Карусель":"karusel-pl4","ОТР":"otr","ТВ Центр":"tvcentr","РЕН ТВ":"rentv","Спас":"spas","СТС":"sts","Домашний":"domashny",
"ТВ-3":"tv3-ru","Пятница!":"piatnica","Звезда":"zvezda","Мир":"mir","ТНТ":"tnt","2x2":"2na2","Че!":"che","ТНТ4":"tnt4","Ю":"yu",
"Суббота!":"super","Солнце":"solnce","RT":"rt-news","РБК":"rbk","360°":"360-podmoskovie","360° Новости":"360-news","Мир 24":"mir-24",
"Москва 24":"moskva-24","Матч ТВ":"match-tv","Матч! Страна":"match-nash-sport","Матч! Арена":"match-arena","Матч! Игра":"match-igra",
"Матч! Боец":"match-boets","КХЛ":"kxl","КХЛ Prime":"kxl-hd","Мосфильм. Золотая коллекция":"mosfilm","Дом кино":"domkino-int",
"Дом кино Премиум":"domkino-premium","Кино ТВ":"kino-tv","Киномикс":"kinomiks","Кинокомедия":"kinokomedia","Киносерия":"kinoseria",
"Наше новое кино":"nashe-novoe-kino","Русский бестселлер":"russky-bestseller","Русский роман":"russky-roman","Моя планета":"moya-planeta",
"Наука":"nauka","Доктор":"doktor","История":"istoria","Авто Плюс":"avto-plus","Драйв":"drive","Живая планета":"zhivaya-planeta",
"Мульт":"mult","Мультиландия":"multimania","О!":None,"Ani":"ani","В гостях у сказки":"v-gostiax-u-skazki","СТС Kids":None,
"МУЗ-ТВ":"muztv","Europa Plus TV":"europa-plus-tv","BRIDGE":"bridge-tv","BRIDGE Classic":"bridge-tv-classic",
"Музыка Первого":"muzyka-pervogo","1HD Music Television":"1hd"
}
FIX = {"НСК 49":"NSK49.ru@SD","ОТС":"OTS.ru@SD","Матч ТВ":"Match.ru@SD","КХЛ Prime":"KHLPrime.ru@HD"}

m3u = M3U.read_text(encoding="utf-8")
rows = []
for line in m3u.splitlines():
    if line.startswith("#EXTINF:"):
        name = line.split(",",1)[1].strip()
        mid = re.search(r'tvg-id="([^"]*)"', line)
        rows.append((name, mid.group(1) if mid else ""))
if len(rows) != 70 or set(n for n,_ in rows) != set(SOURCE):
    raise SystemExit("playlist/mapping mismatch")
target = {n: FIX.get(n, old) for n,old in rows}
if any(not x for x in target.values()):
    raise SystemExit("empty target tvg-id")
source_to_target = {SOURCE[n]: target[n] for n,_ in rows if SOURCE[n]}

src_gz = Path("/tmp/iptvx-epg-lite.xml.gz")
with urllib.request.urlopen(EPG_URL, timeout=90) as r, src_gz.open("wb") as f:
    shutil.copyfileobj(r, f, 1024*1024)

tmp_xml = Path("/tmp/novosibirsk-lampa.xml")
counts = {sid: 0 for sid in source_to_target}
programmes = 0
with gzip.open(src_gz, "rt", encoding="utf-8", errors="strict") as inp, tmp_xml.open("w", encoding="utf-8") as out:
    out.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    out.write('<tv generator-info-name="karlinksk/awg-pi IPTV EPG">\n')
    for name,_ in rows:
        out.write(f'  <channel id="{escape(target[name])}"><display-name>{escape(name)}</display-name></channel>\n')
    for line in inp:
        if "<programme " not in line:
            continue
        m = re.search(r'channel="([^"]+)"', line)
        if not m or m.group(1) not in source_to_target:
            continue
        sid = m.group(1)
        line = line.replace(f'channel="{sid}"', f'channel="{source_to_target[sid]}"', 1)
        out.write("  " + line.lstrip())
        counts[sid] += 1
        programmes += 1
    out.write("</tv>\n")
zero = [sid for sid,n in counts.items() if n == 0]
if zero:
    raise SystemExit("EPG has zero programmes for: " + ",".join(zero))

tmp_gz = OUT.with_suffix(OUT.suffix + ".tmp")
with tmp_xml.open("rb") as src, tmp_gz.open("wb") as raw:
    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as dst:
        shutil.copyfileobj(src, dst)
tmp_gz.replace(OUT)
print(f"channels=70 mapped=68 programmes={programmes} bytes={OUT.stat().st_size}")
