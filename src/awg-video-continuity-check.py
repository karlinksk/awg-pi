#!/usr/bin/env python3
"""Stage18: bounded 2MiB multi-frame YouTube proof, with NO DIRECT fallback.

yt-dlp resolves a single low-resolution video stream URL through the local
Mihomo. We DO NOT download using yt-dlp --test (truncates media) or ffmpeg's
network downloader. Instead, a bounded first 2MiB byte-range is fetched by urllib through the
same forced 127.0.0.1 proxy, from a strict googlevideo.com allowlist.
The signed media URL never appears in journals, exceptions or reports.
Only local RAM bytes are passed to ffmpeg, with network protocols disabled.
PASS requires >=24 video frames actually decoded, not just one HTTP range or frame.
"""
from __future__ import annotations
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import tempfile
import types
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

VIDEO_URL="https://www.youtube.com/watch?v=jNQXAC9IVRw"
RAM=Path("/dev/shm")
RANGE_CAP=2*1024*1024
MIN_DECODED_FRAMES=24
MAX_METADATA_URL=16000
TIME_LIMIT=45
ALLOWED_KINDS={".mp4",".webm"}
FRAME_MAGIC=(b"\x1a\x45\xdf\xa3",)
TARGET="/dev/shm/awg-stage15/bin/yt-dlp"


def report(state,reason):
    return {"state":state,"reason":reason,"method":"video_frame_decode",
            "shadow_only":True}


def safe_media_url(url):
    if not isinstance(url,str) or len(url)>MAX_METADATA_URL:
        return False
    try:
        parsed=urllib.parse.urlsplit(url)
        host=(parsed.hostname or "").lower()
        return (parsed.scheme=="https" and not parsed.username
                and not parsed.password
                and (parsed.port is None or parsed.port==443)
                and (host=="googlevideo.com" or host.endswith(".googlevideo.com"))
                and parsed.path=="/videoplayback")
    except ValueError:
        return False


class SafeRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not safe_media_url(newurl):
            raise ValueError("unapproved media redirect")
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def fetch_range(port,url,*,cap=RANGE_CAP,timeout=12):
    """Via forced loopback proxy only. A 206 + bounded bytes is still NOT PASS."""
    if not (type(port) is int and 1<=port<=65535 and safe_media_url(url)):
        raise ValueError("unapproved media request")
    if not (type(cap) is int and 128<=cap<=RANGE_CAP):
        raise ValueError("invalid range cap")
    class ForcedProxy(urllib.request.ProxyHandler):
        def proxy_open(self,req,proxy,proxy_type):
            req.set_proxy("127.0.0.1:"+str(port),"http")
            return None
    proxy="http://127.0.0.1:"+str(port)
    opener=urllib.request.build_opener(
        ForcedProxy({"http":proxy,"https":proxy}),
        SafeRedirects(),urllib.request.HTTPSHandler())
    req=urllib.request.Request(url,headers={
        "User-Agent":"Mozilla/5.0 (compatible; AWG-Pi-Video-Range-Check)",
        "Range":"bytes=0-"+str(cap-1),
        "Accept-Encoding":"identity"})
    with opener.open(req,timeout=timeout) as response:
        if response.status != 206 or not safe_media_url(response.geturl()):
            raise ValueError("ranged response not confirmed")
        # A 206 for an unrelated offset cannot establish the initial frame.
        header=response.headers.get("Content-Range","")
        match=re.fullmatch(r"bytes 0-(\d+)/(\d+|\*)",header)
        if not match or int(match.group(1))>=cap:
            raise ValueError("initial byte range not confirmed")
        media=response.read(cap+1)
        if len(media)>cap:
            raise ValueError("media exceeded range cap")
        if len(media)<128:
            raise ValueError("media too small")
        # Require an actual video container head, never accept HTML or arbitrary 206.
        if not (media.startswith(FRAME_MAGIC) or
                (len(media)>16 and media[4:8] in (b"ftyp",b"styp")
                 and int.from_bytes(media[:4],"big")>=12)):
            raise ValueError("unverified media container")
        return media


def env_for_child():
    env={k:v for k,v in os.environ.items() if k.lower() not in (
        "http_proxy","https_proxy","all_proxy","no_proxy","ftp_proxy")}
    env["PATH"]="/dev/shm/awg-stage15/bin:/usr/bin:/bin"
    env["HOME"]="/dev/shm"
    env["TMPDIR"]="/dev/shm"
    env["XDG_CACHE_HOME"]="/dev/shm"
    return env


def limited_child():
    resource.setrlimit(resource.RLIMIT_FSIZE,(RANGE_CAP+4096,RANGE_CAP+4096))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_CPU,(20,20))


def subprocess_group(args,**kwargs):
    timeout=kwargs.pop("timeout",20)
    kwargs.pop("check",None)
    if kwargs.pop("start_new_session",False) is not True:
        raise ValueError("subprocess group required")
    proc=subprocess.Popen(args,start_new_session=True,**kwargs)
    try:
        out,err=proc.communicate(timeout=timeout)
        return types.SimpleNamespace(returncode=proc.returncode,
                                     stdout=out,stderr=err)
    except subprocess.TimeoutExpired:
        try:os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        proc.communicate()
        raise


def decode_reason(returncode,stderr):
    """ONLY fixed enum; never publish ffmpeg raw errors or URLs."""
    if returncode==0:
        return "youtube_no_decoded_frame"
    text=(stderr or b"")[:4096]
    if isinstance(text,bytes):
        text=text.decode("utf-8","replace")
    text=text.lower()
    if any(term in text for term in ("invalid data found","end of file",
                                     "moov atom not found","file ended prematurely",
                                     "truncat","partial file")):
        return "youtube_initial_fragment_incomplete"
    if "unsupported codec" in text or "decoder not found" in text:
        return "youtube_video_codec_unsupported"
    if "invalid argument" in text:
        return "youtube_video_invalid_container"
    return "youtube_video_decode_unverified"


def verify(port,*,executable=TARGET,ffmpeg="/usr/bin/ffmpeg",
           runner:Callable=subprocess_group,version_runner=subprocess.run,
           fetcher:Callable=fetch_range):
    if not(type(port) is int and 1<=port<=65535):
        return report("UNKNOWN","invalid_proxy_port")
    if not(Path(executable).is_file() and Path(ffmpeg).is_file()):
        return report("UNKNOWN","media_runtime_unavailable")
    node=shutil.which("node",path="/dev/shm/awg-stage15/bin")
    if not node:
        return report("UNKNOWN","node22_unavailable")
    try:
        v=version_runner([node,"--version"],capture_output=True,
                         text=True,timeout=2,check=False)
        if v.returncode!=0 or not re.fullmatch(r"v(2[2-9]|[3-9]\d)\.\d+\.\d+",v.stdout.strip()):
            return report("UNKNOWN","node22_unavailable")
        with tempfile.TemporaryDirectory(prefix="awg-stage17-range-",dir=RAM) as scratch:
            # Request the URL for *one video-only stream*. This is private and
            # short-lived, never written to disk, log or diagnostics.
            args=["/usr/bin/python3",str(executable),
                  "--ignore-config","--no-playlist","--no-progress","--no-warnings",
                  "--proxy","http://127.0.0.1:"+str(port),
                  "--force-ipv4","--js-runtimes","node","--no-cache-dir",
                  "--socket-timeout","5","--retries","0","--fragment-retries","0",
                  "--extractor-retries","0","--get-url",
                  "--format","bestvideo[height<=240]/bestvideo",VIDEO_URL]
            res=runner(args,cwd=scratch,env=env_for_child(),
                       stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL,timeout=22,check=False,
                       start_new_session=True,preexec_fn=limited_child)
            if res.returncode!=0:
                return report("UNKNOWN","youtube_metadata_or_extractor_unavailable")
            stdout=res.stdout
            if not isinstance(stdout,(str,bytes)):
                return report("UNKNOWN","youtube_media_url_unavailable")
            if isinstance(stdout,bytes):
                stdout=stdout.decode("utf-8","replace")
            if len(stdout)>MAX_METADATA_URL+1:
                return report("UNKNOWN","youtube_media_url_unavailable")
            urls=stdout.strip().splitlines()
            if len(urls)!=1 or not safe_media_url(urls[0]):
                return report("UNKNOWN","youtube_media_url_unavailable")
            try:
                media=fetcher(port,urls[0],cap=RANGE_CAP,timeout=12)
            except urllib.error.HTTPError as err:
                if err.code==403:
                    return report("UNKNOWN","youtube_media_http403")
                return report("UNKNOWN","youtube_media_http_unverified")
            except (urllib.error.URLError,TimeoutError,OSError):
                return report("UNKNOWN","youtube_media_connection_unavailable")
            except ValueError:
                return report("UNKNOWN","youtube_media_range_unverified")
            if not isinstance(media,bytes) or not 128<=len(media)<=RANGE_CAP:
                return report("UNKNOWN","youtube_media_range_unverified")
            ext=".webm" if media.startswith(FRAME_MAGIC) else ".mp4"
            target=Path(scratch)/("sample"+ext)
            with target.open("xb") as output:
                output.write(media)
            # Not even ffmpeg is permitted to open network protocols.
            decoder=runner([ffmpeg,"-v","error","-nostdin",
                            "-protocol_whitelist","file,pipe,crypto",
                            "-i",str(target),"-an","-frames:v",str(MIN_DECODED_FRAMES),
                            "-f","null","-progress","pipe:1","-"],
                           cwd=scratch,env=env_for_child(),
                           stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE,timeout=8,check=False,
                           start_new_session=True,preexec_fn=limited_child)
            progress=decoder.stdout
            if isinstance(progress,bytes):
                progress=progress.decode("ascii","replace")
            count=max([int(x) for x in re.findall(
                r"(?m)^frame=\s*(\d+)\s*$",progress)] or [0]) if isinstance(progress,str) else 0
            if decoder.returncode==0 and count>=MIN_DECODED_FRAMES:
                return report("PASS","youtube_24_video_frames_decoded")
            if decoder.returncode==0 and count<MIN_DECODED_FRAMES:
                return report("UNKNOWN","youtube_insufficient_decoded_frames")
            return report("UNKNOWN",decode_reason(decoder.returncode,decoder.stderr))
    except (OSError,ValueError,TypeError,subprocess.TimeoutExpired):
        return report("UNKNOWN","youtube_bounded_media_probe_unavailable")
