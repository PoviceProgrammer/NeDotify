$sum = 0
Get-CimInstance Win32_PerfFormattedData_PerfProc_Process -Filter "Name like '%python%' or Name like '%msedgewebview2%'" -ErrorAction SilentlyContinue |
Measure-Object -Property PercentProcessorTime -Sum |
ForEach-Object { $sum = $_.Sum }
Write-Output $sum
