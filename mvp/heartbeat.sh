#!/bin/bash
# fenli 服务自愈脚本 — 每1分钟自检，连续3次失败自动重启
FAIL_FILE=/tmp/fenli_fail_count
URL=http://localhost:8777/api/health

if curl -s --max-time 5 "$URL" | grep -q '"status":"ok"'; then
    echo "0" > $FAIL_FILE
else
    COUNT=$(cat $FAIL_FILE 2>/dev/null || echo 0)
    COUNT=$((COUNT + 1))
    echo $COUNT > $FAIL_FILE
    if [ $COUNT -ge 3 ]; then
        echo "$(date): 连续${COUNT}次失败，自动重启" >> /tmp/fenli_recovery.log
        sudo systemctl restart fenli.service
        echo "0" > $FAIL_FILE
    fi
fi
