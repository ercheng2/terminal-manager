#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
坤展成终端管理系统 — 服务器端 v1.3-58
基于HTTP轮询通信，更稳定可靠
支持tkinter桌面GUI + 文件传输功能
v1.3-58: 设备列表添加编辑名称功能
"""

import os, sys, json, time, datetime, uuid, threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import shutil

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

app = FastAPI(title='坤展成终端管理系统')

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
    print(f'[轮询-GET] client_id={client_id}, cpu={cpu_percent}, mem={memory_percent}, disk={disk_percent}')
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
        print(f'[轮询-POST] client_id={client_id}, cpu={cpu_percent}, mem={memory_percent}, disk={disk_percent}')
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


# ===== Tkinter GUI =====
class ServerGUI:
    def __init__(self):
        self.root = tk.Tk()
        icon_path = resource_path('icon.ico')
        if os.path.exists(icon_path):
            self.root.iconbitmap(icon_path)
        self.root.title('坤展成终端管理系统 v1.3-53 - 服务器端')
        self.root.geometry('1100x700')
        self.root.minsize(900, 600)
        
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
        tk.Label(title_frame, text='坤展成终端管理系统 v1.3-53 - 服务器端',
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
        
        # 基本信息区域
        info_frame = tk.LabelFrame(right_frame, text=' 基本信息 ', font=('Microsoft YaHei', 10, 'bold'))
        info_frame.pack(fill='x', padx=10, pady=5)
        
        self.info_labels = {}
        info_grid = tk.Frame(info_frame)
        info_grid.pack(padx=10, pady=8)
        fields = [('主机名', 'hostname'), ('IP地址', 'ip'), ('MAC地址', 'mac'),
                  ('操作系统', 'os'), ('系统版本', 'os_version'), ('架构', 'arch')]
        for i, (label, key) in enumerate(fields):
            row, col = i // 2, (i % 2) * 2
            tk.Label(info_grid, text=f'{label}：', font=('Microsoft YaHei', 9), anchor='e', width=10).grid(row=row, column=col, sticky='e', pady=2)
            if key == 'mac':
                self.info_labels[key] = tk.Entry(info_grid, font=('Microsoft YaHei', 9), width=25, relief='sunken', bg='white')
                self.info_labels[key].grid(row=row, column=col+1, sticky='w', pady=2, padx=(5, 15))
                self.info_labels[key].config(state='readonly')
            else:
                self.info_labels[key] = tk.Label(info_grid, text='-', font=('Microsoft YaHei', 9), anchor='w', width=25, relief='sunken', bg='white')
                self.info_labels[key].grid(row=row, column=col+1, sticky='w', pady=2, padx=(5, 15))
        
        # 系统状态区域
        status_frame = tk.LabelFrame(right_frame, text=' 系统状态 ', font=('Microsoft YaHei', 10, 'bold'))
        status_frame.pack(fill='x', padx=10, pady=5)
        
        status_grid = tk.Frame(status_frame)
        status_grid.pack(padx=10, pady=8)
        
        # CPU
        tk.Label(status_grid, text='CPU使用率：', font=('Microsoft YaHei', 9)).grid(row=0, column=0, sticky='e', pady=3)
        self.cpu_var = tk.StringVar(value='0%')
        tk.Label(status_grid, textvariable=self.cpu_var, font=('Microsoft YaHei', 9), width=8, relief='sunken', bg='white').grid(row=0, column=1, sticky='w', padx=5)
        self.cpu_progress = ttk.Progressbar(status_grid, length=150, mode='determinate', maximum=100)
        self.cpu_progress.grid(row=0, column=2, padx=5)
        
        # 内存
        tk.Label(status_grid, text='内存使用率：', font=('Microsoft YaHei', 9)).grid(row=1, column=0, sticky='e', pady=3)
        self.mem_var = tk.StringVar(value='0%')
        tk.Label(status_grid, textvariable=self.mem_var, font=('Microsoft YaHei', 9), width=8, relief='sunken', bg='white').grid(row=1, column=1, sticky='w', padx=5)
        self.mem_progress = ttk.Progressbar(status_grid, length=150, mode='determinate', maximum=100)
        self.mem_progress.grid(row=1, column=2, padx=5)
        
        # 磁盘
        tk.Label(status_grid, text='磁盘使用率：', font=('Microsoft YaHei', 9)).grid(row=2, column=0, sticky='e', pady=3)
        self.disk_var = tk.StringVar(value='0%')
        tk.Label(status_grid, textvariable=self.disk_var, font=('Microsoft YaHei', 9), width=8, relief='sunken', bg='white').grid(row=2, column=1, sticky='w', padx=5)
        self.disk_progress = ttk.Progressbar(status_grid, length=150, mode='determinate', maximum=100)
        self.disk_progress.grid(row=2, column=2, padx=5)
        
        # 操作按钮区域
        btn_frame = tk.LabelFrame(right_frame, text=' 远程控制 ', font=('Microsoft YaHei', 10, 'bold'))
        btn_frame.pack(fill='x', padx=10, pady=5)
        
        btn_grid = tk.Frame(btn_frame)
        btn_grid.pack(padx=10, pady=8)
        buttons = [
            ('关机', '#e74c3c', self._cmd_shutdown),
            ('重启', '#f39c12', self._cmd_restart),
            ('音量+', '#3498db', self._cmd_volume_up),
            ('音量-', '#3498db', self._cmd_volume_down),
            ('静音', '#3498db', self._cmd_mute),
            ('取消静音', '#3498db', self._cmd_unmute),
        ]
        for i, (text, color, cmd) in enumerate(buttons):
            row, col = i // 3, i % 3
            tk.Button(btn_grid, text=text, width=10, bg=color, fg='white', font=('Microsoft YaHei', 9, 'bold'),
                     command=cmd).grid(row=row, column=col, padx=5, pady=5)
        
        # 远程控制状态提示
        self.cmd_status_var = tk.StringVar(value='')
        self.cmd_status_label = tk.Label(btn_frame, textvariable=self.cmd_status_var, font=('Microsoft YaHei', 9), anchor='w', fg='#27ae60')
        self.cmd_status_label.pack(fill='x', padx=10, pady=(0, 5))
        
        # 文件传输区域
        file_frame = tk.LabelFrame(right_frame, text=' 文件传输 ', font=('Microsoft YaHei', 10, 'bold'))
        file_frame.pack(fill='x', padx=10, pady=5)
        
        file_grid = tk.Frame(file_frame)
        file_grid.pack(padx=10, pady=8)
        
        tk.Button(file_grid, text='选择文件', width=10, command=self._select_file).grid(row=0, column=0, padx=5, sticky='w')
        self.file_path_var = tk.StringVar(value='未选择文件')
        tk.Label(file_grid, textvariable=self.file_path_var, font=('Microsoft YaHei', 8), anchor='w',
                bg='white', relief='sunken', width=40).grid(row=0, column=1, padx=5, sticky='ew')
        tk.Button(file_grid, text='发送文件', width=10, bg='#27ae60', fg='white', font=('Microsoft YaHei', 9, 'bold'),
                 command=self._send_file).grid(row=0, column=2, padx=5)
        
        # 传输状态
        self.transfer_status_var = tk.StringVar(value='就绪')
        tk.Label(file_grid, text='状态：', font=('Microsoft YaHei', 9)).grid(row=1, column=0, sticky='w', pady=(5, 0))
        tk.Label(file_grid, textvariable=self.transfer_status_var, font=('Microsoft YaHei', 9), anchor='w',
                fg='#27ae60').grid(row=1, column=1, columnspan=2, sticky='w', pady=(5, 0))
        
        self.selected_file = None
        
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
                card_bg = '#abebc6' if cid == self.selected_client_id else '#d5f5e3'
            else:
                card_bg = '#e8f4f8' if cid == self.selected_client_id else 'white'
            
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
            
            # 左侧状态圆点（Canvas）
            dot_canvas = tk.Canvas(card, width=14, height=14, bg=card_bg, highlightthickness=0)
            dot_canvas.pack(side='left', padx=(8, 2), pady=5)
            dot_color = '#27ae60' if online else '#95a5a6'
            dot_canvas.create_oval(2, 2, 12, 12, fill=dot_color, outline='')
            
            # 文字标签 - 只显示主机名+IP
            content = f'{hostname}\nIP: {ip}'
            lbl = tk.Label(card, text=content, font=('Microsoft YaHei', 9), 
                          bg=card_bg,
                          anchor='w', justify='left')
            lbl.pack(side='left', fill='x', padx=(0, 0), pady=5)
            
            # 右侧按钮区
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
            
            # 设备名称（编辑按钮左侧显示）
            if alias:
                alias_label = tk.Label(btn_frame, text=alias, font=('Microsoft YaHei', 9, 'bold'), 
                                      bg=card_bg, fg='#2c3e50', anchor='e')
                alias_label.pack(side='right', padx=(8, 4))
            
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
                self.transfer_status_var.set(f'✅ 发送成功: {filename}')
                self.root.after(3000, lambda: self.transfer_status_var.set('就绪'))
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
