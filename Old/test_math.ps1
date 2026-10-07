$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$url = "file:///E:/_Git/PriceCheckURL/dashboard.html"

# Teste 1: com Preço-Alvo padrão de 2050
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $chrome
$psi.Arguments = "--headless=new --disable-gpu --no-sandbox --allow-file-access-from-files --virtual-time-budget=2000 --dump-dom $url"
$psi.RedirectStandardOutput = $true
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true

$proc = [System.Diagnostics.Process]::Start($psi)
$out2050 = $proc.StandardOutput.ReadToEnd()
$proc.WaitForExit()

Write-Host "--- TESTE COM PREÇO ALVO R$ 2.050,00 ---"
Write-Host "Terabyte Standard (+2.02%): $($out2050.Contains('EXCELENTE OPORTUNIDADE'))"
Write-Host "Faixa Excelente: $($out2050.Contains('2.111,50'))"
Write-Host "Faixa Aceitável: $($out2050.Contains('2.214,00'))"
Write-Host "Faixa Acima: $($out2050.Contains('2.357,50'))"

