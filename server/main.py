#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
坤展成终端管理系统 — 服务器端 v1.4.0
基于HTTP轮询通信，更稳定可靠
支持tkinter桌面GUI + 文件传输功能
v1.4.0: 添加远程桌面控制功能
"""

import os, sys, json, time, datetime, uuid, threading, io, queue, struct
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import shutil
import urllib.request
import urllib.error
from PIL import Image, ImageTk

def resource_path(relative_path):
    """获取资源文件绝对路径（兼容PyInstaller打包）"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --windowed打包后print会报错，重定向到日志文件
if getattr(sys, 'frozen', False):
    _log_path = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), 'server.log')
    sys.stdout = open(_log_path, 'a', encoding='utf-8')
    sys.stderr = sys.stdout

# ===== 路径适配 =====
if getattr(sys, 'frozen', False):
    _APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))

BASE_DIR = _APP_DIR
DB_FILE = os.path.join(BASE_DIR, 'devices.json')
UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads')

# 设备别名存储
_device_alias = {}  # client_id -> 自定义名称
_ALIAS_FILE = os.path.join(BASE_DIR, 'device_alias.json')

def _load_device_alias():
    """加载设备别名"""
    global _device_alias
    try:
        if os.path.exists(_ALIAS_FILE):
            with open(_ALIAS_FILE, 'r', encoding='utf-8') as f:
                _device_alias = json.load(f)
    except:
        _device_alias = {}

def _save_device_alias():
    """保存设备别名"""
    try:
        with open(_ALIAS_FILE, 'w', encoding='utf-8') as f:
            json.dump(_device_alias, f, ensure_ascii=False, indent=2)
    except:
        pass

# 确保上传目录存在
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ===== 数据存储 =====
def load_devices():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"clients": {}, "commands": {}}

def save_devices(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ===== FastAPI =====
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title='坤展成终端管理系统')

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory="static"), name="static")

# 内存中的数据
_clients = {}  # client_id -> client_info
_commands = {}  # task_id -> command_info
_file_transfers = {}  # task_id -> transfer_info
_file_name_map = {}  # uuid_name -> original_name（解决中文文件名编码问题）

# 加载持久化数据
def _load_persistent():
    data = load_devices()
    for cid, info in data.get('clients', {}).items():
        _clients[cid] = {
            **info,
            'last_seen': datetime.datetime.strptime(info.get('last_seen', ''), '%Y-%m-%d %H:%M:%S') if info.get('last_seen') else datetime.datetime.now(),
        }
    for tid, cmd in data.get('commands', {}).items():
        _commands[tid] = cmd

_load_persistent()

def _save_persistent():
    data = {
        'clients': {},
        'commands': {},
    }
    for cid, info in _clients.items():
        data['clients'][cid] = {
            'hostname': info.get('hostname', ''),
            'os': info.get('os', ''),
            'os_version': info.get('os_version', ''),
            'ip': info.get('ip', ''),
            'mac': info.get('mac', ''),
            'arch': info.get('arch', ''),
            'cpu': info.get('cpu', ''),
            'cpu_percent': info.get('cpu_percent', 0),
            'memory_percent': info.get('memory_percent', 0),
            'disk_percent': info.get('disk_percent', 0),
            'first_seen': info.get('first_seen', ''),
            'last_seen': info['last_seen'].strftime('%Y-%m-%d %H:%M:%S') if isinstance(info['last_seen'], datetime.datetime) else info.get('last_seen', ''),
        }
    for tid, cmd in _commands.items():
        data['commands'][tid] = cmd
    save_devices(data)


# ===== UDP广播 =====
import socket

BROADCAST_PORT = 15080

def _get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '127.0.0.1'

def _broadcast_server():
    """每3秒向局域网广播服务器信息"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    local_ip = _get_local_ip()
    msg = json.dumps({
        'type': 'kzc_server',
        'ip': local_ip,
        'port': 8080,
    }).encode('utf-8')
    while True:
        try:
            sock.sendto(msg, ('255.255.255.255', BROADCAST_PORT))
            sock.sendto(msg, ('<broadcast>', BROADCAST_PORT))
        except:
            pass
        time.sleep(3)


# ===== API路由 =====
@app.get('/')
async def index():
    return HTMLResponse(MANAGER_HTML)

@app.get('/api/devices')
async def get_devices():
    """获取设备列表"""
    result = []
    now = datetime.datetime.now()
    for cid, info in _clients.items():
        last_seen = info.get('last_seen')
        if isinstance(last_seen, str):
            try:
                last_seen = datetime.datetime.strptime(last_seen, '%Y-%m-%d %H:%M:%S')
            except:
                last_seen = now - datetime.timedelta(days=1)
        online = (now - last_seen).total_seconds() < 10  # 10秒内在线
        result.append({
            'id': cid,
            'hostname': info.get('hostname', ''),
            'os': info.get('os', ''),
            'os_version': info.get('os_version', ''),
            'ip': info.get('ip', ''),
            'mac': info.get('mac', ''),
            'arch': info.get('arch', ''),
            'cpu': info.get('cpu', ''),
            'cpu_percent': info.get('cpu_percent', 0),
            'memory_percent': info.get('memory_percent', 0),
            'disk_percent': info.get('disk_percent', 0),
            'status': 'online' if online else 'offline',
            'last_seen': info['last_seen'].strftime('%Y-%m-%d %H:%M:%S') if isinstance(info['last_seen'], datetime.datetime) else str(info.get('last_seen', '')),
            'first_seen': info.get('first_seen', ''),
        })
    return {'devices': result}

@app.get('/api/commands')
async def get_commands():
    """获取指令日志"""
    result = []
    for tid, cmd in _commands.items():
        result.append({
            'id': tid,
            'cmd': cmd.get('cmd', ''),
            'target_hostname': cmd.get('target_hostname', ''),
            'target_id': cmd.get('target_id', ''),
            'time': cmd.get('time', ''),
            'status': cmd.get('status', 'pending'),
            'response': cmd.get('response', ''),
        })
    result.sort(key=lambda x: x['time'], reverse=True)
    return {'logs': result[:100]}  # 只返回最近100条

@app.post('/api/command')
async def send_command(request: Request):
    """发送指令"""
    body = await request.json()
    target_ids = body.get('target_ids', [])  # client_id列表
    cmd = body.get('cmd', '')
    extra = body.get('extra', {})

    if not target_ids:
        target_ids = list(_clients.keys())

    results = {}
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for target_id in target_ids:
        if target_id not in _clients:
            results[target_id] = 'offline'
            continue
        task_id = uuid.uuid4().hex[:8]
        command = {
            'id': task_id,
            'cmd': cmd,
            'extra': extra,
            'target_id': target_id,
            'target_hostname': _clients[target_id].get('hostname', ''),
            'time': now,
            'status': 'pending',
            'response': '',
        }
        _commands[task_id] = command
        results[target_id] = task_id

    _save_persistent()
    return {'task_ids': results}

@app.post('/api/client/register')
async def client_register(request: Request):
    """客户端注册"""
    try:
        data = await request.json()
        hostname = data.get('hostname', '')
        ip = data.get('ip', '')
        mac = data.get('mac', '')

        # 生成或查找client_id
        client_id = None
        for cid, info in _clients.items():
            if info.get('hostname') == hostname and info.get('mac') == mac:
                client_id = cid
                break

        if not client_id:
            client_id = uuid.uuid4().hex[:12]
            # 新客户端，创建完整记录
            _clients[client_id] = {
                'hostname': hostname,
                'os': data.get('os', ''),
                'os_version': data.get('os_version', ''),
                'ip': ip,
                'mac': mac,
                'arch': data.get('arch', ''),
                'cpu': data.get('cpu', ''),
                'cpu_percent': data.get('cpu_percent', 0),
                'memory_percent': data.get('memory_percent', 0),
                'disk_percent': data.get('disk_percent', 0),
                'first_seen': data.get('first_seen', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                'last_seen': datetime.datetime.now(),
            }
        else:
            # 已存在的客户端，只更新时间、IP和系统状态，不覆盖其他字段
            _clients[client_id]['last_seen'] = datetime.datetime.now()
            _clients[client_id]['ip'] = ip
            # 更新系统状态
            if data.get('cpu_percent') is not None:
                try:
                    _clients[client_id]['cpu_percent'] = float(data['cpu_percent'])
                except:
                    pass
            if data.get('memory_percent') is not None:
                try:
                    _clients[client_id]['memory_percent'] = float(data['memory_percent'])
                except:
                    pass
            if data.get('disk_percent') is not None:
                try:
                    _clients[client_id]['disk_percent'] = float(data['disk_percent'])
                except:
                    pass
            print(f'[注册] 更新客户端 {client_id}: cpu={data.get("cpu_percent")}, mem={data.get("memory_percent")}, disk={data.get("disk_percent")}')

        _save_persistent()
        return {'client_id': client_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get('/api/client/poll')
async def client_poll_get(client_id: str, cpu_percent: float = 0, memory_percent: float = 0, disk_percent: float = 0, ip: str = ''):
    """客户端轮询指令（GET方式，兼容旧客户端）"""
    # 轮询日志频率高，只在状态变化时打印
    # print(f'[轮询-GET] client_id={client_id}, cpu={cpu_percent}, mem={memory_percent}, disk={disk_percent}')
    return await _client_poll_impl(client_id, cpu_percent, memory_percent, disk_percent, ip)

@app.post('/api/client/poll')
async def client_poll_post(request: Request):
    """客户端轮询指令 + 上报系统状态（POST方式）"""
    try:
        data = await request.json()
        client_id = data.get('client_id', '')
        cpu_percent = data.get('cpu_percent', 0)
        memory_percent = data.get('memory_percent', 0)
        disk_percent = data.get('disk_percent', 0)
        ip = data.get('ip', '')
        # print(f'[轮询-POST] client_id={client_id}, cpu={cpu_percent}, mem={memory_percent}, disk={disk_percent}')
        return await _client_poll_impl(client_id, cpu_percent, memory_percent, disk_percent, ip)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

async def _client_poll_impl(client_id, cpu_percent, memory_percent, disk_percent, ip):
    """轮询指令的内部实现"""
    if client_id not in _clients:
        raise HTTPException(status_code=400, detail='未注册')
    
    # 更新最后在线时间
    _clients[client_id]['last_seen'] = datetime.datetime.now()
    
    # 更新系统状态
    updated = []
    if cpu_percent:
        try:
            _clients[client_id]['cpu_percent'] = float(cpu_percent)
            updated.append(f'cpu={cpu_percent}')
        except:
            pass
    if memory_percent:
        try:
            _clients[client_id]['memory_percent'] = float(memory_percent)
            updated.append(f'mem={memory_percent}')
        except:
            pass
    if disk_percent:
        try:
            _clients[client_id]['disk_percent'] = float(disk_percent)
            updated.append(f'disk={disk_percent}')
        except:
            pass
    if ip:
        _clients[client_id]['ip'] = ip
    
    if updated:
        print(f'[轮询] 更新 {client_id}: {", ".join(updated)}')
    
    # 获取该客户端的待处理指令
    commands = []
    for tid, cmd in _commands.items():
        if cmd.get('target_id') == client_id and cmd.get('status') == 'pending':
            commands.append(cmd)
    
    return {'client_id': client_id, 'commands': commands}

@app.post('/api/client/status')
async def client_status(request: Request):
    """客户端上报系统状态（POST方式，更可靠）"""
    try:
        data = await request.json()
        client_id = data.get('client_id', '')
        if client_id not in _clients:
            raise HTTPException(status_code=400, detail='未注册')
        _clients[client_id]['last_seen'] = datetime.datetime.now()
        if 'cpu_percent' in data:
            _clients[client_id]['cpu_percent'] = float(data['cpu_percent'])
        if 'memory_percent' in data:
            _clients[client_id]['memory_percent'] = float(data['memory_percent'])
        if 'disk_percent' in data:
            _clients[client_id]['disk_percent'] = float(data['disk_percent'])
        if data.get('ip'):
            _clients[client_id]['ip'] = data['ip']
        return {'success': True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post('/api/client/result')
async def client_result(request: Request):
    """客户端上报执行结果"""
    try:
        data = await request.json()
        client_id = data.get('client_id', '')
        task_id = data.get('task_id', '')
        status = data.get('status', 'unknown')
        msg = data.get('response', data.get('msg', ''))

        if task_id in _commands:
            _commands[task_id]['status'] = status
            _commands[task_id]['response'] = msg

        _save_persistent()
        return {'success': True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ===== 文件下载API =====
@app.get('/api/file/{filename:path}')
async def download_file(filename: str):
    """提供文件下载（流式传输，支持大文件，支持中文文件名）"""
    import urllib.parse
    # URL解码（支持中文文件名）
    filename = urllib.parse.unquote(filename)
    # 安全检查：禁止路径穿越
    filename = os.path.basename(filename)
    
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail='文件不存在')
    
    def iter_file():
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(65536)  # 64KB chunks
                if not chunk:
                    break
                yield chunk
    
    file_size = os.path.getsize(file_path)
    # RFC 5987编码，支持中文文件名
    encoded_filename = urllib.parse.quote(filename)
    return StreamingResponse(
        iter_file(),
        media_type='application/octet-stream',
        headers={
            'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}",
            'Content-Length': str(file_size),
        }
    )

@app.post('/api/file/download')
async def download_file_post(request: Request):
    """POST方式下载文件（更可靠，支持中文文件名）"""
    import urllib.parse
    try:
        data = await request.json()
        # 优先用server_file_name（UUID文件名）查找，回退到file_name
        server_file_name = data.get('server_file_name', '')
        file_name = data.get('file_name', '')
        
        # 先用server_file_name（UUID文件名）查找
        actual_name = server_file_name if server_file_name else file_name
        actual_name = os.path.basename(actual_name)
        
        file_path = os.path.join(UPLOAD_DIR, actual_name)
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f'文件不存在: {actual_name}')
        
        def iter_file():
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk
        
        file_size = os.path.getsize(file_path)
        # 用原始文件名作为下载文件名
        original_name = _file_name_map.get(actual_name, actual_name)
        encoded_filename = urllib.parse.quote(original_name)
        return StreamingResponse(
            iter_file(),
            media_type='application/octet-stream',
            headers={
                'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}",
                'Content-Length': str(file_size),
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ===== 文件上传API =====
@app.post("/api/file/upload")
async def upload_file(request: Request):
    """文件上传接口（支持大文件）"""
    try:
        import uuid as _uuid
        form = await request.form()
        file = form.get("file")
        if not file:
            raise HTTPException(status_code=400, detail="未上传文件")
        
        # 获取原始文件名
        original_name = file.filename or "unknown"
        ext = os.path.splitext(original_name)[1]
        # 生成UUID文件名避免中文和特殊字符问题
        uuid_name = f'{_uuid.uuid4().hex[:12]}{ext}'
        
        # 保存到uploads目录
        file_path = os.path.join(UPLOAD_DIR, uuid_name)
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        # 保存文件名映射
        _file_name_map[uuid_name] = original_name
        
        return {
            "success": True,
            "server_file_name": uuid_name,
            "original_name": original_name,
            "file_size": len(content)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===== 管理界面HTML =====
MANAGER_HTML = '''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>坤展成终端管理系统</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: "Microsoft YaHei", Arial, sans-serif; background: #f5f6fa; }
.header { background: #2c3e50; color: white; padding: 15px 30px; }
.header h1 { font-size: 20px; }
.header span { font-size: 12px; color: #bdc3c7; }
.container { max-width: 1200px; margin: 20px auto; padding: 0 20px; }
.card { background: white; border-radius: 10px; padding: 20px; margin-bottom: 15px; box-shadow: 0 2px 10px rgba(0,0,0,0.08); }
.stats { display: flex; gap: 15px; margin-bottom: 15px; }
.stat-box { flex: 1; padding: 15px; border-radius: 8px; text-align: center; color: white; }
.stat-box.online { background: #27ae60; }
.stat-box.offline { background: #e74c3c; }
.stat-box.total { background: #3498db; }
.stat-box .num { font-size: 28px; font-weight: bold; }
.stat-box .label { font-size: 12px; opacity: 0.9; }
.toolbar { display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; }
.btn { padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600; }
.btn-danger { background: #e74c3c; color: white; }
.btn-warning { background: #f39c12; color: white; }
.btn-success { background: #27ae60; color: white; }
.btn-primary { background: #3498db; color: white; }
.btn:hover { opacity: 0.85; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #eee; font-size: 13px; }
th { background: #f8f9fa; font-weight: 600; color: #555; }
.status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 5px; }
.status-dot.online { background: #27ae60; }
.status-dot.offline { background: #e74c3c; }
input[type="checkbox"] { width: 16px; height: 16px; cursor: pointer; }
.log-area { max-height: 300px; overflow-y: auto; }
.refresh-btn { float: right; }
select, input[type="text"] { padding: 6px 10px; border: 1px solid #ddd; border-radius: 4px; font-size: 13px; }
</style>
</head>
<body>
<div class="header">
    <h1>坤展成终端管理系统</h1>
    <span>北京万乘兄弟科技有限公司</span>
</div>
<div class="container">
    <div class="stats" id="stats">
        <div class="stat-box online"><div class="num" id="onlineCount">0</div><div class="label">在线设备</div></div>
        <div class="stat-box offline"><div class="num" id="offlineCount">0</div><div class="label">离线设备</div></div>
        <div class="stat-box total"><div class="num" id="totalCount">0</div><div class="label">设备总数</div></div>
    </div>

    <div class="card">
        <h3 style="margin-bottom:10px">设备列表 <button class="btn btn-primary refresh-btn" onclick="refresh()">刷新</button></h3>
        <div class="toolbar">
            <button class="btn btn-danger" onclick="sendCmd('shutdown')">批量关机</button>
            <button class="btn btn-warning" onclick="sendCmd('restart')">批量重启</button>
            <button class="btn btn-success" onclick="sendCmd('cancel')">取消关机</button>
            <button class="btn btn-primary" onclick="sendCmd('volume:up')">音量+</button>
            <button class="btn btn-primary" onclick="sendCmd('volume:down')">音量-</button>
            <button class="btn btn-primary" onclick="sendCmd('mute')">静音</button>
            <button class="btn btn-primary" onclick="sendCmd('unmute')">取消静音</button>
            <button class="btn btn-primary" onclick="sendCmd('status')">查询状态</button>
        </div>
        <table>
            <thead><tr>
                <th><input type="checkbox" id="selectAll" onchange="toggleAll()"></th>
                <th>状态</th><th>主机名</th><th>IP</th><th>系统</th><th>架构</th><th>CPU</th><th>内存</th><th>最后在线</th><th>操作</th>
            </tr></thead>
            <tbody id="deviceTable"></tbody>
        </table>
    </div>

    <div class="card">
        <h3 style="margin-bottom:10px">指令日志</h3>
        <div class="log-area">
            <table>
                <thead><tr><th>时间</th><th>指令</th><th>目标</th><th>状态</th><th>响应</th></tr></thead>
                <tbody id="logTable"></tbody>
            </table>
        </div>
    </div>
</div>

<script>
let devices = [];
let selectedIds = [];

function refresh() {
    fetch('/api/devices').then(r=>r.json()).then(data => {
        devices = data.devices || [];
        renderDevices();
    });
    fetch('/api/commands').then(r=>r.json()).then(data => {
        const logs = (data.logs || []).reverse();
        renderLogs(logs);
    });
}

function renderDevices() {
    let html = '', online = 0, offline = 0;
    devices.forEach(d => {
        const isOnline = d.status === 'online';
        if (isOnline) online++; else offline++;
        html += '<tr><td><input type="checkbox" class="dev-check" value="'+d.id+'" onchange="updateSelection()" '+(isOnline?'':'disabled')+'></td>';
        html += '<td><span class="status-dot '+(isOnline?'online':'offline')+'"></span>'+(isOnline?'在线':'离线')+'</td>';
        html += '<td>'+d.hostname+'</td>';
        html += '<td>'+d.ip+'</td>';
        html += '<td>'+d.os+' '+d.os_version+'</td>';
        html += '<td>'+d.arch+'</td>';
        html += '<td>'+d.cpu_percent+'%</td>';
        html += '<td>'+d.memory_percent+'%</td>';
        html += '<td>'+d.last_seen+'</td>';
        html += '<td>'+(isOnline?'<button class="btn btn-primary" onclick="sendCmdSingle(\\''+d.id+'\\',\\'status\\')">状态</button>':'-')+'</td></tr>';
    });
    document.getElementById('deviceTable').innerHTML = html;
    document.getElementById('onlineCount').textContent = online;
    document.getElementById('offlineCount').textContent = offline;
    document.getElementById('totalCount').textContent = online + offline;
}

function renderLogs(logs) {
    let html = '';
    logs.forEach(l => {
        const statusColor = l.status==='success'?'#27ae60':l.status==='failed'?'#e74c3c':'#f39c12';
        html += '<tr><td>'+(l.time||'-')+'</td><td>'+(l.cmd||'-')+'</td>';
        html += '<td>'+(l.target_hostname||l.target_id||'-')+'</td>';
        html += '<td style="color:'+statusColor+'">'+(l.status||'-')+'</td>';
        html += '<td>'+(l.response||'-')+'</td></tr>';
    });
    document.getElementById('logTable').innerHTML = html;
}

function toggleAll() {
    const checked = document.getElementById('selectAll').checked;
    document.querySelectorAll('.dev-check').forEach(c => { if (!c.disabled) c.checked = checked; });
    updateSelection();
}

function updateSelection() {
    selectedIds = [];
    document.querySelectorAll('.dev-check:checked').forEach(c => selectedIds.push(c.value));
}

function sendCmd(cmd) {
    if (selectedIds.length === 0) { alert('请选择设备'); return; }
    fetch('/api/command', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({target_ids: selectedIds, cmd: cmd})
    }).then(r=>r.json()).then(data => {
        alert('指令已发送：' + cmd + '\\n任务ID：' + JSON.stringify(data.task_ids));
        setTimeout(refresh, 2000);
    });
}

function sendCmdSingle(id, cmd) {
    fetch('/api/command', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({target_ids: [id], cmd: cmd})
    }).then(r=>r.json()).then(data => {
        setTimeout(refresh, 2000);
    });
}

refresh();
setInterval(refresh, 10000);
</script>
</body>
</html>'''


# ===== 赛博朋克风格管理界面HTML =====
CYBER_HTML = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=1920, height=1080">
<title>坤展成终端管理系统v1.4.0-服务器端</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body {
    width: 1920px;
    height: 1080px;
    overflow: hidden;
    font-family: 'Microsoft YaHei', 'Consolas', sans-serif;
    background: #0a0e1a;
}
.bg-container {
    position: fixed;
    top: 0; left: 0;
    width: 1920px; height: 1080px;
    background: url('/static/bg.jpg') no-repeat center center;
    background-size: cover;
    z-index: 0;
}
.main-content {
    position: absolute;
    top: 0; left: 0;
    width: 1920px; height: 1080px;
    z-index: 1;
}

/* 标题区 */
.title-area {
    position: absolute;
    top: 18px;
    left: 50%;
    transform: translateX(-50%);
    text-align: center;
    white-space: nowrap;
}
.title-area h1 {
    font-size: 32px;
    font-weight: bold;
    color: #00d4ff;
    text-shadow: 0 0 20px #00d4ff, 0 0 40px #0066ff;
    letter-spacing: 4px;
    margin-bottom: 6px;
}
.title-area .subtitle {
    font-size: 14px;
    color: #7aa8cc;
    letter-spacing: 2px;
}

/* 三个圆形数据模块 */
.stats-row {
    position: absolute;
    top: 90px;
    left: 0;
    width: 100%;
    display: flex;
    justify-content: center;
    gap: 120px;
}
.stat-ring {
    width: 180px;
    height: 180px;
    border-radius: 50%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    position: relative;
}
.stat-ring::before {
    content: '';
    position: absolute;
    top: -8px; left: -8px; right: -8px; bottom: -8px;
    border-radius: 50%;
    background: conic-gradient(var(--ring-color) var(--percent, 0%), transparent var(--percent, 0%));
    opacity: 0.6;
    z-index: -1;
}
.stat-ring::after {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    border-radius: 50%;
    border: 3px solid var(--ring-color);
    box-shadow: 0 0 20px var(--ring-color), inset 0 0 20px var(--ring-color);
}
.stat-ring.online { --ring-color: #00ff88; }
.stat-ring.offline { --ring-color: #ff4466; }
.stat-ring.total { --ring-color: #00aaff; }
.stat-ring .value {
    font-size: 48px;
    font-weight: bold;
    font-family: 'Consolas', monospace;
    color: white;
    text-shadow: 0 0 10px var(--ring-color);
}
.stat-ring .label {
    font-size: 16px;
    color: var(--ring-color);
    margin-top: 4px;
    letter-spacing: 2px;
}

/* 设备列表区域 */
.device-list-area {
    position: absolute;
    top: 290px;
    left: 30px;
    width: 400px;
    height: 560px;
    background: rgba(10, 20, 40, 0.85);
    border: 2px solid #00aaff;
    border-radius: 8px;
    box-shadow: 0 0 20px rgba(0, 170, 255, 0.4), inset 0 0 30px rgba(0, 100, 200, 0.2);
    overflow: hidden;
}
.device-list-header {
    padding: 12px 16px;
    background: linear-gradient(180deg, rgba(0, 100, 200, 0.4), rgba(0, 50, 100, 0.2));
    border-bottom: 1px solid #00aaff;
}
.device-list-header span {
    font-size: 16px;
    color: #00d4ff;
    letter-spacing: 3px;
    text-shadow: 0 0 10px #00d4ff;
}
.device-list {
    height: calc(100% - 45px);
    overflow-y: auto;
    padding: 8px;
}
.device-list::-webkit-scrollbar { width: 6px; }
.device-list::-webkit-scrollbar-track { background: rgba(0,50,100,0.3); }
.device-list::-webkit-scrollbar-thumb { background: #00aaff; border-radius: 3px; }
.device-item {
    display: flex;
    align-items: center;
    padding: 10px 12px;
    margin-bottom: 6px;
    background: rgba(0, 40, 80, 0.5);
    border: 1px solid rgba(0, 170, 255, 0.3);
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.2s;
}
.device-item:hover {
    background: rgba(0, 80, 160, 0.6);
    border-color: #00d4ff;
    box-shadow: 0 0 15px rgba(0, 212, 255, 0.3);
}
.device-item.selected {
    background: rgba(0, 120, 200, 0.6);
    border-color: #00ffff;
    box-shadow: 0 0 20px rgba(0, 255, 255, 0.4);
}
.device-status-dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    margin-right: 10px;
    flex-shrink: 0;
}
.device-status-dot.online {
    background: #00ff88;
    box-shadow: 0 0 8px #00ff88;
}
.device-status-dot.offline {
    background: #666;
    box-shadow: 0 0 4px #666;
}
.device-info {
    flex: 1;
    min-width: 0;
}
.device-info .hostname {
    font-size: 14px;
    color: white;
    font-weight: bold;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.device-info .ip {
    font-size: 12px;
    color: #7aa8cc;
    font-family: 'Consolas', monospace;
}
.device-delete {
    width: 24px;
    height: 24px;
    background: rgba(255, 68, 102, 0.2);
    border: 1px solid #ff4466;
    border-radius: 4px;
    color: #ff4466;
    font-size: 14px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.2s;
    flex-shrink: 0;
    margin-left: 8px;
}
.device-delete:hover {
    background: #ff4466;
    color: white;
    box-shadow: 0 0 10px #ff4466;
}

/* 设备信息区域 */
.device-info-area {
    position: absolute;
    top: 290px;
    left: 450px;
    width: 720px;
    height: 320px;
    background: rgba(10, 20, 40, 0.85);
    border: 2px solid #00aaff;
    border-radius: 8px;
    box-shadow: 0 0 20px rgba(0, 170, 255, 0.4), inset 0 0 30px rgba(0, 100, 200, 0.2);
    padding: 20px;
}
.device-info-area .section-title {
    font-size: 16px;
    color: #00d4ff;
    letter-spacing: 3px;
    margin-bottom: 16px;
    text-shadow: 0 0 10px #00d4ff;
}
.info-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px 30px;
}
.info-item {
    display: flex;
    align-items: center;
}
.info-item .label {
    font-size: 13px;
    color: #7aa8cc;
    width: 80px;
    flex-shrink: 0;
}
.info-item .value {
    font-size: 14px;
    color: white;
    font-family: 'Consolas', monospace;
    flex: 1;
}
.info-item .value.highlight {
    color: #00ffff;
    text-shadow: 0 0 5px #00ffff;
}
.progress-section {
    margin-top: 20px;
    border-top: 1px solid rgba(0, 170, 255, 0.3);
    padding-top: 16px;
}
.progress-item {
    display: flex;
    align-items: center;
    margin-bottom: 10px;
}
.progress-item .label {
    font-size: 12px;
    color: #7aa8cc;
    width: 50px;
}
.progress-item .bar {
    flex: 1;
    height: 14px;
    background: rgba(0, 40, 80, 0.8);
    border-radius: 7px;
    overflow: hidden;
    border: 1px solid rgba(0, 170, 255, 0.3);
}
.progress-item .bar .fill {
    height: 100%;
    border-radius: 6px;
    transition: width 0.3s;
}
.progress-item.cpu .bar .fill { background: linear-gradient(90deg, #ff4466, #ff8844); }
.progress-item.memory .bar .fill { background: linear-gradient(90deg, #ffaa00, #ffcc00); }
.progress-item.disk .bar .fill { background: linear-gradient(90deg, #0066ff, #00aaff); }
.progress-item .percent {
    font-size: 12px;
    color: white;
    width: 50px;
    text-align: right;
    font-family: 'Consolas', monospace;
}
.no-selection {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: #4a6a8a;
    font-size: 16px;
    letter-spacing: 2px;
}

/* 远程控制区域 */
.remote-ctrl-area {
    position: absolute;
    top: 630px;
    left: 450px;
    width: 700px;
    height: 220px;
    background: rgba(10, 20, 40, 0.85);
    border: 2px solid #00aaff;
    border-radius: 8px;
    box-shadow: 0 0 20px rgba(0, 170, 255, 0.4), inset 0 0 30px rgba(0, 100, 200, 0.2);
    padding: 16px;
}
.remote-ctrl-area .section-title {
    font-size: 16px;
    color: #00d4ff;
    letter-spacing: 3px;
    margin-bottom: 16px;
    text-shadow: 0 0 10px #00d4ff;
}
.ctrl-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
}
.ctrl-btn {
    padding: 12px 8px;
    background: linear-gradient(180deg, rgba(0, 80, 160, 0.6), rgba(0, 40, 100, 0.8));
    border: 2px solid #0088ff;
    border-radius: 6px;
    color: white;
    font-size: 13px;
    cursor: pointer;
    transition: all 0.2s;
    text-align: center;
    letter-spacing: 1px;
}
.ctrl-btn:hover {
    background: linear-gradient(180deg, rgba(0, 120, 200, 0.8), rgba(0, 80, 160, 0.9));
    border-color: #00ffff;
    box-shadow: 0 0 20px rgba(0, 255, 255, 0.5), 0 0 40px rgba(0, 200, 255, 0.3);
    transform: translateY(-2px);
    text-shadow: 0 0 10px #00ffff;
}
.ctrl-btn:active {
    transform: translateY(0);
}
.ctrl-btn.danger {
    border-color: #ff4466;
}
.ctrl-btn.danger:hover {
    border-color: #ff6688;
    box-shadow: 0 0 20px rgba(255, 68, 102, 0.5);
}
.ctrl-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}
.ctrl-btn:disabled:hover {
    transform: none;
    box-shadow: none;
}

/* 文件传输区域 */
.file-transfer-area {
    position: absolute;
    top: 630px;
    left: 1170px;
    width: 720px;
    height: 220px;
    background: rgba(10, 20, 40, 0.85);
    border: 2px solid #00aaff;
    border-radius: 8px;
    box-shadow: 0 0 20px rgba(0, 170, 255, 0.4), inset 0 0 30px rgba(0, 100, 200, 0.2);
    padding: 16px;
}
.file-transfer-area .section-title {
    font-size: 16px;
    color: #00d4ff;
    letter-spacing: 3px;
    margin-bottom: 16px;
    text-shadow: 0 0 10px #00d4ff;
}
.file-select-row {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 16px;
}
.file-input {
    flex: 1;
    padding: 10px 14px;
    background: rgba(0, 40, 80, 0.8);
    border: 1px solid rgba(0, 170, 255, 0.5);
    border-radius: 6px;
    color: #aaa;
    font-size: 13px;
}
.file-status {
    font-size: 13px;
    color: #00ff88;
    margin-bottom: 16px;
    font-family: 'Consolas', monospace;
}
.file-status.error { color: #ff4466; }
.send-btn {
    padding: 14px 40px;
    background: linear-gradient(180deg, rgba(0, 180, 80, 0.7), rgba(0, 120, 60, 0.9));
    border: 2px solid #00ff88;
    border-radius: 6px;
    color: white;
    font-size: 15px;
    cursor: pointer;
    transition: all 0.2s;
    letter-spacing: 2px;
}
.send-btn:hover {
    background: linear-gradient(180deg, rgba(0, 220, 100, 0.8), rgba(0, 160, 80, 0.9));
    border-color: #00ffff;
    box-shadow: 0 0 25px rgba(0, 255, 136, 0.6);
    transform: translateY(-2px);
}
.send-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}
.send-btn:disabled:hover {
    transform: none;
    box-shadow: none;
}

/* 底部状态栏 */
.status-bar {
    position: absolute;
    bottom: 0;
    left: 0;
    width: 100%;
    height: 36px;
    background: linear-gradient(180deg, rgba(0, 40, 80, 0.9), rgba(0, 20, 50, 0.95));
    border-top: 1px solid rgba(0, 170, 255, 0.5);
    display: flex;
    align-items: center;
    padding: 0 20px;
    gap: 40px;
}
.status-item {
    font-size: 12px;
    color: #7aa8cc;
    font-family: 'Consolas', monospace;
}
.status-item .value {
    color: #00d4ff;
    margin-left: 6px;
}
.status-item .online-count {
    color: #00ff88;
    text-shadow: 0 0 5px #00ff88;
}
.status-item .server-status {
    color: #00ff88;
    margin-left: 6px;
    letter-spacing: 1px;
}
</style>
</head>
<body>
<div class="bg-container"></div>
<div class="main-content">
    <!-- 标题区 -->
    <div class="title-area">
        <h1>坤展成终端管理系统v1.4.0-服务器端</h1>
        <div class="subtitle">北京万乘兄弟科技有限公司 联系电话:18210234280</div>
    </div>

    <!-- 三个圆形数据模块 -->
    <div class="stats-row">
        <div class="stat-ring online">
            <div class="value" id="onlineCount">0</div>
            <div class="label">在线设备</div>
        </div>
        <div class="stat-ring offline">
            <div class="value" id="offlineCount">0</div>
            <div class="label">离线设备</div>
        </div>
        <div class="stat-ring total">
            <div class="value" id="totalCount">0</div>
            <div class="label">设备总数</div>
        </div>
    </div>

    <!-- 设备列表区域 -->
    <div class="device-list-area">
        <div class="device-list-header">
            <span>设备列表</span>
        </div>
        <div class="device-list" id="deviceList">
            <!-- 动态生成 -->
        </div>
    </div>

    <!-- 设备信息区域 -->
    <div class="device-info-area">
        <div class="section-title">设备信息</div>
        <div id="deviceInfoContent">
            <div class="no-selection">请从左侧选择设备查看详情</div>
        </div>
    </div>

    <!-- 远程控制区域 -->
    <div class="remote-ctrl-area">
        <div class="section-title">远程控制</div>
        <div class="ctrl-grid">
            <button class="ctrl-btn" id="btnDesktop" onclick="sendCmd('start_remote_desktop')" disabled>远程桌面</button>
            <button class="ctrl-btn danger" id="btnShutdown" onclick="sendCmd('shutdown')" disabled>关机</button>
            <button class="ctrl-btn danger" id="btnRestart" onclick="sendCmd('restart')" disabled>重启</button>
            <button class="ctrl-btn" id="btnMute" onclick="sendCmd('mute')" disabled>静音</button>
            <button class="ctrl-btn" id="btnUnmute" onclick="sendCmd('unmute')" disabled>取消静音</button>
            <button class="ctrl-btn" id="btnVolUp" onclick="sendCmd('volume:up')" disabled>音量+</button>
            <button class="ctrl-btn" id="btnVolDown" onclick="sendCmd('volume:down')" disabled>音量-</button>
            <button class="ctrl-btn" id="btnStatus" onclick="sendCmd('status')" disabled>查询状态</button>
        </div>
    </div>

    <!-- 文件传输区域 -->
    <div class="file-transfer-area">
        <div class="section-title">文件传输</div>
        <div class="file-select-row">
            <input type="file" id="fileInput" class="file-input" style="display:none" onchange="onFileSelected(this)">
            <input type="text" id="filePath" class="file-input" readonly placeholder="未选择文件" style="cursor:pointer" onclick="document.getElementById('fileInput').click()">
        </div>
        <div class="file-status" id="fileStatus">就绪</div>
        <button class="send-btn" id="sendBtn" onclick="sendFile()" disabled>发送文件</button>
    </div>

    <!-- 底部状态栏 -->
    <div class="status-bar">
        <div class="status-item">
            服务器:<span class="value" id="serverAddr">-:8080</span>
        </div>
        <div class="status-item">
            在线设备:<span class="value online-count" id="onlineCountBar">0/0</span>
        </div>
        <div class="status-item">
            <span class="server-status">服务运行中</span>
        </div>
    </div>
</div>

<script>
let devices = [];
let selectedId = null;
let selectedFile = null;

function getServerIP() {
    // 从当前页面URL提取服务器IP
    const match = window.location.href.match(/\\/\\/([^\\/]+)/);
    return match ? match[1] : 'localhost';
}

function refresh() {
    fetch('/api/devices').then(r => r.json()).then(data => {
        devices = data.devices || [];
        renderDevices();
        updateStats();
    });
}

function renderDevices() {
    const container = document.getElementById('deviceList');
    let html = '';
    devices.forEach(d => {
        const isOnline = d.status === 'online';
        const isSelected = d.id === selectedId;
        html += '<div class="device-item' + (isSelected ? ' selected' : '') + '" onclick="selectDevice(\\'' + d.id + '\\')">';
        html += '<div class="device-status-dot ' + (isOnline ? 'online' : 'offline') + '"></div>';
        html += '<div class="device-info">';
        html += '<div class="hostname">' + escapeHtml(d.hostname || '未知') + '</div>';
        html += '<div class="ip">' + escapeHtml(d.ip || '-') + '</div>';
        html += '</div>';
        html += '<div class="device-delete" onclick="event.stopPropagation(); deleteDevice(\\'' + d.id + '\\')">✕</div>';
        html += '</div>';
    });
    if (devices.length === 0) {
        html = '<div style="padding:20px;text-align:center;color:#4a6a8a;">暂无设备连接</div>';
    }
    container.innerHTML = html;
}

function updateStats() {
    const online = devices.filter(d => d.status === 'online').length;
    const offline = devices.length - online;
    document.getElementById('onlineCount').textContent = online;
    document.getElementById('offlineCount').textContent = offline;
    document.getElementById('totalCount').textContent = devices.length;
    document.getElementById('onlineCountBar').textContent = online + '/' + devices.length;
    
    // 更新圆形环形的进度效果
    document.querySelector('.stat-ring.online').style.setProperty('--percent', (online / Math.max(devices.length, 1)) * 100 + '%');
    document.querySelector('.stat-ring.offline').style.setProperty('--percent', (offline / Math.max(devices.length, 1)) * 100 + '%');
    document.querySelector('.stat-ring.total').style.setProperty('--percent', '100%');
}

function selectDevice(id) {
    selectedId = id;
    renderDevices();
    renderDeviceInfo();
    updateCtrlBtns(true);
}

function renderDeviceInfo() {
    const container = document.getElementById('deviceInfoContent');
    if (!selectedId) {
        container.innerHTML = '<div class="no-selection">请从左侧选择设备查看详情</div>';
        return;
    }
    const d = devices.find(x => x.id === selectedId);
    if (!d) {
        container.innerHTML = '<div class="no-selection">设备不存在</div>';
        return;
    }
    const cpu = parseFloat(d.cpu_percent) || 0;
    const mem = parseFloat(d.memory_percent) || 0;
    const disk = parseFloat(d.disk_percent) || 0;
    
    container.innerHTML = '<div class="info-grid">' +
        '<div class="info-item"><span class="label">主机名:</span><span class="value highlight">' + escapeHtml(d.hostname || '-') + '</span></div>' +
        '<div class="info-item"><span class="label">IP地址:</span><span class="value highlight">' + escapeHtml(d.ip || '-') + '</span></div>' +
        '<div class="info-item"><span class="label">MAC地址:</span><span class="value">' + escapeHtml(d.mac || '-') + '</span></div>' +
        '<div class="info-item"><span class="label">操作系统:</span><span class="value">' + escapeHtml(d.os || '-') + '</span></div>' +
        '<div class="info-item"><span class="label">系统版本:</span><span class="value">' + escapeHtml(d.os_version || '-') + '</span></div>' +
        '<div class="info-item"><span class="label">架构:</span><span class="value">' + escapeHtml(d.arch || '-') + '</span></div>' +
        '<div class="info-item"><span class="label">最后在线:</span><span class="value">' + escapeHtml(d.last_seen || '-') + '</span></div>' +
        '<div class="info-item"><span class="label">状态:</span><span class="value" style="color:' + (d.status === 'online' ? '#00ff88' : '#ff4466') + '">' + (d.status === 'online' ? '在线' : '离线') + '</span></div>' +
        '</div>' +
        '<div class="progress-section">' +
        '<div class="progress-item cpu"><span class="label">CPU</span><div class="bar"><div class="fill" style="width:' + cpu + '%"></div></div><span class="percent">' + cpu.toFixed(1) + '%</span></div>' +
        '<div class="progress-item memory"><span class="label">内存</span><div class="bar"><div class="fill" style="width:' + mem + '%"></div></div><span class="percent">' + mem.toFixed(1) + '%</span></div>' +
        '<div class="progress-item disk"><span class="label">磁盘</span><div class="bar"><div class="fill" style="width:' + disk + '%"></div></div><span class="percent">' + disk.toFixed(1) + '%</span></div>' +
        '</div>';
}

function updateCtrlBtns(enabled) {
    const btns = ['btnDesktop', 'btnShutdown', 'btnRestart', 'btnMute', 'btnUnmute', 'btnVolUp', 'btnVolDown', 'btnStatus'];
    btns.forEach(id => {
        document.getElementById(id).disabled = !enabled;
    });
    document.getElementById('sendBtn').disabled = !enabled;
}

function sendCmd(cmd) {
    if (!selectedId) return;
    fetch('/api/command', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({target_ids: [selectedId], cmd: cmd})
    }).then(r => r.json()).then(data => {
        console.log('指令已发送:', cmd, data);
    }).catch(err => {
        console.error('发送失败:', err);
    });
}

function deleteDevice(id) {
    if (!confirm('确定删除该设备？')) return;
    fetch('/api/command', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({target_ids: [id], cmd: 'delete_device'})
    }).then(() => {
        if (selectedId === id) {
            selectedId = null;
            renderDeviceInfo();
            updateCtrlBtns(false);
        }
        refresh();
    });
}

function onFileSelected(input) {
    const file = input.files[0];
    if (file) {
        selectedFile = file;
        document.getElementById('filePath').value = file.name;
        document.getElementById('fileStatus').textContent = '已选择: ' + file.name + ' (' + formatSize(file.size) + ')';
        document.getElementById('fileStatus').className = 'file-status';
    }
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1024 * 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB';
    return (bytes / 1024 / 1024 / 1024).toFixed(2) + ' GB';
}

function sendFile() {
    if (!selectedId || !selectedFile) return;
    const status = document.getElementById('fileStatus');
    status.textContent = '正在上传...';
    status.className = 'file-status';
    
    const formData = new FormData();
    formData.append('file', selectedFile);
    
    fetch('/api/file/upload', {
        method: 'POST',
        body: formData
    }).then(r => r.json()).then(data => {
        if (data.server_file_name) {
            status.textContent = '文件已上传，发送中...';
            return fetch('/api/command', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    target_ids: [selectedId],
                    cmd: 'file_transfer',
                    extra: {
                        file_name: selectedFile.name,
                        file_size: selectedFile.size,
                        server_file_name: data.server_file_name,
                        download_url: window.location.protocol + '//' + getServerIP() + ':8080/api/file/' + data.server_file_name
                    }
                })
            });
        }
    }).then(() => {
        status.textContent = '发送成功！';
        status.className = 'file-status';
        setTimeout(() => {
            status.textContent = '就绪';
        }, 3000);
    }).catch(err => {
        status.textContent = '发送失败: ' + err;
        status.className = 'file-status error';
    });
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 初始化
document.getElementById('serverAddr').textContent = getServerIP() + ':8080';
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>'''


@app.get('/cyber')
async def cyber_index():
    """赛博朋克风格管理界面"""
    return HTMLResponse(CYBER_HTML)


# ===== 远程桌面查看器 =====
class RemoteDesktopViewer:
    """远程桌面查看器"""
    
    def __init__(self, parent, client_ip, client_id, server_ip, display_mode='最大化窗口'):
        self.client_ip = client_ip
        self.client_id = client_id
        self.server_ip = server_ip
        self.running = True
        self.last_hash = None
        self.screen_scale = 1.0
        self.client_screen_size = None
        self.offset_x = 0
        self.offset_y = 0
        self.current_img = None
        self.display_mode = display_mode
        self._is_fullscreen = False
        
        # 创建查看器窗口
        self.win = tk.Toplevel(parent)
        self.win.title(f'远程桌面 - {client_ip}')
        self.win.geometry('1024x700')
        self.win.protocol('WM_DELETE_WINDOW', self._on_close)
        
        # 根据显示模式设置窗口（延迟执行，确保窗口已绘制）
        if display_mode == '全屏':
            self.win.after(100, lambda: self.win.attributes('-fullscreen', True))
            self._is_fullscreen = True
        else:
            # 最大化窗口 - 有标题栏和关闭按钮
            self.win.after(100, lambda: self.win.state('zoomed'))
        
        # 工具栏
        toolbar = tk.Frame(self.win, bg='#2c3e50')
        toolbar.pack(fill='x')
        tk.Label(toolbar, text=f'  远程桌面: {client_ip}', font=('Microsoft YaHei', 10, 'bold'), 
                fg='white', bg='#2c3e50').pack(side='left', padx=5)
        
        # 质量选择
        tk.Label(toolbar, text='画质:', fg='white', bg='#2c3e50', font=('Microsoft YaHei', 9)).pack(side='left', padx=(15, 2))
        self.quality_var = tk.IntVar(value=95)
        self.quality_var.trace_add('write', lambda *args: self._notify_quality())
        quality_scale = tk.Scale(toolbar, from_=20, to=95, orient='horizontal', 
                                variable=self.quality_var, length=100, bg='#2c3e50', fg='white',
                                highlightthickness=0, troughcolor='#34495e')
        quality_scale.pack(side='left')
        
        # 全屏切换按钮
        self._fullscreen_btn = tk.Button(toolbar, text='🔲全屏', bg='#3498db', fg='white', 
                 font=('Microsoft YaHei', 9, 'bold'), command=self._toggle_fullscreen)
        self._fullscreen_btn.pack(side='right', padx=5, pady=3)
        
        # 断开按钮
        tk.Button(toolbar, text='断开', bg='#e74c3c', fg='white', font=('Microsoft YaHei', 9, 'bold'),
                 command=self._on_close).pack(side='right', padx=10, pady=3)
        
        # FPS显示
        self.fps_var = tk.StringVar(value='FPS: --')
        tk.Label(toolbar, textvariable=self.fps_var, fg='#2ecc71', bg='#2c3e50', 
                font=('Consolas', 9)).pack(side='right', padx=10)
        
        # 画面显示区域
        self.canvas = tk.Canvas(self.win, bg='#1a1a2e', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self._canvas_img_id = self.canvas.create_image(0, 0, anchor='nw')  # 预创建canvas image item
        
        # 状态提示
        self.status_var = tk.StringVar(value='正在连接...')
        tk.Label(self.win, textvariable=self.status_var, font=('Microsoft YaHei', 9), 
                bg='#ecf0f1', anchor='w').pack(fill='x')
        
        # 绑定键鼠事件
        self.canvas.bind('<Button-1>', self._on_mouse_press)
        self.canvas.bind('<ButtonRelease-1>', self._on_mouse_release)
        self.canvas.bind('<Button-3>', self._on_mouse_right_press)
        self.canvas.bind('<ButtonRelease-3>', self._on_mouse_right_release)
        self.canvas.bind('<Double-Button-1>', self._on_mouse_double_click)
        self.canvas.bind('<B1-Motion>', self._on_mouse_drag)
        self.canvas.bind('<Motion>', self._on_mouse_move)
        self.canvas.bind('<MouseWheel>', self._on_scroll)
        self.canvas.bind('<Key>', self._on_key_press)
        self.canvas.focus_set()
        # ESC退出全屏
        self.win.bind('<Escape>', lambda e: self._toggle_fullscreen() if self._is_fullscreen else None)
        # 窗口大小变化时更新canvas缓存尺寸
        self.canvas.bind('<Configure>', self._on_canvas_resize)
        
        # 当前显示的图片
        self.current_photo = None
        self.current_img = None
        self.offset_x = 0
        self.offset_y = 0
        self.screen_scale = 1.0
        self.frame_count = 0
        self.fps_timer = time.time()
        self._last_move_time = 0  # 鼠标移动节流
        self._canvas_size = (1024, 700)  # 缓存canvas尺寸
        self._latest_img = None  # 解码完的PIL Image
        self._latest_photo = None  # 后台线程创建的PhotoImage，(photo, offset_x, offset_y)
        self._raw_frame = None  # 收到的JPEG原始数据（收帧线程写入，解码线程读取）
        self._frame_event = threading.Event()  # 帧到达事件，替代sleep轮询
        
        # 启动主线程轮询显示（1ms间隔）
        self._poll_display()
        
        # 输入指令队列 + 异步发送线程
        self._input_queue = queue.Queue()
        self._input_thread = threading.Thread(target=self._input_sender, daemon=True)
        self._input_thread.start()
        
        # 启动解码线程（独立于收帧线程，避免收帧被解码阻塞）
        self._decode_thread = threading.Thread(target=self._decode_worker, daemon=True)
        self._decode_thread.start()
        
        # 启动截屏拉取线程
        self._fetch_thread = threading.Thread(target=self._fetch_loop, daemon=True)
        self._fetch_thread.start()
    
    def _get_screen_info(self):
        """获取客户端屏幕分辨率"""
        try:
            url = f'http://{self.client_ip}:5901/screen_info'
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=3) as resp:
                info = json.loads(resp.read().decode())
                self.client_screen_size = info
                return info
        except:
            return None
    
    def _fetch_loop(self):
        """帧获取——优先TCP流5902，失败自动回退HTTP 5901"""
        import socket
        
        self._get_screen_info()
        self._notify_quality()
        
        while self.running:
            # 先试TCP流模式
            try:
                test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                test_sock.settimeout(2)
                test_sock.connect((self.client_ip, 5902))
                test_sock.close()
                # TCP可用，用流模式
                self._fetch_via_tcp()
                return  # _fetch_via_tcp退出后不再重试
            except:
                pass
            
            # TCP不可用，用HTTP模式
            self._fetch_via_http()
            return
    
    def _fetch_via_tcp(self):
        """TCP流模式——后台解码，主线程只显示"""
        import socket
        
        while self.running:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)
                sock.settimeout(5)
                sock.connect((self.client_ip, 5902))
                sock.settimeout(3)
                self.win.after(0, lambda: self.status_var.set('已连接(流模式)'))
                
                while self.running:
                    header = b''
                    while len(header) < 4 and self.running:
                        try:
                            chunk = sock.recv(4 - len(header))
                            if not chunk:
                                raise ConnectionError()
                            header += chunk
                        except socket.timeout:
                            continue
                    
                    if not self.running:
                        break
                    if len(header) < 4:
                        raise ConnectionError("Incomplete header")
                    
                    frame_len = struct.unpack('!I', header)[0]
                    if frame_len == 0:
                        continue
                    if frame_len > 10 * 1024 * 1024:
                        raise ValueError("Frame too large")
                    
                    frame_data = bytearray()
                    while len(frame_data) < frame_len and self.running:
                        try:
                            chunk = sock.recv(min(frame_len - len(frame_data), 262144))
                            if not chunk:
                                raise ConnectionError()
                            frame_data.extend(chunk)
                        except socket.timeout:
                            continue
                    frame_data = bytes(frame_data)
                    
                    if not self.running:
                        break
                    if len(frame_data) < frame_len:
                        raise ConnectionError("Incomplete frame")
                    
                    self.frame_count += 1
                    now = time.time()
                    if now - self.fps_timer >= 1.0:
                        fps = self.frame_count / (now - self.fps_timer)
                        self.win.after(0, lambda f=fps: self.fps_var.set(f'FPS: {f:.1f}'))
                        self.frame_count = 0
                        self.fps_timer = now
                    
                    # 收到帧数据，存入解码队列（不阻塞收帧）
                    self._raw_frame = frame_data
                    self._frame_event.set()
                
            except Exception as e:
                if not self.running:
                    break
                self.win.after(0, lambda: self.status_var.set('流断开，重连中...'))
                time.sleep(2)
                try:
                    sock.close()
                except:
                    pass
    
    def _fetch_via_http(self):
        """HTTP模式——后台解码，主线程只显示"""
        self.win.after(0, lambda: self.status_var.set('已连接(HTTP)'))
        
        while self.running:
            try:
                quality = self.quality_var.get()
                url = f'http://{self.client_ip}:5901/screen?quality={quality}'
                req = urllib.request.Request(url)
                
                with urllib.request.urlopen(req, timeout=2) as resp:
                    jpeg_data = resp.read()
                
                self.frame_count += 1
                now = time.time()
                if now - self.fps_timer >= 1.0:
                    fps = self.frame_count / (now - self.fps_timer)
                    self.win.after(0, lambda f=fps: self.fps_var.set(f'FPS: {f:.1f}'))
                    self.frame_count = 0
                    self.fps_timer = now
                
                # 收到帧数据，存入解码队列
                self._raw_frame = jpeg_data
                self._frame_event.set()
                
            except Exception as e:
                if not self.running:
                    break
                self.win.after(0, lambda: self.status_var.set('HTTP重连中...'))
                time.sleep(1)
    
    def _decode_worker(self):
        """独立解码线程：用Event等待帧，跳过积压帧只解码最新"""
        while self.running:
            self._frame_event.wait(timeout=0.1)
            self._frame_event.clear()
            
            raw = self._raw_frame
            if raw:
                self._raw_frame = None
                # 如果有更新的帧，跳过当前帧
                while self._raw_frame is not None:
                    raw = self._raw_frame
                    self._raw_frame = None
                img = self._decode_and_scale(raw)
                if img:
                    # 把PhotoImage创建也放后台，减少主线程负担
                    try:
                        photo = ImageTk.PhotoImage(img)
                        self._latest_photo = (photo, self.offset_x, self.offset_y)
                    except:
                        self._latest_img = img
    
    def _decode_and_scale(self, jpeg_data):
        """后台线程：JPEG解码+缩放（draft降采样+resize补齐）"""
        try:
            img = Image.open(io.BytesIO(jpeg_data))
            iw, ih = img.size  # 原始尺寸
            cw, ch = self._canvas_size
            
            if cw > 100 and ch > 100:
                self.screen_scale = min(cw / iw, ch / ih)
                new_w = int(iw * self.screen_scale)
                new_h = int(ih * self.screen_scale)
                
                need_scale = abs(new_w - iw) > iw * 0.02 or abs(new_h - ih) > ih * 0.02
                
                if need_scale:
                    # 尝试draft（JPEG解码阶段降采样，快5-8倍，但只支持2的幂次缩小）
                    drafted = False
                    try:
                        img.draft('RGB', (new_w, new_h))
                        img.load()
                        dw, dh = img.size
                        # draft成功且尺寸确实变小了
                        if dw < iw or dh < ih:
                            drafted = True
                            # draft后可能还需微调（draft只做2x/4x缩小）
                            if abs(dw - new_w) > 2 or abs(dh - new_h) > 2:
                                img = img.resize((new_w, new_h), Image.BILINEAR)
                    except:
                        pass
                    
                    if not drafted:
                        img = img.resize((new_w, new_h), Image.BILINEAR)
                
                self.offset_x = (cw - new_w) // 2
                self.offset_y = (ch - new_h) // 2
            
            return img
        except:
            return None
    
    def _poll_display(self):
        """主线程轮询：1ms检查新帧，有就显示"""
        if not self.running:
            return
        
        # 优先用后台线程创建好的PhotoImage（省掉主线程转换时间）
        if self._latest_photo:
            photo, ox, oy = self._latest_photo
            self._latest_photo = None
            self.current_photo = photo
            try:
                self.canvas.itemconfig(self._canvas_img_id, image=self.current_photo)
                self.canvas.coords(self._canvas_img_id, ox, oy)
            except Exception as e:
                pass
        elif self._latest_img:
            img = self._latest_img
            self._latest_img = None
            try:
                self.current_photo = ImageTk.PhotoImage(img)
                self.canvas.itemconfig(self._canvas_img_id, image=self.current_photo)
                self.canvas.coords(self._canvas_img_id, self.offset_x, self.offset_y)
            except Exception as e:
                pass
        
        self.win.after(1, self._poll_display)
    
    def _show_frame(self, img):
        """直接显示一帧（备用）"""
        try:
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()
            if cw > 100 and ch > 100:
                self._canvas_size = (cw, ch)
            
            self.current_photo = ImageTk.PhotoImage(img)
            self.canvas.itemconfig(self._canvas_img_id, image=self.current_photo)
            self.canvas.coords(self._canvas_img_id, self.offset_x, self.offset_y)
        except Exception as e:
            print(f'[远程桌面] 显示失败: {e}')
    
    def _notify_quality(self):
        """通知客户端画质设置"""
        try:
            quality = self.quality_var.get()
            url = f'http://{self.client_ip}:5901/input'
            data = json.dumps({'input_type': 'set_quality', 'quality': quality}).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
            urllib.request.urlopen(req, timeout=1)
        except:
            pass
    
    def _recv_exact(self, sock, n):
        """精确接收n字节数据"""
        data = b''
        while len(data) < n and self.running:
            try:
                chunk = sock.recv(min(n - len(data), 131072))
                if not chunk:
                    return None
                data += chunk
            except socket.timeout:
                continue
            except:
                return None
        return data if len(data) == n else None
    
    def _canvas_to_client(self, cx, cy):
        """将Canvas坐标转换为客户端屏幕坐标"""
        client_x = int((cx - self.offset_x) / self.screen_scale)
        client_y = int((cy - self.offset_y) / self.screen_scale)
        return client_x, client_y
    
    def _send_input(self, input_data):
        """异步发送输入指令（放入队列，由专门线程发送）"""
        self._input_queue.put(input_data)
    
    def _input_sender(self):
        """输入发送线程——批量合并指令，HTTP长连接复用"""
        import http.client
        conn = None
        while self.running:
            try:
                # 批量取出队列中的指令
                batch = []
                try:
                    item = self._input_queue.get(timeout=0.05)
                    batch.append(item)
                except queue.Empty:
                    # 空闲时关闭长连接，避免占用资源
                    if conn:
                        try:
                            conn.close()
                        except:
                            pass
                        conn = None
                    continue
                
                # 非阻塞取出剩余（最多10ms内积压的）
                deadline = time.time() + 0.01
                while not self._input_queue.empty() and len(batch) < 20 and time.time() < deadline:
                    try:
                        batch.append(self._input_queue.get_nowait())
                    except queue.Empty:
                        break
                
                # 去重：mouse_move/mouse_drag只保留最后一条
                deduped = {}
                for item in batch:
                    itype = item.get('input_type', '')
                    if itype in ('mouse_move', 'mouse_drag'):
                        deduped[itype] = item
                    else:
                        deduped[f'{itype}_{len(deduped)}'] = item
                
                # 合并为一次HTTP请求发送（减少TCP连接开销）
                items = list(deduped.values())
                try:
                    if not conn:
                        conn = http.client.HTTPConnection(self.client_ip, 5901, timeout=1)
                    data = json.dumps({'input_type': 'batch', 'items': items}).encode('utf-8')
                    conn.request('POST', '/input', body=data, headers={'Content-Type': 'application/json'})
                    resp = conn.getresponse()
                    resp.read()  # 必须读完response才能复用连接
                except:
                    # 连接断开，重建
                    try:
                        conn.close()
                    except:
                        pass
                    conn = None
            except:
                pass
    
    def _on_mouse_press(self, event):
        x, y = self._canvas_to_client(event.x, event.y)
        self._send_input({'input_type': 'mouse_press', 'x': x, 'y': y, 'button': 'left'})
    
    def _on_mouse_release(self, event):
        x, y = self._canvas_to_client(event.x, event.y)
        self._send_input({'input_type': 'mouse_release', 'x': x, 'y': y, 'button': 'left'})
    
    def _on_mouse_right_press(self, event):
        x, y = self._canvas_to_client(event.x, event.y)
        self._send_input({'input_type': 'mouse_press', 'x': x, 'y': y, 'button': 'right'})
    
    def _on_mouse_right_release(self, event):
        x, y = self._canvas_to_client(event.x, event.y)
        self._send_input({'input_type': 'mouse_release', 'x': x, 'y': y, 'button': 'right'})
    
    def _on_mouse_double_click(self, event):
        x, y = self._canvas_to_client(event.x, event.y)
        self._send_input({'input_type': 'mouse_click', 'x': x, 'y': y, 'button': 'left', 'clicks': 2})
    
    def _on_mouse_drag(self, event):
        # 拖动时只发坐标移动，press已经在之前发了
        x, y = self._canvas_to_client(event.x, event.y)
        self._send_input({'input_type': 'mouse_move', 'x': x, 'y': y})
    
    def _on_mouse_move(self, event):
        now = time.time()
        if now - self._last_move_time < 0.03:  # 30ms节流
            return
        self._last_move_time = now
        x, y = self._canvas_to_client(event.x, event.y)
        self._send_input({'input_type': 'mouse_move', 'x': x, 'y': y})
    
    def _on_canvas_resize(self, event):
        """canvas尺寸变化时更新缓存，触发重新缩放"""
        if event.width > 100 and event.height > 100:
            self._canvas_size = (event.width, event.height)
    
    def _on_scroll(self, event):
        x, y = self._canvas_to_client(event.x, event.y)
        delta = event.delta // 120
        self._send_input({'input_type': 'scroll', 'x': x, 'y': y, 'delta': delta})
    
    def _on_key_press(self, event):
        # 简单按键映射
        key = event.keysym
        # 映射特殊键
        key_map = {'Return': 'enter', 'BackSpace': 'backspace', 'Escape': 'escape',
                   'Tab': 'tab', 'space': 'space', 'Delete': 'delete',
                   'Left': 'left', 'Right': 'right', 'Up': 'up', 'Down': 'down',
                   'Home': 'home', 'End': 'end', 'Prior': 'pageup', 'Next': 'pagedown'}
        mapped_key = key_map.get(key, key)
        
        # 处理组合键
        modifiers = []
        if event.state & 0x1:  # Shift
            modifiers.append('shift')
        if event.state & 0x4:  # Ctrl
            modifiers.append('ctrl')
        if event.state & 0x8:  # Alt
            modifiers.append('alt')
        
        if modifiers and len(mapped_key) == 1:
            self._send_input({'input_type': 'key_hotkey', 'keys': modifiers + [mapped_key]})
        else:
            self._send_input({'input_type': 'key_press', 'key': mapped_key})
    
    def _on_close(self):
        """关闭查看器"""
        self.running = False
        # 发送停止指令
        try:
            local_ip = _get_local_ip()
            url = f'http://{local_ip}:8080/api/command'
            data = json.dumps({
                'target_ids': [self.client_id],
                'cmd': 'stop_remote_desktop'
            }).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
            urllib.request.urlopen(req, timeout=2)
        except:
            pass
        self.win.destroy()
    
    def _toggle_fullscreen(self):
        """切换全屏/窗口模式"""
        if self._is_fullscreen:
            self.win.attributes('-fullscreen', False)
            self.win.state('zoomed')
            self._is_fullscreen = False
            self._fullscreen_btn.config(text='🔲全屏')
        else:
            self.win.state('normal')
            self.win.attributes('-fullscreen', True)
            self._is_fullscreen = True
            self._fullscreen_btn.config(text='🔲窗口')


# ===== Tkinter GUI =====
# ===== 注册码生成工具 =====
import hashlib

def _generate_activation_key(serial):
    """根据序列号生成注册码"""
    secret = 'KZC-ACTIVATE-2026-SECRET'
    h = hashlib.sha256((serial + secret).encode()).hexdigest().upper()
    return f'{h[0:4]}-{h[4:8]}-{h[8:12]}-{h[12:16]}'

class ServerGUI:
    def __init__(self):
        self.root = tk.Tk()
        icon_path = resource_path('icon.ico')
        if os.path.exists(icon_path):
            self.root.iconbitmap(icon_path)
        self.root.title('坤展成终端管理系统 v1.3-53 - 服务器端')
        self.root.geometry('1100x700')
        self.root.minsize(900, 600)
        self.root.after(100, lambda: self.root.state('zoomed'))  # 默认最大化
        
        self.selected_client_id = None
        self._refresh_after_id = None
        self._last_online_count = 0
        
        self._build_ui()
        self._start_refresh()
    
    def _build_ui(self):
        # 顶部标题栏
        title_frame = tk.Frame(self.root, bg='#2c3e50', height=60)
        title_frame.pack(fill='x')
        title_frame.pack_propagate(False)
        tk.Label(title_frame, text='坤展成终端管理系统 v1.4.0 - 服务器端',
                font=('Microsoft YaHei', 14, 'bold'), fg='white', bg='#2c3e50').pack(pady=(8, 0))
        tk.Label(title_frame, text='北京万乘兄弟科技有限公司  联系电话：18210234280',
                font=('Microsoft YaHei', 8), fg='#bdc3c7', bg='#2c3e50').pack()
        
        # 统计卡片区域
        stats_frame = tk.Frame(self.root, bg='#ecf0f1')
        stats_frame.pack(fill='x', padx=5, pady=(5, 0))
        
        card_data = [
            ('在线设备', '#27ae60', 'stat_online'),
            ('离线设备', '#e74c3c', 'stat_offline'),
            ('设备总数', '#3498db', 'stat_total'),
        ]
        self.stat_vars = {}
        for text, color, key in card_data:
            card = tk.Frame(stats_frame, bg=color, padx=20, pady=8)
            card.pack(side='left', expand=True, fill='x', padx=3)
            var = tk.StringVar(value='0')
            self.stat_vars[key] = var
            tk.Label(card, textvariable=var, font=('Microsoft YaHei', 18, 'bold'), fg='white', bg=color).pack()
            tk.Label(card, text=text, font=('Microsoft YaHei', 9), fg='white', bg=color).pack()
        
        # 主区域：左右分栏
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill='both', expand=True, padx=5, pady=5)
        
        # 左侧：设备列表面板
        left_frame = tk.Frame(main_frame, bg='#ecf0f1', width=320)
        left_frame.pack(side='left', fill='both', padx=(0, 5))
        left_frame.pack_propagate(False)
        
        # 左侧标题
        tk.Label(left_frame, text='设备列表', font=('Microsoft YaHei', 11, 'bold'),
                bg='#ecf0f1').pack(pady=(10, 5))
        
        # 设备列表容器（带滚动条）
        list_container = tk.Frame(left_frame, bg='#ecf0f1')
        list_container.pack(fill='both', expand=True, padx=5)
        
        self.canvas = tk.Canvas(list_container, bg='#ecf0f1', highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_container, orient='vertical', command=self.canvas.yview)
        self.device_list_frame = tk.Frame(self.canvas, bg='#ecf0f1')
        
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        self.canvas_window = self.canvas.create_window((0, 0), window=self.device_list_frame, anchor='nw')
        
        self.device_list_frame.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfig(self.canvas_window, width=e.width))
        
        # 右侧：设备详情面板
        right_frame = tk.Frame(main_frame)
        right_frame.pack(side='right', fill='both', expand=True)
        
        # 详情标题
        self.detail_title = tk.Label(right_frame, text='请选择左侧设备查看详情',
                font=('Microsoft YaHei', 12, 'bold'), anchor='w')
        self.detail_title.pack(fill='x', padx=10, pady=(10, 5))
        
        # 设备信息区域（基本信息+系统状态 合并）
        info_frame = tk.LabelFrame(right_frame, text=' 设备信息 ', font=('Microsoft YaHei', 10, 'bold'))
        info_frame.pack(fill='x', padx=10, pady=5)
        
        self.info_labels = {}
        info_grid = tk.Frame(info_frame)
        info_grid.pack(padx=10, pady=6)
        
        # 基本信息左列
        fields_left = [('主机名', 'hostname'), ('IP地址', 'ip'), ('MAC地址', 'mac')]
        for i, (label, key) in enumerate(fields_left):
            tk.Label(info_grid, text=f'{label}：', font=('Microsoft YaHei', 9), anchor='e', width=8).grid(row=i, column=0, sticky='e', pady=1)
            if key == 'mac':
                self.info_labels[key] = tk.Entry(info_grid, font=('Microsoft YaHei', 9), width=22, relief='sunken', bg='white')
                self.info_labels[key].grid(row=i, column=1, sticky='w', pady=1, padx=(3, 10))
                self.info_labels[key].config(state='readonly')
            else:
                self.info_labels[key] = tk.Label(info_grid, text='-', font=('Microsoft YaHei', 9), anchor='w', width=22, relief='sunken', bg='white')
                self.info_labels[key].grid(row=i, column=1, sticky='w', pady=1, padx=(3, 10))
        
        # 系统版本右列
        fields_right = [('操作系统', 'os'), ('系统版本', 'os_version'), ('架构', 'arch')]
        for i, (label, key) in enumerate(fields_right):
            tk.Label(info_grid, text=f'{label}：', font=('Microsoft YaHei', 9), anchor='e', width=8).grid(row=i, column=2, sticky='e', pady=1)
            self.info_labels[key] = tk.Label(info_grid, text='-', font=('Microsoft YaHei', 9), anchor='w', width=22, relief='sunken', bg='white')
            self.info_labels[key].grid(row=i, column=3, sticky='w', pady=1, padx=(3, 0))
        
        # 系统状态（紧跟基本信息下方）
        stat_grid = tk.Frame(info_frame)
        stat_grid.pack(padx=10, pady=(0, 6))
        
        for i, (label, var_name, color) in enumerate([
            ('CPU', 'cpu_var', '#e74c3c'), ('内存', 'mem_var', '#f39c12'), ('磁盘', 'disk_var', '#3498db')
        ]):
            tk.Label(stat_grid, text=f'{label}：', font=('Microsoft YaHei', 9), width=5, anchor='e').grid(row=0, column=i*3, sticky='e', padx=(0,2))
            var = tk.StringVar(value='0%')
            setattr(self, var_name, var)
            lbl = tk.Label(stat_grid, textvariable=var, font=('Microsoft YaHei', 9, 'bold'), width=6, relief='sunken', bg='white')
            lbl.grid(row=0, column=i*3+1, sticky='w', padx=2)
            prog = ttk.Progressbar(stat_grid, length=80, mode='determinate', maximum=100)
            prog.grid(row=0, column=i*3+2, padx=2)
            setattr(self, f'{var_name.replace("_var","")}_progress', prog)
        
        # 远程桌面大按钮（独立醒目）+ 显示模式选择
        rdp_frame = tk.Frame(right_frame)
        rdp_frame.pack(fill='x', padx=10, pady=(5, 0))
        
        rdp_btn_frame = tk.Frame(rdp_frame)
        rdp_btn_frame.pack(fill='x')
        
        # 全屏勾选框
        self.rdp_fullscreen_var = tk.BooleanVar(value=False)
        tk.Checkbutton(rdp_btn_frame, text='全屏', variable=self.rdp_fullscreen_var,
                       font=('Microsoft YaHei', 9), fg='#2c3e50', selectcolor='#f0f0f0',
                       activebackground='#f5f5f5', activeforeground='#2c3e50'
                       ).pack(side='right', padx=(5, 0))
        
        tk.Button(rdp_btn_frame, text='🖥️  远程桌面', bg='#8e44ad', fg='white',
                 font=('Microsoft YaHei', 13, 'bold'), command=self._cmd_remote_desktop,
                 height=1, cursor='hand2', activebackground='#7d3c98', activeforeground='white'
                 ).pack(side='left', fill='x', expand=True, pady=2)
        
        # 操作按钮区域（远程控制 + 文件传输 左右并排）
        action_row = tk.Frame(right_frame)
        action_row.pack(fill='x', padx=10, pady=5)
        
        # 左侧：远程控制
        ctrl_frame = tk.LabelFrame(action_row, text=' 远程控制 ', font=('Microsoft YaHei', 10, 'bold'))
        ctrl_frame.pack(side='left', fill='both', expand=True, padx=(0, 5))
        
        ctrl_grid = tk.Frame(ctrl_frame)
        ctrl_grid.pack(padx=8, pady=6)
        
        # 系统控制按钮
        ctrl_buttons = [
            ('关机', '#e74c3c', self._cmd_shutdown),
            ('重启', '#f39c12', self._cmd_restart),
            ('静音', '#3498db', self._cmd_mute),
            ('取消静音', '#3498db', self._cmd_unmute),
            ('音量+', '#3498db', self._cmd_volume_up),
            ('音量-', '#3498db', self._cmd_volume_down),
        ]
        for i, (text, color, cmd) in enumerate(ctrl_buttons):
            row, col = i // 3, i % 3
            tk.Button(ctrl_grid, text=text, width=8, bg=color, fg='white',
                     font=('Microsoft YaHei', 9, 'bold'), command=cmd
                     ).grid(row=row, column=col, padx=3, pady=2)
        
        # 右侧：文件传输
        file_frame = tk.LabelFrame(action_row, text=' 文件传输 ', font=('Microsoft YaHei', 10, 'bold'))
        file_frame.pack(side='right', fill='both', expand=True, padx=(5, 0))
        
        file_grid = tk.Frame(file_frame)
        file_grid.pack(padx=8, pady=6)
        
        tk.Button(file_grid, text='选择文件', width=10, command=self._select_file
                 ).grid(row=0, column=0, padx=4, pady=3)
        tk.Button(file_grid, text='发送文件', width=10, bg='#27ae60', fg='white',
                 font=('Microsoft YaHei', 9, 'bold'), command=self._send_file
                 ).grid(row=0, column=1, padx=4, pady=3)
        
        self.file_path_var = tk.StringVar(value='未选择文件')
        tk.Label(file_grid, textvariable=self.file_path_var, font=('Microsoft YaHei', 8),
                anchor='w', relief='sunken', bg='white', width=24
                ).grid(row=1, column=0, columnspan=2, sticky='ew', padx=4, pady=2)
        
        self.transfer_status_var = tk.StringVar(value='就绪')
        tk.Label(file_grid, textvariable=self.transfer_status_var, font=('Microsoft YaHei', 9),
                anchor='w', fg='#27ae60'
                ).grid(row=2, column=0, columnspan=2, sticky='w', padx=4, pady=(0, 2))
        
        # 拖拽文件提示区
        drop_label = tk.Label(file_frame, text='📂 拖拽文件到此处发送', font=('Microsoft YaHei', 10),
                             fg='#7f8c8d', bg='#f5f5f5', relief='groove', height=3)
        drop_label.pack(fill='x', padx=8, pady=(0, 8))
        
        # 注册拖拽事件（windnd）
        try:
            import windnd
            def on_drop(files):
                if files:
                    path = files[0].decode('gbk') if isinstance(files[0], bytes) else files[0]
                    self.selected_file = path
                    self.file_path_var.set(os.path.basename(path))
                    self.transfer_status_var.set('已选择，点击发送或拖入即发')
                    # 拖入后自动发送
                    self._send_file()
            windnd.hook_dropfiles(file_frame, func=on_drop)
        except:
            pass
        
        # 状态提示
        self.cmd_status_var = tk.StringVar(value='就绪')
        self.cmd_status_label = tk.Label(right_frame, textvariable=self.cmd_status_var,
                 font=('Microsoft YaHei', 9), anchor='w', fg='#27ae60')
        self.cmd_status_label.pack(fill='x', padx=10)
        self.selected_file = None
        
        # 底部：本地服务器信息
        local_info_frame = tk.LabelFrame(self.root, text=' 本地服务器信息 ', font=('Microsoft YaHei', 9, 'bold'))
        local_info_frame.pack(fill='x', padx=5, pady=(0, 2), side='bottom')
        
        local_grid = tk.Frame(local_info_frame)
        local_grid.pack(padx=8, pady=4)
        
        # 获取本地信息
        import platform
        local_ip = _get_local_ip()
        try:
            import uuid as _uuid
            local_mac = ':'.join([f'{b:02x}' for b in _uuid.getnode().to_bytes(6, 'big')])
        except:
            local_mac = '未知'
        
        local_items = [
            ('主机名', platform.node()),
            ('IP地址', local_ip),
            ('MAC地址', local_mac),
            ('系统', f'{platform.system()} {platform.release()}'),
            ('架构', platform.machine()),
        ]
        for i, (k, v) in enumerate(local_items):
            tk.Label(local_grid, text=f'{k}:', font=('Microsoft YaHei', 8), fg='#7f8c8d', anchor='e', width=7
                    ).grid(row=0, column=i*2, sticky='e', padx=(4, 1))
            tk.Label(local_grid, text=v, font=('Microsoft YaHei', 8), fg='#2c3e50', anchor='w'
                    ).grid(row=0, column=i*2+1, sticky='w', padx=(0, 8))
        
        # 底部状态栏
        status_bar = tk.Frame(self.root, bg='#34495e', height=28)
        status_bar.pack(fill='x', side='bottom')
        status_bar.pack_propagate(False)
        
        self.lbl_server = tk.Label(status_bar, text='', font=('Microsoft YaHei', 9), fg='white', bg='#34495e', anchor='w')
        self.lbl_server.pack(side='left', padx=10)
        self.lbl_online = tk.Label(status_bar, text='', font=('Microsoft YaHei', 9), fg='#2ecc71', bg='#34495e', anchor='w')
        self.lbl_online.pack(side='left', padx=20)
        self.lbl_service = tk.Label(status_bar, text='服务运行中', font=('Microsoft YaHei', 9), fg='#2ecc71', bg='#34495e', anchor='w')
        self.lbl_service.pack(side='right', padx=10)
    
    def _start_refresh(self):
        """启动定时刷新"""
        self._refresh_devices()
        self._refresh_after_id = self.root.after(5000, self._start_refresh)
    
    def _refresh_devices(self):
        """刷新设备列表"""
        # 复制_clients数据，避免线程问题
        clients_copy = dict(_clients)
        now = datetime.datetime.now()
        
        print(f'[GUI] 刷新设备列表，当前{len(clients_copy)}个设备')
        
        # 清除现有设备卡片
        for widget in self.device_list_frame.winfo_children():
            widget.destroy()
        
        online_count = 0
        for cid, info in clients_copy.items():
            print(f'[GUI] 设备 {cid}: cpu={info.get("cpu_percent", "N/A")}, mem={info.get("memory_percent", "N/A")}, disk={info.get("disk_percent", "N/A")}')
            last_seen = info.get('last_seen', now)
            if isinstance(last_seen, str):
                try:
                    last_seen = datetime.datetime.strptime(last_seen, '%Y-%m-%d %H:%M:%S')
                except:
                    last_seen = now - datetime.timedelta(days=1)
            online = (now - last_seen).total_seconds() < 10
            
            if online:
                online_count += 1
            
            # 根据在线状态设置卡片背景色
            if online:
                card_bg = '#ffeaa7' if cid == self.selected_client_id else '#d5f5e3'
            else:
                card_bg = '#ffeaa7' if cid == self.selected_client_id else 'white'
            
            # 设备卡片
            card = tk.Frame(self.device_list_frame, bg=card_bg, relief='raised', bd=1)
            card.pack(fill='x', padx=5, pady=3)
            
            # 选中效果
            if cid == self.selected_client_id:
                card.config(relief='raised', bd=2)
            
            # 设备信息
            hostname = info.get('hostname', '未知')
            ip = info.get('ip', '')
            alias = _device_alias.get(cid, '')
            
            # 左侧状态圆点+在线/离线文字
            status_frame = tk.Frame(card, bg=card_bg)
            status_frame.pack(side='left', padx=(8, 2), pady=5)
            dot_canvas = tk.Canvas(status_frame, width=12, height=12, bg=card_bg, highlightthickness=0)
            dot_canvas.pack(side='left')
            dot_color = '#27ae60' if online else '#95a5a6'
            dot_canvas.create_oval(1, 1, 11, 11, fill=dot_color, outline='')
            status_text = '在线' if online else '离线'
            status_fg = '#27ae60' if online else '#95a5a6'
            tk.Label(status_frame, text=status_text, font=('Microsoft YaHei', 8),
                    bg=card_bg, fg=status_fg).pack(side='left', padx=(2, 0))
            
            # 文字标签 - 显示主机名+IP+别名换行
            if alias:
                content = f'{hostname}\nIP: {ip}\n[{alias}]'
            else:
                content = f'{hostname}\nIP: {ip}'
            lbl = tk.Label(card, text=content, font=('Microsoft YaHei', 9), 
                          bg=card_bg,
                          anchor='w', justify='left')
            lbl.pack(side='left', fill='x', padx=(0, 0), pady=5)
            
            # 右侧按钮区（先pack，保证固定右侧位置）
            btn_frame = tk.Frame(card, bg=card_bg)
            btn_frame.pack(side='right', padx=(0, 8), pady=5)
            
            # 删除按钮
            del_btn = tk.Label(btn_frame, text='✖', font=('Microsoft YaHei', 10), 
                               bg=card_bg, fg='#e74c3c', cursor='hand2')
            del_btn.pack(side='right', padx=(4, 0))
            
            # 编辑按钮
            edit_btn = tk.Label(btn_frame, text='✏️', font=('Microsoft YaHei', 10), 
                               bg=card_bg, cursor='hand2')
            edit_btn.pack(side='right')
            
            def on_edit(event, cid=cid):
                self._edit_device_alias(cid)
            edit_btn.bind('<Button-1>', on_edit)
            
            def on_delete(event, cid=cid):
                self._delete_device(cid)
            del_btn.bind('<Button-1>', on_delete)
            del_btn.bind('<Enter>', lambda e, w=del_btn: w.config(bg='#fadbd8'))
            del_btn.bind('<Leave>', lambda e, w=del_btn, orig_bg=card_bg: w.config(bg=orig_bg))
            
            # 绑定点击事件
            def on_click(cid=cid):
                self._select_device(cid)
            for widget in [card, lbl, dot_canvas, btn_frame]:
                widget.bind('<Button-1>', lambda e, c=cid: on_click(c))
                widget.bind('<Enter>', lambda e, w=card: w.config(cursor='hand2') if hasattr(w, 'config') else None)
                widget.bind('<Leave>', lambda e, w=card, eb=edit_btn, db=del_btn, dc=dot_canvas, bf=btn_frame, orig_bg=card_bg: (w.config(bg=orig_bg), eb.config(bg=orig_bg), db.config(bg=orig_bg), dc.config(bg=orig_bg), bf.config(bg=orig_bg)) if hasattr(w, 'config') else None)
            
            # edit_btn 悬停效果
            edit_btn.bind('<Enter>', lambda e, w=card, eb=edit_btn: (w.config(cursor='hand2'), eb.config(bg='#f0f0f0')))
            edit_btn.bind('<Leave>', lambda e, w=card, eb=edit_btn, db=del_btn, dc=dot_canvas, bf=btn_frame, orig_bg=card_bg: (w.config(bg=orig_bg), eb.config(bg=orig_bg), db.config(bg=orig_bg), dc.config(bg=orig_bg), bf.config(bg=orig_bg)))
        
        # 更新状态栏
        local_ip = _get_local_ip()
        self.lbl_server.config(text=f'服务器: {local_ip}:8080')
        self.lbl_online.config(text=f'在线设备: {online_count}/{len(clients_copy)}')
        self._last_online_count = online_count
        
        # 更新统计卡片
        total = len(clients_copy)
        offline_count = total - online_count
        self.stat_vars['stat_online'].set(str(online_count))
        self.stat_vars['stat_offline'].set(str(offline_count))
        self.stat_vars['stat_total'].set(str(total))
        
        # 如果有选中的设备，更新详情
        if self.selected_client_id and self.selected_client_id in _clients:
            self._update_device_detail()
    
    def _select_device(self, cid):
        """选择设备"""
        self.selected_client_id = cid
        self._refresh_devices()  # 重新渲染以显示选中效果
    
    def _edit_device_alias(self, cid):
        """编辑设备别名"""
        current_alias = _device_alias.get(cid, '')
        # 创建简单的编辑弹窗
        dialog = tk.Toplevel(self.root)
        dialog.title('编辑设备名称')
        dialog.geometry('350x120')
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 居中显示
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 350) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 120) // 2
        dialog.geometry(f'+{x}+{y}')
        
        hostname = _clients.get(cid, {}).get('hostname', cid)
        tk.Label(dialog, text=f'设备: {hostname}', font=('Microsoft YaHei', 9)).pack(pady=(10, 5))
        
        entry = tk.Entry(dialog, font=('Microsoft YaHei', 10), width=30)
        entry.pack(padx=20)
        entry.insert(0, current_alias)
        entry.select_range(0, 'end')
        entry.focus_set()
        
        def on_confirm():
            new_alias = entry.get().strip()
            if new_alias:
                _device_alias[cid] = new_alias
            elif cid in _device_alias:
                del _device_alias[cid]
            _save_device_alias()
            dialog.destroy()
            self._refresh_devices()
        
        def on_cancel():
            dialog.destroy()
        
        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text='确定', width=8, bg='#27ae60', fg='white', command=on_confirm).pack(side='left', padx=5)
        tk.Button(btn_frame, text='取消', width=8, command=on_cancel).pack(side='left', padx=5)
        
        entry.bind('<Return>', lambda e: on_confirm())
        entry.bind('<Escape>', lambda e: on_cancel())
    
    def _delete_device(self, cid):
        """删除设备"""
        hostname = _clients.get(cid, {}).get('hostname', cid)
        alias = _device_alias.get(cid, '')
        display = alias if alias else hostname
        # 确认弹窗
        dialog = tk.Toplevel(self.root)
        dialog.title('删除设备')
        dialog.geometry('300x110')
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 300) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 110) // 2
        dialog.geometry(f'+{x}+{y}')
        
        tk.Label(dialog, text=f'确定删除设备 "{display}" ？', font=('Microsoft YaHei', 10)).pack(pady=(15, 10))
        
        def on_confirm():
            if cid in _clients:
                del _clients[cid]
            if cid in _device_alias:
                del _device_alias[cid]
                _save_device_alias()
            if self.selected_client_id == cid:
                self.selected_client_id = None
            dialog.destroy()
            self._refresh_devices()
        
        def on_cancel():
            dialog.destroy()
        
        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=5)
        tk.Button(btn_frame, text='删除', width=8, bg='#e74c3c', fg='white', command=on_confirm).pack(side='left', padx=5)
        tk.Button(btn_frame, text='取消', width=8, command=on_cancel).pack(side='left', padx=5)
    
    def _update_device_detail(self, info=None):
        """更新设备详情 - 直接从_clients全局变量读取最新数据"""
        # 直接从全局变量读取最新数据，不依赖传入的info参数
        if not self.selected_client_id or self.selected_client_id not in _clients:
            return
        
        live_info = _clients[self.selected_client_id]
        
        cpu_raw = live_info.get('cpu_percent', 0)
        mem_raw = live_info.get('memory_percent', 0)
        disk_raw = live_info.get('disk_percent', 0)
        
        # 系统状态转换
        try:
            cpu = float(cpu_raw) if cpu_raw is not None else 0.0
        except (ValueError, TypeError):
            cpu = 0.0
        try:
            mem = float(mem_raw) if mem_raw is not None else 0.0
        except (ValueError, TypeError):
            mem = 0.0
        try:
            disk = float(disk_raw) if disk_raw is not None else 0.0
        except (ValueError, TypeError):
            disk = 0.0
        
        # 更新标题和基本信息
        hostname = live_info.get('hostname', '未知')
        alias = _device_alias.get(self.selected_client_id, '')
        display_name = f'{alias}（{hostname}）' if alias else hostname
        self.detail_title.config(text=f'设备详情 - {display_name}')
        self.info_labels['hostname'].config(text=hostname)
        for key, label in [('ip', 'IP地址'), ('os', '操作系统'), ('os_version', '系统版本'), ('arch', '架构')]:
            self.info_labels[key].config(text=live_info.get(key, '-'))
        # mac 字段单独处理（使用Entry控件，需先切换状态再设置值）
        mac_value = live_info.get('mac', '-')
        self.info_labels['mac'].config(state='normal')
        self.info_labels['mac'].delete(0, 'end')
        self.info_labels['mac'].insert(0, mac_value)
        self.info_labels['mac'].config(state='readonly')
        
        # 更新系统状态
        self.cpu_var.set(f'{cpu:.1f}%')
        self.cpu_progress['value'] = cpu
        self.mem_var.set(f'{mem:.1f}%')
        self.mem_progress['value'] = mem
        self.disk_var.set(f'{disk:.1f}%')
        self.disk_progress['value'] = disk
    
    def _send_command(self, cmd):
        """发送命令到选中设备"""
        if not self.selected_client_id:
            self.cmd_status_var.set('⚠️ 请先选择设备')
            self.cmd_status_label.config(fg='#f39c12')
            self.root.after(3000, lambda: self.cmd_status_var.set(''))
            return
        
        import urllib.request
        import urllib.error
        
        try:
            local_ip = _get_local_ip()
            url = f'http://{local_ip}:8080/api/command'
            data = json.dumps({
                'target_ids': [self.selected_client_id],
                'cmd': cmd
            }).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                self.cmd_status_var.set(f'✅ 指令已发送: {cmd}')
                self.cmd_status_label.config(fg='#27ae60')
                self.root.after(3000, lambda: self.cmd_status_var.set(''))
        except Exception as e:
            self.cmd_status_var.set(f'❌ 发送失败: {e}')
            self.cmd_status_label.config(fg='#e74c3c')
            self.root.after(5000, lambda: self.cmd_status_var.set(''))
    
    def _cmd_shutdown(self):
        self._send_command('shutdown')
    
    def _cmd_restart(self):
        self._send_command('restart')
    
    def _cmd_volume_up(self):
        self._send_command('volume:up')
    
    def _cmd_volume_down(self):
        self._send_command('volume:down')
    
    def _cmd_mute(self):
        self._send_command('mute')
    
    def _cmd_unmute(self):
        self._send_command('unmute')
    
    def _gen_activation_key(self):
        """生成注册码工具"""
        dlg = tk.Toplevel(self.root)
        dlg.title('注册码生成工具')
        dlg.geometry('420x220')
        dlg.resizable(False, False)
        
        tk.Label(dlg, text='注册码生成', font=('Microsoft YaHei', 14, 'bold')).pack(pady=(15, 10))
        tk.Label(dlg, text='请输入客户端序列号：', font=('Microsoft YaHei', 9)).pack(padx=20, anchor='w')
        
        var_serial = tk.StringVar()
        tk.Entry(dlg, textvariable=var_serial, width=30, font=('Consolas', 11)).pack(padx=20, fill='x')
        
        result_var = tk.StringVar(value='')
        tk.Label(dlg, textvariable=result_var, font=('Consolas', 12, 'bold'), fg='#27ae60').pack(pady=10)
        
        def gen():
            serial = var_serial.get().strip().upper()
            if not serial:
                messagebox.showwarning('提示', '请输入序列号')
                return
            key = _generate_activation_key(serial)
            result_var.set(f'注册码: {key}')
            dlg.clipboard_clear()
            dlg.clipboard_append(key)
        
        tk.Button(dlg, text='生成并复制', command=gen, bg='#8e44ad', fg='white',
                 font=('Microsoft YaHei', 10, 'bold'), width=15).pack(pady=5)
    
    def _cmd_remote_desktop(self):
        """启动远程桌面"""
        if not self.selected_client_id:
            self.cmd_status_var.set('⚠️ 请先选择设备')
            self.cmd_status_label.config(fg='#f39c12')
            self.root.after(3000, lambda: self.cmd_status_var.set(''))
            return
        
        client_info = _clients.get(self.selected_client_id, {})
        client_ip = client_info.get('ip', '')
        if not client_ip:
            self.cmd_status_var.set('⚠️ 无法获取设备IP')
            self.cmd_status_label.config(fg='#f39c12')
            self.root.after(3000, lambda: self.cmd_status_var.set(''))
            return
        
        # 发送启动远程桌面指令
        try:
            local_ip = _get_local_ip()
            url = f'http://{local_ip}:8080/api/command'
            data = json.dumps({
                'target_ids': [self.selected_client_id],
                'cmd': 'start_remote_desktop',
                'extra': {'port': 5901}
            }).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read().decode('utf-8'))
            
            # 等待客户端服务启动
            time.sleep(1)
            
            # 打开查看器（传入显示模式）
            display_mode = '全屏' if self.rdp_fullscreen_var.get() else '最大化窗口'
            RemoteDesktopViewer(self.root, client_ip, self.selected_client_id, local_ip, display_mode=display_mode)
            self.cmd_status_var.set('✅ 远程桌面已启动')
            self.cmd_status_label.config(fg='#27ae60')
            self.root.after(3000, lambda: self.cmd_status_var.set(''))
        except Exception as e:
            self.cmd_status_var.set(f'❌ 远程桌面启动失败: {e}')
            self.cmd_status_label.config(fg='#e74c3c')
            self.root.after(5000, lambda: self.cmd_status_var.set(''))
    
    def _select_file(self):
        """选择要发送的文件"""
        path = filedialog.askopenfilename(title='选择要发送的文件')
        if path:
            self.selected_file = path
            self.file_path_var.set(os.path.basename(path))
    
    def _send_file(self):
        """发送文件到选中设备"""
        if not self.selected_client_id:
            self.transfer_status_var.set('⚠️ 请先选择设备')
            self.root.after(3000, lambda: self.transfer_status_var.set('就绪'))
            return
        
        if not self.selected_client_id or not self.selected_file:
            self.transfer_status_var.set('⚠️ 请选择文件和目标设备')
            self.root.after(3000, lambda: self.transfer_status_var.set('就绪'))
            return
        
        import urllib.request
        import urllib.error
        
        try:
            local_ip = _get_local_ip()
            
            # 复制文件到uploads目录，用UUID重命名避免中文文件名编码问题
            import uuid as _uuid
            filename = os.path.basename(self.selected_file)
            ext = os.path.splitext(filename)[1]  # 保留扩展名
            uuid_name = f'{_uuid.uuid4().hex[:12]}{ext}'
            dest_path = os.path.join(UPLOAD_DIR, uuid_name)
            shutil.copy2(self.selected_file, dest_path)
            
            # 保存文件名映射（UUID -> 原始文件名）
            _file_name_map[uuid_name] = filename
            
            file_size = os.path.getsize(dest_path)
            # 用POST下载接口，文件名在body中传递，支持中文
            download_url = f'http://{local_ip}:8080/api/file/download'
            
            # 发送文件传输指令
            url = f'http://{local_ip}:8080/api/command'
            data = json.dumps({
                'target_ids': [self.selected_client_id],
                'cmd': 'file_transfer',
                'extra': {
                    'file_name': filename,            # 原始文件名，客户端用于保存
                    'file_size': file_size,
                    'download_url': download_url,
                    'server_file_name': uuid_name     # 服务器上的UUID文件名
                }
            }).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                self.transfer_status_var.set(f'✅ 发送成功，对方已接收完毕: {filename}')
                self.root.after(8000, lambda: self.transfer_status_var.set('就绪'))
        except Exception as e:
            self.transfer_status_var.set(f'❌ 发送失败: {e}')
            self.root.after(5000, lambda: self.transfer_status_var.set('就绪'))
    
    def run(self):
        self.root.mainloop()


# ===== 启动 =====
def main():
    import uvicorn
    import asyncio
    
    # 加载设备别名
    _load_device_alias()
    
    # 启动UDP广播
    t_broadcast = threading.Thread(target=_broadcast_server, daemon=True)
    t_broadcast.start()
    
    # 启动FastAPI服务（后台线程，用Config+Server确保事件循环正确）
    def run_server():
        try:
            config = uvicorn.Config(app, host='0.0.0.0', port=8080, log_level='info')
            server = uvicorn.Server(config)
            # 在新的事件循环中运行
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(server.serve())
        except Exception as e:
            print(f'[服务器] FastAPI启动失败: {e}')
    
    t_server = threading.Thread(target=run_server, daemon=True)
    t_server.start()
    
    # 等待服务器启动
    import socket as _socket
    for i in range(15):
        time.sleep(0.5)
        try:
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect(('127.0.0.1', 8080))
            s.close()
            print('[服务器] FastAPI启动成功，端口8080已监听')
            break
        except:
            if i == 14:
                print('[服务器] 警告：FastAPI可能未成功启动')
    
    local_ip = _get_local_ip()
    print('=' * 50)
    print('  坤展成终端管理系统 — 服务器端 v1.3-58')
    print(f'  管理界面: http://{local_ip}:8080')
    print(f'  UDP广播端口: {BROADCAST_PORT}')
    print('  通信协议: HTTP轮询（稳定可靠）')
    print('=' * 50)
    
    # 启动tkinter GUI
    gui = ServerGUI()
    gui.run()

if __name__ == '__main__':
    main()
