#!/bin/bash
# ═══ 一键部署脚本 ═══
# 用法:
#   ./deploy.sh          # 本地Docker部署
#   ./deploy.sh cloud    # 云服务器部署（纯Python+MySQL）

set -e

RED='\033[0;31m' GREEN='\033[0;32m' NC='\033[0m'

if [ "$1" = "cloud" ]; then
    echo -e "${GREEN}=== 云服务器部署 ===${NC}"

    # 1. 安装依赖
    pip install -r requirements.txt

    # 2. 初始化MySQL（需要提前安装MySQL）
    echo "确保MySQL已安装并运行。数据库名: fenli"
    echo "环境变量: MYSQL_HOST=127.0.0.1 MYSQL_PORT=3306 MYSQL_USER=root MYSQL_PASS=你的密码"

    # 3. 启动
    echo -e "${GREEN}启动服务...${NC}"
    nohup python server.py > server.log 2>&1 &
    echo "PID: $!"
    echo "日志: tail -f server.log"
    echo -e "${GREEN}部署完成！访问 http://服务器IP:8777${NC}"

elif [ "$1" = "systemd" ]; then
    echo -e "${GREEN}=== 创建systemd服务 ===${NC}"
    SERVICE_FILE="/etc/systemd/system/fenli.service"
    sudo tee $SERVICE_FILE > /dev/null << SERVICE_EOF
[Unit]
Description=无限流规则怪谈
After=network.target mysql.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
Environment="MYSQL_HOST=127.0.0.1"
Environment="MYSQL_PORT=3306"
Environment="MYSQL_USER=root"
Environment="MYSQL_PASS=${MYSQL_PASS:-root}"
Environment="MYSQL_DB=fenli"
ExecStart=$(which python) server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE_EOF
    sudo systemctl daemon-reload
    sudo systemctl enable fenli
    sudo systemctl start fenli
    echo -e "${GREEN}systemd服务已创建并启动${NC}"
    echo "查看状态: sudo systemctl status fenli"
    echo "查看日志: sudo journalctl -u fenli -f"

else
    echo -e "${GREEN}=== Docker部署 ===${NC}"

    # 检查Docker
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}请先安装Docker${NC}"
        exit 1
    fi

    # 构建和启动
    docker compose up -d --build

    echo -e "${GREEN}部署完成！${NC}"
    echo "访问: http://localhost:8777"
    echo "查看日志: docker compose logs -f app"
    echo "停止: docker compose down"
fi
