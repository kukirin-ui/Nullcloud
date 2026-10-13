@echo off
rem Windows. Needs Ollama (https://ollama.com/download) and Python 3.
rem Enables CPU + GPU acceleration (NVIDIA CUDA / AMD ROCm / Vulkan) + Flash-Attention & KV-cache q8_0.
set MODEL=llama3.2:3b
set GPU_LAYERS=99
set OLLAMA_FLASH_ATTENTION=1
set OLLAMA_KV_CACHE_TYPE=q8_0
where ollama >nul 2>&1 || (echo Install Ollama first: https://ollama.com/download & pause & exit /b 1)
ollama pull %MODEL%
python -m pip install -q -r "%~dp0..\server\requirements.txt"
if not exist "%USERPROFILE%\.nullcloud-token" powershell -NoProfile -Command "[guid]::NewGuid().ToString('N').Substring(0,24) | Set-Content -NoNewline $env:USERPROFILE\.nullcloud-token"
set /p TOKEN=<"%USERPROFILE%\.nullcloud-token"
set LLM_URL=http://127.0.0.1:11434/v1/chat/completions
echo Your token: %TOKEN%
python "%~dp0..\server\server.py"
