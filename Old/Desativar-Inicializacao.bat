@echo off
title PriceCheckURL - Desativar Inicializacao
echo ======================================================
echo   PriceCheckURL - Desativar Inicializacao Automatica
echo ======================================================
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Register-ScheduledTask.ps1" -Action UnregisterAll
echo.
echo Pressione qualquer tecla para fechar esta janela...
pause >nul

