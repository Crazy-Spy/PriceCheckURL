Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""E:\_Git\PriceCheckURL\Start-DashboardServer.ps1""", 0, False

