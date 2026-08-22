$sum = 0
Get-Process -Name python, msedgewebview2 -ErrorAction SilentlyContinue | ForEach-Object {
    $pid_str = $_.Id
    $filter = "Name like '%pid_${pid_str}_luid%'"
    Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine -Filter $filter -ErrorAction SilentlyContinue | 
    Measure-Object -Property UtilizationPercentage -Sum | 
    ForEach-Object { $sum += $_.Sum }
}
Write-Output $sum
