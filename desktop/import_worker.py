"""Bounded acquisition using installed yt-dlp; isolated network policy, no AI."""
import ipaddress
import json
import math
import os
from pathlib import Path
import shutil
import socket
import sys
import subprocess
import time
from urllib.parse import urlsplit, unquote
import urllib.request
import urllib.error
from story_director import atomic_json
from desktop.video_import import MAX_BYTES, MAX_SECONDS, RESERVE, EXTENSIONS


def safe_http(value):
    parts = urlsplit(value)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.port not in (None, 80, 443):
        raise ValueError('Only public web connections without credentials or custom ports are supported')


def validate_source(body):
    if not isinstance(body, dict) or body.get('kind') not in ('local', 'url'):
        raise ValueError('Choose a local file or video URL')
    value = body.get('source')
    if not isinstance(value, str) or not value.strip() or len(value) > 8192 or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid source')
    if body['kind'] == 'local':
        if not Path(value).is_absolute() or Path(value).suffix.lower() not in EXTENSIONS:
            raise ValueError('Choose MP4, MOV, MKV, WEBM, AVI or M4V video')
    else:
        if body.get("acknowledged") is not True:
            raise ValueError("Confirm that you have permission to download this video")
        safe_http(value)
        parts = urlsplit(value)
        if parts.scheme not in ('https', 'http') or not parts.hostname or parts.username or parts.password or parts.port not in (None, 80, 443):
            raise ValueError('Use a public HTTP(S) video URL without credentials or custom ports')
        host = parts.hostname.lower()
        platform = any(host == h or host.endswith('.' + h) for h in ('youtube.com', 'youtu.be', 'tiktok.com', 'instagram.com'))
        if not platform and Path(unquote(parts.path)).suffix.lower() not in EXTENSIONS:
            raise ValueError('Use a public YouTube, TikTok, Instagram or direct video-file link')
    return value.strip()


def public_ip(value):
    address = ipaddress.ip_address(value)
    if not address.is_global or address.is_reserved or address.is_multicast or (address.version == 6 and (address.ipv4_mapped or address.sixtofour or address.teredo or address in ipaddress.ip_network('64:ff9b::/96') or address in ipaddress.ip_network('64:ff9b:1::/48'))):
        raise ValueError('Private, local and internal network targets are blocked')


def install_network_guard():
    """Only in this child. Every DNS answer and actual connect is checked, including redirects."""
    resolve, connect, connect_ex = socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex
    def checked_dns(*args, **kwargs):
        answers = resolve(*args, **kwargs)
        if not answers:
            raise ValueError('Source host could not be resolved')
        for answer in answers:
            public_ip(answer[4][0])
        return answers
    def checked_connect(self, address):
        public_ip(address[0])  # refuse unresolved names at connect; DNS rebinding cannot escape
        return connect(self, address)
    def checked_connect_ex(self, address):
        public_ip(address[0])
        return connect_ex(self, address)
    socket.getaddrinfo = checked_dns
    socket.socket.connect, socket.socket.connect_ex = checked_connect, checked_connect_ex
    redirect = urllib.request.HTTPRedirectHandler.redirect_request
    def checked_redirect(self, req, fp, code, msg, headers, url):
        safe_http(url)
        return redirect(self, req, fp, code, msg, headers, url)
    urllib.request.HTTPRedirectHandler.redirect_request = checked_redirect


def javascript_runtimes():
    # Deno denies filesystem/network access unless explicitly granted. No remote scripts.
    from desktop.download_runtime import deno_path
    located=deno_path()
    return {'deno': {'path': located}} if located else {}


def import_error(error):
    """Fixed user-facing messages; never expose signed URLs, cookies or downloader logs."""
    text = str(error).lower()
    if 'unavailable' in text or 'private video' in text or 'removed' in text:
        return 'This video is unavailable or private. Check the link or choose another public video.'
    if 'sign in' in text or 'login' in text or 'bot' in text or 'age-restricted' in text:
        return 'The platform requires sign-in or verification for this video. Import a local copy you have permission to use.'
    if 'requested format' in text or 'no video formats' in text:
        return 'No supported public video download was offered. Try another public video or import a local file.'
    if '403' in text or 'forbidden' in text:
        return 'The platform refused the download. Retry later or import a local copy you have permission to use.'
    if isinstance(error, (TimeoutError, socket.timeout)) or 'timed out' in text:
        return 'The source timed out. Check your connection and retry.'
    if isinstance(error, urllib.error.URLError) or 'name resolution' in text:
        return 'The video host could not be reached. Check your connection and retry.'
    return 'Download failed. Check the public source availability and retry.'


def check_space(folder, extra=0):
    if shutil.disk_usage(folder).free < RESERVE + max(0, extra):
        raise ValueError('Insufficient storage: keep 2 GB free in the library')


def probe(path):
    if not path.is_file() or path.stat().st_size <= 0 or path.stat().st_size > MAX_BYTES:
        raise ValueError('Choose an existing, nonempty video below 2 GB')
    try:
        process = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-format_whitelist', 'mov,matroska,webm,avi,m4v', '-show_entries', 'stream=codec_type,codec_name,width,height,duration,avg_frame_rate:stream_disposition=attached_pic:format=duration', '-of', 'json', str(path)],
            capture_output=True, timeout=30, check=True)
        data = json.loads(process.stdout)
        stream = next(s for s in data['streams'] if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic'))
        duration = float(data.get('format', {}).get('duration') or stream.get('duration') or 0)
        if not math.isfinite(duration) or duration <= 0 or duration > MAX_SECONDS:
            raise ValueError('Video duration must be between zero and two hours')
        if stream.get('codec_name') not in ('h264', 'hevc', 'vp8', 'vp9', 'av1', 'mpeg4', 'mpeg2video', 'prores', 'mjpeg'):
            raise ValueError('This video codec is not supported')
        width, height = int(stream['width']), int(stream['height'])
        if width <= 0 or height <= 0 or width > 16384 or height > 16384:
            raise ValueError('Invalid video dimensions')
        from fractions import Fraction
        try: fps = float(Fraction(stream.get('avg_frame_rate', '0/1')))
        except (ValueError, ZeroDivisionError): fps = 0
        audio = next((s.get('codec_name', '') for s in data['streams'] if s.get('codec_type') == 'audio'), '')
        return dict(duration=duration, width=width, height=height, size=path.stat().st_size, mtime_ns=path.stat().st_mtime_ns, codec=stream['codec_name'], fps=fps if math.isfinite(fps) else 0, audio_codec=audio, format=path.suffix.lstrip('.').upper())
    except (subprocess.SubprocessError, KeyError, StopIteration, json.JSONDecodeError):
        raise ValueError('FFprobe could not validate a video stream in this file') from None


class ImportJob:
    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self.data = dict(state='validating', status='Validating source…', downloaded=0, total=None, title='Video source', platform='Local file')
        self.last_write = 0
    def update(self, **values):
        self.data.update(values)
        # Windows status readers can briefly deny replacement of the open file.
        # Retry only known transient Windows sharing/access errors; stay bounded.
        for attempt in range(8):
            try:
                atomic_json(str(self.folder / 'state.json'), self.data)
                break
            except PermissionError as error:
                if os.name != 'nt' or getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == 7:
                    raise
                time.sleep(.01 * 2 ** min(attempt, 4))
    def progress(self, downloaded, total=None):
        if downloaded > MAX_BYTES or (total and total > MAX_BYTES):
            raise ValueError('Source exceeds the 2 GB import limit')
        check_space(self.folder)
        if time.monotonic() - self.last_write >= .15:
            self.last_write = time.monotonic()
            self.update(state='downloading', status='Downloading source video…', downloaded=downloaded, total=total)
    def thumbnail(self, path):
        target = self.folder / 'preview.jpg'
        try:
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-protocol_whitelist', 'file,pipe', '-format_whitelist', 'mov,matroska,webm,avi,m4v', '-i', str(path), '-frames:v', '1', '-vf', 'scale=320:180:force_original_aspect_ratio=decrease', '-threads', '1', str(target)], capture_output=True, check=True, timeout=15)
            self.update(thumbnail=str(target))
        except (OSError, subprocess.SubprocessError):
            self.update(thumbnail_warning='Thumbnail unavailable')
    def local(self, source):
        path = Path(source).resolve(strict=True)
        self.update(title=path.name, state='validating', status='Validating video streams…')
        metadata = probe(path)
        # Preserve normal local originals; only long VLC paths need a short alias.
        if len(str(path)) >= 240:
            alias = self.folder / ('source' + path.suffix.lower())
            try:
                os.link(path, alias)
            except OSError:
                check_space(self.folder, metadata['size'])
                with path.open('rb') as incoming, alias.open('xb') as outgoing:
                    copied = 0
                    while block := incoming.read(1024**2):
                        outgoing.write(block); copied += len(block); self.progress(copied, metadata['size'])
                if alias.stat().st_size != metadata['size']:
                    raise ValueError('The selected file changed during import')
            if Path(source).stat().st_size != metadata['size'] or Path(source).stat().st_mtime_ns != metadata['mtime_ns']:
                raise ValueError('The selected file changed during import')
            path = alias
            metadata = probe(path)
        self.finish(path, metadata)
    def finish(self, path, metadata=None):
        self.update(state='validating_media', status='Validating imported media…')
        metadata = metadata or probe(path)
        self.thumbnail(path)
        if not path.is_file() or path.stat().st_size != metadata['size'] or path.stat().st_mtime_ns != metadata['mtime_ns']:
            raise ValueError('Source was removed or changed during import. Select it again')
        record = dict(import_id=self.folder.name, path=str(path), **metadata, **{k: self.data[k] for k in ('title', 'platform', 'thumbnail') if k in self.data})
        atomic_json(str(self.folder / 'manifest.json'), record)
        self.update(state='completed', status='Import completed. Ready for AI Clipper.', media=record, downloaded=metadata['size'], total=metadata['size'], **metadata)
    def direct(self, source):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.update(state='metadata', status='Fetching source information…', platform='Direct video', title=Path(unquote(urlsplit(source).path)).name[:160])
        try:
            with opener.open(urllib.request.Request(source, method='HEAD'), timeout=15) as response:
                total = int(response.headers.get('Content-Length') or 0) or None
                if total and total > MAX_BYTES:
                    raise ValueError('Source exceeds the 2 GB import limit')
                check_space(self.folder, total or 0)
        except urllib.error.HTTPError as error:
            if error.code not in (405, 501):
                raise
        self.update(state='preparing', status='Preparing download…')
        target = self.folder / ('source' + Path(unquote(urlsplit(source).path)).suffix.lower())
        temporary = target.with_suffix(target.suffix + '.part')
        for attempt in range(2):
            try:
                with opener.open(source, timeout=15) as response, temporary.open('wb') as output:
                    total = int(response.headers.get('Content-Length') or 0) or None
                    if total and total > MAX_BYTES:
                        raise ValueError('Source exceeds the 2 GB import limit')
                    check_space(self.folder, total or 0)
                    downloaded = 0
                    while block := response.read(256*1024):
                        downloaded += len(block); self.progress(downloaded, total); output.write(block)
                    if total and downloaded != total:
                        raise ValueError('Download ended before the complete file arrived')
                temporary.replace(target)
                break
            except (OSError, TimeoutError):
                temporary.unlink(missing_ok=True)
                if attempt:
                    raise
        self.finish(target)
    def platform(self, source):
        self.update(state="metadata", platform="Video platform", status="Fetching video metadata…")
        import yt_dlp
        from yt_dlp.networking import _urllib
        redirect = _urllib.RedirectHandler.redirect_request
        def guarded_redirect(handler, req, fp, code, msg, headers, url):
            safe_http(url)
            return redirect(handler, req, fp, code, msg, headers, url)
        _urllib.RedirectHandler.redirect_request = guarded_redirect
        from yt_clients import fallback_extractor_args, youtube_non_video_reason
        if youtube_non_video_reason(source):
            raise ValueError('Use one video, not a playlist, channel or search page')
        class Quiet:
            def debug(self, *a): pass
            def info(self, *a): pass
            def warning(self, *a): pass
            def error(self, *a): pass
        completed_bytes = 0
        selected_total = None
        def hook(data):
            if data.get('status') == 'downloading':
                self.progress(completed_bytes + int(data.get('downloaded_bytes') or 0), selected_total)

        opts = dict(quiet=True, logger=Quiet(), no_warnings=True, proxy='', cachedir=False, noplaylist=True,
            socket_timeout=15, retries=2, fragment_retries=2, max_filesize=MAX_BYTES,
            outtmpl=str(self.folder / 'source.%(ext)s'), restrictfilenames=True, overwrites=False,
            format='bestvideo[protocol=https][ext=mp4][height<=1080]+bestaudio[protocol=https][ext=m4a]/best[protocol=https][ext=mp4]/bestvideo[protocol=https][ext=webm][height<=1080]+bestaudio[protocol=https][ext=webm]/best[protocol=https][ext=webm]/best[protocol=http][ext=mp4]', fixup='never', postprocessors=[],
            progress_hooks=[hook], extractor_args=fallback_extractor_args('', ''), js_runtimes=javascript_runtimes(), remote_components=set())
        self.update(state='metadata', status='Fetching video metadata…')
        with yt_dlp.YoutubeDL(opts) as ydl:
            # Only Python's guarded urllib transport: no native curl, external downloaders or JS network clients.
            director = ydl._request_director
            director.handlers = {k: v for k, v in director.handlers.items() if type(v).__name__ == 'UrllibRH'}
            if not director.handlers:
                raise ValueError('Installed downloader has no supported safe transport')
            info = ydl.extract_info(source, download=False)
            if not info or info.get('_type', 'video') != 'video' or info.get('is_live') or info.get('has_drm'):
                raise ValueError('Use a public, non-live, unprotected single video')
            duration = float(info.get('duration') or 0)
            formats = info.get('requested_formats') or [info]
            if len(formats) not in (1, 2) or any(f.get('protocol') not in ('http', 'https') or f.get('ext') not in ('mp4', 'm4a', 'webm') for f in formats):
                raise ValueError('No supported public video streams were offered. Import a local video instead')
            if len(formats) == 2 and (formats[0].get('vcodec') in (None, 'none') or formats[1].get('acodec') in (None, 'none')):
                raise ValueError('The platform did not offer a valid video and audio pair')
            selected_total = sum(f['filesize'] for f in formats) if all(f.get('filesize') for f in formats) else None
            size = sum(f.get('filesize') or f.get('filesize_approx') or 0 for f in formats)
            if not math.isfinite(duration) or duration <= 0 or duration > MAX_SECONDS or (size and size > MAX_BYTES):
                raise ValueError('Video exceeds the size or duration limit')
            check_space(self.folder, size or 0)
            self.update(title=str(info.get('title') or 'Video')[:200], duration=duration, width=info.get('width'), height=info.get('height'),
                        platform=info.get('extractor_key', 'Video platform'), state='preparing', status='Preparing download…', total=selected_total)
            if info.get('thumbnail'):
                try:
                    from PIL import Image
                    import io
                    with ydl.urlopen(info['thumbnail']) as response:
                        content = response.read(2*1024**2+1)
                    if len(content) > 2*1024**2:
                        raise ValueError()
                    with Image.open(io.BytesIO(content)) as image:
                        if image.width*image.height > 16_000_000:
                            raise ValueError()
                        image.thumbnail((320,180)); image.convert('RGB').save(self.folder / 'preview.jpg')
                    self.update(thumbnail=str(self.folder / 'preview.jpg'))
                except Exception:
                    self.update(thumbnail_warning='Remote thumbnail unavailable')
            if len(formats) == 1:
                ydl.process_info(info)
                target = self.folder / ('source.' + info['ext'])
            else:
                # Download HTTP streams independently. FFmpeg only sees local files, never remote URLs.
                ydl.params['outtmpl']['default'] = str(self.folder / 'source.%(format_id)s.%(ext)s')
                streams = []
                for number, format_info in enumerate(formats):
                    item = {k: v for k, v in info.items() if k not in ('requested_formats', 'requested_downloads', '__postprocessors', '__files_to_move')}
                    item.update(format_info)
                    item['format_id'] = str(number)
                    target_stream = Path(ydl.prepare_filename(item))
                    ydl.process_info(item)
                    if not target_stream.is_file():
                        raise ValueError('A video stream download did not complete')
                    completed_bytes += target_stream.stat().st_size
                    if completed_bytes > MAX_BYTES:
                        raise ValueError('Source exceeds the 2 GB import limit')
                    streams.append(target_stream)
                probe(streams[0])
                check_space(self.folder, completed_bytes)
                self.update(state='merging', status='Combining downloaded video and audio…', downloaded=completed_bytes, total=None)
                target = self.folder / 'source.mp4'
                args = ['ffmpeg', '-nostdin', '-v', 'error', '-y']
                for stream in streams:
                    args += ['-protocol_whitelist', 'file,pipe', '-format_whitelist', 'mov,matroska,webm', '-i', str(stream)]
                args += ['-map', '0:v:0', '-map', '1:a:0', '-c', 'copy', '-movflags', '+faststart', str(target)]
                try:
                    subprocess.run(args, capture_output=True, check=True, timeout=120)
                except (OSError, subprocess.SubprocessError):
                    raise ValueError('The downloaded video and audio could not be combined. Retry or import a local file') from None
                for stream in streams:
                    stream.unlink(missing_ok=True)
        if not target.is_file():
            raise ValueError('Downloader did not produce a complete supported video')
        self.finish(target)


def run(folder):
    job = ImportJob(folder)
    try:
        body = json.loads((job.folder / 'request.json').read_text('utf-8'))
        source = validate_source(body)
        check_space(job.folder)
        if body['kind'] == 'local':
            job.local(source)
        else:
            install_network_guard()
            from security_utils import assert_public_url
            assert_public_url(source)
            if Path(unquote(urlsplit(source).path)).suffix.lower() in EXTENSIONS:
                job.direct(source)
            else:
                job.platform(source)
    except (ValueError, PermissionError, FileNotFoundError) as error:
        # Never persist URLs, signed query parameters, cookies or downloader exception strings.
        safe = str(error) if isinstance(error, ValueError) else 'File missing or access denied. Select it again.'
        if 'http' in safe.lower() or len(safe) > 220:
            safe = 'The video could not be imported. Check permissions, limits and source availability.'
        job.update(state='failed', status=safe)
    except Exception as error:
        job.update(state='failed', status=import_error(error), error_code=type(error).__name__)
    finally:
        (job.folder / 'request.json').unlink(missing_ok=True)
