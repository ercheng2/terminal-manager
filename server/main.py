#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
坤展成终端管理系统 — 服务器端
集中管理所有终端设备，WebSocket通信，Web管理界面
"""

import os, sys, json, time, asyncio, datetime, uuid
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ===== 路径适配 =====
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_FILE = os.path.join(BASE_DIR, 'devices.json')

# ===== 数据存储（JSON文件，轻量级） =====
def load_devices():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"devices": {}, "commands_log": []}

def save_devices(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ===== 终端连接管理 =====
class ConnectionManager:
    def __init__(self):
        self.active_connections = {}  # hostname -> websocket
        self.device_info = {}         # hostname -> device info

    async def connect(self, websocket, hostname):
        self.active_connections[hostname] = websocket
        # 更新设备状态
        data = load_devices()
        if hostname in data['devices']:
            data['devices'][hostname]['status'] = 'online'
            data['devices'][hostname]['last_seen'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        else:
            data['devices'][hostname] = {
                'status': 'online',
                'first_seen': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'last_seen': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            }
        save_devices(data)

    async def disconnect(self, hostname):
        if hostname in self.active_connections:
            del self.active_connections[hostname]
        data = load_devices()
        if hostname in data['devices']:
            data['devices'][hostname]['status'] = 'offline'
            data['devices'][hostname]['last_seen'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            save_devices(data)

    async def send_command(self, hostname, command_data):
        if hostname in self.active_connections:
            ws = self.active_connections[hostname]
            await ws.send(json.dumps(command_data))
            return True
        return False

    async def broadcast_command(self, command_data):
        results = {}
        for hostname, ws in self.active_connections.items():
            try:
                await ws.send(json.dumps(command_data))
                results[hostname] = 'sent'
            except:
                results[hostname] = 'failed'
        return results

    def get_online_devices(self):
        return list(self.active_connections.keys())

manager = ConnectionManager()

# ===== FastAPI =====
app = FastAPI(title='坤展成终端管理系统')

@app.get('/')
async def index():
    return HTMLResponse(MANAGER_HTML)

@app.get('/api/devices')
async def get_devices():
    data = load_devices()
    # 合并实时在线状态
    for hostname in data['devices']:
        data['devices'][hostname]['status'] = 'online' if hostname in manager.active_connections else 'offline'
    return data

@app.post('/api/command')
async def send_command(request: Request):
    body = await request.json()
    targets = body.get('targets', [])  # hostname列表，空=全部在线
    cmd = body.get('cmd', '')
    extra = body.get('extra', {})

    task_id = uuid.uuid4().hex[:8]
    command_data = {
        'type': 'command',
        'task_id': task_id,
        'cmd': cmd,
        **extra,
    }

    # 记录日志
    data = load_devices()
    data['commands_log'].append({
        'task_id': task_id,
        'cmd': cmd,
        'targets': targets or manager.get_online_devices(),
        'time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'status': 'sent',
    })
    if len(data['commands_log']) > 500:
        data['commands_log'] = data['commands_log'][-500:]
    save_devices(data)

    if not targets:
        # 广播给所有在线设备
        results = await manager.broadcast_command(command_data)
    else:
        results = {}
        for hostname in targets:
            success = await manager.send_command(hostname, command_data)
            results[hostname] = 'sent' if success else 'offline'

    return {'task_id': task_id, 'results': results}

@app.get('/api/logs')
async def get_logs():
    data = load_devices()
    return {'logs': data.get('commands_log', [])[-50:]}

# ===== WebSocket：终端连接 =====
@app.websocket('/ws/client')
async def ws_client(websocket: WebSocket):
    await websocket.accept()
    hostname = None
    try:
        # 第一条消息是注册信息
        msg = await asyncio.wait_for(websocket.receive_text(), timeout=30)
        data = json.loads(msg)
        if data.get('type') == 'register':
            hostname = data.get('hostname', 'unknown')
            manager.device_info[hostname] = data
            await manager.connect(websocket, hostname)

        # 持续监听
        while True:
            msg = await websocket.receive_text()
            try:
                resp = json.loads(msg)
                # 处理终端返回的结果
                if resp.get('type') == 'result':
                    data = load_devices()
                    for log in data['commands_log']:
                        if log['task_id'] == resp.get('task_id'):
                            log['status'] = resp.get('status', 'unknown')
                            log['response'] = resp.get('msg', '')
                            break
                    save_devices(data)
            except:
                pass
    except WebSocketDisconnect:
        pass
    except:
        pass
    finally:
        if hostname:
            await manager.disconnect(hostname)


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
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
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
                <th>状态</th><th>主机名</th><th>IP</th><th>系统</th><th>架构</th><th>最后在线</th><th>操作</th>
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
function refresh() {
    fetch('/api/devices').then(r=>r.json()).then(data => {
        var devices = data.devices || {};
        var html = '', online = 0, offline = 0;
        var hostnames = Object.keys(devices).sort();
        for (var h of hostnames) {
            var d = devices[h];
            var isOnline = d.status === 'online';
            if (isOnline) online++; else offline++;
            var info = d.info || {};
            html += '<tr><td><input type="checkbox" class="dev-check" value="'+h+'" '+(isOnline?'':'disabled')+'></td>';
            html += '<td><span class="status-dot '+(isOnline?'online':'offline')+'"></span>'+(isOnline?'在线':'离线')+'</td>';
            html += '<td>'+h+'</td>';
            html += '<td>'+(info.ip||'-')+'</td>';
            html += '<td>'+(info.os||'-')+' '+(info.os_version||'')+'</td>';
            html += '<td>'+(info.arch||'-')+'</td>';
            html += '<td>'+(d.last_seen||'-')+'</td>';
            html += '<td>'+(isOnline?'<button class="btn btn-primary" onclick="sendCmdSingle(\\''+h+'\\',\\'status\\')">状态</button>':'-')+'</td></tr>';
        }
        document.getElementById('deviceTable').innerHTML = html;
        document.getElementById('onlineCount').textContent = online;
        document.getElementById('offlineCount').textContent = offline;
        document.getElementById('totalCount').textContent = online + offline;
    });
    fetch('/api/logs').then(r=>r.json()).then(data => {
        var logs = (data.logs || []).reverse();
        var html = '';
        for (var l of logs.slice(0, 30)) {
            var statusColor = l.status==='success'?'#27ae60':l.status==='failed'?'#e74c3c':'#f39c12';
            html += '<tr><td>'+(l.time||'-')+'</td><td>'+(l.cmd||'-')+'</td>';
            html += '<td>'+(l.targets||[]).join(', ')+'</td>';
            html += '<td style="color:'+statusColor+'">'+(l.status||'-')+'</td>';
            html += '<td>'+(l.response||'-')+'</td></tr>';
        }
        document.getElementById('logTable').innerHTML = html;
    });
}

function toggleAll() {
    var checked = document.getElementById('selectAll').checked;
    document.querySelectorAll('.dev-check').forEach(c => { if (!c.disabled) c.checked = checked; });
}

function getSelected() {
    var targets = [];
    document.querySelectorAll('.dev-check:checked').forEach(c => targets.push(c.value));
    return targets;
}

function sendCmd(cmd) {
    var targets = getSelected();
    if (targets.length === 0) { alert('请选择设备'); return; }
    fetch('/api/command', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({targets: targets, cmd: cmd})
    }).then(r=>r.json()).then(data => {
        alert('指令已发送：' + cmd + '\\n任务ID：' + data.task_id);
        setTimeout(refresh, 2000);
    });
}

function sendCmdSingle(hostname, cmd) {
    fetch('/api/command', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({targets: [hostname], cmd: cmd})
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
    print('=' * 50)
    print('  坤展成终端管理系统 — 服务器端')
    print('  管理界面: http://127.0.0.1:8080')
    print('  局域网访问: http://本机IP:8080')
    print('=' * 50)
    uvicorn.run(app, host='0.0.0.0', port=8080)
