import hashlib
import io
import json
import urllib.error
import pytest
import workbench.updater as u


CONTENT = b'MZ' + bytes(range(256)) * 1024


def release():
    return dict(tag_name='v0.4.1', assets=[dict(id=123, name='OrderFollowup.exe', size=len(CONTENT),
        browser_download_url=f'https://github.com/{u.REPOSITORY}/releases/download/v0.4.1/OrderFollowup.exe',
        digest='sha256:' + hashlib.sha256(CONTENT).hexdigest())])


class Response(io.BytesIO):
    def __init__(self, data, status=200, headers=None, fail_after=None):
        super().__init__(data)
        self.status = status
        self.headers = headers or {}
        self.fail_after = fail_after

    def read1(self, count):
        if self.fail_after is not None and self.tell() >= self.fail_after:
            raise ConnectionResetError(10054, 'remote reset')
        return super().read(count)


@pytest.fixture
def download_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(u, 'data_dir', lambda: tmp_path)
    monkeypatch.setattr(u.time, 'sleep', lambda _: None)
    return tmp_path


def test_winerror10054_switches_official_endpoint_and_resumes(download_dir, monkeypatch):
    requests = []
    def open_url(req, **kwargs):
        requests.append(req)
        if len(requests) == 1:
            return Response(CONTENT, fail_after=65536)
        assert req.full_url == f'https://api.github.com/repos/{u.REPOSITORY}/releases/assets/123'
        assert req.get_header('Accept') == 'application/octet-stream'
        assert req.get_header('Range') == 'bytes=65536-'
        return Response(CONTENT[65536:], 206, {'Content-Range': f'bytes 65536-{len(CONTENT)-1}/{len(CONTENT)}'})
    monkeypatch.setattr(u.urllib.request, 'urlopen', open_url)
    messages = []
    target = u.download_release(release(), messages.append)
    assert target.read_bytes() == CONTENT
    assert len(requests) == 2 and any('重试' in m for m in messages)
    assert any('0.06 /' in m for m in messages)  # 首个 64 KB 即有进度，不再等到 1 MB。
    assert not target.with_suffix('.part').exists()
    logs = [json.loads(line) for line in u.log_path().read_text(encoding='utf-8').splitlines()]
    assert any(r.get('error', '').startswith('连接被重置') for r in logs)
    assert logs[-1]['stage'] == 'download_verified'


def test_failed_attempts_keep_progress_and_next_click_resumes(download_dir, monkeypatch):
    calls = []
    def fail(req, **kwargs):
        calls.append(req)
        if len(calls) == 1:
            return Response(CONTENT, fail_after=65536)
        raise TimeoutError('slow connection')
    monkeypatch.setattr(u.urllib.request, 'urlopen', fail)
    with pytest.raises(RuntimeError, match='保留下载进度'):
        u.download_release(release())
    assert len(calls) == u.DOWNLOAD_ATTEMPTS
    part = download_dir/'updates'/'v0.4.1'/'OrderFollowup.part'
    assert part.read_bytes() == CONTENT[:65536]
    def resume(req, **kwargs):
        assert req.get_header('Range') == 'bytes=65536-'
        return Response(CONTENT[65536:], 206, {'Content-Range': f'bytes 65536-{len(CONTENT)-1}/{len(CONTENT)}'})
    monkeypatch.setattr(u.urllib.request, 'urlopen', resume)
    assert u.download_release(release()).read_bytes() == CONTENT


def test_server_ignores_range_restart_does_not_duplicate_content(download_dir, monkeypatch):
    calls = []
    def open_url(req, **kwargs):
        calls.append(req)
        return Response(CONTENT, fail_after=65536) if len(calls) == 1 else Response(CONTENT)
    monkeypatch.setattr(u.urllib.request, 'urlopen', open_url)
    assert u.download_release(release()).read_bytes() == CONTENT
    assert calls[1].get_header('Range') == 'bytes=65536-'


def test_wrong_range_is_rejected_without_appending(download_dir, monkeypatch):
    calls = []
    def open_url(req, **kwargs):
        calls.append(req)
        if len(calls) == 1:
            return Response(CONTENT, fail_after=65536)
        return Response(b'bad data', 206, {'Content-Range': f'bytes 0-7/{len(CONTENT)}'})
    monkeypatch.setattr(u.urllib.request, 'urlopen', open_url)
    with pytest.raises(RuntimeError):
        u.download_release(release())
    assert (download_dir/'updates/v0.4.1/OrderFollowup.part').read_bytes() == CONTENT[:65536]
    assert not (download_dir/'updates/v0.4.1/OrderFollowup.exe').exists()


def test_checksum_failure_keeps_old_verified_file_and_discards_partial(download_dir, monkeypatch):
    target = download_dir/'updates/v0.4.1/OrderFollowup.exe'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'old verified file')
    monkeypatch.setattr(u.urllib.request, 'urlopen', lambda *a, **k: Response(b'X'*len(CONTENT)))
    with pytest.raises(ValueError, match='校验失败'):
        u.download_release(release())
    assert target.read_bytes() == b'old verified file'
    assert not target.with_suffix('.part').exists()


def test_fully_received_partial_is_verified_without_network(download_dir, monkeypatch):
    part = download_dir/'updates/v0.4.1/OrderFollowup.part'
    part.parent.mkdir(parents=True)
    part.write_bytes(CONTENT)
    a = release()['assets'][0]
    part.with_suffix('.part.json').write_text(json.dumps(dict(size=len(CONTENT), digest=a['digest'][7:], url=a['browser_download_url'])))
    monkeypatch.setattr(u.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('完整文件应该直接校验'))
    assert u.download_release(release()).read_bytes() == CONTENT


def test_short_read_resumes_and_foreign_asset_url_is_ignored(download_dir, monkeypatch):
    r = release()
    r['assets'][0]['url'] = 'https://foreign.example/credential-target'
    calls = []
    def open_url(req, **kwargs):
        calls.append(req.full_url)
        if len(calls) == 1:
            return Response(CONTENT[:100])
        assert req.get_header('Range') == 'bytes=100-'
        return Response(CONTENT[100:], 206, {'Content-Range': f'bytes 100-{len(CONTENT)-1}/{len(CONTENT)}'})
    monkeypatch.setattr(u.urllib.request, 'urlopen', open_url)
    assert u.download_release(r).read_bytes() == CONTENT
    assert not any('foreign.example' in url for url in calls)


def test_filesystem_failure_is_not_retried_as_network(download_dir, monkeypatch):
    target = download_dir/'updates/v0.4.1'
    target.mkdir(parents=True)
    # 目标 .part 是目录，模拟无法写入，不能报告网络故障或覆盖已安装程序。
    (target/'OrderFollowup.part').mkdir()
    monkeypatch.setattr(u.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('写入路径错误不应请求网络'))
    with pytest.raises(OSError):
        u.download_release(release())
