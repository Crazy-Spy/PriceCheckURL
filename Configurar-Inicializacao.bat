@echo off
title PriceCheckURL - Configurador de Inicializacao
echo ======================================================
echo   PriceCheckURL - Ativar Inicializacao com o Windows
echo ======================================================
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Register-ScheduledTask.ps1" -Action RegisterAll
echo.
echo Pressione qualquer tecla para fechar esta janela...
pause >nul

