@echo off
title PriceCheckURL - Status do Sistema
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Register-ScheduledTask.ps1" -Action Status
echo.
echo Pressione qualquer tecla para fechar esta janela...
pause >nul

