#!/bin/bash
# fenli 日志持久化脚本
# 运行: bash setup_logging.sh

set -e

echo "=== 配置 fenli 日志持久化 ==="

# 创建日志目录
sudo mkdir -p /var/log/fenli

# 开启 journald 持久化存储
if ! grep -q "Storage=persistent" /etc/systemd/journald.conf; then
    sudo bash -c 'echo "Storage=persistent" >> /etc/systemd/journald.conf'
    echo "已添加 Storage=persistent 到 journald.conf"
else
    echo "journald.conf 已包含 Storage=persistent"
fi

# 重启 journald
sudo systemctl restart systemd-journald
echo "journald 已重启"

# 配置 heartbeat cron
SCRIPT_PATH="$HOME/fenli/heartbeat.sh"
if [ -f "$SCRIPT_PATH" ]; then
    # 添加 cron job（如不存在）
    if ! crontab -l 2>/dev/null | grep -q "heartbeat.sh"; then
        (crontab -l 2>/dev/null; echo "*/1 * * * * $SCRIPT_PATH") | crontab -
        echo "已添加 heartbeat cron job"
    else
        echo "heartbeat cron job 已存在"
    fi
else
    echo "警告: heartbeat.sh 不存在于 $SCRIPT_PATH，请先部署它"
fi

echo "=== 日志持久化配置完成 ==="
echo "查看 journald 日志: sudo journalctl -u fenli -f"
echo "查看 cron 配置: crontab -l"
