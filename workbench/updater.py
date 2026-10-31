"""从固定公开仓库获取版本；SHA-256 校验后才允许替换程序。"""
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from . import REPOSITORY, VERSION
from .storage import data_dir


def version_tuple(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise ValueError("版本号格式不正确，仅支持正式版本 x.y.z")
    return tuple(map(int, match.groups()))


def get_release():
    req = urllib.request.Request(f"https://api.github.com/repos/{REPOSITORY}/releases/latest", headers={"User-Agent": "OrderFollowupDesktop", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=25) as response:
        release = json.load(response)
    if release.get("draft") or release.get("prerelease"):
        raise ValueError("更新源返回了非正式版本")
    version_tuple(release["tag_name"])
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
    target = data_dir() / "updates" / release["tag_name"] / "OrderFollowup.exe"
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    digest = hashlib.sha256()
    req = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "OrderFollowupDesktop"})
    try:
        with urllib.request.urlopen(req, timeout=45) as response, partial.open("wb") as stream:
            total = 0
            while chunk := response.read(1024 * 1024):
                stream.write(chunk); digest.update(chunk); total += len(chunk)
                progress(f"正在下载：{total / 1048576:.1f} / {asset['size'] / 1048576:.1f} MB")
        if total != asset["size"] or digest.hexdigest().lower() != asset["digest"][7:].lower():
            raise ValueError("下载文件校验失败，请重新检查更新")
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def launch_replacement(source, target=None, wait_pid=None):
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
    Start-Process -FilePath $target -WorkingDirectory (Split-Path -Parent $target) -WindowStyle Hidden
    '更新完成' | Set-Content -LiteralPath $log -Encoding UTF8
}} catch {{
    $errorMessage = $_.Exception.Message
    if ($replaced -and (Test-Path -LiteralPath $backup)) {{
        Copy-Item -LiteralPath $backup -Destination $target -Force -ErrorAction SilentlyContinue
    }}
    $errorMessage | Set-Content -LiteralPath $log -Encoding UTF8
    Start-Process -FilePath $target -WindowStyle Hidden -ErrorAction SilentlyContinue
}}
''', encoding="utf-8-sig")
    return subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], creationflags=subprocess.CREATE_NO_WINDOW)

