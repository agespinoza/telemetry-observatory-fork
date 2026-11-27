from types import SimpleNamespace

import host_sensor


def test_collect_skips_inaccessible_volume_and_process(monkeypatch):
    def disk_usage(path):
        if path == '/private':
            raise PermissionError()
        return SimpleNamespace(total=100, used=40, free=60, percent=40)

    class BadProcess:
        @property
        def info(self):
            raise host_sensor.psutil.AccessDenied()

    monkeypatch.setattr(host_sensor.psutil, 'disk_partitions', lambda all=False: [SimpleNamespace(mountpoint='/', device='disk1', fstype='apfs'), SimpleNamespace(mountpoint='/private', device='disk2', fstype='apfs')])
    monkeypatch.setattr(host_sensor.psutil, 'disk_usage', disk_usage)
    monkeypatch.setattr(host_sensor.psutil, 'process_iter', lambda fields: [BadProcess(), SimpleNamespace(info={'pid': 7, 'name': 'App', 'memory_info': SimpleNamespace(rss=1024), 'cpu_percent': 2})])
    monkeypatch.setattr(host_sensor.psutil, 'cpu_percent', lambda interval: 4)
    monkeypatch.setattr(host_sensor.psutil, 'virtual_memory', lambda: SimpleNamespace(_asdict=lambda: {'total': 100, 'used': 40, 'percent': 40}))
    monkeypatch.setattr(host_sensor.psutil, 'swap_memory', lambda: None)
    monkeypatch.setattr(host_sensor.psutil, 'disk_io_counters', lambda: None)
    monkeypatch.setattr(host_sensor.psutil, 'net_io_counters', lambda: None)
    result = host_sensor.collect()
    assert result['disks'][0]['mount'] == '/'
    assert len(result['disks']) == 1
    assert result['applications'][0]['pid'] == 7
