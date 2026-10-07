<#
.SYNOPSIS
    Monitor de Preços e Disponibilidade de Produtos (Terabyte, Kabum, Pichau).
    Registra histórico para gráficos e atualiza dados para o dashboard HTML.

.DESCRIPTION
    Lê os produtos de config.json, realiza a consulta nas lojas (via curl ou headless Chrome/Edge),
    extrai preços e estoque, persiste histórico em JSON/CSV/JS para consumo pelo dashboard.html.
#>

[CmdletBinding()]
param(
    [string]$ConfigFile = "",
    [string]$DataDir = "",
    [switch]$ForceHeadless
)

$ErrorActionPreference = "Continue"

# Garantir resolução correta de diretórios mesmo se chamado externamente
$scriptDir = $PSScriptRoot
if (-not $scriptDir -and $MyInvocation.MyCommand.Path) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if (-not $scriptDir) {
    $scriptDir = (Get-Location).Path
}

if (-not $ConfigFile) {
    $ConfigFile = Join-Path $scriptDir "config.json"
}
if (-not $DataDir) {
    $DataDir = Join-Path $scriptDir "data"
}

# Garantir codificação UTF-8 no console
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "  PriceCheckURL - Verificador de Preços e Estoque     " -ForegroundColor Cyan
Write-Host "  Execução iniciada em: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Gray
Write-Host "======================================================`n" -ForegroundColor Cyan

# 1. Carregar configurações
if (-not (Test-Path $ConfigFile)) {
    Write-Error "Arquivo de configuração não encontrado: $ConfigFile"
    exit 1
}

$config = Get-Content $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
$timeoutSec = if ($config.settings.timeoutSeconds) { $config.settings.timeoutSeconds } else { 30 }
$userAgent = if ($config.settings.userAgent) { $config.settings.userAgent } else { "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36" }
$targetPrice = if ($config.settings.targetPrice) { [double]$config.settings.targetPrice } elseif ($config.targetPrice) { [double]$config.targetPrice } else { 2050.0 }
Write-Host "[*] Preço-Alvo de referência: R$ $($targetPrice.ToString('N2'))" -ForegroundColor DarkCyan

# 2. Localizar navegador headless para fallback de anti-bot (Cloudflare)
$browserPath = $null
$possibleBrowsers = @(
    "C:\Program Files\Google\Chrome\Application\chrome.exe",
    "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
)
foreach ($path in $possibleBrowsers) {
    if (Test-Path $path) {
        $browserPath = $path
        break
    }
}

if ($browserPath) {
    Write-Host "[OK] Navegador headless identificado: $browserPath" -ForegroundColor DarkGray
} else {
    Write-Host "[AVISO] Nenhum executável do Chrome ou Edge encontrado para modo headless." -ForegroundColor Yellow
}

# 3. Preparar diretório de dados
if (-not (Test-Path $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
}

$latestPricesFile = Join-Path $DataDir "latest_prices.json"
$historyFile      = Join-Path $DataDir "price_history.json"
$historyCsvFile   = Join-Path $DataDir "price_history.csv"
$dataJsFile       = Join-Path $DataDir "data.js"

# Carregar dados anteriores
$previousLatest = @{}
if (Test-Path $latestPricesFile) {
    try {
        $prevData = Get-Content $latestPricesFile -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($p in $prevData) {
            $previousLatest[$p.id] = $p
        }
    } catch {
        Write-Host "[AVISO] Não foi possível ler latest_prices.json anterior. Iniciando novo ciclo." -ForegroundColor DarkYellow
    }
}

$existingHistory = @()
if (Test-Path $historyFile) {
    try {
        $rawHist = Get-Content $historyFile -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($h in $rawHist) {
            if ($h.value -is [array]) {
                foreach ($sub in $h.value) {
                    if ($sub.itemId -and $sub.price) { $existingHistory += $sub }
                }
            } elseif ($h.itemId -and $h.price) {
                $existingHistory += $h
            }
        }
    } catch {
        $existingHistory = @()
    }
}

# Funcoes auxiliares de conversao e gerenciamento de navegador CDP (Bypass de Cloudflare)
function Convert-PriceStringToDouble {
    param([string]$priceStr)
    if ([string]::IsNullOrWhiteSpace($priceStr)) { return $null }
    $clean = $priceStr.Replace("R$", "").Replace("&nbsp;", "").Replace("`u{a0}", "").Replace(" ", "").Trim()

    if ($clean -match '\.(\d{3}),(\d{2})$') {
        $clean = $clean.Replace(".", "").Replace(",", ".")
    } elseif ($clean -match ',(\d{3})\.(\d{2})$') {
        $clean = $clean.Replace(",", "")
    } elseif ($clean.Contains(",") -and -not $clean.Contains(".")) {
        $clean = $clean.Replace(",", ".")
    }

    $val = 0.0
    if ([double]::TryParse($clean, [System.Globalization.NumberStyles]::Any, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$val)) {
        return [Math]::Round($val, 2)
    }
    return $null
}

$script:cdpBrowser = $null
$script:cdpProfile = $null
$script:cdpWs = $null
$script:cdpCts = $null
$script:cdpPort = 9222
$script:cdpCmdSeq = 0

function Start-CdpBrowser {
    param([string]$ExePath)
    if ($script:cdpBrowser -and -not $script:cdpBrowser.HasExited) { return }
    if (-not $ExePath -or -not (Test-Path $ExePath)) { return }

    $script:cdpProfile = Join-Path ([System.IO.Path]::GetTempPath()) ("pricecheck_cdp_" + [System.Guid]::NewGuid().ToString())
    New-Item -ItemType Directory -Path $script:cdpProfile -Force | Out-Null

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $ExePath
    $psi.Arguments = "--remote-debugging-port=$script:cdpPort --user-data-dir=`"$script:cdpProfile`" --no-first-run --no-default-browser-check about:blank"
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Minimized
    $script:cdpBrowser = [System.Diagnostics.Process]::Start($psi)

    Start-Sleep -Seconds 2

    try {
        $targets = Invoke-RestMethod -Uri "http://127.0.0.1:$script:cdpPort/json"
        $pageTarget = $targets | Where-Object { $_.type -eq "page" } | Select-Object -First 1
        if ($pageTarget) {
            $script:cdpWs = New-Object System.Net.WebSockets.ClientWebSocket
            $script:cdpCts = New-Object System.Threading.CancellationTokenSource
            $uri = New-Object System.Uri($pageTarget.webSocketDebuggerUrl)
            $script:cdpWs.ConnectAsync($uri, $script:cdpCts.Token).Wait()
        }
    } catch {}
}

function Stop-CdpBrowser {
    try {
        if ($script:cdpWs -and $script:cdpWs.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
            $script:cdpWs.CloseAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, "Done", $script:cdpCts.Token).Wait()
        }
    } catch {}
    try {
        if ($script:cdpBrowser -and -not $script:cdpBrowser.HasExited) {
            $script:cdpBrowser.Kill()
        }
    } catch {}
    if ($script:cdpProfile -and (Test-Path $script:cdpProfile)) {
        Remove-Item $script:cdpProfile -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-CdpSend {
    param($method, $params = @{})
    if (-not $script:cdpWs -or $script:cdpWs.State -ne [System.Net.WebSockets.WebSocketState]::Open) { return $null }
    $script:cdpCmdSeq++
    $msg = @{ id = $script:cdpCmdSeq; method = $method; params = $params } | ConvertTo-Json -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($msg)
    $segment = New-Object System.ArraySegment[byte] -ArgumentList @(,$bytes)
    $script:cdpWs.SendAsync($segment, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $script:cdpCts.Token).Wait()

    $buffer = New-Object byte[] 65536
    $ms = New-Object System.IO.MemoryStream
    do {
        $recvSegment = New-Object System.ArraySegment[byte] -ArgumentList @(,$buffer)
        $res = $script:cdpWs.ReceiveAsync($recvSegment, $script:cdpCts.Token).Result
        $ms.Write($buffer, 0, $res.Count)
    } while (-not $res.EndOfMessage)

    return [System.Text.Encoding]::UTF8.GetString($ms.ToArray()) | ConvertFrom-Json
}

# Funcao auxiliar: Requisicao HTTP inteligente (curl + fallback CDP com bypass real de Cloudflare)
function Get-PageContent {
    param(
        [string]$Url,
        [string]$Method,
        [string]$BrowserExe,
        [string]$UA,
        [int]$Timeout
    )

    $useHeadless = ($Method -eq "headless") -or $ForceHeadless

    # 1. Se for curl ou auto, tenta curl primeiro
    if (-not $useHeadless) {
        try {
            $tempFile = [System.IO.Path]::GetTempFileName()
            $curlArgs = @(
                "-s", "-k", "-L",
                "-A", $UA,
                "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "-H", "Accept-Language: pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                "--compressed",
                "--max-time", "$Timeout",
                "$Url",
                "-o", $tempFile
            )
            & curl.exe @curlArgs
            if (Test-Path $tempFile) {
                $content = Get-Content $tempFile -Raw -Encoding UTF8
                Remove-Item $tempFile -Force -ErrorAction SilentlyContinue

                # Validar se nao caiu no Cloudflare Challenge ou erro
                if ($content -and $content.Length -gt 5000 -and 
                    $content -notlike "*<title>Just a moment...*" -and
                    $content -notlike "*challenges.cloudflare.com*") {
                    return $content
                }
            }
        } catch {}
    }

    # 2. Fallback: Browser minimizado com CDP (resolve Cloudflare Turnstile instantaneamente)
    if ($BrowserExe -and (Test-Path $BrowserExe)) {
        try {
            Start-CdpBrowser -ExePath $BrowserExe
            if ($script:cdpWs -and $script:cdpWs.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
                [void](Invoke-CdpSend -method "Page.navigate" -params @{ url = $Url })
                for ($i = 0; $i -lt 8; $i++) {
                    Start-Sleep -Seconds 1
                    $titleRes = Invoke-CdpSend -method "Runtime.evaluate" -params @{ expression = "document.title"; returnByValue = $true }
                    $curTitle = if ($titleRes.result -and $titleRes.result.result) { $titleRes.result.result.value } else { "" }
                    if ($curTitle -and $curTitle -notlike "*Just a moment*" -and $curTitle -ne "about:blank") {
                        break
                    }
                }
                Start-Sleep -Milliseconds 700
                $htmlRes = Invoke-CdpSend -method "Runtime.evaluate" -params @{ expression = "document.documentElement.outerHTML"; returnByValue = $true }
                $browserHtml = if ($htmlRes.result -and $htmlRes.result.result) { $htmlRes.result.result.value } else { $null }
                if ($browserHtml -and $browserHtml.Length -gt 3000 -and $browserHtml -notlike "*<title>Just a moment...*") {
                    return $browserHtml
                }
            }
        } catch {
            Write-Host "  [!] Erro no navegador CDP: $_" -ForegroundColor Red
        }
    }

    return $null
}

# Funcao auxiliar: Parser de Produto com PRIORIDADE TOTAL PARA PRECO A VISTA / PIX
function Parse-ProductData {
    param(
        [string]$Html,
        [object]$ItemConfig
    )

    $result = [PSCustomObject]@{
        Id               = $ItemConfig.id
        Name             = $ItemConfig.name
        Store            = $ItemConfig.store
        Url              = $ItemConfig.url
        Price            = $null
        PriceOriginal    = $null
        InStock          = $false
        AvailabilityText = "Desconhecido"
        ImageUrl         = $null
        Sku              = $null
        RawTitle         = $null
        Success          = $false
    }

    if ([string]::IsNullOrWhiteSpace($Html)) {
        return $result
    }

    $storeName = if ($ItemConfig.store) { $ItemConfig.store.ToLower() } else { "" }
    $urlLower = if ($ItemConfig.url) { $ItemConfig.url.ToLower() } else { "" }

    # ==========================================
    # 1. PARSER ESPECIFICO KABUM (Preco a vista com desconto Prime/Logado)
    # ==========================================
    if ($storeName -like "*kabum*" -or $urlLower -like "*kabum.com.br*") {
        if ($Html -match '<script id="__NEXT_DATA__" type="application/json">(.*?)</script>') {
            try {
                $nextData = $matches[1] | ConvertFrom-Json
                $pageProps = $nextData.props.pageProps
                $prod = if ($pageProps.product) { $pageProps.product } else { $pageProps.productData }

                if ($prod) {
                    if ($prod.title) { $result.RawTitle = $prod.title }
                    elseif ($prod.name) { $result.RawTitle = $prod.name }

                    if ($prod.id) { $result.Sku = "$($prod.id)" }

                    if ($prod.thumbnail) { $result.ImageUrl = $prod.thumbnail }
                    elseif ($prod.medias -and $prod.medias.Count -gt 0 -and $prod.medias[0].images -and $prod.medias[0].images.g) {
                        $result.ImageUrl = $prod.medias[0].images.g
                    }

                    if ($prod.available -ne $null) {
                        $result.InStock = [bool]$prod.available
                        $result.AvailabilityText = if ($result.InStock) { "Em Estoque" } else { "Esgotado" }
                    }

                    # Calculo estrito de preco a vista com abatimento exclusivo Prime/Logado
                    $pBase = 0.0
                    if ($prod.prices -and $prod.prices.priceWithDiscount) {
                        $pBase = [double]$prod.prices.priceWithDiscount
                    } elseif ($prod.priceWithDiscount) {
                        $pBase = [double]$prod.priceWithDiscount
                    } elseif ($prod.price) {
                        $pBase = [double]$prod.price
                    }

                    $pOriginal = if ($prod.prices -and $prod.prices.oldPrice) { [double]$prod.prices.oldPrice } elseif ($prod.price) { [double]$prod.price } else { $null }
                    if ($pOriginal -and $pOriginal -gt 0) {
                        $result.PriceOriginal = [Math]::Round($pOriginal, 2)
                    }

                    # Verificar savePrime / prime.save
                    $saveDiscount = 0.0
                    if ($prod.savePrime) {
                        $saveDiscount = [double]$prod.savePrime
                    } elseif ($prod.prime -and $prod.prime.save) {
                        $saveDiscount = [double]$prod.prime.save
                    }

                    if ($saveDiscount -gt 0 -and $pBase -gt $saveDiscount) {
                        $result.Price = [Math]::Round(($pBase - $saveDiscount), 2)
                    } elseif ($pBase -gt 0) {
                        $result.Price = [Math]::Round($pBase, 2)
                    }

                    if ($result.Price -gt 0) {
                        $result.Success = $true
                        if ($result.RawTitle -and -not $result.Name) { $result.Name = $result.RawTitle }
                        return $result
                    }
                }
            } catch {}
        }
    }

    # ==========================================
    # 2. PARSER ESPECIFICO TERABYTE (dataLayer + #val-prod)
    # ==========================================
    if ($storeName -like "*terabyte*" -or $urlLower -like "*terabyteshop.com.br*") {
        # Extrair dados de dataLayer
        if ($Html -match '''value''\s*:\s*([\d\.]+)' -or $Html -match '''price''\s*:\s*([\d\.]+)') {
            $result.Price = [Math]::Round([double]$matches[1], 2)
        }
        if ($Html -match '''item_name''\s*:\s*''([^'']+)''') {
            $result.RawTitle = $matches[1]
        }
        if ($Html -match 'class="img-fluid[^"]*"\s*src="([^"]+)"' -or $Html -match 'id="img-produto"\s*src="([^"]+)"') {
            $result.ImageUrl = $matches[1]
        }
        if ($Html -match 'PRODUTO INDISPONIVEL' -or $Html -match 'id="indisponivel"') {
            $result.InStock = $false
            $result.AvailabilityText = "Esgotado"
        } else {
            $result.InStock = $true
            $result.AvailabilityText = "Em Estoque"
        }

        if ($result.Price -gt 0) {
            $result.Success = $true
            if ($result.RawTitle -and -not $result.Name) { $result.Name = $result.RawTitle }
            return $result
        }
    }

    # ==========================================
    # 3. PARSER ESPECIFICO PICHAU (Prioridade a vista / PIX)
    # ==========================================
    if ($storeName -like "*pichau*" -or $urlLower -like "*pichau.com.br*") {
        # 3.1 Prioridade absoluta: Meta tags oficiais da Pichau com valor a vista
        if ($Html -match '<meta\s+name="product:price:amount"\s+content="([^"]+)"' -or $Html -match '<meta\s+content="([^"]+)"\s+name="product:price:amount"') {
            $result.Price = Convert-PriceStringToDouble $matches[1]
        } elseif ($Html -match '<meta\s+name="twitter:data1"\s+content="([^"]+)"' -or $Html -match '<meta\s+content="([^"]+)"\s+name="twitter:data1"') {
            $result.Price = Convert-PriceStringToDouble $matches[1]
        }

        # 3.2 Fallback de texto: trecho com a vista / no PIX
        if ($result.Price -eq $null -or $result.Price -le 0) {
            if ($Html -match '(?i)(?:à|a|\?|\ufffd)?\s*vista[\s\r\n<>\w="''-]{0,120}?R\$[\s\xA0]*([\d\.,]+)') {
                $result.Price = Convert-PriceStringToDouble $matches[1]
            } elseif ($Html -match '(?i)R\$[\s\xA0]*([\d\.,]+)[\s\r\n<>\w="''-]{0,90}?no PIX com') {
                $result.Price = Convert-PriceStringToDouble $matches[1]
            }
        }

        # Extrair preco original de / parcelado
        if ($Html -match '(?i)de\s*R\$[\s\xA0]*([\d\.,]+)') {
            $result.PriceOriginal = Convert-PriceStringToDouble $matches[1]
        }

        if ($Html -match 'INDISPONÍVEL' -or $Html -match 'ESGOTADO' -or $Html -match 'Produto Esgotado') {
            $result.InStock = $false
            $result.AvailabilityText = "Esgotado"
        } else {
            $result.InStock = $true
            $result.AvailabilityText = "Em Estoque"
        }

        if ($Html -match '<meta\s+property="og:image"\s+content="([^"]+)"' -or $Html -match '<meta\s+content="([^"]+)"\s+property="og:image"') {
            $result.ImageUrl = $matches[1]
        }
        if ($Html -match '<meta\s+property="og:title"\s+content="([^"]+)"' -or $Html -match '<meta\s+content="([^"]+)"\s+property="og:title"') {
            $result.RawTitle = $matches[1]
        }

        if ($result.Price -gt 0) {
            $result.Success = $true
            if ($result.RawTitle -and -not $result.Name) { $result.Name = $result.RawTitle }
            return $result
        }
    }

    # ==========================================
    # 4. FALLBACK GERAL: JSON-LD schema.org
    # ==========================================
    $ldMatches = [regex]::Matches($Html, '<script[^>]*type=["'']application/ld\+json["''][^>]*>(.*?)</script>', [System.Text.RegularExpressions.RegexOptions]::Singleline)
    foreach ($m in $ldMatches) {
        $jsonStr = $m.Groups[1].Value.Trim()
        try {
            $ld = $jsonStr | ConvertFrom-Json
            $products = @()
            if ($ld."@type" -eq "Product") {
                $products += $ld
            } elseif ($ld."@graph") {
                $products += ($ld."@graph" | Where-Object { $_."@type" -eq "Product" })
            }

            foreach ($p in $products) {
                if ($p.name) { $result.RawTitle = $p.name }
                if ($p.image) {
                    if ($p.image -is [array]) { $result.ImageUrl = $p.image[0] }
                    else { $result.ImageUrl = $p.image }
                }
                if ($p.sku) { $result.Sku = $p.sku }
                elseif ($p.mpn) { $result.Sku = $p.mpn }

                $offer = $null
                if ($p.offers) {
                    if ($p.offers -is [array]) { $offer = $p.offers[0] }
                    else { $offer = $p.offers }
                }

                if ($offer) {
                    if ($offer.price) {
                        $result.Price = Convert-PriceStringToDouble "$($offer.price)"
                    }

                    if ($offer.availability) {
                        $avail = "$($offer.availability)"
                        if ($avail -like "*InStock*") {
                            $result.InStock = $true
                            $result.AvailabilityText = "Em Estoque"
                        } elseif ($avail -like "*OutOfStock*" -or $avail -like "*Discontinued*") {
                            $result.InStock = $false
                            $result.AvailabilityText = "Esgotado"
                        }
                    }
                }

                if ($result.Price -gt 0) {
                    $result.Success = $true
                    break
                }
            }
        } catch {}
        if ($result.Success) { break }
    }

    if ($result.RawTitle -and -not $result.Name) {
        $result.Name = $result.RawTitle
    }

    return $result
}

# Funcao auxiliar: Classificador de Alerta de Preco baseado em Preco-Alvo (%)
function Get-PriceAlertTier {
    param(
        [double]$Price,
        [double]$TargetPrice
    )

    if ($Price -le 0 -or $TargetPrice -le 0) {
        return @{
            category    = "Sem Preco"
            action      = "Indisponivel"
            badge       = "N/A"
            theme       = "muted"
            percentDiff = 0.0
            targetPrice = $TargetPrice
        }
    }

    # percentual = ((precoAtual / precoAlvo) - 1) * 100
    $percentDiff = [Math]::Round(((($Price / $TargetPrice) - 1.0) * 100.0), 2)

    # 1. COMPRA CERTA (<= 0%): precoAtual <= precoAlvo
    if ($percentDiff -le 0.0) {
        return @{
            category    = "COMPRA CERTA"
            action      = "Preco atingiu ou ficou abaixo do seu preco-alvo."
            badge       = "Compra Certa"
            theme       = "compra_certa"
            percentDiff = $percentDiff
            targetPrice = $TargetPrice
        }
    }

    # 2. EXCELENTE OPORTUNIDADE (0% a +3%): 0% < percentual <= 3%
    if ($percentDiff -le 3.0) {
        return @{
            category    = "EXCELENTE OPORTUNIDADE"
            action      = "Apenas ate 3% acima do preco-alvo. Vale comprar."
            badge       = "Excelente (+3%)"
            theme       = "excelente"
            percentDiff = $percentDiff
            targetPrice = $TargetPrice
        }
    }

    # 3. OTIMO PRECO (+3% a +5%): 3% < percentual <= 5%
    if ($percentDiff -le 5.0) {
        return @{
            category    = "OTIMO PRECO"
            action      = "Ate 5% acima do preco-alvo. Ainda e uma excelente oportunidade."
            badge       = "Otimo (+5%)"
            theme       = "otimo"
            percentDiff = $percentDiff
            targetPrice = $TargetPrice
        }
    }

    # 4. PRECO ACEITAVEL (+5% a +8%): 5% < percentual <= 8%
    if ($percentDiff -le 8.0) {
        return @{
            category    = "PRECO ACEITAVEL"
            action      = "Ate 8% acima do preco-alvo. Pode valer a compra dependendo da disponibilidade."
            badge       = "Aceitavel (+8%)"
            theme       = "aceitavel"
            percentDiff = $percentDiff
            targetPrice = $TargetPrice
        }
    }

    # 5. ACIMA DO IDEAL (+8% a +15%): 8% < percentual <= 15%
    if ($percentDiff -le 15.0) {
        return @{
            category    = "ACIMA DO IDEAL"
            action      = "Preco acima do ideal. Melhor esperar."
            badge       = "Acima (+15%)"
            theme       = "acima_ideal"
            percentDiff = $percentDiff
            targetPrice = $TargetPrice
        }
    }

    # 6. FORA DO RADAR (> +15%): percentual > 15%
    return @{
        category    = "FORA DO RADAR"
        action      = "Preco mais de 15% acima do preco-alvo."
        badge       = "Fora do Radar"
        theme       = "fora_radar"
        percentDiff = $percentDiff
        targetPrice = $TargetPrice
    }
}

# Containers support (fallback to flat items if not defined)
$containers = @()
if ($config.containers -and $config.containers.Count -gt 0) {
    $containers = $config.containers
} elseif ($config.items -and $config.items.Count -gt 0) {
    $containers = @(
        [PSCustomObject]@{
            id          = "default"
            name        = "Geral"
            category    = "Hardware"
            icon        = "cpu"
            targetPrice = $targetPrice
            items       = $config.items
        }
    )
}

$totalContainers = $containers.Count
$totalItems = 0
foreach ($c in $containers) {
    if ($c.items) { $totalItems += $c.items.Count }
}

Write-Host "[*] Monitorando $totalContainers container(s) com $totalItems produto(s) no total." -ForegroundColor Cyan

# 4. Executar verificacao para cada container e item
$timestampNow = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
$currentResults = @()
$newHistoryEntries = @()
$itemIndex = 0

foreach ($container in $containers) {
    $cId = if ($container.id) { $container.id } else { "default" }
    $cName = if ($container.name) { $container.name } else { "Geral" }
    $cTargetPrice = if ($container.targetPrice) { [double]$container.targetPrice } else { $targetPrice }

    Write-Host "`n------------------------------------------------------" -ForegroundColor DarkCyan
    Write-Host " Container: $cName (Alvo: R$ $($cTargetPrice.ToString('N2')))" -ForegroundColor Cyan
    Write-Host "------------------------------------------------------" -ForegroundColor DarkCyan

    if (-not $container.items -or $container.items.Count -eq 0) {
        Write-Host "  [i] Nenhum item cadastrado neste container." -ForegroundColor Gray
        continue
    }

    foreach ($item in $container.items) {
        $itemIndex++
        Write-Host "[$itemIndex/$totalItems] Consultando: $($item.store) - $($item.name)..." -NoNewline

        $method = if ($item.preferredMethod) { $item.preferredMethod } else { "auto" }
        $html = Get-PageContent -Url $item.url -Method $method -BrowserExe $browserPath -UA $userAgent -Timeout $timeoutSec

        $parsed = Parse-ProductData -Html $html -ItemConfig $item

        # Verificar dados previos para tratamento de variacoes
        $prev = $previousLatest[$item.id]
        $prevPrice = if ($prev -and $prev.price) { [double]$prev.price } else { $null }

        # Se falhou a leitura temporariamente, mas existia valor anterior, preserva o valor anterior com status de aviso
        if (-not $parsed.Success -or $parsed.Price -eq $null -or $parsed.Price -le 0) {
            if ($prevPrice -ne $null) {
                Write-Host " [FALHA NA LEITURA - Preservando R$ $($prevPrice.ToString('N2'))]" -ForegroundColor DarkYellow
                $parsed.Price = $prevPrice
                $parsed.InStock = if ($prev.inStock -ne $null) { $prev.inStock } else { $false }
                $parsed.AvailabilityText = if ($prev.availabilityText) { $prev.availabilityText } else { "Leitura Indisponível" }
                if (-not $parsed.ImageUrl) { $parsed.ImageUrl = $prev.imageUrl }
                if (-not $parsed.RawTitle) { $parsed.RawTitle = $prev.rawTitle }
                $parsed.Success = $false
            } else {
                Write-Host " [FALHA NA LEITURA]" -ForegroundColor Red
            }
        } else {
            $stockColor = if ($parsed.InStock) { "Green" } else { "DarkYellow" }
            Write-Host " R$ $($parsed.Price.ToString('N2')) " -ForegroundColor Green -NoNewline
            Write-Host "($($parsed.AvailabilityText))" -ForegroundColor $stockColor
        }

        # Calculo de variacao de preco
        $priceDiff = 0.0
        $priceDiffPercent = 0.0
        $variationType = "none" # "none", "up", "down"

        if ($prevPrice -ne $null -and $parsed.Price -ne $null) {
            $priceDiff = [Math]::Round(($parsed.Price - $prevPrice), 2)
            if ($prevPrice -gt 0) {
                $priceDiffPercent = [Math]::Round((($priceDiff / $prevPrice) * 100), 2)
            }
            if ($priceDiff -gt 0.01) {
                $variationType = "up"
            } elseif ($priceDiff -lt -0.01) {
                $variationType = "down"
            }
        }

        # Classificacao conforme Preco-Alvo do Container (%)
        $alertTier = Get-PriceAlertTier -Price $parsed.Price -TargetPrice $cTargetPrice

        # Objeto de resultado consolidado com containerId
        $resultItem = [PSCustomObject]@{
            id               = $item.id
            containerId      = $cId
            containerName    = $cName
            name             = $item.name
            store            = $item.store
            url              = $item.url
            rawTitle         = $parsed.RawTitle
            price            = $parsed.Price
            priceOriginal    = $parsed.PriceOriginal
            previousPrice    = $prevPrice
            priceChange      = $priceDiff
            priceChangePct   = $priceDiffPercent
            variationType    = $variationType
            alertTier        = $alertTier
            inStock          = $parsed.InStock
            availabilityText = $parsed.AvailabilityText
            imageUrl         = $parsed.ImageUrl
            sku              = $parsed.Sku
            lastUpdated      = $timestampNow
            status           = if ($parsed.Success) { "success" } elseif ($prevPrice) { "warning" } else { "error" }
        }

        $currentResults += $resultItem

        # Adicionar entrada ao historico temporal se temos um preco valido
        if ($resultItem.price -ne $null -and $resultItem.price -gt 0) {
            $historyEntry = [PSCustomObject]@{
                timestamp   = $timestampNow
                containerId = $cId
                itemId      = $item.id
                store       = $item.store
                name        = $item.name
                price       = $resultItem.price
                inStock     = $resultItem.inStock
            }
            $newHistoryEntries += $historyEntry
        }

        # Pequena pausa respeitosa entre requisicoes
        Start-Sleep -Milliseconds 800
    }
}

# Backfill containerId em historicos antigos se ausente
foreach ($h in $existingHistory) {
    if (-not $h.containerId) {
        $cMatch = $containers | Where-Object { 
            if ($_.items) { $_.items.id -contains $h.itemId } else { $false } 
        } | Select-Object -First 1
        $assignedId = if ($cMatch) { $cMatch.id } else { "ryzen-7-5800x3d" }
        $h | Add-Member -NotePropertyName "containerId" -NotePropertyValue $assignedId -Force
    }
}

# 5. Avaliacao de Variacao para Atualizacao do Historico Temporal POR CONTAINER
# REGRA: Cada container e avaliado de forma independente.
# Um container so ganha um novo ponto temporal se houver mudanca de preco em alguma oferta dele (ou novo item/inicio).
# Se todos os precos de um container permanecerem iguais aos do ultimo registro, nada e gravado para ele nesta rodada.

$allHistory = @($existingHistory)
$totalContainersUpdated = 0

foreach ($c in $containers) {
    $cId = $c.id
    $cExistingHistory = $existingHistory | Where-Object { $_.containerId -eq $cId }
    $cCurrentResults  = $currentResults | Where-Object { $_.containerId -eq $cId }
    $cNewEntries      = $newHistoryEntries | Where-Object { $_.containerId -eq $cId }

    if ($cNewEntries.Count -eq 0) {
        continue
    }

    $cHasPriceChange = $false

    if ($cExistingHistory.Count -eq 0) {
        $cHasPriceChange = $true
        Write-Host "`n[*] Container '$($c.name)': primeiro registro de historico gravado." -ForegroundColor Cyan
    } else {
        foreach ($res in $cCurrentResults) {
            if ($res.price -ne $null -and $res.price -gt 0) {
                $lastEntry = $cExistingHistory | Where-Object { $_.itemId -eq $res.id } | Select-Object -Last 1
                if ($lastEntry) {
                    $lastPrice = [double]$lastEntry.price
                    $currentPrice = [double]$res.price
                    if ([Math]::Abs($currentPrice - $lastPrice) -gt 0.01) {
                        $cHasPriceChange = $true
                        Write-Host "`n[!] Mudanca de preco em '$($c.name)' [$($res.store) - $($res.name)]: R$ $lastPrice -> R$ $currentPrice" -ForegroundColor Yellow
                        break
                    }
                } else {
                    $cHasPriceChange = $true
                    Write-Host "`n[+] Novo produto adicionado em '$($c.name)': [$($res.store) - $($res.name)]" -ForegroundColor Cyan
                    break
                }
            }
        }
    }

    if ($cHasPriceChange) {
        # Grava os dados deste container para o novo timestamp
        $allHistory += $cNewEntries
        $totalContainersUpdated++
        Write-Host "[+] Novo marco temporal registrado para container '$($c.name)'." -ForegroundColor Green
    } else {
        Write-Host "[=] Container '$($c.name)': precos estaveis (sem alteracao). O grafico mantera o marco anterior." -ForegroundColor DarkGray
    }
}

# Otimizacao: Manter no historico os ultimos 5.000 pontos
if ($allHistory.Count -gt 5000) {
    $allHistory = $allHistory | Select-Object -Last 5000
}

# 6. Salvar arquivos de dados

# 6.1 data/latest_prices.json
$currentResults | ConvertTo-Json -Depth 5 | Set-Content $latestPricesFile -Encoding UTF8

# 6.2 data/price_history.json
$allHistory | ConvertTo-Json -Depth 4 | Set-Content $historyFile -Encoding UTF8

# 6.3 data/price_history.csv
$allHistory | Export-Csv -Path $historyCsvFile -NoTypeInformation -Encoding UTF8 -Delimiter ";"

# 6.4 data/data.js (Carregamento nativo no navegador sem restricao de CORS para duplo clique em file://)
$targetPriceJs = [string]::Format([System.Globalization.CultureInfo]::InvariantCulture, "{0:0.00}", $targetPrice)
$containersJson = if ($containers.Count -eq 1) {
    "[" + ($containers[0] | ConvertTo-Json -Depth 5) + "]"
} else {
    $containers | ConvertTo-Json -Depth 5
}
$itemsJson = if ($currentResults.Count -eq 1) {
    "[" + ($currentResults[0] | ConvertTo-Json -Depth 5) + "]"
} else {
    $currentResults | ConvertTo-Json -Depth 5
}
$historyJson = if ($allHistory.Count -eq 1) {
    "[" + ($allHistory[0] | ConvertTo-Json -Depth 4) + "]"
} else {
    $allHistory | ConvertTo-Json -Depth 4
}
$jsContent = @"
// PriceCheckURL - Dados atualizados automaticamente
window.PRICE_DATA = {
    lastCheck: "$timestampNow",
    targetPrice: $targetPriceJs,
    totalItems: $($currentResults.Count),
    containers: $containersJson,
    items: $itemsJson,
    history: $historyJson
};
"@
$jsContent | Set-Content $dataJsFile -Encoding UTF8

Write-Host "`n======================================================" -ForegroundColor Cyan
Write-Host "  Resumo da Atualizacao:" -ForegroundColor Cyan
Write-Host "  - latest_prices.json : $($currentResults.Count) itens atualizados em $($containers.Count) container(s)" -ForegroundColor Gray
Write-Host "  - price_history.json : $($allHistory.Count) pontos historicos registrados" -ForegroundColor Gray
Write-Host "  - price_history.csv  : Salvo para abertura no Excel" -ForegroundColor Gray
Write-Host "  - data.js            : Gerado para visualizacao offline no dashboard.html" -ForegroundColor Gray
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "Concluido com sucesso em: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n" -ForegroundColor Green

# Finalizar sessao do navegador CDP se foi inicializada
Stop-CdpBrowser
