<#
.SYNOPSIS
    Servidor HTTP Local nativo para o Dashboard do PriceCheckURL.
    Permite gerenciar containers, URLs e disparar verificações via navegador.

.DESCRIPTION
    Utiliza System.Net.HttpListener do .NET nativo do Windows (sem necessidade de Node.js ou Python).
    Disponibiliza rotas REST:
      - GET  /                     -> Serve dashboard.html
      - GET  /api/config           -> Retorna o conteúdo de config.json
      - POST /api/config           -> Atualiza config.json com novos containers/produtos
      - POST /api/check-now        -> Dispara Check-Prices.ps1 em segundo plano
      - GET  /api/status           -> Retorna status da execução do monitor
      - GET  /*                    -> Serve arquivos estáticos (html, js, json, css)

.EXAMPLE
    .\Start-DashboardServer.ps1
    .\Start-DashboardServer.ps1 -Port 8080 -OpenBrowser
#>

[CmdletBinding()]
param(
    [int]$Port = 8080,
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Continue"

# Garantir UTF-8
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
try { $OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$scriptDir = $PSScriptRoot
if (-not $scriptDir -and $MyInvocation.MyCommand.Path) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if (-not $scriptDir) {
    $scriptDir = (Get-Location).Path
}

$configPath  = Join-Path $scriptDir "config.json"
$checkScript = Join-Path $scriptDir "Check-Prices.ps1"

# Iniciar HttpListener
$prefix = "http://localhost:$Port/"
$listener = New-Object System.Net.HttpListener

try {
    $listener.Prefixes.Add($prefix)
    $listener.Start()
} catch {
    Write-Error "Nao foi possivel iniciar o servidor na porta $Port. Verifique se a porta ja esta em uso. Erro: $_"
    exit 1
}

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "  PriceCheckURL - Servidor Web & API Local            " -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host " Servidor rodando em: $prefix" -ForegroundColor Green
Write-Host " Arquivo de configuracao: $configPath" -ForegroundColor DarkGray
Write-Host " Pressione Ctrl+C nesta janela para encerrar." -ForegroundColor Yellow
Write-Host "======================================================`n" -ForegroundColor Cyan

if ($OpenBrowser) {
    Start-Process $prefix
}

# Rastreamento de processo de checagem em background
$global:activeScrapeProcess = $null

function Send-JsonResponse {
    param(
        $Response,
        $Obj,
        [int]$StatusCode = 200,
        [string]$Method = "GET"
    )
    try {
        $json = $Obj | ConvertTo-Json -Depth 10
        $buffer = [System.Text.Encoding]::UTF8.GetBytes($json)
        $Response.StatusCode = $StatusCode
        $Response.ContentType = "application/json; charset=utf-8"
        $Response.AddHeader("Access-Control-Allow-Origin", "*")
        $Response.AddHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
        $Response.AddHeader("Access-Control-Allow-Headers", "Content-Type")
        $Response.ContentLength64 = $buffer.Length
        if ($Method -ne "HEAD") {
            $Response.OutputStream.Write($buffer, 0, $buffer.Length)
        }
        $Response.OutputStream.Close()
    } catch {}
}

function Send-FileResponse {
    param(
        $Response,
        [string]$FilePath,
        [string]$ContentType,
        [string]$Method = "GET"
    )
    try {
        if (Test-Path $FilePath) {
            $bytes = [System.IO.File]::ReadAllBytes($FilePath)
            $Response.StatusCode = 200
            $Response.ContentType = $ContentType
            $Response.AddHeader("Access-Control-Allow-Origin", "*")
            $Response.AddHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
            $Response.AddHeader("Access-Control-Allow-Headers", "Content-Type")
            $Response.AddHeader("Cache-Control", "no-cache, no-store, must-revalidate")
            $Response.ContentLength64 = $bytes.Length
            if ($Method -ne "HEAD") {
                $Response.OutputStream.Write($bytes, 0, $bytes.Length)
            }
            $Response.OutputStream.Close()
        } else {
            $Response.StatusCode = 404
            $Response.OutputStream.Close()
        }
    } catch {}
}

function Get-MimeType {
    param([string]$Path)
    $ext = [System.IO.Path]::GetExtension($Path).ToLower()
    switch ($ext) {
        ".html" { return "text/html; charset=utf-8" }
        ".htm"  { return "text/html; charset=utf-8" }
        ".js"   { return "application/javascript; charset=utf-8" }
        ".json" { return "application/json; charset=utf-8" }
        ".css"  { return "text/css; charset=utf-8" }
        ".png"  { return "image/png" }
        ".jpg"  { return "image/jpeg" }
        ".jpeg" { return "image/jpeg" }
        ".svg"  { return "image/svg+xml" }
        ".ico"  { return "image/x-icon" }
        ".csv"  { return "text/csv; charset=utf-8" }
        default { return "application/octet-stream" }
    }
}

try {
    while ($listener.IsListening) {
        $context = $listener.GetContext()
        $request = $context.Request
        $response = $context.Response

        $rawUrl = $request.RawUrl
        $path = $rawUrl.Split('?')[0]
        $httpMethod = $request.HttpMethod.ToUpper()

        # Tratamento de CORS Preflight
        if ($httpMethod -eq "OPTIONS") {
            $response.StatusCode = 200
            $response.AddHeader("Access-Control-Allow-Origin", "*")
            $response.AddHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            $response.AddHeader("Access-Control-Allow-Headers", "Content-Type")
            $response.OutputStream.Close()
            continue
        }

        # ROTA 1: GET /api/config
        if ($path -eq "/api/config" -and ($httpMethod -eq "GET" -or $httpMethod -eq "HEAD")) {
            if (Test-Path $configPath) {
                Send-FileResponse $response $configPath "application/json; charset=utf-8" -Method $httpMethod
            } else {
                Send-JsonResponse $response @{ error = "Arquivo config.json nao encontrado." } 404 -Method $httpMethod
            }
            continue
        }

        # ROTA 2: POST /api/config (Atualizar configurações e containers)
        if ($path -eq "/api/config" -and $httpMethod -eq "POST") {
            try {
                $reader = New-Object System.IO.StreamReader($request.InputStream, [System.Text.Encoding]::UTF8)
                $body = $reader.ReadToEnd()
                $reader.Close()

                # Validar JSON
                $parsed = $body | ConvertFrom-Json
                if (-not $parsed.containers -and -not $parsed.items) {
                    throw "Formato invalido: 'containers' ou 'items' e obrigatorio."
                }

                # Salvar em config.json com backup de seguranca
                $backupFile = "$configPath.bak"
                Copy-Item $configPath $backupFile -Force -ErrorAction SilentlyContinue

                $utf8NoBom = New-Object System.Text.UTF8Encoding $false
                [System.IO.File]::WriteAllText($configPath, $body, $utf8NoBom)

                Write-Host "[API] config.json atualizado com sucesso via Dashboard." -ForegroundColor Green

                Send-JsonResponse $response @{
                    success = $true
                    message = "Configuracoes salvas com sucesso!"
                }
            } catch {
                Write-Host "[API] Erro ao salvar config.json: $_" -ForegroundColor Red
                Send-JsonResponse $response @{
                    success = $false
                    error = "$_"
                } 400
            }
            continue
        }

        # ROTA 3: POST /api/check-now (Disparar verificação de preços)
        if ($path -eq "/api/check-now" -and $httpMethod -eq "POST") {
            $isRunning = $false
            if ($global:activeScrapeProcess) {
                try {
                    $isRunning = -not $global:activeScrapeProcess.HasExited
                } catch {
                    $isRunning = $false
                }
            }

            if ($isRunning) {
                Send-JsonResponse $response @{
                    success = $false
                    running = $true
                    message = "Uma verificacao ja esta em andamento no momento."
                }
                continue
            }

            Write-Host "[API] Disparando Check-Prices.ps1 via requisicao do usuario..." -ForegroundColor Cyan
            $global:activeScrapeProcess = Start-Process powershell.exe -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File `"$checkScript`"" -PassThru -WindowStyle Hidden

            Send-JsonResponse $response @{
                success = $true
                running = $true
                message = "Verificacao iniciada em segundo plano!"
                pid     = $global:activeScrapeProcess.Id
            }
            continue
        }

        # ROTA 4: GET /api/status (Verificar status do scraper)
        if ($path -eq "/api/status" -and ($httpMethod -eq "GET" -or $httpMethod -eq "HEAD")) {
            $isRunning = $false
            if ($global:activeScrapeProcess) {
                try {
                    $isRunning = -not $global:activeScrapeProcess.HasExited
                } catch {
                    $isRunning = $false
                }
            }

            $lastCheckTime = $null
            $latestPricesFile = Join-Path (Join-Path $scriptDir "data") "latest_prices.json"
            if (Test-Path $latestPricesFile) {
                try {
                    $lp = Get-Content $latestPricesFile -Raw -Encoding UTF8 | ConvertFrom-Json
                    if ($lp -and $lp[0] -and $lp[0].lastUpdated) {
                        $lastCheckTime = $lp[0].lastUpdated
                    }
                } catch {}
            }

            Send-JsonResponse $response @{
                isChecking = $isRunning
                lastCheck  = $lastCheckTime
                timestamp  = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
            } -Method $httpMethod
            continue
        }

        # ROTA ESTÁTICA: Servir arquivos do dashboard
        $relPath = $path.TrimStart('/')
        if ([string]::IsNullOrWhiteSpace($relPath)) {
            $relPath = "dashboard.html"
        }

        $filePath = Join-Path $scriptDir $relPath
        if (Test-Path $filePath -PathType Leaf) {
            $mime = Get-MimeType $filePath
            Send-FileResponse $response $filePath $mime -Method $httpMethod
        } else {
            $response.StatusCode = 404
            $err = [System.Text.Encoding]::UTF8.GetBytes("404 Not Found: $path")
            $response.OutputStream.Write($err, 0, $err.Length)
            $response.OutputStream.Close()
        }
    }
} finally {
    if ($listener.IsListening) {
        $listener.Stop()
    }
    $listener.Close()
}
