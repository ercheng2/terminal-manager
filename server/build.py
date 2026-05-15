# -*- coding: utf-8 -*-
"""
PyInstaller 打包配置 — 坤展成终端管理服务器端
"""

import os, sys, subprocess, shutil

BASE = os.path.dirname(os.path.abspath(__file__))

cmd = [
    sys.executable, '-m', 'PyInstaller',
    '--name', '坤展成终端管理-服务器',
    '--onefile',
    '--hidden-import', 'uvicorn.logging',
    '--hidden-import', 'uvicorn.loops',
    '--hidden-import', 'uvicorn.loops.auto',
    '--hidden-import', 'uvicorn.protocols',
    '--hidden-import', 'uvicorn.protocols.http',
    '--hidden-import', 'uvicorn.protocols.http.auto',
    '--hidden-import', 'uvicorn.protocols.websockets',
    '--hidden-import', 'uvicorn.protocols.websockets.auto',
    '--hidden-import', 'uvicorn.lifespan',
    '--hidden-import', 'uvicorn.lifespan.on',
    '--clean',
    os.path.join(BASE, 'main.py'),
]

print('=' * 60)
print('  开始打包 坤展成终端管理服务器 ...')
print('=' * 60)

result = subprocess.run(cmd, cwd=BASE)

if result.returncode != 0:
    print('[ERROR] 打包失败！')
    sys.exit(1)

print('[OK] 打包成功！')
print('输出目录:', os.path.join(BASE, 'dist'))
