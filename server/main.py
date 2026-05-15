#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
坤展成终端管理系统 — 服务器端 v1.2
基于HTTP轮询通信，更稳定可靠
"""

import os, sys, json, time, datetime, uuid, threading
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse

# ===== 路径适配 =====
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_FILE = os.path.join(BASE_DIR, 'devices.json')

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
app = FastAPI(title='坤展成终端管理系统')

# 内存中的数据
_clients = {}  # client_id -> client_info
_commands = {}  # task_id -> command_info

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

        _save_persistent()
        return {'client_id': client_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get('/api/client/poll')
async def client_poll(client_id: str):
    """客户端轮询指令"""
    if client_id not in _clients:
        raise HTTPException(status_code=400, detail='未注册')

    # 更新最后在线时间
    _clients[client_id]['last_seen'] = datetime.datetime.now()

    # 获取该客户端的待处理指令
    commands = []
    for tid, cmd in _commands.items():
        if cmd.get('target_id') == client_id and cmd.get('status') == 'pending':
            commands.append(cmd)

    return {'client_id': client_id, 'commands': commands}

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

# ===== 启动 =====
if __name__ == '__main__':
    import uvicorn
    local_ip = _get_local_ip()
    print('=' * 50)
    print('  坤展成终端管理系统 — 服务器端 v1.2')
    print(f'  管理界面: http://{local_ip}:8080')
    print(f'  UDP广播端口: {BROADCAST_PORT}')
    print('  通信协议: HTTP轮询（稳定可靠）')
    print('=' * 50)
    # 启动UDP广播
    t = threading.Thread(target=_broadcast_server, daemon=True)
    t.start()
    uvicorn.run(app, host='0.0.0.0', port=8080)
