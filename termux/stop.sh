#!/data/data/com.termux/files/usr/bin/bash
pkill -f "llama-server.*--port 8081"
pkill -f "server/server.py"
termux-wake-unlock 2>/dev/null
echo "Stopped."
