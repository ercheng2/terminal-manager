#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
坤展成终端管理系统 — 客户端 v1.4.0
基于HTTP轮询通信，更稳定可靠
"""

import os, sys, json, time, threading, platform, subprocess, ctypes, queue
import hashlib, io, struct
from http.server import HTTPServer, BaseHTTPRequestHandler
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
import urllib.request
import urllib.error
import socket

def resource_path(relative_path):
    """获取资源文件绝对路径（兼容PyInstaller打包）"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --windowed打包后print会报错，重定向
if getattr(sys, 'frozen', False):
    try:
        _log_path = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), 'client.log')
        _log_file = open(_log_path, 'a', encoding='utf-8')
        sys.stdout = _log_file
        sys.stderr = _log_file
    except:
        sys.stdout = open(os.devnull, 'w')
        sys.stderr = sys.stdout

# pystray托盘支持
try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_PYSTRAY = True
except ImportError:
    HAS_PYSTRAY = False

# Windows注册表支持
if platform.system() == 'Windows':
    try:
        import winreg
        HAS_WINREG = True
    except ImportError:
        HAS_WINREG = False
else:
    HAS_WINREG = False

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
    "download_dir": "",
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


# ===== Windows注册表操作 =====
REG_RUN_KEY = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Run'

def _get_run_key():
    """获取Windows注册表Run键"""
    if not HAS_WINREG:
        return None
    try:
        return winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0, winreg.KEY_ALL_ACCESS)
    except WindowsError:
        return None

def _write_startup_reg(name, path):
    """写入启动项到注册表"""
    if not HAS_WINREG:
        return False
    try:
        key = _get_run_key()
        if key:
            # 确保路径使用反斜杠，并用双引号包裹（处理路径含空格的情况）
            reg_path = os.path.normpath(path)
            if not reg_path.startswith('"'):
                reg_path = f'"{reg_path}"'
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, reg_path)
            winreg.CloseKey(key)
            print(f'[注册表] 写入启动项: {name} -> {reg_path}')
            return True
    except Exception as e:
        print(f'[注册表] 写入失败: {e}')
    return False

def _delete_startup_reg(name):
    """从注册表删除启动项"""
    if not HAS_WINREG:
        return False
    try:
        key = _get_run_key()
        if key:
            winreg.DeleteValue(key, name)
            winreg.CloseKey(key)
            print(f'[注册表] 删除启动项: {name}')
            return True
    except FileNotFoundError:
        # 键不存在，忽略
        pass
    except Exception as e:
        print(f'[注册表] 删除失败: {e}')
    return False

def _sync_startup_to_registry(startup_items):
    """同步启动项到注册表（根据enabled状态）"""
    if not HAS_WINREG:
        return
    try:
        key = _get_run_key()
        if not key:
            return
        # 获取当前注册表中所有值
        existing = {}
        i = 0
        while True:
            try:
                n, v, _ = winreg.EnumValue(key, i)
                # 去掉引号后存储，便于比较
                existing[n] = v.strip('"')
                i += 1
            except OSError:
                break
        winreg.CloseKey(key)
        
        # 收集应该存在和应该删除的项
        should_exist = {item['name']: item['path'] for item in startup_items if item.get('enabled', True)}
        should_delete = set(existing.keys()) - set(should_exist.keys())
        
        # 删除不应该存在的项
        for name in should_delete:
            _delete_startup_reg(name)
        
        # 添加应该存在但还不存在的项，或路径不一致的需要更新
        for name, path in should_exist.items():
            norm_path = os.path.normpath(path)
            if name not in existing or existing[name] != norm_path:
                _write_startup_reg(name, path)
    except Exception as e:
        print(f'[注册表] 同步失败: {e}')


# ===== 系统托盘 =====
_tray_icon = None
_tray_root_ref = None

def _create_tray_image():
    """从ico文件创建托盘图标"""
    try:
        icon_path = resource_path('icon.ico')
        if os.path.exists(icon_path):
            img = Image.open(icon_path)
            img = img.resize((16, 16), Image.LANCZOS)
            return img
    except Exception:
        pass
    # fallback
    img = Image.new('RGB', (16, 16), (41, 128, 185))
    draw = ImageDraw.Draw(img)
    draw.text((3, 1), 'K', fill='white')
    return img

def _on_tray_show(icon, item):
    """显示主窗口"""
    if _tray_root_ref:
        _tray_root_ref.after(0, _tray_root_ref.deiconify)
        _tray_root_ref.after(0, _tray_root_ref.lift)

def _on_tray_quit(icon, item):
    """真正退出程序"""
    global _tray_icon
    if _tray_icon:
        _tray_icon.stop()
        _tray_icon = None
    if _tray_root_ref:
        _tray_root_ref.after(0, _tray_root_ref.quit)

def _start_tray(root):
    """启动系统托盘"""
    global _tray_icon, _tray_root_ref
    if not HAS_PYSTRAY:
        print('[托盘] pystray未安装，托盘功能不可用')
        return
    try:
        _tray_root_ref = root
        menu = pystray.Menu(
            pystray.MenuItem('显示主窗口', _on_tray_show, default=True),
            pystray.MenuItem('退出程序', _on_tray_quit),
        )
        _tray_icon = pystray.Icon(
            'kzc_terminal',
            _create_tray_image(),
            '坤展成终端管理',
            menu
        )
        # 在独立线程运行托盘
        t = threading.Thread(target=_tray_icon.run, daemon=True)
        t.start()
        print('[托盘] 托盘图标已启动')
    except Exception as e:
        print(f'[托盘] 启动失败: {e}')

def _stop_tray():
    """停止系统托盘"""
    global _tray_icon
    if _tray_icon:
        try:
            _tray_icon.stop()
        except:
            pass
        _tray_icon = None
        print('[托盘] 托盘图标已关闭')


# ===== 音量控制 =====
class VolumeControl:
    """Windows音量控制 - 纯ctypes COM API直接读取，无需外部exe"""
    VK_VOLUME_MUTE = 0xAD
    VK_VOLUME_UP = 0xAF
    VK_VOLUME_DOWN = 0xAE

    _cached_volume = 50
    _cached_muted = False
    _bg_thread = None
    _bg_running = False
    _app_ref = None
    _status = '未初始化'
    _com_ok = False
    _vol_ptr = None  # IAudioEndpointVolume COM指针

    # COM GUID字符串
    _CLSID_STR = '{BCDE0395-E52F-467C-8E3D-C4579291692E}'
    _IID_ENUM_STR = '{A95664D2-9614-4F35-A746-DE8DB63617E6}'
    _IID_VOL_STR = '{5CDF2C82-841E-4546-9722-0CF74078229A}'

    @staticmethod
    def _init_com():
        """纯ctypes初始化COM，直接获取IAudioEndpointVolume指针"""
        try:
            ole32 = ctypes.windll.ole32

            # 每个线程必须调用CoInitialize
            hr = ole32.CoInitialize(None)
            # S_OK=0, S_FALSE=1(已初始化), RPC_E_CHANGED_MODE=-2147417850(不同模式但可用)
            if hr not in (0, 1) and hr != -2147417850:
                VolumeControl._status = f'CoInit:0x{hr & 0xFFFFFFFF:X}'
                return False

            # GUID结构体
            class GUID(ctypes.Structure):
                _fields_ = [
                    ('Data1', ctypes.c_ulong),
                    ('Data2', ctypes.c_ushort),
                    ('Data3', ctypes.c_ushort),
                    ('Data4', ctypes.c_ubyte * 8),
                ]

            # IIDFromString解析GUID字符串
            ole32.IIDFromString.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(GUID)]
            ole32.IIDFromString.restype = ctypes.HRESULT

            clsid = GUID()
            iid_enum = GUID()
            iid_vol = GUID()
            ole32.IIDFromString(VolumeControl._CLSID_STR, ctypes.byref(clsid))
            ole32.IIDFromString(VolumeControl._IID_ENUM_STR, ctypes.byref(iid_enum))
            ole32.IIDFromString(VolumeControl._IID_VOL_STR, ctypes.byref(iid_vol))

            # CoCreateInstance -> IMMDeviceEnumerator
            ole32.CoCreateInstance.argtypes = [
                ctypes.POINTER(GUID), ctypes.c_void_p, ctypes.c_ulong,
                ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)
            ]
            ole32.CoCreateInstance.restype = ctypes.HRESULT

            enumerator = ctypes.c_void_p()
            hr = ole32.CoCreateInstance(
                ctypes.byref(clsid), None, 0x17,  # CLSCTX_ALL
                ctypes.byref(iid_enum), ctypes.byref(enumerator)
            )
            if hr != 0 or not enumerator.value:
                VolumeControl._status = f'CoCreate:0x{hr & 0xFFFFFFFF:X}'
                return False

            # IMMDeviceEnumerator::GetDefaultAudioEndpoint (vtable slot 4)
            vtbl_ptr = ctypes.cast(enumerator, ctypes.POINTER(ctypes.c_void_p))[0]
            vtbl = ctypes.cast(vtbl_ptr, ctypes.POINTER(ctypes.c_void_p))

            get_default = ctypes.WINFUNCTYPE(
                ctypes.HRESULT, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
                ctypes.POINTER(ctypes.c_void_p)
            )(vtbl[4])

            device = ctypes.c_void_p()
            hr = get_default(enumerator, 0, 0, ctypes.byref(device))  # eRender=0, eConsole=0
            if hr != 0 or not device.value:
                VolumeControl._status = f'GetDev:0x{hr & 0xFFFFFFFF:X}'
                return False

            # IMMDevice::Activate -> IAudioEndpointVolume (vtable slot 3)
            dev_vtbl_ptr = ctypes.cast(device, ctypes.POINTER(ctypes.c_void_p))[0]
            dev_vtbl = ctypes.cast(dev_vtbl_ptr, ctypes.POINTER(ctypes.c_void_p))

            activate = ctypes.WINFUNCTYPE(
                ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(GUID),
                ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
            )(dev_vtbl[3])

            volume = ctypes.c_void_p()
            hr = activate(device, ctypes.byref(iid_vol), 0x17, None, ctypes.byref(volume))
            if hr != 0 or not volume.value:
                VolumeControl._status = f'Activate:0x{hr & 0xFFFFFFFF:X}'
                return False

            # 释放enumerator和device（只需保留volume接口）
            release = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)
            release(dev_vtbl[2])(device)
            release(vtbl[2])(enumerator)

            VolumeControl._vol_ptr = volume
            VolumeControl._com_ok = True
            VolumeControl._status = 'COM_OK'
            print('[音量] COM初始化成功')
            return True

        except Exception as e:
            VolumeControl._status = f'err:{e}'
            print(f'[音量] COM初始化异常: {e}')
            return False

    @staticmethod
    def _read_volume():
        """通过COM读取真实音量和静音状态"""
        if not VolumeControl._com_ok or not VolumeControl._vol_ptr:
            return False
        try:
            vol_ptr = VolumeControl._vol_ptr
            vtbl_ptr = ctypes.cast(vol_ptr, ctypes.POINTER(ctypes.c_void_p))[0]
            vtbl = ctypes.cast(vtbl_ptr, ctypes.POINTER(ctypes.c_void_p))

            # GetMasterVolumeLevelScalar (vtable slot 9)
            get_vol = ctypes.WINFUNCTYPE(
                ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_float)
            )(vtbl[9])
            level = ctypes.c_float()
            hr = get_vol(vol_ptr, ctypes.byref(level))
            if hr == 0:
                VolumeControl._cached_volume = int(round(level.value * 100))
            else:
                VolumeControl._status = f'readVol:0x{hr & 0xFFFFFFFF:X}'
                VolumeControl._com_ok = False
                return False

            # GetMute (vtable slot 15)
            get_mute = ctypes.WINFUNCTYPE(
                ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)
            )(vtbl[15])
            mute_val = ctypes.c_int()
            hr = get_mute(vol_ptr, ctypes.byref(mute_val))
            if hr == 0:
                VolumeControl._cached_muted = bool(mute_val.value)

            VolumeControl._status = f'OK:{VolumeControl._cached_volume}%'
            return True
        except Exception as e:
            VolumeControl._status = f'readErr:{e}'
            VolumeControl._com_ok = False
            return False

    @staticmethod
    def _set_volume_com(val):
        """通过COM设置音量，并触发系统音量OSD显示"""
        if not VolumeControl._com_ok or not VolumeControl._vol_ptr:
            return False
        try:
            vol_ptr = VolumeControl._vol_ptr
            vtbl_ptr = ctypes.cast(vol_ptr, ctypes.POINTER(ctypes.c_void_p))[0]
            vtbl = ctypes.cast(vtbl_ptr, ctypes.POINTER(ctypes.c_void_p))
            # SetMasterVolumeLevelScalar (vtable slot 7)
            set_vol = ctypes.WINFUNCTYPE(
                ctypes.HRESULT, ctypes.c_void_p, ctypes.c_float, ctypes.c_void_p
            )(vtbl[7])
            hr = set_vol(vol_ptr, val / 100.0, None)
            if hr == 0:
                # 触发系统音量OSD：先发一个音量+再发一个音量-，让系统弹出音量条
                old_vol = VolumeControl._cached_volume
                if val < old_vol:
                    # 音量减了，发VK_VOLUME_DOWN触发OSD
                    ctypes.windll.user32.keybd_event(VolumeControl.VK_VOLUME_DOWN, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(VolumeControl.VK_VOLUME_DOWN, 0, 2, 0)
                    # 音量被减了1，补回来
                    set_vol(vol_ptr, val / 100.0, None)
                elif val > old_vol:
                    # 音量加了，发VK_VOLUME_UP触发OSD
                    ctypes.windll.user32.keybd_event(VolumeControl.VK_VOLUME_UP, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(VolumeControl.VK_VOLUME_UP, 0, 2, 0)
                    # 音量被加了1，补回来
                    set_vol(vol_ptr, val / 100.0, None)
                else:
                    # 音量没变，发VK_VOLUME_UP再VK_VOLUME_DOWN触发OSD
                    ctypes.windll.user32.keybd_event(VolumeControl.VK_VOLUME_UP, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(VolumeControl.VK_VOLUME_UP, 0, 2, 0)
                    set_vol(vol_ptr, val / 100.0, None)
                return True
            return False
        except:
            return False

    @staticmethod
    def _set_mute_com(mute_flag):
        """通过COM设置静音，并触发系统音量OSD显示"""
        if not VolumeControl._com_ok or not VolumeControl._vol_ptr:
            return False
        try:
            vol_ptr = VolumeControl._vol_ptr
            vtbl_ptr = ctypes.cast(vol_ptr, ctypes.POINTER(ctypes.c_void_p))[0]
            vtbl = ctypes.cast(vtbl_ptr, ctypes.POINTER(ctypes.c_void_p))
            # SetMute (vtable slot 14)
            set_mute = ctypes.WINFUNCTYPE(
                ctypes.HRESULT, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p
            )(vtbl[14])
            hr = set_mute(vol_ptr, 1 if mute_flag else 0, None)
            if hr == 0:
                # 发一次静音键触发系统OSD
                ctypes.windll.user32.keybd_event(VolumeControl.VK_VOLUME_MUTE, 0, 0, 0)
                ctypes.windll.user32.keybd_event(VolumeControl.VK_VOLUME_MUTE, 0, 2, 0)
                # 静音键会切换状态，如果OSD切换后的状态和我们想设的不一致，再设一次
                time.sleep(0.05)
                # 读取当前静音状态
                get_mute = ctypes.WINFUNCTYPE(
                    ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)
                )(vtbl[15])
                current = ctypes.c_int()
                get_mute(vol_ptr, ctypes.byref(current))
                if current.value != (1 if mute_flag else 0):
                    set_mute(vol_ptr, 1 if mute_flag else 0, None)
                return True
            return False
        except:
            return False

    @staticmethod
    def start_bg_monitor(app=None):
        VolumeControl._app_ref = app
        VolumeControl._bg_running = True
        VolumeControl._bg_thread = threading.Thread(target=VolumeControl._bg_loop, daemon=True)
        VolumeControl._bg_thread.start()

    @staticmethod
    def stop_bg_monitor():
        VolumeControl._bg_running = False

    @staticmethod
    def get_status():
        return VolumeControl._status

    @staticmethod
    def _bg_loop():
        # 初始化COM
        if VolumeControl._init_com():
            VolumeControl._read_volume()
            print(f'[音量] ★首次读取: {VolumeControl._cached_volume}% 静音={VolumeControl._cached_muted}')
        else:
            print(f'[音量] COM初始化失败: {VolumeControl._status}，使用keybd_event备用')

        # 立即刷新UI
        if VolumeControl._app_ref:
            try:
                VolumeControl._app_ref.root.after(0, VolumeControl._app_ref._update_volume_display)
            except:
                pass

        while VolumeControl._bg_running:
            if VolumeControl._com_ok:
                if not VolumeControl._read_volume():
                    # COM指针失效，重新初始化
                    print('[音量] 读取失败，重新初始化COM')
                    VolumeControl._init_com()
            else:
                # 尝试重新初始化
                VolumeControl._init_com()

            if VolumeControl._app_ref:
                try:
                    VolumeControl._app_ref.root.after(0, VolumeControl._app_ref._update_volume_display)
                except:
                    pass
            time.sleep(3)

    @staticmethod
    def get_volume():
        return VolumeControl._cached_volume

    @staticmethod
    def set_volume(val):
        val = max(0, min(100, val))
        if VolumeControl._com_ok:
            VolumeControl._set_volume_com(val)
        else:
            VolumeControl._key_event(VolumeControl.VK_VOLUME_DOWN, 50)
            time.sleep(0.1)
            VolumeControl._key_event(VolumeControl.VK_VOLUME_UP, max(1, val // 2))
        VolumeControl._cached_volume = val
        return True

    @staticmethod
    def volume_up(step=10):
        new_vol = min(100, VolumeControl._cached_volume + step)
        if VolumeControl._com_ok:
            VolumeControl._set_volume_com(new_vol)
        else:
            VolumeControl._key_event(VolumeControl.VK_VOLUME_UP, max(1, step // 2))
        VolumeControl._cached_volume = new_vol
        return True

    @staticmethod
    def volume_down(step=10):
        new_vol = max(0, VolumeControl._cached_volume - step)
        if VolumeControl._com_ok:
            VolumeControl._set_volume_com(new_vol)
        else:
            VolumeControl._key_event(VolumeControl.VK_VOLUME_DOWN, max(1, step // 2))
        VolumeControl._cached_volume = new_vol
        return True

    @staticmethod
    def mute():
        if VolumeControl._com_ok:
            VolumeControl._set_mute_com(True)
        else:
            VolumeControl._key_event(VolumeControl.VK_VOLUME_MUTE, 1)
        VolumeControl._cached_muted = True
        return True

    @staticmethod
    def unmute():
        if VolumeControl._com_ok:
            VolumeControl._set_mute_com(False)
        else:
            VolumeControl._key_event(VolumeControl.VK_VOLUME_MUTE, 1)
        VolumeControl._cached_muted = False
        return True

    @staticmethod
    def is_muted():
        return VolumeControl._cached_muted

    @staticmethod
    def _key_event(vk_code, press_count=1):
        try:
            for _ in range(press_count):
                ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
                ctypes.windll.user32.keybd_event(vk_code, 0, 2, 0)
                time.sleep(0.03)
            return True
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
    _cpu_inited = False

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
            # cpu_percent首次调用返回0，需要先调用一次初始化
            if not SystemInfo._cpu_inited:
                psutil.cpu_percent(interval=0)
                SystemInfo._cpu_inited = True
                time.sleep(0.3)
            info['cpu_percent'] = psutil.cpu_percent(interval=0)
            mem = psutil.virtual_memory()
            info['memory_total'] = mem.total
            info['memory_percent'] = mem.percent
            try:
                info['disk_percent'] = psutil.disk_usage('C:\\').percent if platform.system() == 'Windows' else psutil.disk_usage('/').percent
            except:
                info['disk_percent'] = 0
            info['uptime'] = int(time.time() - psutil.boot_time())
            print(f'[系统信息] psutil正常: CPU={info["cpu_percent"]}% MEM={info["memory_percent"]}% DISK={info["disk_percent"]}%')
        except Exception as e:
            print(f'[系统信息] psutil采集失败: {e}')
            info['cpu_percent'] = 0
            info['memory_percent'] = 0
            info['disk_percent'] = 0
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


# ===== UDP/TCP中控指令监听（兼容v1.1协议） =====
class ControlListener:
    """监听UDP和TCP中控指令，兼容原坤展成关机软件v1.1协议"""

    def __init__(self, on_command=None):
        self.on_command = on_command  # 回调：收到指令字符串
        self.udp_port = 5005
        self.tcp_port = 5006
        self.running = False
        self._udp_thread = None
        self._tcp_thread = None

    def start(self, udp_port=5005, tcp_port=5006):
        self.udp_port = udp_port
        self.tcp_port = tcp_port
        self.running = True
        self._udp_thread = threading.Thread(target=self._listen_udp, daemon=True)
        self._udp_thread.start()
        self._tcp_thread = threading.Thread(target=self._listen_tcp, daemon=True)
        self._tcp_thread.start()

    def stop(self):
        self.running = False

    def _listen_udp(self):
        """监听UDP指令"""
        while self.running:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.settimeout(3)
                sock.bind(('0.0.0.0', self.udp_port))
                print(f'[中控] UDP监听启动，端口: {self.udp_port}')
                while self.running:
                    try:
                        data, addr = sock.recvfrom(1024)
                        cmd = data.decode('utf-8').strip()
                        print(f'[中控] UDP收到: {cmd} 来自 {addr}')
                        if cmd and self.on_command:
                            self.on_command(cmd, 'udp')
                    except socket.timeout:
                        continue
                    except:
                        pass
            except Exception as e:
                print(f'[中控] UDP监听异常: {e}')
                time.sleep(3)

    def _listen_tcp(self):
        """监听TCP指令"""
        while self.running:
            try:
                server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.settimeout(3)
                server.bind(('0.0.0.0', self.tcp_port))
                server.listen(5)
                print(f'[中控] TCP监听启动，端口: {self.tcp_port}')
                while self.running:
                    try:
                        client, addr = server.accept()
                        client.settimeout(5)
                        data = client.recv(1024)
                        cmd = data.decode('utf-8').strip()
                        print(f'[中控] TCP收到: {cmd} 来自 {addr}')
                        if cmd and self.on_command:
                            self.on_command(cmd, 'tcp')
                            # 返回确认
                            client.send(b'OK')
                        client.close()
                    except socket.timeout:
                        continue
                    except:
                        pass
            except Exception as e:
                print(f'[中控] TCP监听异常: {e}')
                time.sleep(3)


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

        # 第二步：轮询指令 + 上报系统状态（GET方式，系统状态通过URL参数传递）
        try:
            fresh_info = SystemInfo.get_info()
            cpu = fresh_info.get('cpu_percent', 0)
            mem = fresh_info.get('memory_percent', 0)
            disk = fresh_info.get('disk_percent', 0)
            client_ip = fresh_info.get('ip', '')
            
            # 使用URL参数传递系统状态
            poll_url = f'{base_url}/api/client/poll?client_id={self.client_id}&cpu_percent={cpu}&memory_percent={mem}&disk_percent={disk}&ip={client_ip}'
            print(f'[轮询] URL: {poll_url}')
            print(f'[轮询] 系统状态: cpu={cpu}, mem={mem}, disk={disk}')
            req = urllib.request.Request(poll_url, method='GET')
            
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
        except urllib.error.HTTPError as e:
            if e.code == 400:
                # 未注册，标记需要重新注册
                self.client_id = ''
                print(f'[HTTP] 需要重新注册')
        except Exception as e:
            print(f'[HTTP] 轮询失败: {e}')

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


# ===== 远程桌面截屏服务 =====
_remote_desktop_server = None
_stream_server_sock = None
_last_screen_hash = None
_last_screen_jpeg = None
_screen_quality = 50

class ScreenHandler(BaseHTTPRequestHandler):
    """截屏HTTP请求处理器"""
    
    def log_message(self, format, *args):
        pass  # 静默日志
    
    def do_GET(self):
        global _last_screen_hash, _last_screen_jpeg, _screen_quality
        
        if self.path.startswith('/screen_info'):
            # 返回屏幕分辨率
            try:
                import mss
                with mss.mss() as sct:
                    monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                    info = json.dumps({'width': monitor['width'], 'height': monitor['height']})
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(info.encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())
            return
        
        if self.path.startswith('/screen'):
            try:
                import mss
                # 解析参数
                quality = _screen_quality
                check_hash = None
                if '?' in self.path:
                    params = self.path.split('?', 1)[1]
                    for p in params.split('&'):
                        if p.startswith('quality='):
                            quality = int(p.split('=')[1])
                        if p.startswith('hash='):
                            check_hash = p.split('=')[1]
                
                # 截屏
                with mss.mss() as sct:
                    monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                    screenshot = sct.grab(monitor)
                    img = Image.frombytes('RGB', screenshot.size, screenshot.bgra, 'raw', 'BGRX')
                
                # 压缩为JPEG
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=quality)
                jpeg_data = buf.getvalue()
                
                # 计算hash用于增量判断
                current_hash = hashlib.md5(jpeg_data).hexdigest()[:12]
                
                # 如果hash相同，返回304
                if check_hash and check_hash == current_hash:
                    self.send_response(304)
                    self.send_header('X-Hash', current_hash)
                    self.end_headers()
                    return
                
                _last_screen_hash = current_hash
                _last_screen_jpeg = jpeg_data
                
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(len(jpeg_data)))
                self.send_header('X-Hash', current_hash)
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(jpeg_data)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f'Screen capture error: {e}'.encode())
            return
        
        self.send_response(404)
        self.end_headers()
    
    def do_POST(self):
        """处理键鼠输入指令"""
        if self.path.startswith('/input'):
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length)
                input_data = json.loads(body.decode('utf-8'))
                
                import pyautogui
                pyautogui.FAILSAFE = False
                
                input_type = input_data.get('input_type', '')
                
                if input_type == 'mouse_move':
                    x, y = input_data.get('x', 0), input_data.get('y', 0)
                    pyautogui.moveTo(x, y, _pause=False)
                elif input_type == 'mouse_click':
                    x, y = input_data.get('x', 0), input_data.get('y', 0)
                    button = input_data.get('button', 'left')
                    clicks = input_data.get('clicks', 1)
                    pyautogui.click(x, y, button=button, clicks=clicks, _pause=False)
                elif input_type == 'mouse_drag':
                    x, y = input_data.get('x', 0), input_data.get('y', 0)
                    button = input_data.get('button', 'left')
                    pyautogui.dragTo(x, y, button=button, _pause=False)
                elif input_type == 'scroll':
                    x, y = input_data.get('x', 0), input_data.get('y', 0)
                    delta = input_data.get('delta', 0)
                    pyautogui.scroll(delta, x, y, _pause=False)
                elif input_type == 'key_press':
                    key = input_data.get('key', '')
                    if key:
                        pyautogui.press(key, _pause=False)
                elif input_type == 'key_hotkey':
                    keys = input_data.get('keys', [])
                    if keys:
                        pyautogui.hotkey(*keys, _pause=False)
                elif input_type == 'type_text':
                    text = input_data.get('text', '')
                    if text:
                        pyautogui.typewrite(text, _pause=False)
                elif input_type == 'set_quality':
                    global _screen_quality
                    _screen_quality = input_data.get('quality', 50)
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'ok'}).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())
            return
        
        self.send_response(404)
        self.end_headers()

def _stream_frames(conn):
    """TCP流推送——持续推送帧到服务器端（优化版）"""
    import mss
    import socket
    sct = mss.mss()
    monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
    
    prev_sample = None  # 上一帧采样，用于增量检测
    scale = 0.5  # 缩放比例，0.5=半分辨率
    frame_interval = 0.033  # 目标帧间隔（~30fps上限）
    last_frame_time = 0
    
    try:
        while True:
            now = time.time()
            # 帧率上限控制
            elapsed = now - last_frame_time
            if elapsed < frame_interval:
                time.sleep(frame_interval - elapsed)
            
            screenshot = sct.grab(monitor)
            raw = screenshot.bgra  # 原始BGRA字节
            
            # 增量检测：采样比较（每隔1000字节取1个，快速判断画面是否变化）
            sample = raw[::1000]
            if prev_sample is not None and sample == prev_sample:
                # 发送空帧标记（长度=0表示无变化）
                conn.sendall(struct.pack('!I', 0))
                continue
            prev_sample = sample
            
            # 转换并缩放
            img = Image.frombytes('RGB', screenshot.size, raw, 'raw', 'BGRX')
            
            if scale < 1.0:
                new_w = int(img.width * scale)
                new_h = int(img.height * scale)
                img = img.resize((new_w, new_h), Image.BILINEAR)
            
            # JPEG压缩（fast mode）
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=_screen_quality, subsampling=0, optimize=False)
            jpeg_data = buf.getvalue()
            
            # 发送：4字节长度 + 帧数据
            conn.sendall(struct.pack('!I', len(jpeg_data)) + jpeg_data)
            last_frame_time = time.time()
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    except Exception as e:
        print(f'[远程桌面] 流推送异常: {e}')
    finally:
        sct.close()
        try:
            conn.close()
        except:
            pass

def _stream_server_loop(port):
    """TCP流服务器——等待服务器端连接后推送帧"""
    global _stream_server_sock
    import socket
    _stream_server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _stream_server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    _stream_server_sock.bind(('0.0.0.0', port))
    _stream_server_sock.listen(1)
    _stream_server_sock.settimeout(1.0)
    print(f'[远程桌面] 流推送服务已启动，端口 {port}')
    
    while _remote_desktop_server:
        try:
            conn, addr = _stream_server_sock.accept()
            print(f'[远程桌面] 服务器连接: {addr}')
            t = threading.Thread(target=_stream_frames, args=(conn,), daemon=True)
            t.start()
        except socket.timeout:
            continue
        except:
            break
    
    try:
        _stream_server_sock.close()
    except:
        pass
    _stream_server_sock = None

def start_remote_desktop_server(port=5901):
    """启动远程桌面截屏服务"""
    global _remote_desktop_server
    try:
        _remote_desktop_server = HTTPServer(('0.0.0.0', port), ScreenHandler)
        t = threading.Thread(target=_remote_desktop_server.serve_forever, daemon=True)
        t.start()
        print(f'[远程桌面] 截屏服务已启动，端口 {port}')
        
        # 同时启动TCP流推送服务
        t2 = threading.Thread(target=_stream_server_loop, args=(port + 1,), daemon=True)
        t2.start()
        
        return True
    except Exception as e:
        print(f'[远程桌面] 截屏服务启动失败: {e}')
        return False

def stop_remote_desktop_server():
    """停止远程桌面截屏服务"""
    global _remote_desktop_server, _stream_server_sock
    if _remote_desktop_server:
        _remote_desktop_server.shutdown()
        _remote_desktop_server = None
    if _stream_server_sock:
        try:
            _stream_server_sock.close()
        except:
            pass
        _stream_server_sock = None
    print('[远程桌面] 服务已停止')


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
        elif cmd == 'start_remote_desktop':
            port = data.get('port', 5901)
            ok = start_remote_desktop_server(port)
            result = {'status': 'success' if ok else 'failed', 'msg': f'远程桌面服务已启动:{port}' if ok else '远程桌面服务启动失败'}
        elif cmd == 'stop_remote_desktop':
            stop_remote_desktop_server()
            result = {'status': 'success', 'msg': '远程桌面服务已停止'}
        elif cmd == 'remote_input':
            # 远程输入指令
            import pyautogui
            pyautogui.FAILSAFE = False
            input_type = data.get('input_type', '')
            try:
                if input_type == 'mouse_move':
                    x, y = data.get('x', 0), data.get('y', 0)
                    pyautogui.moveTo(x, y, _pause=False)
                elif input_type == 'mouse_click':
                    x, y = data.get('x', 0), data.get('y', 0)
                    button = data.get('button', 'left')
                    clicks = data.get('clicks', 1)
                    pyautogui.click(x, y, button=button, clicks=clicks, _pause=False)
                elif input_type == 'mouse_drag':
                    x, y = data.get('x', 0), data.get('y', 0)
                    button = data.get('button', 'left')
                    pyautogui.dragTo(x, y, button=button, _pause=False)
                elif input_type == 'scroll':
                    x, y = data.get('x', 0), data.get('y', 0)
                    delta = data.get('delta', 0)
                    pyautogui.scroll(delta, x, y, _pause=False)
                elif input_type == 'key_press':
                    key = data.get('key', '')
                    if key:
                        pyautogui.press(key, _pause=False)
                elif input_type == 'key_hotkey':
                    keys = data.get('keys', [])
                    if keys:
                        pyautogui.hotkey(*keys, _pause=False)
                elif input_type == 'type_text':
                    text = data.get('text', '')
                    if text:
                        pyautogui.typewrite(text, _pause=False)
                result = {'status': 'success', 'msg': f'输入已执行: {input_type}'}
            except Exception as e:
                result = {'status': 'failed', 'msg': f'输入执行失败: {e}'}
        elif cmd == 'file_transfer':
            # 文件传输指令
            file_name = data.get('extra', {}).get('file_name', '')
            file_size = data.get('extra', {}).get('file_size', 0)
            download_url = data.get('extra', {}).get('download_url', '')
            server_file_name = data.get('extra', {}).get('server_file_name', '')
            if file_name and download_url:
                # 在后台线程下载文件
                threading.Thread(target=self._download_file, args=(task_id, file_name, file_size, download_url, server_file_name), daemon=True).start()
                result = {'status': 'pending', 'msg': f'正在接收文件: {file_name}'}
            else:
                result = {'status': 'failed', 'msg': '文件传输参数不完整'}

        print(f'[指令] 结果: {result}')
        self.app.http_client.send_result(task_id, result['status'], result['msg'])
        self.app.root.after(0, lambda: self.app._show_msg(f'远程指令 {cmd}: {result["msg"]}'))
        return result

    def _download_file(self, task_id, file_name, file_size, download_url, server_file_name=''):
        """后台下载文件（POST方式，支持中文文件名）"""
        import urllib.request
        import urllib.error
        
        # 展开环境变量
        download_dir = self.app.config.get('download_dir', '')
        if not download_dir:
            # 默认保存到桌面/KZC_Received
            desktop = os.path.expandvars('%USERPROFILE%\\Desktop')
            download_dir = os.path.join(desktop, 'KZC_Received')
        
        # 安全检查：文件名不能包含路径穿越
        file_name = os.path.basename(file_name)
        
        # 创建下载目录
        try:
            os.makedirs(download_dir, exist_ok=True)
        except Exception as e:
            self.app.http_client.send_result(task_id, 'failed', f'创建目录失败: {e}')
            self.app.root.after(0, lambda: self.app._show_msg(f'文件传输失败: {e}'))
            return
        
        dest_path = os.path.join(download_dir, file_name)
        
        try:
            print(f'[文件传输] 开始下载: {file_name} ({file_size} bytes) -> {dest_path}')
            self.app.root.after(0, lambda: self.app._show_msg(f'正在接收文件: {file_name}'))
            
            # 用POST请求下载，文件名在body中，支持中文
            post_data = json.dumps({
                'file_name': file_name,
                'server_file_name': server_file_name
            }).encode('utf-8')
            req = urllib.request.Request(download_url, data=post_data, 
                                        headers={'Content-Type': 'application/json', 'User-Agent': 'KZC-Terminal-Manager'},
                                        method='POST')
            with urllib.request.urlopen(req, timeout=60) as resp:
                total_read = 0
                with open(dest_path, 'wb') as f:
                    while True:
                        chunk = resp.read(65536)  # 64KB
                        if not chunk:
                            break
                        f.write(chunk)
                        total_read += len(chunk)
            
            print(f'[文件传输] 下载完成: {dest_path}')
            self.app.http_client.send_result(task_id, 'success', f'文件已保存: {dest_path}')
            self.app.root.after(0, lambda fn=file_name, dp=dest_path: self.app._show_file_received(fn, dp))
            
        except urllib.error.URLError as e:
            print(f'[文件传输] 下载失败: {e}')
            self.app.http_client.send_result(task_id, 'failed', f'下载失败: {e}')
            self.app.root.after(0, lambda: self.app._show_msg(f'文件传输失败: {e}'))
        except Exception as e:
            print(f'[文件传输] 异常: {e}')
            self.app.http_client.send_result(task_id, 'failed', f'异常: {e}')
            self.app.root.after(0, lambda: self.app._show_msg(f'文件传输失败: {e}'))


# ===== 主窗口 =====
class TerminalApp:
    def __init__(self):
        self.config = load_config()
        self.root = tk.Tk()
        icon_path = resource_path('icon.ico')
        if os.path.exists(icon_path):
            self.root.iconbitmap(icon_path)
        self.root.title('坤展成终端管理系统 v1.4.0')
        self.root.geometry('800x680')
        self.root.resizable(True, True)
        self.root.minsize(800, 680)

        self.http_client = HTTPClient(on_command=self._on_http_command)
        self.command_handler = CommandHandler(self)
        self.server_discovery = ServerDiscovery(on_found=self._on_server_found)
        self.control_listener = ControlListener(on_command=self._on_control_command)

        self._build_ui()
        self._load_config_to_ui()

        self.server_discovery.start()
        saved_ip = self.config.get('server_ip', '')
        if saved_ip:
            self.http_client.configure(saved_ip, self.config.get('server_port', 8080))
        self.http_client.start()
        # 启动中控UDP/TCP监听
        self.control_listener.start(udp_port=5005, tcp_port=5006)
        # 启动后台音量监控
        VolumeControl.start_bg_monitor(app=self)

        self._refresh_status()
        
        # ===== 启动时自动延时启动 =====
        # 启动delayed_apps中的程序
        delayed_apps = self.config.get('delayed_apps', [])
        if delayed_apps:
            threading.Thread(target=self._auto_start_delayed_apps, args=(delayed_apps,), daemon=True).start()
        
        # 启动enabled且delay>0的startup_items
        startup_items = self.config.get('startup_items', [])
        startup_with_delay = [item for item in startup_items if item.get('enabled', True) and item.get('delay', 0) > 0]
        if startup_with_delay:
            threading.Thread(target=self._auto_start_delayed_apps, args=(startup_with_delay,), daemon=True).start()
        
        # 同步启动项到注册表（确保enabled状态的项写入注册表）
        if startup_items:
            _sync_startup_to_registry(startup_items)

        # 启动系统托盘
        _start_tray(self.root)
        
        # 记录是否需要启动时最小化到托盘
        self._start_minimized = self.config.get('minimize_to_tray', False)

    def _on_http_command(self, data):
        """HTTP轮询收到指令"""
        self.root.after(0, lambda: self.command_handler.handle(data))

    def _on_control_command(self, cmd, source='udp'):
        """中控UDP/TCP收到指令"""
        print(f'[中控] 收到指令: {cmd} ({source})')
        cmd_map = {
            'shutdown': 'shutdown', 'restart': 'restart', 'cancel': 'cancel',
            'volume:up': 'volume:up', 'volume:down': 'volume:down',
            'mute': 'mute', 'unmute': 'unmute', 'status': 'status', 'help': 'help',
        }
        mapped_cmd = cmd_map.get(cmd.lower().strip(), cmd.lower().strip())
        data = {'id': f'ctrl_{int(time.time())}', 'cmd': mapped_cmd}
        self.root.after(0, lambda: self.command_handler.handle(data))
        self.root.after(0, lambda: self._show_msg(f'中控指令({source}): {mapped_cmd}'))

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
        tk.Label(title_frame, text='坤展成终端管理系统 v1.3-58',
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
        self.step_spin = tk.Spinbox(step_frame, from_=1, to=50, textvariable=self.var_step, width=5,
                command=self._save_step)
        self.step_spin.pack(side='left', padx=3)
        # 回车保存并移走光标
        self.step_spin.bind('<Return>', lambda e: (self._save_step(), self.step_spin.selection_clear(), self.root.focus_set()))
        # 失去焦点时保存并清除选择
        self.step_spin.bind('<FocusOut>', lambda e: (self._save_step(), self.step_spin.selection_clear()))
        # 点击窗口任意控件时，如果焦点在步长框则移走光标
        self.root.bind_all('<Button-1>', self._on_click_anywhere)
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
        
        # 下载目录设置
        tk.Label(net_grid, text='下载目录：', font=('Microsoft YaHei', 9)).grid(row=3, column=0, sticky='e', pady=2)
        dl_dir_frame = tk.Frame(net_grid)
        dl_dir_frame.grid(row=3, column=1, pady=2, padx=5, sticky='w')
        self.var_download_dir = tk.StringVar(value='')
        tk.Entry(dl_dir_frame, textvariable=self.var_download_dir, width=25, font=('Microsoft YaHei', 9)).pack(side='left')
        tk.Button(dl_dir_frame, text='浏览', width=5, command=self._browse_download_dir).pack(side='left', padx=3)
        
        self.var_min_tray = tk.BooleanVar(value=False)
        tk.Checkbutton(net_grid, text='启动时最小化到托盘', variable=self.var_min_tray, font=('Microsoft YaHei', 9)).grid(row=4, column=0, columnspan=2, sticky='w', pady=2)

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
        # 下载目录：支持环境变量展开
        dl_dir = cfg.get('download_dir', '')
        if not dl_dir:
            desktop = os.path.expandvars('%USERPROFILE%\\Desktop')
            dl_dir = os.path.join(desktop, 'KZC_Received')
        self.var_download_dir.set(dl_dir)
        if cfg.get('activated'):
            self.lbl_activate.config(text='已激活（永久版）', fg='#27ae60')
        for item in cfg.get('delayed_apps', []):
            self.delay_tree.insert('', 'end', values=(item['name'], item.get('delay', 0), item['path']))
        for item in cfg.get('startup_items', []):
            en = '✓' if item.get('enabled', True) else '✗'
            self.startup_tree.insert('', 'end', values=(en, item['name'], item.get('delay', 0), item['path']))

    # ==================== 音量操作 ====================
    def _browse_download_dir(self):
        """浏览选择下载目录"""
        path = filedialog.askdirectory(title='选择文件接收目录')
        if path:
            self.var_download_dir.set(path)
    def _vol_up(self):
        step = self.var_step.get()
        VolumeControl.volume_up(step)
        self._update_volume_display()
        self._show_msg(f'音量+{step}%')

    def _vol_down(self):
        step = self.var_step.get()
        VolumeControl.volume_down(step)
        self._update_volume_display()
        self._show_msg(f'音量-{step}%')

    def _mute(self):
        VolumeControl.mute()
        self._update_volume_display()
        self._show_msg('已静音')

    def _unmute(self):
        VolumeControl.unmute()
        self._update_volume_display()
        self._show_msg('已取消静音')

    def _save_step(self):
        self.config['volume_step'] = self.var_step.get()
        save_config(self.config)

    def _on_click_anywhere(self, event):
        """点击窗口任意地方时，如果焦点在步长框且点击的不是步长框，移走光标"""
        try:
            w = event.widget
            # 检查点击的是不是步长框或其子组件
            is_spin = False
            try:
                p = w
                for _ in range(10):
                    if p == self.step_spin:
                        is_spin = True
                        break
                    p = p.master
            except:
                pass
            if not is_spin and self.root.focus_get() == self.step_spin:
                self._save_step()
                self.step_spin.selection_clear()
                self.root.focus_set()
        except:
            pass

    def _update_volume_display(self):
        vol = VolumeControl.get_volume()
        muted = VolumeControl.is_muted()
        mute_str = ' 已静音' if muted else ' 未静音'
        st = VolumeControl.get_status()
        # 采集系统信息显示在状态栏
        sys_info = SystemInfo.get_info()
        cpu = sys_info.get('cpu_percent', '?')
        mem = sys_info.get('memory_percent', '?')
        disk = sys_info.get('disk_percent', '?')
        self.lbl_volume.config(text=f'音量：{vol}%{mute_str} | CPU:{cpu}% MEM:{mem}% DISK:{disk}%')
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
    
    def _show_file_received(self, file_name, dest_path):
        """显示文件接收完成提示弹窗，3秒自动消失"""
        dlg = tk.Toplevel(self.root)
        dlg.title('文件接收完成')
        dlg.geometry('320x100')
        dlg.resizable(False, False)
        dlg.attributes('-topmost', True)
        # 居中显示
        dlg.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 320) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 100) // 2
        dlg.geometry(f'+{x}+{y}')
        
        tk.Label(dlg, text='✅ 文件接收完成', font=('Microsoft YaHei', 11, 'bold'), fg='#27ae60').pack(pady=(10, 2))
        tk.Label(dlg, text=f'{file_name}', font=('Microsoft YaHei', 9), fg='#2c3e50').pack()
        tk.Label(dlg, text=f'保存至: {dest_path}', font=('Microsoft YaHei', 8), fg='#7f8c8d').pack()
        
        # 3秒后自动关闭
        dlg.after(3000, dlg.destroy)

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

    def _auto_start_delayed_apps(self, app_list):
        """自动延时启动列表中的应用（按顺序延时启动）"""
        print(f'[自动启动] 开始延时启动 {len(app_list)} 个应用')
        for i, item in enumerate(app_list):
            delay = item.get('delay', 0)
            name = item.get('name', '未知')
            path = item.get('path', '')
            if i > 0 and delay > 0:
                print(f'[自动启动] 等待 {delay} 秒后启动 {name}...')
                time.sleep(delay)
            elif i == 0 and delay > 0:
                # 第一个应用也等待延时
                print(f'[自动启动] 等待 {delay} 秒后启动 {name}...')
                time.sleep(delay)
            if path and os.path.exists(path):
                try:
                    print(f'[自动启动] 启动 {name}: {path}')
                    os.startfile(path)
                except Exception as e:
                    print(f'[自动启动] 启动失败 {name}: {e}')
            else:
                print(f'[自动启动] 路径不存在: {path}')

    # ==================== 启动项管理 ====================
    def _add_startup(self):
        path = filedialog.askopenfilename(title='选择启动程序', filetypes=[('程序', '*.exe *.bat *.cmd *.lnk'), ('所有文件', '*.*')])
        if not path:
            return
        name = os.path.basename(path)
        # 弹窗设置延时
        dlg = tk.Toplevel(self.root)
        dlg.title('设置启动项')
        dlg.geometry('280x130')
        dlg.resizable(False, False)
        tk.Label(dlg, text=f'应用：{name}', font=('Microsoft YaHei', 9)).pack(pady=5)
        tk.Label(dlg, text='延时启动（秒，0表示立即启动）：', font=('Microsoft YaHei', 9)).pack()
        var_d = tk.IntVar(value=0)
        tk.Entry(dlg, textvariable=var_d, width=10).pack(pady=5)
        def confirm():
            nonlocal name, path
            delay = var_d.get()
            enabled = True
            self.startup_tree.insert('', 'end', values=('✓', name, delay, path))
            self.config.setdefault('startup_items', []).append({'name': name, 'delay': delay, 'path': path, 'enabled': enabled})
            save_config(self.config)
            # 同步写入注册表
            _write_startup_reg(name, path)
            dlg.destroy()
        tk.Button(dlg, text='确定', command=confirm).pack(pady=5)

    def _del_startup(self):
        sel = self.startup_tree.selection()
        if not sel:
            return
        for item in sel:
            vals = self.startup_tree.item(item, 'values')
            name = vals[1]
            self.startup_tree.delete(item)
            self.config['startup_items'] = [a for a in self.config.get('startup_items', []) if not (a['name'] == vals[1] and a['path'] == vals[3])]
            # 同步从注册表删除
            _delete_startup_reg(name)
        save_config(self.config)

    def _toggle_startup(self):
        sel = self.startup_tree.selection()
        if not sel:
            return
        for item in sel:
            vals = list(self.startup_tree.item(item, 'values'))
            name = vals[1]
            path = vals[3]
            vals[0] = '✗' if vals[0] == '✓' else '✓'
            self.startup_tree.item(item, values=vals)
            for a in self.config.get('startup_items', []):
                if a['name'] == vals[1] and a['path'] == vals[3]:
                    a['enabled'] = (vals[0] == '✓')
                    # 同步操作注册表
                    if a['enabled']:
                        _write_startup_reg(name, path)
                    else:
                        _delete_startup_reg(name)
        save_config(self.config)

    # ==================== 保存/激活/退出 ====================
    def _save_settings(self):
        self.config['minimize_to_tray'] = self.var_min_tray.get()
        self.config['volume_step'] = self.var_step.get()
        self.config['download_dir'] = self.var_download_dir.get()
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
        status_parts = []
        if self.http_client.connected:
            status_parts.append(f'服务器:已连接')
        elif self.var_server_ip.get():
            status_parts.append(f'服务器:连接中...')
        else:
            status_parts.append('服务器:搜索中')
        status_parts.append(f'UDP:{5005} TCP:{5006}')
        self.lbl_network.config(text='通讯：' + ' | '.join(status_parts),
                               fg='#27ae60' if self.http_client.connected else '#f39c12')
        self.root.after(3000, self._refresh_status)

    def _hide_to_tray(self):
        """隐藏窗口到托盘"""
        self.root.withdraw()  # 隐藏窗口

    def _quit(self):
        """真正退出程序"""
        _stop_tray()  # 先停止托盘
        self.http_client.stop()
        self.server_discovery.stop()
        self.control_listener.stop()
        VolumeControl.stop_bg_monitor()
        self.root.destroy()

    def run(self):
        # 设置窗口关闭事件处理（点X按钮时隐藏到托盘而不是退出）
        self.root.protocol('WM_DELETE_WINDOW', self._hide_to_tray)
        
        # 如果设置了启动时最小化到托盘，则隐藏窗口
        if getattr(self, '_start_minimized', False):
            self.root.after(100, self.root.withdraw)  # 延迟一点隐藏，确保窗口创建完成
            print('[托盘] 启动时最小化到托盘')
        
        self.root.mainloop()


if __name__ == '__main__':
    app = TerminalApp()
    app.run()
