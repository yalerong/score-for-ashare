#!/usr/bin/env python3
"""
定时任务设置模块
支持Windows任务计划程序和Linux cron
"""

import os
import platform
import sys
from datetime import datetime


def setup_windows_task():
    """设置Windows任务计划程序"""
    print("\n" + "=" * 60)
    print("设置Windows定时任务")
    print("=" * 60)
    
    script_path = os.path.abspath(__file__)
    project_dir = os.path.dirname(script_path)
    tracker_script = os.path.join(project_dir, 'sentiment_tracker.py')
    
    print(f"\n项目目录: {project_dir}")
    print(f"追踪器脚本: {tracker_script}")
    
    print("\n请选择定时任务频率:")
    print("1. 每天收盘后运行一次 (15:30)")
    print("2. 每小时运行一次 (交易日 9:30-15:30)")
    print("3. 每30分钟运行一次")
    print("4. 自定义")
    print("5. 删除现有任务")
    
    choice = input("\n请选择 (1-5): ").strip()
    
    if choice == '5':
        # 删除任务
        cmd = 'schtasks /delete /tn "A股情绪指标追踪器" /f'
        os.system(cmd)
        print("\n✅ 任务已删除")
        return
    
    # 构建Python路径
    python_path = sys.executable
    
    if choice == '1':
        # 每天15:30运行
        cmd = f'''
        schtasks /create /tn "A股情绪指标追踪器" /tr "\\\"{python_path}\\\" \\\"{tracker_script}\\\"" /sc daily /st 15:30 /f
        '''
        description = "每天15:30运行"
        
    elif choice == '2':
        # 每小时运行（简化版，实际需要多个任务）
        print("\n⚠️ 每小时运行需要创建多个任务")
        print("建议: 使用实时监控模式代替")
        return
        
    elif choice == '3':
        # 每30分钟运行
        print("\n⚠️ 每30分钟运行需要创建多个任务")
        print("建议: 使用实时监控模式代替")
        return
        
    elif choice == '4':
        print("\n自定义设置:")
        time_str = input("请输入运行时间 (HH:MM, 例如 15:30): ").strip()
        cmd = f'''
        schtasks /create /tn "A股情绪指标追踪器" /tr "\\\"{python_path}\\\" \\\"{tracker_script}\\\"" /sc daily /st {time_str} /f
        '''
        description = f"每天{time_str}运行"
        
    else:
        print("无效选项")
        return
    
    # 执行任务创建命令
    print(f"\n正在创建任务: {description}...")
    result = os.system(cmd)
    
    if result == 0:
        print(f"\n✅ 任务创建成功!")
        print(f"   任务名称: A股情绪指标追踪器")
        print(f"   执行时间: {description}")
        print(f"\n您可以在 '任务计划程序' 中查看和管理此任务")
    else:
        print(f"\n❌ 任务创建失败，请检查权限")
        print("   提示: 需要以管理员身份运行")


def setup_linux_cron():
    """设置Linux cron任务"""
    print("\n" + "=" * 60)
    print("设置Linux定时任务 (crontab)")
    print("=" * 60)
    
    script_path = os.path.abspath(__file__)
    project_dir = os.path.dirname(script_path)
    tracker_script = os.path.join(project_dir, 'sentiment_tracker.py')
    python_path = sys.executable
    
    print(f"\n项目目录: {project_dir}")
    
    print("\n请选择定时任务频率:")
    print("1. 每天收盘后运行一次 (15:30)")
    print("2. 工作日每小时运行")
    print("3. 自定义")
    print("4. 查看当前crontab")
    print("5. 删除所有情绪指标任务")
    
    choice = input("\n请选择 (1-5): ").strip()
    
    if choice == '4':
        os.system('crontab -l')
        return
    
    if choice == '5':
        # 获取当前crontab
        current = os.popen('crontab -l 2>/dev/null').read()
        # 过滤掉情绪指标相关的任务
        new_cron = '\n'.join([line for line in current.split('\n') 
                              if 'sentiment_tracker' not in line])
        
        # 写入新的crontab
        with open('/tmp/cron_temp', 'w') as f:
            f.write(new_cron)
        os.system('crontab /tmp/cron_temp')
        os.remove('/tmp/cron_temp')
        print("\n✅ 相关任务已删除")
        return
    
    # 构建cron表达式
    if choice == '1':
        cron_expr = "30 15 * * 1-5"  # 工作日15:30
        description = "工作日15:30运行"
    elif choice == '2':
        cron_expr = "0 9-15 * * 1-5"  # 工作日9-15点每小时
        description = "工作日9-15点每小时运行"
    elif choice == '3':
        print("\n请输入cron表达式")
        print("格式: 分 时 日 月 星期")
        print("示例: 30 15 * * 1-5 (工作日15:30)")
        cron_expr = input("cron表达式: ").strip()
        description = f"自定义: {cron_expr}"
    else:
        print("无效选项")
        return
    
    # 构建完整的cron任务
    cron_job = f"{cron_expr} cd {project_dir} && {python_path} {tracker_script} >> {project_dir}/logs/cron.log 2>&1"
    
    # 获取当前crontab
    current_cron = os.popen('crontab -l 2>/dev/null').read()
    
    # 检查是否已存在
    if 'sentiment_tracker' in current_cron:
        print("\n⚠️  已存在情绪指标任务")
        replace = input("是否替换现有任务? (y/n): ").strip().lower()
        if replace != 'y':
            return
        # 移除旧任务
        current_cron = '\n'.join([line for line in current_cron.split('\n') 
                                  if 'sentiment_tracker' not in line])
    
    # 添加新任务
    new_cron = current_cron + '\n' + cron_job + '\n'
    
    # 写入crontab
    with open('/tmp/cron_temp', 'w') as f:
        f.write(new_cron)
    
    result = os.system('crontab /tmp/cron_temp')
    os.remove('/tmp/cron_temp')
    
    if result == 0:
        print(f"\n✅ 任务创建成功!")
        print(f"   {description}")
        print(f"   cron表达式: {cron_expr}")
        print(f"\n使用 'crontab -l' 查看所有任务")
    else:
        print("\n❌ 任务创建失败")


def create_bat_file():
    """创建Windows批处理文件"""
    print("\n" + "=" * 60)
    print("创建批处理文件")
    print("=" * 60)
    
    script_path = os.path.abspath(__file__)
    project_dir = os.path.dirname(script_path)
    tracker_script = os.path.join(project_dir, 'sentiment_tracker.py')
    python_path = sys.executable
    
    bat_content = f'''@echo off
chcp 65001 >nul
title A股情绪指标追踪器
cd /d "{project_dir}"
echo 正在启动A股情绪指标追踪器...
echo.
"{python_path}" "{tracker_script}"
echo.
echo 按任意键退出...
pause >nul
'''
    
    bat_path = os.path.join(project_dir, '运行追踪器.bat')
    with open(bat_path, 'w', encoding='utf-8') as f:
        f.write(bat_content)
    
    print(f"\n✅ 批处理文件已创建: {bat_path}")
    print("   双击此文件即可运行追踪器")


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("A股情绪指标 - 定时任务设置")
    print("=" * 60)
    
    system = platform.system()
    print(f"\n检测到操作系统: {system}")
    
    print("\n请选择操作:")
    
    if system == 'Windows':
        print("1. 设置Windows任务计划程序")
        print("2. 创建批处理文件（推荐）")
        print("3. 删除现有任务")
        
        choice = input("\n请选择 (1-3): ").strip()
        
        if choice == '1':
            setup_windows_task()
        elif choice == '2':
            create_bat_file()
        elif choice == '3':
            cmd = 'schtasks /delete /tn "A股情绪指标追踪器" /f'
            os.system(cmd)
            print("\n✅ 任务已删除")
        else:
            print("无效选项")
            
    elif system == 'Linux':
        print("1. 设置crontab定时任务")
        print("2. 查看当前crontab")
        print("3. 删除情绪指标任务")
        
        choice = input("\n请选择 (1-3): ").strip()
        
        if choice == '1':
            setup_linux_cron()
        elif choice == '2':
            os.system('crontab -l')
        elif choice == '3':
            setup_linux_cron()
        else:
            print("无效选项")
    else:
        print(f"不支持的操作系统: {system}")
        print("请手动设置定时任务")


if __name__ == '__main__':
    main()
