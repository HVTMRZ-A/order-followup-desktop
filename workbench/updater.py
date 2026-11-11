"""从固定公开仓库获取版本；SHA-256 校验后才允许替换程序。"""
import hashlib
import json
import os
import re
import subprocess
import sys
import ssl
import time
import http.client
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from . import REPOSITORY, VERSION
from .storage import data_dir

DOWNLOAD_ATTEMPTS = 4
NETWORK_ERRORS = (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError, http.client.HTTPException)


def log_path():
    return data_dir() / 'updates' / 'download-log.jsonl'


def log_update(stage, **fields):
    # 日志只记录阶段、字节数及错误类型，不记录订单、代理密码或临时签名 URL。
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(at=datetime.now().isoformat(timespec='seconds'),
                                         version=VERSION, stage=stage, **fields), ensure_ascii=False) + '\n')
    except OSError:
        pass  # 日志失败不改变下载和校验结果。


def network_error(exc):
    reason = getattr(exc, 'reason', exc)
    if isinstance(exc, urllib.error.HTTPError):
        return f'HTTP {exc.code}'
    code = getattr(reason, 'winerror', None) or getattr(reason, 'errno', None)
    if code in (10054, 104) or '10054' in str(reason):
        return '连接被重置（WinError 10054 / ConnectionReset）'
    if isinstance(reason, TimeoutError):
        return '连接或读取超时'
    if isinstance(reason, ssl.SSLError):
        return 'TLS 连接失败：' + type(reason).__name__
    return type(reason).__name__


def version_tuple(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise ValueError("版本号格式不正确，仅支持正式版本 x.y.z")
    return tuple(map(int, match.groups()))


def get_release():
    log_update('check_start')
    req = urllib.request.Request(f"https://api.github.com/repos/{REPOSITORY}/releases/latest", headers={"User-Agent": "OrderFollowupDesktop", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            release = json.load(response)
    except NETWORK_ERRORS as exc:
        log_update('check_failed', error=network_error(exc))
        raise
    if release.get("draft") or release.get("prerelease"):
        raise ValueError("更新源返回了非正式版本")
    version_tuple(release["tag_name"])
    log_update('check_ok', release=release['tag_name'])
    return release


def asset_info(release):
    asset = next((a for a in release.get("assets", []) if a["name"] == "OrderFollowup.exe"), None)
    if not asset:
        raise ValueError("该版本尚未上传 Windows 程序，请稍后重试")
    prefix = f"https://github.com/{REPOSITORY}/releases/download/"
    if not asset["browser_download_url"].startswith(prefix):
        raise ValueError("更新文件来源不匹配")
    digest = asset.get("digest", "") or ""
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        raise ValueError("更新文件缺少 SHA-256 校验信息，已停止更新")
    return asset


def download_release(release, progress=lambda message: None):
    asset = asset_info(release)
    version_tuple(release['tag_name'])
    size = asset.get('size')
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ValueError('更新文件大小无效，已停止更新')
    target = data_dir() / "updates" / release["tag_name"] / "OrderFollowup.exe"
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    expected = asset['digest'][7:].lower()
    metadata = partial.with_suffix('.part.json')
    identity = dict(size=size, digest=expected, url=asset['browser_download_url'])
    try:
        reusable = metadata.exists() and json.loads(metadata.read_text(encoding='utf-8')) == identity
    except (ValueError, OSError):
        reusable = False
    if not reusable or (partial.exists() and partial.stat().st_size > size):
        partial.unlink(missing_ok=True)
    metadata.write_text(json.dumps(identity), encoding='utf-8')
    endpoints = [('GitHub 下载入口', asset['browser_download_url'])]
    asset_id = asset.get('id')
    if isinstance(asset_id, int) and not isinstance(asset_id, bool) and asset_id > 0:
        endpoints.append(('GitHub 官方 API', f'https://api.github.com/repos/{REPOSITORY}/releases/assets/{asset_id}'))
    last_error = None
    for attempt in range(DOWNLOAD_ATTEMPTS):
        offset = partial.stat().st_size if partial.exists() else 0
        if offset == size:
            progress('下载完成，正在校验 SHA-256……')
            with partial.open('rb') as stream:
                complete_digest = hashlib.file_digest(stream, 'sha256').hexdigest().lower()
            if complete_digest == expected:
                partial.replace(target)
                metadata.unlink(missing_ok=True)
                log_update('download_verified', release=release['tag_name'], bytes=size)
                return target
            partial.unlink(missing_ok=True)
            metadata.unlink(missing_ok=True)
            log_update('checksum_failed', release=release['tag_name'])
            raise ValueError('下载文件校验失败，已丢弃损坏内容；现有程序未改变。请重新检查更新。')
        name, url = endpoints[attempt % len(endpoints)]
        headers = {'User-Agent': 'OrderFollowupDesktop', 'Accept': 'application/octet-stream', 'Accept-Encoding': 'identity'}
        if offset:
            headers['Range'] = f'bytes={offset}-'
        progress(f"正在连接{name}（第 {attempt+1}/{DOWNLOAD_ATTEMPTS} 次），已下载 {offset/1048576:.2f} / {size/1048576:.2f} MB……")
        log_update('download_connect', attempt=attempt+1, endpoint=name, bytes=offset)
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=20) as response:
                status = getattr(response, 'status', 200)
                if status == 206:
                    match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                    if not match or int(match[1]) != offset or int(match[3]) != size or not offset <= int(match[2]) < size:
                        raise http.client.HTTPException('续传范围不匹配')
                elif status == 200:
                    if offset:
                        progress('服务器不支持续传，本次从头重新下载……')
                    offset = 0
                else:
                    raise http.client.HTTPException('下载响应状态异常')
                received = offset
                last_emit = 0
                # read1 在收到当前可用数据时就返回，慢速链路不用等满 1 MB 才更新界面。
                read = getattr(response, 'read1', response.read)
                with partial.open('ab' if offset else 'wb') as stream:
                    while chunk := read(64 * 1024):
                        if received + len(chunk) > size:
                            raise ValueError('下载数据超出发布文件大小，已停止更新')
                        stream.write(chunk)
                        received += len(chunk)
                        now = time.monotonic()
                        if now - last_emit >= 0.25 or received == size:
                            progress(f'正在下载：{received/1048576:.2f} / {size/1048576:.2f} MB（{received*100/size:.1f}%）')
                            last_emit = now
                if received != size:
                    raise http.client.IncompleteRead(b'', size-received)
        except NETWORK_ERRORS as exc:
            last_error = network_error(exc)
            count = partial.stat().st_size if partial.exists() else 0
            log_update('download_interrupted', attempt=attempt+1, bytes=count, error=last_error)
            if attempt + 1 < DOWNLOAD_ATTEMPTS:
                progress(f'{last_error}，保留已下载内容，准备重试……')
                time.sleep(min(attempt+1, 3))
                continue
            break
        except ValueError:
            partial.unlink(missing_ok=True)
            metadata.unlink(missing_ok=True)
            log_update('download_invalid', attempt=attempt+1)
            raise
        # 传输成功后在本次请求内完成校验，不额外消耗重试次数。
        progress('下载完成，正在校验 SHA-256……')
        with partial.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest().lower()
        if digest != expected:
            partial.unlink(missing_ok=True)
            metadata.unlink(missing_ok=True)
            log_update('checksum_failed', release=release['tag_name'])
            raise ValueError('下载文件校验失败，已丢弃损坏内容；现有程序未改变。请重新检查更新。')
        partial.replace(target)
        metadata.unlink(missing_ok=True)
        log_update('download_verified', release=release['tag_name'], bytes=size)
        return target
    raise RuntimeError(f'更新下载失败：{last_error}。已尝试 {DOWNLOAD_ATTEMPTS} 次，保留下载进度；点击“检查新版本”可继续。详情见更新日志。')


def launch_replacement(source, target=None, wait_pid=None, restart_args=()):
    target = Path(target or sys.executable).resolve()
    source = Path(source).resolve()
    if source == target or not source.is_file():
        raise ValueError("更新路径无效")
    # 写入同目录暂存文件，先验证目标目录可写；不请求管理员权限。
    staged = target.with_name(target.stem + ".update.exe")
    import shutil
    shutil.copy2(source, staged)
    def ps_literal(value):
        return "'" + str(value).replace("'", "''") + "'"
    arguments = " -ArgumentList " + ps_literal(subprocess.list2cmdline(list(restart_args))) if restart_args else ""
    script = data_dir() / "updates" / "apply-update.ps1"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(f'''$ErrorActionPreference = 'Stop'
$target = {ps_literal(target)}
$source = {ps_literal(staged)}
$backup = {ps_literal(target.with_name(target.stem + '.previous.exe'))}
$log = {ps_literal(data_dir() / 'updates' / 'update-result.txt')}
$replaced = $false
try {{
    $process = Get-Process -Id {wait_pid if wait_pid is not None else os.getpid()} -ErrorAction SilentlyContinue
    if ($process) {{ $process.WaitForExit() }}
    $done = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {{
        try {{
            [System.IO.File]::Replace($source, $target, $backup, $true)
            $replaced = $true
            $done = $true
            break
        }} catch {{ Start-Sleep -Seconds 1 }}
    }}
    if (-not $done) {{ throw '无法替换程序；请关闭其他程序实例后重试。' }}
    Start-Process -FilePath $target -WorkingDirectory (Split-Path -Parent $target){arguments} -WindowStyle Normal
    '更新完成' | Set-Content -LiteralPath $log -Encoding UTF8
}} catch {{
    $errorMessage = $_.Exception.Message
    if ($replaced -and (Test-Path -LiteralPath $backup)) {{
        Copy-Item -LiteralPath $backup -Destination $target -Force -ErrorAction SilentlyContinue
    }}
    $errorMessage | Set-Content -LiteralPath $log -Encoding UTF8
    Start-Process -FilePath $target -WindowStyle Normal -ErrorAction SilentlyContinue
}}
''', encoding="utf-8-sig")
    environment = os.environ.copy()
    # 重启必须重新解压单文件包，不能沿用即将被旧进程清理的 _MEIPASS。
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    frozen_dir = str(getattr(sys, "_MEIPASS", ""))
    if frozen_dir:
        environment["PATH"] = os.pathsep.join(p for p in environment.get("PATH", "").split(os.pathsep) if not p.lower().startswith(frozen_dir.lower()))
        for key in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
            if frozen_dir.lower() in environment.get(key, "").lower():
                environment.pop(key, None)
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    try:
        return subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
    finally:
        if frozen_dir:
            ctypes.windll.kernel32.SetDllDirectoryW(frozen_dir)

