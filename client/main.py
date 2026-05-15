#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
坤展成终端管理系统 — 客户端 v1.2
基于HTTP轮询通信，更稳定可靠
"""

import os, sys, json, time, threading, platform, subprocess, ctypes
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
import urllib.request
import urllib.error
import socket

# ===== 配置管理 =====
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')

DEFAULT_CONFIG = {
    "server_ip": "",
    "server_port": 8080,
    "client_name": "",
    "auto_start": False,
    "minimize_to_tray": False,
    "volume_step": 10,
    "delayed_apps": [],
    "startup_items": [],
    "activated": False,
    "activation_key": "",
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
        except:
            pass
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ===== 音量控制 =====
class VolumeControl:
    """Windows音量控制 - 使用keybd_event模拟键盘音量键，最可靠零依赖"""

    VK_VOLUME_MUTE = 0xAD
    VK_VOLUME_UP = 0xAF
    VK_VOLUME_DOWN = 0xAE

    @staticmethod
    def _key_event(vk_code, press_count=1):
        """模拟按键 - 最可靠的方式"""
        try:
            for _ in range(press_count):
                ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)  # key down
                ctypes.windll.user32.keybd_event(vk_code, 0, 2, 0)  # key up
                time.sleep(0.05)
            return True
        except Exception as e:
            print(f'[音量] 按键模拟失败: {e}')
            return False

    @staticmethod
    def get_volume():
        """获取当前音量 0-100"""
        try:
            import pythoncom
            pythoncom.CoInitialize()
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from comtypes import CLSCTX_ALL
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            return int(round(volume.GetMasterVolumeLevelScalar() * 100))
        except:
            return 0

    @staticmethod
    def set_volume(val):
        """设置音量：先降到0再升到目标"""
        try:
            import pythoncom
            pythoncom.CoInitialize()
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from comtypes import CLSCTX_ALL
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            volume.SetMasterVolumeLevelScalar(val / 100.0, None)
            return True
        except:
            pass
        # pycaw失败，用按键模拟
        VolumeControl._key_event(VolumeControl.VK_VOLUME_DOWN, 50)
        time.sleep(0.1)
        presses = max(1, val // 2)
        VolumeControl._key_event(VolumeControl.VK_VOLUME_UP, presses)
        return True

    @staticmethod
    def volume_up(step=10):
        """音量+，每次按键约2%"""
        presses = max(1, step // 2)
        return VolumeControl._key_event(VolumeControl.VK_VOLUME_UP, presses)

    @staticmethod
    def volume_down(step=10):
        """音量-"""
        presses = max(1, step // 2)
        return VolumeControl._key_event(VolumeControl.VK_VOLUME_DOWN, presses)

    @staticmethod
    def mute():
        """静音"""
        return VolumeControl._key_event(VolumeControl.VK_VOLUME_MUTE, 1)

    @staticmethod
    def unmute():
        """取消静音（静音键是toggle，如果已静音就按一次取消）"""
        try:
            import pythoncom
            pythoncom.CoInitialize()
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from comtypes import CLSCTX_ALL
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            if volume.GetMute() == 1:
                VolumeControl._key_event(VolumeControl.VK_VOLUME_MUTE, 1)
            return True
        except:
            VolumeControl._key_event(VolumeControl.VK_VOLUME_MUTE, 1)
            return True

    @staticmethod
    def is_muted():
        try:
            import pythoncom
            pythoncom.CoInitialize()
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from comtypes import CLSCTX_ALL
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            return volume.GetMute() == 1
        except:
            return False


# ===== 电源控制 =====
class PowerControl:
    @staticmethod
    def shutdown():
        try:
            subprocess.run(['shutdown', '/s', '/t', '0'], capture_output=True, timeout=10)
            return True
        except:
            return False

    @staticmethod
    def restart():
        try:
            subprocess.run(['shutdown', '/r', '/t', '0'], capture_output=True, timeout=10)
            return True
        except:
            return False

    @staticmethod
    def cancel_shutdown():
        try:
            subprocess.run(['shutdown', '/a'], capture_output=True, timeout=10)
            return True
        except:
            return False

    @staticmethod
    def lock_screen():
        try:
            subprocess.run(['rundll32.exe', 'user32.dll,LockWorkStation'], capture_output=True, timeout=10)
            return True
        except:
            return False

    @staticmethod
    def logout():
        try:
            subprocess.run(['shutdown', '/l'], capture_output=True, timeout=10)
            return True
        except:
            return False

    @staticmethod
    def timed_shutdown(seconds):
        try:
            subprocess.run(['shutdown', '/s', '/t', str(seconds)], capture_output=True, timeout=10)
            return True
        except:
            return False

    @staticmethod
    def run_script(script_content, script_type='bat'):
        try:
            if platform.system() == 'Windows':
                if script_type == 'ps1':
                    result = subprocess.run(
                        ['powershell', '-Command', script_content],
                        capture_output=True, text=True, timeout=60)
                else:
                    tmp = os.path.join(os.environ.get('TEMP', '.'), '_kzc_cmd.bat')
                    with open(tmp, 'w', encoding='gbk') as f:
                        f.write(script_content)
                    result = subprocess.run(tmp, capture_output=True, text=True, timeout=60)
                    try:
                        os.remove(tmp)
                    except:
                        pass
            else:
                tmp = '/tmp/_kzc_cmd.sh'
                with open(tmp, 'w') as f:
                    f.write(script_content)
                os.chmod(tmp, 0o755)
                result = subprocess.run(['bash', tmp], capture_output=True, text=True, timeout=60)
                try:
                    os.remove(tmp)
                except:
                    pass
            return {'success': result.returncode == 0, 'output': result.stdout[-500:] if result.stdout else '', 'error': result.stderr[-500:] if result.stderr else ''}
        except Exception as e:
            return {'success': False, 'error': str(e)}


# ===== 系统信息采集 =====
class SystemInfo:
    @staticmethod
    def get_info():
        info = {
            'hostname': platform.node(),
            'os': platform.system(),
            'os_version': platform.version(),
            'arch': platform.machine(),
            'ip': SystemInfo._get_local_ip(),
            'mac': SystemInfo._get_mac(),
            'cpu': platform.processor(),
            'cpu_count': os.cpu_count(),
        }
        try:
            import psutil
            mem = psutil.virtual_memory()
            info['memory_total'] = mem.total
            info['memory_percent'] = mem.percent
            info['cpu_percent'] = psutil.cpu_percent(interval=0.5)
            try:
                info['disk_percent'] = psutil.disk_usage('C:\\').percent if platform.system() == 'Windows' else psutil.disk_usage('/').percent
            except:
                info['disk_percent'] = 0
            info['uptime'] = int(time.time() - psutil.boot_time())
        except:
            pass
        return info

    @staticmethod
    def _get_local_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return '0.0.0.0'

    @staticmethod
    def _get_mac():
        try:
            import uuid
            return ':'.join(['{:02x}'.format((uuid.getnode() >> ele) & 0xff) for ele in range(0, 8*6, 8)][::-1])
        except:
            return ''


# ===== UDP自动发现服务器 =====
BROADCAST_PORT = 15080

class ServerDiscovery:
    def __init__(self, on_found=None):
        self.on_found = on_found
        self.running = False
        self._thread = None
        self.server_ip = None
        self.server_port = None

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False

    def _listen(self):
        while self.running:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.settimeout(5)
                sock.bind(('', BROADCAST_PORT))
                while self.running:
                    try:
                        data, addr = sock.recvfrom(1024)
                        msg = json.loads(data.decode('utf-8'))
                        if msg.get('type') == 'kzc_server':
                            ip = msg.get('ip', '')
                            port = msg.get('port', 8080)
                            if ip and (ip != self.server_ip or port != self.server_port):
                                self.server_ip = ip
                                self.server_port = port
                                print(f'[发现] 服务器: {ip}:{port}')
                                if self.on_found:
                                    self.on_found(ip, port)
                    except socket.timeout:
                        continue
                    except:
                        pass
            except Exception as e:
                print(f'[发现] 监听失败: {e}')
                time.sleep(3)


# ===== HTTP通信客户端 =====
class HTTPClient:
    """基于HTTP轮询与服务器通信"""

    def __init__(self, on_command=None):
        self.server_ip = ''
        self.server_port = 8080
        self.connected = False
        self.running = False
        self.on_command = on_command
        self.poll_interval = 3  # 3秒轮询一次
        self._thread = None
        self.client_id = ''  # 服务器分配的客户端ID
        self._last_command_ids = set()  # 已处理的指令ID

    def configure(self, ip, port):
        self.server_ip = ip
        self.server_port = port

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False

    def _poll_loop(self):
        """轮询循环"""
        while self.running:
            if not self.server_ip:
                time.sleep(2)
                continue
            try:
                self._register_and_poll()
            except Exception as e:
                self.connected = False
                print(f'[HTTP] 通信失败: {e}')
            if self.running:
                time.sleep(self.poll_interval)

    def _register_and_poll(self):
        """注册并轮询指令"""
        base_url = f'http://{self.server_ip}:{self.server_port}'
        
        # 第一步：注册
        info = SystemInfo.get_info()
        reg_data = json.dumps({
            'hostname': info['hostname'],
            'os': info['os'],
            'os_version': info['os_version'],
            'ip': info['ip'],
            'mac': info['mac'],
            'arch': info['arch'],
            'cpu': info.get('cpu', ''),
            'cpu_percent': info.get('cpu_percent', 0),
            'memory_percent': info.get('memory_percent', 0),
            'disk_percent': info.get('disk_percent', 0),
        }).encode('utf-8')

        req = urllib.request.Request(
            f'{base_url}/api/client/register',
            data=reg_data,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                self.client_id = result.get('client_id', '')
                self.connected = True
                print(f'[HTTP] 已注册, client_id={self.client_id}')
        except urllib.error.HTTPError as e:
            # 可能已注册，继续
            if e.code == 400:
                self.connected = True
        except Exception as e:
            self.connected = False
            raise

        if not self.connected or not self.client_id:
            return

        # 第二步：轮询指令
        try:
            req = urllib.request.Request(
                f'{base_url}/api/client/poll?client_id={self.client_id}',
                method='GET'
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                commands = result.get('commands', [])
                for cmd in commands:
                    cmd_id = cmd.get('id', '')
                    if cmd_id not in self._last_command_ids:
                        self._last_command_ids.add(cmd_id)
                        # 只保留最近100个
                        if len(self._last_command_ids) > 100:
                            self._last_command_ids = set(list(self._last_command_ids)[-50:])
                        if self.on_command:
                            self.on_command(cmd)
        except:
            pass

    def send_result(self, task_id, status, msg=''):
        """发送指令执行结果"""
        if not self.server_ip or not self.client_id:
            return
        base_url = f'http://{self.server_ip}:{self.server_port}'
        data = json.dumps({
            'client_id': self.client_id,
            'task_id': task_id,
            'status': status,
            'msg': msg,
        }).encode('utf-8')
        try:
            req = urllib.request.Request(
                f'{base_url}/api/client/result',
                data=data,
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                pass
        except Exception as e:
            print(f'[HTTP] 发送结果失败: {e}')


# ===== 指令处理 =====
class CommandHandler:
    def __init__(self, app):
        self.app = app

    def handle(self, data):
        cmd = data.get('cmd', '')
        task_id = data.get('id', data.get('task_id', ''))
        result = {'status': 'failed', 'msg': '未知指令'}
        print(f'[指令] 收到: {cmd}, id: {task_id}')

        if cmd == 'shutdown':
            result = {'status': 'success' if PowerControl.shutdown() else 'failed', 'msg': '关机指令已执行' if PowerControl.shutdown() else '关机失败'}
        elif cmd == 'restart':
            result = {'status': 'success' if PowerControl.restart() else 'failed', 'msg': '重启指令已执行' if PowerControl.restart() else '重启失败'}
        elif cmd == 'cancel':
            result = {'status': 'success' if PowerControl.cancel_shutdown() else 'failed', 'msg': '已取消关机' if PowerControl.cancel_shutdown() else '取消失败'}
        elif cmd == 'lock':
            result = {'status': 'success' if PowerControl.lock_screen() else 'failed', 'msg': '已锁屏' if PowerControl.lock_screen() else '锁屏失败'}
        elif cmd == 'logout':
            result = {'status': 'success' if PowerControl.logout() else 'failed', 'msg': '已注销' if PowerControl.logout() else '注销失败'}
        elif cmd == 'timed_shutdown':
            seconds = data.get('seconds', 60)
            result = {'status': 'success' if PowerControl.timed_shutdown(seconds) else 'failed', 'msg': f'{seconds}秒后关机' if PowerControl.timed_shutdown(seconds) else '定时关机失败'}
        elif cmd == 'volume:up':
            step = self.app.config.get('volume_step', 10)
            ok = VolumeControl.volume_up(step)
            result = {'status': 'success' if ok else 'failed', 'msg': f'音量+{step}%' if ok else '音量控制失败'}
        elif cmd == 'volume:down':
            step = self.app.config.get('volume_step', 10)
            ok = VolumeControl.volume_down(step)
            result = {'status': 'success' if ok else 'failed', 'msg': f'音量-{step}%' if ok else '音量控制失败'}
        elif cmd == 'mute':
            ok = VolumeControl.mute()
            result = {'status': 'success' if ok else 'failed', 'msg': '已静音' if ok else '静音失败'}
        elif cmd == 'unmute':
            ok = VolumeControl.unmute()
            result = {'status': 'success' if ok else 'failed', 'msg': '已取消静音' if ok else '取消静音失败'}
        elif cmd == 'status':
            vol = VolumeControl.get_volume()
            muted = VolumeControl.is_muted()
            info = SystemInfo.get_info()
            result = {'status': 'success', 'msg': json.dumps({
                'volume': vol, 'muted': muted,
                'cpu_percent': info.get('cpu_percent', 0),
                'memory_percent': info.get('memory_percent', 0),
            }, ensure_ascii=False)}
        elif cmd == 'script':
            script = data.get('content', '')
            script_type = data.get('script_type', 'bat')
            res = PowerControl.run_script(script, script_type)
            result = {'status': 'success' if res['success'] else 'failed', 'msg': res.get('output', '') or res.get('error', '')}

        print(f'[指令] 结果: {result}')
        self.app.http_client.send_result(task_id, result['status'], result['msg'])
        self.app.root.after(0, lambda: self.app._show_msg(f'远程指令 {cmd}: {result["msg"]}'))
        return result


# ===== 主窗口 =====
class TerminalApp:
    def __init__(self):
        self.config = load_config()
        self.root = tk.Tk()
        self.root.title('坤展成终端管理系统 v1.0')
        self.root.geometry('800x680')
        self.root.resizable(True, True)
        self.root.minsize(800, 680)

        self.http_client = HTTPClient(on_command=self._on_command)
        self.command_handler = CommandHandler(self)
        self.server_discovery = ServerDiscovery(on_found=self._on_server_found)

        self._build_ui()
        self._load_config_to_ui()

        self.server_discovery.start()
        saved_ip = self.config.get('server_ip', '')
        if saved_ip:
            self.http_client.configure(saved_ip, self.config.get('server_port', 8080))
        self.http_client.start()

        self._refresh_status()

    def _on_command(self, data):
        self.root.after(0, lambda: self.command_handler.handle(data))

    def _on_server_found(self, ip, port):
        print(f'[自动发现] 服务器 {ip}:{port}')
        self.root.after(0, lambda: self._update_server_info(ip, port))
        if not self.http_client.connected or self.http_client.server_ip != ip:
            self.http_client.configure(ip, port)
            self.config['server_ip'] = ip
            self.config['server_port'] = port
            save_config(self.config)

    def _update_server_info(self, ip, port):
        self.var_server_ip.set(ip)
        self.var_server_port.set(port)
        self._show_msg(f'自动发现服务器 {ip}:{port}')

    # ==================== UI构建 ====================
    def _build_ui(self):
        # 顶部标题区
        title_frame = tk.Frame(self.root, bg='#2c3e50', height=60)
        title_frame.pack(fill='x')
        title_frame.pack_propagate(False)
        tk.Label(title_frame, text='坤展成终端管理系统 v1.0',
                font=('Microsoft YaHei', 15, 'bold'), fg='white', bg='#2c3e50').pack(pady=(8, 0))
        tk.Label(title_frame, text='北京万乘兄弟科技有限公司  联系电话：18210234280',
                font=('Microsoft YaHei', 8), fg='#bdc3c7', bg='#2c3e50').pack()

        # 状态栏
        status_frame = tk.Frame(self.root, bg='#ecf0f1', height=30)
        status_frame.pack(fill='x')
        status_frame.pack_propagate(False)
        self.lbl_activate = tk.Label(status_frame, text='未激活', font=('Microsoft YaHei', 9), fg='#e74c3c', bg='#ecf0f1')
        self.lbl_activate.pack(side='left', padx=15)
        self.lbl_volume = tk.Label(status_frame, text='音量：--', font=('Microsoft YaHei', 9), fg='#2c3e50', bg='#ecf0f1')
        self.lbl_volume.pack(side='left', padx=15)
        self.lbl_network = tk.Label(status_frame, text='通讯：未连接', font=('Microsoft YaHei', 9), fg='#e74c3c', bg='#ecf0f1')
        self.lbl_network.pack(side='left', padx=15)

        # 主区域
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill='both', expand=True, padx=8, pady=5)

        # --- 左侧 ---
        left_frame = tk.Frame(main_frame)
        left_frame.pack(side='left', fill='both', padx=(0, 4))

        # 快捷音量控制
        vol_frame = tk.LabelFrame(left_frame, text=' 快捷音量控制 ', font=('Microsoft YaHei', 10, 'bold'))
        vol_frame.pack(fill='x', pady=(0, 5))
        btn_frame = tk.Frame(vol_frame)
        btn_frame.pack(pady=5)
        tk.Button(btn_frame, text='音量+', width=8, command=self._vol_up).grid(row=0, column=0, padx=3, pady=2)
        tk.Button(btn_frame, text='音量-', width=8, command=self._vol_down).grid(row=0, column=1, padx=3, pady=2)
        tk.Button(btn_frame, text='静音', width=8, command=self._mute).grid(row=1, column=0, padx=3, pady=2)
        tk.Button(btn_frame, text='取消静音', width=8, command=self._unmute).grid(row=1, column=1, padx=3, pady=2)
        step_frame = tk.Frame(vol_frame)
        step_frame.pack(pady=(0, 5))
        tk.Label(step_frame, text='步长：', font=('Microsoft YaHei', 9)).pack(side='left')
        self.var_step = tk.IntVar(value=10)
        tk.Spinbox(step_frame, from_=1, to=50, textvariable=self.var_step, width=5).pack(side='left', padx=3)
        tk.Label(step_frame, text='%').pack(side='left')
        tk.Button(step_frame, text='保存', command=self._save_step).pack(side='left', padx=8)

        # 电源控制
        power_frame = tk.LabelFrame(left_frame, text=' 电源控制 ', font=('Microsoft YaHei', 10, 'bold'))
        power_frame.pack(fill='x', pady=(0, 5))
        pw_btn_frame = tk.Frame(power_frame)
        pw_btn_frame.pack(pady=8)
        tk.Button(pw_btn_frame, text='关 机', width=8, bg='#e74c3c', fg='white', font=('Microsoft YaHei', 10, 'bold'), command=self._shutdown).grid(row=0, column=0, padx=5, pady=3)
        tk.Button(pw_btn_frame, text='重 启', width=8, bg='#f39c12', fg='white', font=('Microsoft YaHei', 10, 'bold'), command=self._restart).grid(row=0, column=1, padx=5, pady=3)
        tk.Button(pw_btn_frame, text='取 消', width=8, bg='#27ae60', fg='white', font=('Microsoft YaHei', 10, 'bold'), command=self._cancel_shutdown).grid(row=1, column=0, columnspan=2, padx=5, pady=3)

        # 指令参考
        ref_frame = tk.LabelFrame(left_frame, text=' 指令参考 ', font=('Microsoft YaHei', 10, 'bold'))
        ref_frame.pack(fill='both', expand=True)
        ref_text = tk.Text(ref_frame, height=8, width=30, font=('Consolas', 9), state='disabled', bg='#fafafa')
        ref_text.pack(fill='both', expand=True, padx=5, pady=5)
        cmds = [('shutdown', '关机'), ('restart', '重启'), ('cancel', '取消关机'),
                ('volume:up', '音量+'), ('volume:down', '音量-'),
                ('mute', '静音'), ('unmute', '取消静音'),
                ('status', '状态查询'), ('help', '帮助')]
        ref_text.config(state='normal')
        for cmd, desc in cmds:
            ref_text.insert('end', f'  {cmd:16s} {desc}\n')
        ref_text.config(state='disabled')

        # --- 右侧 ---
        right_frame = tk.Frame(main_frame)
        right_frame.pack(side='right', fill='both', expand=True, padx=(4, 0))

        # 网络设置
        net_frame = tk.LabelFrame(right_frame, text=' 网络设置（自动发现服务器） ', font=('Microsoft YaHei', 10, 'bold'))
        net_frame.pack(fill='x', pady=(0, 5))
        net_grid = tk.Frame(net_frame)
        net_grid.pack(padx=10, pady=5)
        tk.Label(net_grid, text='服务器IP：', font=('Microsoft YaHei', 9)).grid(row=0, column=0, sticky='e', pady=2)
        self.var_server_ip = tk.StringVar(value='')
        tk.Label(net_grid, textvariable=self.var_server_ip, width=18, anchor='w', font=('Microsoft YaHei', 9), fg='#27ae60', bg='#ecf0f1', relief='sunken').grid(row=0, column=1, pady=2, padx=5, sticky='w')
        tk.Label(net_grid, text='端口：', font=('Microsoft YaHei', 9)).grid(row=1, column=0, sticky='e', pady=2)
        self.var_server_port = tk.IntVar(value=8080)
        tk.Label(net_grid, textvariable=self.var_server_port, width=18, anchor='w', font=('Microsoft YaHei', 9), fg='#27ae60', bg='#ecf0f1', relief='sunken').grid(row=1, column=1, pady=2, padx=5, sticky='w')
        self.var_min_tray = tk.BooleanVar(value=False)
        tk.Checkbutton(net_grid, text='启动时最小化到托盘', variable=self.var_min_tray, font=('Microsoft YaHei', 9)).grid(row=2, column=0, columnspan=2, sticky='w', pady=2)

        # 延时启动
        delay_frame = tk.LabelFrame(right_frame, text=' 延时启动 ', font=('Microsoft YaHei', 10, 'bold'))
        delay_frame.pack(fill='x', pady=(0, 5))
        delay_cols = ('name', 'delay', 'path')
        self.delay_tree = ttk.Treeview(delay_frame, columns=delay_cols, show='headings', height=3)
        self.delay_tree.heading('name', text='文件名')
        self.delay_tree.heading('delay', text='延时(秒)')
        self.delay_tree.heading('path', text='路径')
        self.delay_tree.column('name', width=100)
        self.delay_tree.column('delay', width=60)
        self.delay_tree.column('path', width=250)
        self.delay_tree.pack(fill='x', padx=5, pady=3)
        delay_btn_frame = tk.Frame(delay_frame)
        delay_btn_frame.pack(pady=3)
        tk.Button(delay_btn_frame, text='添加应用', width=10, command=self._add_delayed_app).pack(side='left', padx=3)
        tk.Button(delay_btn_frame, text='删除', width=8, command=self._del_delayed_app).pack(side='left', padx=3)
        tk.Button(delay_btn_frame, text='立即启动', width=10, command=self._launch_delayed).pack(side='left', padx=3)

        # 启动项设置
        startup_frame = tk.LabelFrame(right_frame, text=' 启动项设置（Windows开机启动） ', font=('Microsoft YaHei', 10, 'bold'))
        startup_frame.pack(fill='both', expand=True)
        startup_cols = ('enabled', 'name', 'delay', 'path')
        self.startup_tree = ttk.Treeview(startup_frame, columns=startup_cols, show='headings', height=3)
        self.startup_tree.heading('enabled', text='启')
        self.startup_tree.heading('name', text='文件名')
        self.startup_tree.heading('delay', text='延时启动')
        self.startup_tree.heading('path', text='路径')
        self.startup_tree.column('enabled', width=35)
        self.startup_tree.column('name', width=100)
        self.startup_tree.column('delay', width=70)
        self.startup_tree.column('path', width=210)
        self.startup_tree.pack(fill='both', expand=True, padx=5, pady=3)
        startup_btn_frame = tk.Frame(startup_frame)
        startup_btn_frame.pack(pady=3)
        tk.Button(startup_btn_frame, text='添加', width=8, command=self._add_startup).pack(side='left', padx=3)
        tk.Button(startup_btn_frame, text='删除', width=8, command=self._del_startup).pack(side='left', padx=3)
        tk.Button(startup_btn_frame, text='启用/禁用', width=10, command=self._toggle_startup).pack(side='left', padx=3)

        # 底部按钮
        bottom_frame = tk.Frame(self.root, bg='#ecf0f1', height=36)
        bottom_frame.pack(fill='x', side='bottom')
        bottom_frame.pack_propagate(False)
        tk.Button(bottom_frame, text='激活软件', width=10, bg='#3498db', fg='white', font=('Microsoft YaHei', 9, 'bold'), command=self._activate).pack(side='left', padx=10, pady=5)
        tk.Button(bottom_frame, text='保存设置', width=10, bg='#27ae60', fg='white', font=('Microsoft YaHei', 9, 'bold'), command=self._save_settings).pack(side='left', padx=5, pady=5)
        tk.Button(bottom_frame, text='退出程序', width=10, bg='#e74c3c', fg='white', font=('Microsoft YaHei', 9, 'bold'), command=self._quit).pack(side='left', padx=5, pady=5)

    # ==================== 配置加载 ====================
    def _load_config_to_ui(self):
        cfg = self.config
        self.var_server_ip.set(cfg.get('server_ip', ''))
        self.var_server_port.set(cfg.get('server_port', 8080))
        self.var_step.set(cfg.get('volume_step', 10))
        self.var_min_tray.set(cfg.get('minimize_to_tray', False))
        if cfg.get('activated'):
            self.lbl_activate.config(text='已激活（永久版）', fg='#27ae60')
        for item in cfg.get('delayed_apps', []):
            self.delay_tree.insert('', 'end', values=(item['name'], item.get('delay', 0), item['path']))
        for item in cfg.get('startup_items', []):
            en = '✓' if item.get('enabled', True) else '✗'
            self.startup_tree.insert('', 'end', values=(en, item['name'], item.get('delay', 0), item['path']))

    # ==================== 音量操作 ====================
    def _vol_up(self):
        step = self.var_step.get()
        if VolumeControl.volume_up(step):
            self._update_volume_display()
            self._show_msg(f'音量+{step}%')
        else:
            self._show_msg('音量控制失败')

    def _vol_down(self):
        step = self.var_step.get()
        if VolumeControl.volume_down(step):
            self._update_volume_display()
            self._show_msg(f'音量-{step}%')
        else:
            self._show_msg('音量控制失败')

    def _mute(self):
        if VolumeControl.mute():
            self._update_volume_display()
            self._show_msg('已静音')
        else:
            self._show_msg('静音失败')

    def _unmute(self):
        if VolumeControl.unmute():
            self._update_volume_display()
            self._show_msg('已取消静音')
        else:
            self._show_msg('取消静音失败')

    def _save_step(self):
        self.config['volume_step'] = self.var_step.get()
        save_config(self.config)

    def _update_volume_display(self):
        vol = VolumeControl.get_volume()
        muted = VolumeControl.is_muted()
        mute_str = ' 已静音' if muted else ' 未静音'
        self.lbl_volume.config(text=f'音量：{vol}%{mute_str}')

    # ==================== 电源操作 ====================
    def _shutdown(self):
        if messagebox.askyesno('确认', '确定要关机吗？'):
            if PowerControl.shutdown():
                self._show_msg('关机指令已执行')

    def _restart(self):
        if messagebox.askyesno('确认', '确定要重启吗？'):
            if PowerControl.restart():
                self._show_msg('重启指令已执行')

    def _cancel_shutdown(self):
        if PowerControl.cancel_shutdown():
            self._show_msg('已取消关机')
        else:
            self._show_msg('没有正在进行的关机任务')

    # ==================== 操作反馈 ====================
    def _show_msg(self, msg):
        self.lbl_network.config(text=f'通讯：{"已连接" if self.http_client.connected else "未连接"} | {msg}', fg='#2c3e50')
        self.root.after(3000, self._refresh_status)

    # ==================== 延时启动 ====================
    def _add_delayed_app(self):
        path = filedialog.askopenfilename(title='选择应用程序', filetypes=[('程序', '*.exe *.bat *.cmd *.lnk'), ('所有文件', '*.*')])
        if not path:
            return
        name = os.path.basename(path)
        delay = 5
        dlg = tk.Toplevel(self.root)
        dlg.title('设置延时')
        dlg.geometry('250x120')
        dlg.resizable(False, False)
        tk.Label(dlg, text=f'应用：{name}', font=('Microsoft YaHei', 9)).pack(pady=5)
        tk.Label(dlg, text='延时（秒）：', font=('Microsoft YaHei', 9)).pack()
        var_d = tk.IntVar(value=5)
        tk.Entry(dlg, textvariable=var_d, width=10).pack(pady=5)
        def confirm():
            nonlocal delay
            delay = var_d.get()
            self.delay_tree.insert('', 'end', values=(name, delay, path))
            self.config.setdefault('delayed_apps', []).append({'name': name, 'delay': delay, 'path': path})
            save_config(self.config)
            dlg.destroy()
        tk.Button(dlg, text='确定', command=confirm).pack(pady=5)

    def _del_delayed_app(self):
        sel = self.delay_tree.selection()
        if not sel:
            return
        for item in sel:
            vals = self.delay_tree.item(item, 'values')
            self.delay_tree.delete(item)
            self.config['delayed_apps'] = [a for a in self.config.get('delayed_apps', []) if not (a['name'] == vals[0] and a['path'] == vals[2])]
        save_config(self.config)

    def _launch_delayed(self):
        sel = self.delay_tree.selection()
        if not sel:
            return
        for item in sel:
            vals = self.delay_tree.item(item, 'values')
            path = vals[2]
            threading.Thread(target=lambda p=path: os.startfile(p), daemon=True).start()

    # ==================== 启动项管理 ====================
    def _add_startup(self):
        path = filedialog.askopenfilename(title='选择启动程序', filetypes=[('程序', '*.exe *.bat *.cmd *.lnk'), ('所有文件', '*.*')])
        if not path:
            return
        name = os.path.basename(path)
        self.startup_tree.insert('', 'end', values=('✓', name, 0, path))
        self.config.setdefault('startup_items', []).append({'name': name, 'delay': 0, 'path': path, 'enabled': True})
        save_config(self.config)

    def _del_startup(self):
        sel = self.startup_tree.selection()
        if not sel:
            return
        for item in sel:
            vals = self.startup_tree.item(item, 'values')
            self.startup_tree.delete(item)
            self.config['startup_items'] = [a for a in self.config.get('startup_items', []) if not (a['name'] == vals[1] and a['path'] == vals[3])]
        save_config(self.config)

    def _toggle_startup(self):
        sel = self.startup_tree.selection()
        if not sel:
            return
        for item in sel:
            vals = list(self.startup_tree.item(item, 'values'))
            vals[0] = '✗' if vals[0] == '✓' else '✓'
            self.startup_tree.item(item, values=vals)
            for a in self.config.get('startup_items', []):
                if a['name'] == vals[1] and a['path'] == vals[3]:
                    a['enabled'] = (vals[0] == '✓')
        save_config(self.config)

    # ==================== 保存/激活/退出 ====================
    def _save_settings(self):
        self.config['minimize_to_tray'] = self.var_min_tray.get()
        self.config['volume_step'] = self.var_step.get()
        save_config(self.config)
        messagebox.showinfo('提示', '设置已保存')

    def _activate(self):
        dlg = tk.Toplevel(self.root)
        dlg.title('激活软件')
        dlg.geometry('350x150')
        dlg.resizable(False, False)
        tk.Label(dlg, text='请输入激活码：', font=('Microsoft YaHei', 10)).pack(pady=10)
        var_key = tk.StringVar()
        tk.Entry(dlg, textvariable=var_key, width=30).pack()
        def do_activate():
            key = var_key.get().strip()
            if key == 'KZC-2026-PERMANENT':
                self.config['activated'] = True
                self.config['activation_key'] = key
                save_config(self.config)
                self.lbl_activate.config(text='已激活（永久版）', fg='#27ae60')
                dlg.destroy()
                messagebox.showinfo('成功', '软件已激活！')
            else:
                messagebox.showerror('错误', '激活码无效')
        tk.Button(dlg, text='激活', command=do_activate, bg='#3498db', fg='white', font=('Microsoft YaHei', 10, 'bold')).pack(pady=10)

    def _refresh_status(self):
        self._update_volume_display()
        if self.http_client.connected:
            self.lbl_network.config(text=f'通讯：已连接 {self.http_client.server_ip}:{self.http_client.server_port}', fg='#27ae60')
        else:
            ip = self.var_server_ip.get()
            if ip:
                self.lbl_network.config(text=f'通讯：正在连接 {ip}...', fg='#f39c12')
            else:
                self.lbl_network.config(text='通讯：搜索服务器中...', fg='#e74c3c')
        self.root.after(3000, self._refresh_status)

    def _quit(self):
        self.http_client.stop()
        self.server_discovery.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    app = TerminalApp()
    app.run()
