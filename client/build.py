# -*- coding: utf-8 -*-
"""
PyInstaller 打包配置 — 坤展成终端管理客户端
"""

import os, sys, subprocess, shutil

BASE = os.path.dirname(os.path.abspath(__file__))

cmd = [
    sys.executable, '-m', 'PyInstaller',
    '--name', '坤展成终端管理',
    '--onefile',
    '--hidden-import', 'pycaw',
    '--hidden-import', 'comtypes',
    '--hidden-import', 'websockets',
    '--hidden-import', 'pystray',
    '--hidden-import', 'PIL',
    '--hidden-import', 'psutil',
    '--clean',
    os.path.join(BASE, 'main.py'),
]

print('=' * 60)
print('  开始打包 坤展成终端管理客户端 ...')
print('=' * 60)

result = subprocess.run(cmd, cwd=BASE)

if result.returncode != 0:
    print('[ERROR] 打包失败！')
    sys.exit(1)

print('[OK] 打包成功！')
print('输出目录:', os.path.join(BASE, 'dist'))
