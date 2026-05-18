"""坤展成终端管理系统 - 注册码生成器（独立工具）"""
import tkinter as tk
from tkinter import messagebox
import hashlib


def generate_activation_key(serial):
    """根据序列号生成注册码"""
    secret = 'KZC-ACTIVATE-2026-SECRET'
    h = hashlib.sha256((serial + secret).encode()).hexdigest().upper()
    return f'{h[0:4]}-{h[4:8]}-{h[8:12]}-{h[12:16]}'


class KeyGenApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('注册码生成器 - 坤展成终端管理系统')
        self.root.geometry('480x320')
        self.root.resizable(False, False)
        self.root.configure(bg='#2c3e50')

        # 标题
        tk.Label(self.root, text='🔑 注册码生成器', font=('Microsoft YaHei', 18, 'bold'),
                 fg='white', bg='#2c3e50').pack(pady=(25, 5))
        tk.Label(self.root, text='坤展成终端管理系统', font=('Microsoft YaHei', 10),
                 fg='#bdc3c7', bg='#2c3e50').pack(pady=(0, 20))

        # 序列号输入
        input_frame = tk.Frame(self.root, bg='#2c3e50')
        input_frame.pack(padx=40, fill='x')

        tk.Label(input_frame, text='序列号：', font=('Microsoft YaHei', 11),
                 fg='white', bg='#2c3e50').pack(side='left')
        self.var_serial = tk.StringVar()
        tk.Entry(input_frame, textvariable=self.var_serial, width=28,
                 font=('Consolas', 12)).pack(side='left', padx=5, fill='x', expand=True)

        # 结果显示
        result_frame = tk.Frame(self.root, bg='#ecf0f1', relief='groove', bd=2)
        result_frame.pack(padx=40, fill='x', pady=20)

        tk.Label(result_frame, text='注册码：', font=('Microsoft YaHei', 10),
                 bg='#ecf0f1').pack(anchor='w', padx=10, pady=(8, 0))
        self.var_result = tk.StringVar(value='')
        tk.Label(result_frame, textvariable=self.var_result, font=('Consolas', 14, 'bold'),
                 fg='#27ae60', bg='#ecf0f1').pack(padx=10, pady=(2, 8))

        # 按钮
        btn_frame = tk.Frame(self.root, bg='#2c3e50')
        btn_frame.pack(pady=5)

        tk.Button(btn_frame, text='生成注册码', command=self._generate,
                  bg='#8e44ad', fg='white', font=('Microsoft YaHei', 11, 'bold'),
                  width=14, cursor='hand2').pack(side='left', padx=5)
        tk.Button(btn_frame, text='复制注册码', command=self._copy,
                  bg='#27ae60', fg='white', font=('Microsoft YaHei', 11, 'bold'),
                  width=14, cursor='hand2').pack(side='left', padx=5)

    def _generate(self):
        serial = self.var_serial.get().strip().upper()
        if not serial:
            messagebox.showwarning('提示', '请输入序列号')
            return
        key = generate_activation_key(serial)
        self.var_result.set(key)
        self.last_key = key

    def _copy(self):
        key = self.var_result.get()
        if not key:
            messagebox.showwarning('提示', '请先生成注册码')
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(key)
        messagebox.showinfo('成功', '注册码已复制到剪贴板')

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    KeyGenApp().run()
