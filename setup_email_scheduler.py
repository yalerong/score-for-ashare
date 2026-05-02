#!/usr/bin/env python3
"""
设置邮件定时任务
每天收盘后自动计算情绪指标并发送邮件
"""

import os
import platform
import sys
from datetime import datetime


def setup_windows_task():
    """设置Windows定时任务"""
    print("\n" + "=" * 60)
    print("设置Windows定时任务")
    print("=" * 60)
    
    project_dir = os.path.dirname(os.path.abspath(__file__))
    report_script = os.path.join(project_dir, 'daily_sentiment_report.py')
    python_path = sys.executable
    
    print(f"\n项目目录: {project_dir}")
    print(f"报告脚本: {report_script}")
    
    print("\n请选择定时任务时间:")
    print("1. 每天收盘后 (15:35)")
    print("2. 每天收盘后 (16:00)")
    print("3. 每天收盘后 (17:00)")
    print("4. 自定义时间")
    print("5. 删除现有任务")
    
    choice = input("\n请选择 (1-5): ").strip()
    
    if choice == '5':
        cmd = 'schtasks /delete /tn "A股情绪指标日报" /f'
        os.system(cmd)
        print("\n✅ 任务已删除")
        return
    
    if choice == '1':
        time_str = "15:35"
    elif choice == '2':
        time_str = "16:00"
    elif choice == '3':
        time_str = "17:00"
    elif choice == '4':
        time_str = input("请输入运行时间 (HH:MM, 例如 15:35): ").strip()
    else:
        print("无效选项")
        return
    
    # 创建任务（只在工作日运行）
    cmd = f'''
    schtasks /create /tn "A股情绪指标日报" /tr "\\\"{python_path}\\\" \\\"{report_script}\\\"" /sc weekly /d MON,TUE,WED,THU,FRI /st {time_str} /f
    '''
    
    print(f"\n正在创建任务: 工作日 {time_str} 运行...")
    result = os.system(cmd)
    
    if result == 0:
        print(f"\n✅ 任务创建成功!")
        print(f"   任务名称: A股情绪指标日报")
        print(f"   执行时间: 工作日 {time_str}")
        print(f"   执行脚本: {report_script}")
        print(f"\n您可以在 '任务计划程序' 中查看和管理此任务")
        print("提示: 需要确保电脑在运行时间处于开机状态")
    else:
        print(f"\n❌ 任务创建失败，请检查权限")
        print("   提示: 需要以管理员身份运行命令提示符")


def create_bat_file():
    """创建批处理文件（手动运行）"""
    print("\n" + "=" * 60)
    print("创建批处理文件")
    print("=" * 60)
    
    project_dir = os.path.dirname(os.path.abspath(__file__))
    report_script = os.path.join(project_dir, 'daily_sentiment_report.py')
    python_path = sys.executable
    
    bat_content = f'''@echo off
chcp 65001 >nul
title A股情绪指标日报
cd /d "{project_dir}"
echo.
echo ========================================
echo A股情绪指标日报
echo ========================================
echo.
echo 正在计算情绪指标并发送邮件...
echo.
"{python_path}" "{report_script}"
echo.
echo ========================================
echo 按任意键退出...
pause >nul
'''
    
    bat_path = os.path.join(project_dir, '发送情绪指标邮件.bat')
    with open(bat_path, 'w', encoding='utf-8') as f:
        f.write(bat_content)
    
    print(f"\n✅ 批处理文件已创建: {bat_path}")
    print("   双击此文件即可手动运行并发送邮件")


def show_config_guide():
    """显示配置指南"""
    print("\n" + "=" * 60)
    print("📧 邮件配置指南")
    print("=" * 60)
    
    print("""
在定时任务运行之前，请先配置邮件信息：

1. 打开 sentiment_email_sender.py 文件

2. 修改 EMAIL_CONFIG 配置：

   EMAIL_CONFIG = {
       # SMTP服务器配置
       'smtp_server': 'smtp.qq.com',      # QQ邮箱服务器
       'smtp_port': 465,                   # QQ邮箱端口
       'use_ssl': True,                    # 使用SSL
       
       # 发件人配置
       'sender_email': 'your_email@qq.com',    # ← 修改为你的QQ邮箱
       'sender_password': 'your_auth_code',     # ← 修改为邮箱授权码
       
       # 收件人配置
       'receiver_emails': [
           'receiver@example.com',              # ← 修改为收件人邮箱
           # 可以添加多个收件人
       ],
   }

3. 如何获取邮箱授权码：
   - QQ邮箱: 设置 -> 账户 -> 开启SMTP服务 -> 获取授权码
   - 163邮箱: 设置 -> POP3/SMTP/IMAP -> 开启服务 -> 获取授权码
   - Gmail: 需要使用应用专用密码

4. 测试邮件发送：
   python sentiment_email_sender.py

""")


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("A股情绪指标 - 邮件定时任务设置")
    print("=" * 60)
    
    system = platform.system()
    print(f"\n检测到操作系统: {system}")
    
    print("\n请选择操作:")
    print("1. 设置定时任务（每天自动运行）")
    print("2. 创建批处理文件（手动运行）")
    print("3. 查看邮件配置指南")
    print("4. 删除定时任务")
    
    choice = input("\n请选择 (1-4): ").strip()
    
    if choice == '1':
        if system == 'Windows':
            setup_windows_task()
        else:
            print("\n❌ 暂不支持此操作系统")
            print("   请手动设置cron任务")
    elif choice == '2':
        create_bat_file()
    elif choice == '3':
        show_config_guide()
    elif choice == '4':
        if system == 'Windows':
            cmd = 'schtasks /delete /tn "A股情绪指标日报" /f'
            os.system(cmd)
            print("\n✅ 任务已删除")
        else:
            print("\n请手动删除cron任务")
    else:
        print("无效选项")


if __name__ == '__main__':
    main()
