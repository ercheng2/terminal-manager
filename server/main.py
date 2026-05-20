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







# 挂载静态文件目录（兼容PyInstaller打包）



_static_dir = resource_path('static')



if not os.path.isdir(_static_dir):



    # 运行目录下也没有，尝试当前工作目录



    _static_dir = os.path.join(os.path.abspath('.'), 'static')



if os.path.isdir(_static_dir):



    app.mount("/static", StaticFiles(directory=_static_dir), name="static")



else:



    # 创建空static目录避免启动报错



    os.makedirs(_static_dir, exist_ok=True)



    app.mount("/static", StaticFiles(directory=_static_dir), name="static")







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
<meta name="viewport" content="width=1920,height=1080">
<title>坤展成终端管理系统v1.4.0-服务器端</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1920px;height:1080px;overflow:hidden;font-family:"Microsoft YaHei",Consolas,sans-serif;background:#0a0e1a}
.bg{position:fixed;top:0;left:0;width:1920px;height:1080px;background:url(/static/bg.jpg) no-repeat center center;background-size:cover;z-index:0}
.ov{position:absolute;top:0;left:0;width:1920px;height:1080px;z-index:1}
.sub{position:absolute;top:56px;left:50%;transform:translateX(-50%);font-size:13px;color:#7aa8cc;letter-spacing:2px;white-space:nowrap}
.ring{position:absolute;width:160px;height:160px;display:flex;flex-direction:column;align-items:center;justify-content:center;pointer-events:none}
.ring .n{font-size:48px;font-weight:bold;line-height:1}
.ring .l{font-size:14px;margin-top:6px;opacity:.9}
.rg{top:241px;left:366px;color:#00ff88;text-shadow:0 0 15px #00ff88}
.rr{top:241px;left:889px;color:#ff4466;text-shadow:0 0 15px #ff4466}
.rb{top:241px;left:1394px;color:#00bbff;text-shadow:0 0 15px #00bbff}
.dl{position:absolute;left:80px;top:160px;width:445px;height:870px;overflow-y:auto}
.dl::-webkit-scrollbar{width:4px}
.dl::-webkit-scrollbar-thumb{background:#0066aa;border-radius:2px}
.di{display:flex;align-items:center;padding:10px 12px;cursor:pointer;border-bottom:1px solid rgba(0,100,180,.2);transition:background .2s}
.di:hover{background:rgba(0,180,255,.1)}
.di.sel{background:rgba(0,180,255,.18);border-left:3px solid #00d4ff}
.dd{width:10px;height:10px;border-radius:50%;margin-right:10px;flex-shrink:0}
.dd.on{background:#00ff88;box-shadow:0 0 6px #00ff88}
.dd.off{background:#555}
.df{flex:1;overflow:hidden}
.dn{font-size:14px;color:#e0e0e0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dp{font-size:12px;color:#7aa8cc;margin-top:2px}
.dx{width:24px;height:24px;border:1px solid #ff4466;border-radius:4px;color:#ff4466;background:transparent;cursor:pointer;font-size:14px;line-height:22px;text-align:center;flex-shrink:0}
.dx:hover{background:#ff4466;color:#fff}
.ia{position:absolute;left:580px;top:160px;width:1300px;height:450px}
.ig{display:grid;grid-template-columns:1fr 1fr;gap:8px 30px;padding:15px 20px}
.ir{display:flex;align-items:center}
.il{color:#00d4ff;font-size:13px;width:80px;flex-shrink:0}
.iv{color:#e0e0e0;font-size:13px;font-family:Consolas,monospace;background:rgba(0,20,50,.6);padding:4px 10px;border-radius:3px;border:1px solid rgba(0,100,180,.3);flex:1;min-height:24px}
.pa{display:flex;gap:20px;padding:15px 20px;margin-top:10px}
.pi{flex:1}
.pl{font-size:12px;color:#7aa8cc;margin-bottom:4px;display:flex;justify-content:space-between}
.pb{height:16px;background:rgba(0,20,40,.8);border-radius:3px;border:1px solid rgba(0,100,180,.3);overflow:hidden}
.pf{height:100%;border-radius:2px;transition:width .5s}
.fg{background:linear-gradient(90deg,#00cc66,#00ff88)}
.fy{background:linear-gradient(90deg,#ccaa00,#ffdd00)}
.fr{background:linear-gradient(90deg,#cc3333,#ff4466)}
.nd{color:#556;font-size:14px;text-align:center;padding-top:40px}
.ca{position:absolute;left:580px;top:640px;width:595px;height:380px}
.cg{display:flex;flex-direction:column;gap:12px;padding:20px}
.cr{display:flex;gap:12px}
.cb{flex:1;padding:12px 8px;background:transparent;border:1px solid #00d4ff;color:#e0e0e0;font-size:14px;font-family:"Microsoft YaHei",sans-serif;cursor:pointer;border-radius:4px;transition:all .2s}
.cb:hover{background:rgba(0,180,255,.15);box-shadow:0 0 12px rgba(0,180,255,.4)}
.cb.dg{border-color:#ff4466;color:#ff6688}
.cb.dg:hover{background:rgba(255,68,102,.15);box-shadow:0 0 12px rgba(255,68,102,.4)}
.cb.wn{border-color:#ff9933;color:#ffaa55}
.cb.wn:hover{background:rgba(255,153,51,.15);box-shadow:0 0 12px rgba(255,153,51,.4)}
.cb.gn{border-color:#00ff88;color:#00ff88}
.cb.gn:hover{background:rgba(0,255,136,.15);box-shadow:0 0 12px rgba(0,255,136,.4)}
.cb.w3{flex:3}
.fa{position:absolute;left:1198px;top:640px;width:680px;height:380px}
.fc{padding:20px}
.fw{display:flex;gap:10px;align-items:center;margin-bottom:15px}
.fi{flex:1;padding:8px 12px;background:rgba(0,20,50,.6);border:1px solid rgba(0,100,180,.3);color:#e0e0e0;font-size:13px;border-radius:4px}
.fj{padding:8px 16px;background:transparent;border:1px solid #00d4ff;color:#00d4ff;cursor:pointer;border-radius:4px;font-size:13px}
.fj:hover{background:rgba(0,180,255,.15)}
.fs{color:#00ff88;font-size:13px;margin:10px 0}
.fe{padding:10px 30px;background:transparent;border:1px solid #00ff88;color:#00ff88;cursor:pointer;border-radius:4px;font-size:14px;font-weight:bold;float:right}
.fe:hover{background:rgba(0,255,136,.15);box-shadow:0 0 12px rgba(0,255,136,.4)}
.fl{margin-top:15px;max-height:200px;overflow-y:auto;font-size:12px;color:#7aa8cc}
.fl::-webkit-scrollbar{width:3px}
.fl::-webkit-scrollbar-thumb{background:#0066aa}
.sb{position:absolute;bottom:0;left:0;width:100%;height:28px;background:rgba(10,15,30,.85);border-top:1px solid rgba(0,100,180,.3);display:flex;align-items:center;padding:0 20px;font-size:12px;color:#7aa8cc}
.sb .rt{margin-left:auto}
</style>
</head>
<body>
<div class="bg"></div>
<div class="ov">
<div class="sub">北京万乘兄弟科技有限公司 联系电话:18210234280</div>
<div class="ring rg"><div class="n" id="oc">0</div><div class="l">在线设备</div></div>
<div class="ring rr"><div class="n" id="fc2">0</div><div class="l">离线设备</div></div>
<div class="ring rb"><div class="n" id="tc">0</div><div class="l">设备总数</div></div>
<div class="dl" id="dL"></div>
<div class="ia" id="iA">
<div class="nd" id="nD">请选择设备查看详情</div>
<div id="dD" style="display:none">
<div class="ig">
<div class="ir"><span class="il">主机名</span><span class="iv" id="dH">-</span></div>
<div class="ir"><span class="il">操作系统</span><span class="iv" id="dO">-</span></div>
<div class="ir"><span class="il">IP地址</span><span class="iv" id="dI">-</span></div>
<div class="ir"><span class="il">系统版本</span><span class="iv" id="dV">-</span></div>
<div class="ir"><span class="il">MAC地址</span><span class="iv" id="dM">-</span></div>
<div class="ir"><span class="il">架构</span><span class="iv" id="dA">-</span></div>
<div class="ir"><span class="il">最后在线</span><span class="iv" id="dL2">-</span></div>
<div class="ir"><span class="il">状态</span><span class="iv" id="dS">-</span></div>
</div>
<div class="pa">
<div class="pi"><div class="pl"><span>CPU</span><span id="cV">0%</span></div><div class="pb"><div class="pf fg" id="cB" style="width:0%"></div></div></div>
<div class="pi"><div class="pl"><span>内存</span><span id="mV">0%</span></div><div class="pb"><div class="pf fg" id="mB" style="width:0%"></div></div></div>
<div class="pi"><div class="pl"><span>磁盘</span><span id="kV">0%</span></div><div class="pb"><div class="pf fg" id="kB" style="width:0%"></div></div></div>
</div>
</div>
</div>
<div class="ca"><div class="cg">
<div class="cr"><button class="cb gn w3" onclick="sc('remote_desktop')">远程桌面</button></div>
<div class="cr"><button class="cb dg" onclick="sc('shutdown')">关机</button><button class="cb wn" onclick="sc('restart')">重启</button><button class="cb" onclick="sc('mute')">静音</button></div>
<div class="cr"><button class="cb" onclick="sc('unmute')">取消静音</button><button class="cb" onclick="sc('volume:up')">音量+</button><button class="cb" onclick="sc('volume:down')">音量-</button></div>
<div class="cr"><button class="cb w3" onclick="sc('status')">查询状态</button></div>
</div></div>
<div class="fa"><div class="fc">
<div class="fw"><input class="fi" id="fP" placeholder="未选择文件" readonly><button class="fj" onclick="document.getElementById('fI').click()">选择文件</button><input type="file" id="fI" style="display:none" onchange="document.getElementById('fP').value=this.files[0]?this.files[0].name:''"></div>
<div class="fs" id="fS">就绪</div>
<button class="fe" onclick="sf()">发送文件</button>
<div class="fl" id="fL"></div>
</div></div>
<div class="sb"><span>服务器地址: <span id="sA">-</span></span><span class="rt">在线设备: <span id="sO">0</span></span></div>
</div>
<script>
var D=[],sid=null;
function ip(){return location.hostname+":"+location.port}
function rf(){fetch("/api/devices").then(function(r){return r.json()}).then(function(d){D=d.devices||[];rd()}).catch(function(){})}
function rd(){var h="",on=0,of=0;D.forEach(function(d){var o=d.status==="online";if(o)on++;else of++;var s=sid===d.id?" sel":"";h+="<div class=\"di"+s+"\" onclick=\"sd('"+d.id+"')\"><div class=\"dd "+(o?"on":"off")+"\"></div><div class=\"df\"><div class=\"dn\">"+d.hostname+"</div><div class=\"dp\">"+d.ip+"</div>"+(d.remark?"<div class=\"dp\" style=\"color:#8899aa;font-size:11px\">"+d.remark+"</div>":"")+"</div><button class=\"dx\" onclick=\"event.stopPropagation();dd('"+d.id+"')\">X</button></div>"});document.getElementById("dL").innerHTML=h;document.getElementById("oc").textContent=on;document.getElementById("fc2").textContent=of;document.getElementById("tc").textContent=on+of;document.getElementById("sO").textContent=on;if(sid)si(sid)}
function sd(id){sid=id;si(id);rd()}
function si(id){var d=D.find(function(x){return x.id===id});if(!d){document.getElementById("nD").style.display="";document.getElementById("dD").style.display="none";return}document.getElementById("nD").style.display="none";document.getElementById("dD").style.display="";document.getElementById("dH").textContent=d.hostname||"-";document.getElementById("dI").textContent=d.ip||"-";document.getElementById("dM").textContent=d.mac||"-";document.getElementById("dO").textContent=d.os||"-";document.getElementById("dV").textContent=d.os_version||"-";document.getElementById("dA").textContent=d.arch||"-";document.getElementById("dL2").textContent=d.last_seen||"-";document.getElementById("dS").textContent=d.status==="online"?"在线":"离线";sp("c",d.cpu_percent);sp("m",d.memory_percent);sp("k",d.disk_percent)}
function sp(p,v){v=parseFloat(v)||0;document.getElementById(p+"V").textContent=v.toFixed(1)+"%";document.getElementById(p+"B").style.width=v+"%";document.getElementById(p+"B").className="pf "+(v>80?"fr":v>50?"fy":"fg")}
function dd(id){if(!confirm("确定删除该设备？"))return;fetch("/api/devices/"+id,{method:"DELETE"}).then(function(){rf()})}
function sc(cmd){if(!sid){alert("请先选择设备");return}fetch("/api/command",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({target_ids:[sid],cmd:cmd})}).then(function(r){return r.json()}).then(function(){setTimeout(rf,1500)})}
function sf(){if(!sid){alert("请先选择设备");return}var f=document.getElementById("fI").files[0];if(!f){alert("请选择文件");return}document.getElementById("fS").textContent="上传中...";document.getElementById("fS").style.color="#ffaa33";var fd=new FormData();fd.append("file",f);fetch("/api/file/upload",{method:"POST",body:fd}).then(function(r){return r.json()}).then(function(d){if(d.filename)return fetch("/api/command",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({target_ids:[sid],cmd:"download:"+d.filename+":"+f.name})})}).then(function(){document.getElementById("fS").textContent="发送成功";document.getElementById("fS").style.color="#00ff88";document.getElementById("fL").innerHTML+="<div>"+new Date().toLocaleTimeString()+" -> "+f.name+"</div>";setTimeout(function(){document.getElementById("fS").textContent="就绪";document.getElementById("fS").style.color="#00ff88"},3000)}).catch(function(){document.getElementById("fS").textContent="发送失败";document.getElementById("fS").style.color="#ff4466"})}
document.getElementById("sA").textContent=ip();rf();setInterval(rf,3000);
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
        try:
            self.win.iconbitmap('icon.ico')
        except:
            pass



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



        self.canvas.focus_set()

        # 用pynput监听全局键盘，直接转发按键到远程
        self._pynput_keys = set()
        self._pynput_listener = None
        self._start_keyboard_listener()

        # 禁用本地输入法，让按键直接发到远程（远程输入法处理中文）
        try:
            import ctypes
            imm32 = ctypes.windll.imm32
            hwnd = int(self.win.winfo_id())
            imm32.ImmAssociateContext(hwnd, 0)
        except:
            pass



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
        self._current_screen_img = None  # 当前完整屏幕Image，用于增量更新



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



                    # recv_exact 辅助函数
                    def recv_exact(sock, n):
                        data = bytearray()
                        while len(data) < n:
                            chunk = sock.recv(n - len(data))
                            if not chunk:
                                raise ConnectionError("Connection closed")
                            data.extend(chunk)
                        return bytes(data)
                    
                    # 读21字节帧头
                    frame_header = recv_exact(sock, 21)
                    frame_type, x, y, fw, fh, jpeg_len = struct.unpack('!BIIIII', frame_header)
                    
                    if frame_type == 2:
                        # 心跳，跳过
                        continue
                    
                    if jpeg_len > 10 * 1024 * 1024:
                        raise ValueError("JPEG too large")
                    
                    jpeg_data = recv_exact(sock, jpeg_len)
                    frame_data = (frame_type, x, y, fw, fh, jpeg_data)



                    



                    if not self.running:



                        break



                    # 帧完整性由recv_exact保证



                    



                    self.frame_count += 1



                    now = time.time()



                    if now - self.fps_timer >= 1.0:



                        fps = self.frame_count / (now - self.fps_timer)



                        self.win.after(0, lambda f=fps: self.fps_var.set(f'FPS: {f:.1f}'))



                        self.frame_count = 0



                        self.fps_timer = now



                    



                    # 收到帧数据，存入解码队列（不阻塞收帧）



                    # 传入帧数据给解码线程，包含帧类型和区域信息
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



                if isinstance(raw, tuple) and len(raw) == 6:
                    frame_type, x, y, fw, fh, jpeg_data = raw
                    img = self._decode_and_apply(frame_type, x, y, fw, fh, jpeg_data)
                else:
                    # 兼容旧格式：raw 是纯 jpeg_data
                    img = self._decode_and_apply(0, 0, 0, 0, 0, raw)



                if img:



                    # 把PhotoImage创建也放后台，减少主线程负担



                    try:



                        photo = ImageTk.PhotoImage(img)



                        self._latest_photo = (photo, self.offset_x, self.offset_y)



                    except:



                        self._latest_img = img



    



    def _decode_and_apply(self, frame_type, x, y, fw, fh, jpeg_data):
        """解码并应用帧 - 支持增量更新"""
        try:
            region = Image.open(io.BytesIO(jpeg_data))
            region.load()
            
            if frame_type == 0:
                self._current_screen_img = region
            elif frame_type == 1:
                if self._current_screen_img is None:
                    self._current_screen_img = region
                else:
                    self._current_screen_img.paste(region, (x, y))
            
            # 在副本上做缩放（不修改原图）
            display_img = self._current_screen_img
            iw, ih = display_img.size
            cw, ch = self._canvas_size
            
            if cw > 100 and ch > 100:
                self.screen_scale = min(cw / iw, ch / ih)
                new_w = int(iw * self.screen_scale)
                new_h = int(ih * self.screen_scale)
                
                if abs(new_w - iw) > iw * 0.02 or abs(new_h - ih) > ih * 0.02:
                    display_img = display_img.resize((new_w, new_h), Image.BILINEAR)
                
                self.offset_x = (cw - new_w) // 2
                self.offset_y = (ch - new_h) // 2
            else:
                self.offset_x = 0
                self.offset_y = 0
            
            return display_img
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
        """输入发送线程——优先TCP(5903)，失败后HTTP备用"""
        import socket
        import json
        import http.client
        
        tcp_conn = None
        http_conn = None
        tcp_fail_count = 0
        use_tcp = True
        
        while self.running:
            try:
                # 批量取出队列中的指令
                batch = []
                
                try:
                    item = self._input_queue.get(timeout=0.001)
                    batch.append(item)
                except queue.Empty:
                    continue
                
                # 非阻塞取出剩余（最多2ms内积压的）
                deadline = time.time() + 0.002
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
                
                items = list(deduped.values())
                
                # 优先使用TCP
                if use_tcp:
                    try:
                        if tcp_conn is None:
                            tcp_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            tcp_conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                            tcp_conn.settimeout(1)
                            tcp_conn.connect((self.client_ip, 5903))
                            print('[远程桌面] TCP输入已连接')
                        
                        # 批量发送，每条一行JSON
                        for item in items:
                            data = json.dumps(item, ensure_ascii=False) + '\n'
                            tcp_conn.sendall(data.encode('utf-8'))
                        
                        tcp_fail_count = 0
                        continue
                        
                    except Exception as e:
                        tcp_fail_count += 1
                        if tcp_fail_count >= 5:
                            use_tcp = False
                            print('[远程桌面] TCP输入失败，切换到HTTP模式')
                        
                        if tcp_conn:
                            try:
                                tcp_conn.close()
                            except:
                                pass
                            tcp_conn = None
                
                # HTTP备用模式
                try:
                    if http_conn is None:
                        http_conn = http.client.HTTPConnection(self.client_ip, 5901, timeout=3)
                    
                    data = json.dumps({'input_type': 'batch', 'items': items}).encode('utf-8')
                    http_conn.request('POST', '/input', body=data, headers={'Content-Type': 'application/json'})
                    resp = http_conn.getresponse()
                    resp.read()
                    
                except:
                    try:
                        if http_conn:
                            http_conn.close()
                    except:
                        pass
                    http_conn = None
                    
            except:
                pass
    def _on_mouse_press(self, event):



        self.canvas.focus_set()  # 点击时获取键盘焦点
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



    



    def _start_keyboard_listener(self):
        """启动pynput全局键盘监听"""
        try:
            from pynput import keyboard

            name_map = {
                'enter': 'enter', 'return': 'enter',
                'backspace': 'backspace', 'tab': 'tab',
                'space': 'space', 'delete': 'delete',
                'left': 'left', 'right': 'right', 'up': 'up', 'down': 'down',
                'home': 'home', 'end': 'end',
                'page_up': 'pageup', 'page_down': 'pagedown',
                'caps_lock': 'capslock', 'insert': 'insert',
                'esc': 'escape', 'num_lock': 'numlock',
            }

            def on_press(key):
                if not self.running:
                    return False
                try:
                    # 只在远程桌面窗口获得焦点时才转发按键
                    try:
                        import ctypes
                        hwnd = ctypes.windll.user32.GetForegroundWindow()
                        # 检查当前前台窗口是否是远程桌面窗口
                        current_hwnd = int(self.win.winfo_id())
                        # winfo_id返回的是子控件句柄，需要获取顶层窗口
                        top_hwnd = ctypes.windll.user32.GetAncestor(current_hwnd, 2)  # GA_ROOT=2
                        if hwnd != top_hwnd:
                            return  # 不是远程桌面窗口，不处理
                    except:
                        pass

                    # 记录按键状态
                    if hasattr(key, 'name') and key.name:
                        self._pynput_keys.add(key.name)

                    # 判断修饰键
                    mods = []
                    if any(k in self._pynput_keys for k in ('ctrl', 'ctrl_l', 'ctrl_r')):
                        mods.append('ctrl')
                    if any(k in self._pynput_keys for k in ('alt', 'alt_l', 'alt_r')):
                        mods.append('alt')
                    if any(k in self._pynput_keys for k in ('shift', 'shift_l', 'shift_r')):
                        mods.append('shift')

                    # 发送按键到远程
                    if hasattr(key, 'char') and key.char:
                        ch = key.char
                        # Ctrl按住时char变成控制字符，需要转回字母
                        if mods and ord(ch) < 32 and ord(ch) >= 1:
                            ch = chr(ord(ch) - 1 + ord('a'))  # →'c', →'v'等
                        if mods:
                            self._send_input({"input_type": "key_hotkey", "keys": mods + [ch]})
                        else:
                            self._send_input({"input_type": "key_press", "key": ch})
                    elif hasattr(key, 'name') and key.name:
                        # 修饰键不单独发送，只用于组合键
                        if key.name in ('ctrl_l', 'ctrl_r', 'alt_l', 'alt_r', 'shift_l', 'shift_r', 'cmd', 'cmd_l', 'cmd_r'):
                            pass
                        elif key.name.startswith('f') and key.name[1:].isdigit():
                            self._send_input({"input_type": "key_press", "key": key.name})
                        else:
                            mapped = name_map.get(key.name, key.name)
                            if mods:
                                self._send_input({"input_type": "key_hotkey", "keys": mods + [mapped]})
                            else:
                                self._send_input({"input_type": "key_press", "key": mapped})
                except:
                    pass

            def on_release(key):
                if not self.running:
                    return False
                try:
                    if hasattr(key, 'name') and key.name:
                        self._pynput_keys.discard(key.name)
                except:
                    pass

            self._pynput_listener = keyboard.Listener(
                on_press=on_press,
                on_release=on_release
            )
            self._pynput_listener.daemon = True
            self._pynput_listener.start()
        except ImportError:
            # pynput不可用，回退到Tkinter方式
            self.canvas.bind('<Key>', self._on_key_press_tk)

    def _on_key_press_tk(self, event):
        """Tkinter回退键盘处理"""
        key = event.keysym
        key_map = {'Return': 'enter', 'BackSpace': 'backspace', 'Escape': 'escape',
                   'Tab': 'tab', 'space': 'space', 'Delete': 'delete',
                   'Left': 'left', 'Right': 'right', 'Up': 'up', 'Down': 'down'}
        mapped_key = key_map.get(key, key.lower() if len(key) > 1 else key)
        self._send_input({"input_type": "key_press", "key": mapped_key})
    def _on_close(self):



        """关闭查看器"""
        if getattr(self, '_pynput_listener', None):
            try:
                self._pynput_listener.stop()
            except:
                pass



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
