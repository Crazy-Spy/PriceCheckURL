<#
.SYNOPSIS
    Gerenciador de Inicialização Automática e Agendamento do PriceCheckURL.

.DESCRIPTION
    Gerencia a execução automática de duas partes do sistema:
    1. MONITOR (Check-Prices.ps1): Agendado a cada 10 minutos para raspar preços em segundo plano.
    2. SERVIDOR (Start-DashboardServer.ps1): Inicia o localhost:8080 automaticamente ao ligar o PC / fazer login.

.PARAMETER Action
    Ação a executar:
      - 'RegisterServer'    : Configura o Servidor Local (localhost:8080) para iniciar com o Windows
      - 'RegisterMonitor'   : Configura a checagem periódica a cada X minutos (padrão: 10)
      - 'RegisterAll'       : Configura ambos (Monitor + Servidor)
      - 'UnregisterServer'  : Remove o início automático do servidor
      - 'UnregisterMonitor' : Remove a tarefa do monitor
      - 'UnregisterAll'     : Remove ambas as automações
      - 'Status'            : Exibe o status do Monitor e do Servidor
      - 'RunNow'            : Dispara uma verificação de preços agora
      - 'StartServerNow'    : Inicia o servidor local agora em segundo plano

.PARAMETER IntervalMinutes
    Intervalo em minutos entre as checagens do monitor. Padrão: 10.
#>

[CmdletBinding()]
param(
    [ValidateSet("Register", "RegisterMonitor", "RegisterServer", "RegisterAll", "Unregister", "UnregisterMonitor", "UnregisterServer", "UnregisterAll", "Status", "RunNow", "StartServerNow")]
    [string]$Action = "Status",

    [int]$IntervalMinutes = 10,
    [string]$MonitorTaskName = "PriceCheckURL-Monitor",
    [string]$ServerTaskName = "PriceCheckURL-Server"
)

$ErrorActionPreference = "Continue"

# Garantir resolução de caminhos absolutos
$scriptDir = $PSScriptRoot
if (-not $scriptDir -and $MyInvocation.MyCommand.Path) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if (-not $scriptDir) {
    $scriptDir = (Get-Location).Path
}

$checkScript   = Join-Path $scriptDir "Check-Prices.ps1"
$serverScript  = Join-Path $scriptDir "Start-DashboardServer.ps1"
$vbsMonitor    = Join-Path $scriptDir "Run-Check-Prices.vbs"
$vbsServer     = Join-Path $scriptDir "Run-Dashboard-Server.vbs"

$startupFolder = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Startup)
$startupShortcut = Join-Path $startupFolder "PriceCheckURL-Server.lnk"

# Garantir existência dos scripts VBS auxiliares para execução invisível
if (-not (Test-Path $vbsMonitor)) {
    $vbsContent = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""$checkScript""", 0, False
"@
    Set-Content -Path $vbsMonitor -Value $vbsContent -Encoding ASCII
}

if (-not (Test-Path $vbsServer)) {
    $vbsServerContent = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""$serverScript""", 0, False
"@
    Set-Content -Path $vbsServer -Value $vbsServerContent -Encoding ASCII
}

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "  PriceCheckURL - Gerenciador de Tarefas e Inicializacao" -ForegroundColor Cyan
Write-Host "======================================================`n" -ForegroundColor Cyan

function Enable-ServerStartup {
    Write-Host "[*] Configurando Servidor Local (localhost:8080) para iniciar com o Windows..." -ForegroundColor Yellow

    # 1. Criar atalho na pasta Inicializar do Usuário (100% garantido, sem necessidade de privilégios de Admin)
    try {
        $wsh = New-Object -ComObject WScript.Shell
        $sc = $wsh.CreateShortcut($startupShortcut)
        $sc.TargetPath = "wscript.exe"
        $sc.Arguments = "`"$vbsServer`""
        $sc.WorkingDirectory = $scriptDir
        $sc.Description = "PriceCheckURL Local Dashboard Server"
        $sc.Save()
        Write-Host "[OK] Atalho criado na pasta Inicializar do Windows!" -ForegroundColor Green
        Write-Host "     Destino: $startupShortcut" -ForegroundColor DarkGray
    } catch {
        Write-Host "[!] Erro ao criar atalho na pasta Inicializar: $_" -ForegroundColor Red
    }

    # 2. Tentar registrar também no Agendador de Tarefas (se tiver permissão de Admin)
    try {
        $action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbsServer`""
        $trigger = New-ScheduledTaskTrigger -AtLogon
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -Priority 7
        Register-ScheduledTask -TaskName $ServerTaskName -Action $action -Trigger $trigger -Settings $settings -Force -ErrorAction Stop | Out-Null
        Write-Host "[OK] Tarefa agendada '$ServerTaskName' registrada no Agendador do Windows (Ao fazer logon)!" -ForegroundColor Green
    } catch {
        Write-Host "[i] Agendador de Tarefas (AtLogon) requer Admin. O atalho na pasta Inicializar garantira a execucao normalmente!" -ForegroundColor DarkGray
    }

    Write-Host "`nO servidor subira silenciosamente em segundo plano toda vez que voce ligar o PC." -ForegroundColor Green
    Write-Host "URL do Dashboard: http://localhost:8080" -ForegroundColor Cyan
}

function Disable-ServerStartup {
    Write-Host "[*] Removendo inicializacao automatica do Servidor Local..." -ForegroundColor Yellow
    if (Test-Path $startupShortcut) {
        Remove-Item $startupShortcut -Force -ErrorAction SilentlyContinue
        Write-Host "[OK] Atalho removido da pasta Inicializar." -ForegroundColor Green
    }
    try {
        Unregister-ScheduledTask -TaskName $ServerTaskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "[OK] Tarefa '$ServerTaskName' removida do Agendador." -ForegroundColor Green
    } catch {}
}

function Enable-MonitorTask {
    Write-Host "[*] Registrando tarefa agendada '$MonitorTaskName' a cada $IntervalMinutes minutos..." -ForegroundColor Yellow

    try {
        $taskAction = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbsMonitor`""
        $timespan = New-TimeSpan -Minutes $IntervalMinutes
        $taskTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval $timespan -RepetitionDuration (New-TimeSpan -Days 3650)
        $taskSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

        Register-ScheduledTask -TaskName $MonitorTaskName -Action $taskAction -Trigger $taskTrigger -Settings $taskSettings -Force -ErrorAction Stop | Out-Null
        Write-Host "[OK] Tarefa '$MonitorTaskName' registrada com sucesso a cada $IntervalMinutes minutos!" -ForegroundColor Green
    } catch {
        Write-Host "[!] Falha no cmdlet nativo ($($_.Exception.Message)). Tentando via schtasks.exe..." -ForegroundColor DarkYellow
        $schCmd = "schtasks.exe /Create /TN `"$MonitorTaskName`" /TR `"wscript.exe `\`"$vbsMonitor`\`"`" /SC MINUTE /MO $IntervalMinutes /F"
        cmd.exe /c $schCmd
    }
}

function Disable-MonitorTask {
    Write-Host "[*] Removendo tarefa agendada '$MonitorTaskName'..." -ForegroundColor Yellow
    try {
        Unregister-ScheduledTask -TaskName $MonitorTaskName -Confirm:$false -ErrorAction Stop
        Write-Host "[OK] Tarefa '$MonitorTaskName' removida com sucesso!" -ForegroundColor Green
    } catch {
        cmd.exe /c "schtasks.exe /Delete /TN `"$MonitorTaskName`" /F"
    }
}

switch ($Action) {
    "RegisterServer" {
        Enable-ServerStartup
    }

    "RegisterMonitor" {
        Enable-MonitorTask
    }

    "Register" {
        Enable-MonitorTask
    }

    "RegisterAll" {
        Enable-MonitorTask
        Write-Host ""
        Enable-ServerStartup
    }

    "UnregisterServer" {
        Disable-ServerStartup
    }

    "UnregisterMonitor" {
        Disable-MonitorTask
    }

    "Unregister" {
        Disable-MonitorTask
    }

    "UnregisterAll" {
        Disable-MonitorTask
        Disable-ServerStartup
    }

    "Status" {
        Write-Host "--- 1. STATUS DO MONITOR PERIODICO (Check-Prices.ps1) ---" -ForegroundColor Cyan
        try {
            $task = Get-ScheduledTask -TaskName $MonitorTaskName -ErrorAction Stop
            $taskInfo = Get-ScheduledTaskInfo -TaskName $MonitorTaskName
            [PSCustomObject]@{
                Tarefa          = $task.TaskName
                Estado          = $task.State
                UltimaExecucao  = $taskInfo.LastRunTime
                ProximaExecucao = $taskInfo.NextRunTime
                Resultado       = $taskInfo.LastTaskResult
            } | Format-List
        } catch {
            Write-Host "[AVISO] Tarefa '$MonitorTaskName' nao encontrada no Agendador.`n" -ForegroundColor Red
        }

        Write-Host "--- 2. STATUS DO SERVIDOR LOCAL (Start-DashboardServer.ps1) ---" -ForegroundColor Cyan
        $startupConfigured = Test-Path $startupShortcut
        $taskConfigured = $false
        try {
            $stask = Get-ScheduledTask -TaskName $ServerTaskName -ErrorAction SilentlyContinue
            if ($stask) { $taskConfigured = $true }
        } catch {}

        Write-Host "Inicializacao no Boot (Pasta Startup): " -NoNewline
        if ($startupConfigured) {
            Write-Host "ATIVADA ($startupShortcut)" -ForegroundColor Green
        } else {
            Write-Host "NAO ATIVADA" -ForegroundColor Yellow
        }

        Write-Host "Agendador de Tarefas (AtLogon)      : " -NoNewline
        if ($taskConfigured) {
            Write-Host "ATIVADA ($ServerTaskName)" -ForegroundColor Green
        } else {
            Write-Host "NAO CONFIGURADA (Opcional)" -ForegroundColor Gray
        }

        # Verificar se está rodando agora na porta 8080
        $isPortActive = $false
        try {
            $tcp = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
            if ($tcp) { $isPortActive = $true }
        } catch {}

        Write-Host "Porta 8080 (http://localhost:8080)   : " -NoNewline
        if ($isPortActive) {
            Write-Host "ONLINE / RODANDO AGORA!" -ForegroundColor Green
        } else {
            Write-Host "OFFLINE (Inicie com: .\Register-ScheduledTask.ps1 -Action StartServerNow)" -ForegroundColor DarkYellow
        }
        Write-Host ""
    }

    "RunNow" {
        Write-Host "[*] Disparando execucao imediata do monitor de precos..." -ForegroundColor Yellow
        try {
            Start-ScheduledTask -TaskName $MonitorTaskName
            Write-Host "[OK] Disparo efetuado em segundo plano! Verifique 'data/latest_prices.json' em instantes." -ForegroundColor Green
        } catch {
            Write-Host "[!] Erro ao disparar tarefa: $($_.Exception.Message)" -ForegroundColor Red
            Write-Host "Executando Check-Prices.ps1 diretamente..." -ForegroundColor Cyan
            & powershell.exe -ExecutionPolicy Bypass -File $checkScript
        }
    }

    "StartServerNow" {
        Write-Host "[*] Iniciando o Servidor Local em segundo plano..." -ForegroundColor Yellow
        try {
            Start-Process wscript.exe -ArgumentList "`"$vbsServer`""
            Start-Sleep -Seconds 2
            Write-Host "[OK] Servidor iniciado em segundo plano!" -ForegroundColor Green
            Write-Host "Acesse o Dashboard em: http://localhost:8080" -ForegroundColor Cyan
        } catch {
            Write-Host "[!] Falha ao iniciar: $_" -ForegroundColor Red
        }
    }
}
