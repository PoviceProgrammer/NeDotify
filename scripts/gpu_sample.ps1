<#
    Repeated GPU sampler for before/after comparisons, scoped to ONE process tree.

    scripts/gpu.ps1 sums every python* and msedgewebview2* process on the machine,
    which silently folds in other WebView2 apps (Teams, SearchHost, Copilot...).
    This script resolves NeDotify's own tree instead: the python.exe running main.py
    plus every msedgewebview2 descendant of it. Numbers from the two scripts are not
    comparable -- use this one for before/after work.

    Usage (from the repo root):
        powershell -ExecutionPolicy Bypass -File scripts/gpu_sample.ps1 -Samples 20 -IntervalMs 500 -Label "M0 baseline"
        powershell -ExecutionPolicy Bypass -File scripts/gpu_sample.ps1 -All      # old machine-wide behaviour
#>
param(
    [int]$Samples = 20,
    [int]$IntervalMs = 500,
    [string]$Label = "",
    [switch]$All
)

# ---- resolve the target PID set once -----------------------------------------
$procs = Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId, Name, CommandLine

function Resolve-AuraPids {
    $root = $procs | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*main.py*' } | Select-Object -First 1
    if (-not $root) { return @() }
    $set = [System.Collections.Generic.HashSet[uint32]]::new()
    [void]$set.Add([uint32]$root.ProcessId)
    # breadth-first over descendants; WebView2 spawns a browser host + N children
    $frontier = @([uint32]$root.ProcessId)
    while ($frontier.Count -gt 0) {
        $next = @()
        foreach ($parent in $frontier) {
            foreach ($child in ($procs | Where-Object { $_.ParentProcessId -eq $parent })) {
                if ($set.Add([uint32]$child.ProcessId)) { $next += [uint32]$child.ProcessId }
            }
        }
        $frontier = $next
    }
    return $set
}

if ($All) {
    $pids = @(Get-Process -Name python, msedgewebview2 -ErrorAction SilentlyContinue | ForEach-Object { [uint32]$_.Id })
    $scope = "machine-wide (all python + msedgewebview2)"
} else {
    $pids = @(Resolve-AuraPids)
    $scope = "NeDotify process tree only"
}
if ($pids.Count -eq 0) { Write-Output "no matching processes found"; exit 1 }

# One CIM query per sample, filtered to the PIDs of interest, instead of one query
# per process -- the per-process form takes ~6s per sample with 20 WebView2 procs.
$filter = ($pids | ForEach-Object { "Name like '%pid_${_}_luid%'" }) -join ' OR '

$values = @()
$lastEngines = @{}
for ($i = 1; $i -le $Samples; $i++) {
    $sum = 0
    $engines = @{}
    Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine -Filter $filter -ErrorAction SilentlyContinue | ForEach-Object {
        $sum += $_.UtilizationPercentage
        if ($_.UtilizationPercentage -gt 0) {
            $eng = ($_.Name -split '_engtype_')[-1]
            if (-not $engines.ContainsKey($eng)) { $engines[$eng] = 0 }
            $engines[$eng] += $_.UtilizationPercentage
        }
    }
    $values += $sum
    $lastEngines = $engines
    Write-Output ("  sample {0,2}: {1,6:N1} %" -f $i, $sum)
    if ($i -lt $Samples) { Start-Sleep -Milliseconds $IntervalMs }
}

$sorted = $values | Sort-Object
$n = $sorted.Count
if ($n % 2 -eq 1) { $median = $sorted[[int](($n - 1) / 2)] }
else { $median = ($sorted[$n / 2 - 1] + $sorted[$n / 2]) / 2 }

Write-Output ""
if ($Label) { Write-Output ("LABEL  : {0}" -f $Label) }
Write-Output ("SCOPE  : {0} -- pids {1}" -f $scope, ($pids -join ','))
Write-Output ("SAMPLES: {0}" -f $n)
Write-Output ("MIN    : {0:N1} %" -f ($sorted[0]))
Write-Output ("MEDIAN : {0:N1} %" -f $median)
Write-Output ("MEAN   : {0:N1} %" -f (($values | Measure-Object -Average).Average))
Write-Output ("MAX    : {0:N1} %" -f ($sorted[$n - 1]))
Write-Output ("ENGINES (last sample): {0}" -f (($lastEngines.GetEnumerator() | Sort-Object -Property Value -Descending | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ', '))
