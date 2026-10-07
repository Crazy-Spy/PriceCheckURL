Set WshShell = CreateObject("WScript.Shell")

WshShell.Run "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""E:\_Git\PriceCheckURL\Check-Prices.ps1""", 0, False