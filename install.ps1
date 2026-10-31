<#
.SYNOPSIS
    一键把 chem-draw-tool 装到能跑：装依赖、取 32 位运行时、两条通道各体检一次。

.DESCRIPTION
    每一步失败都不中断，最后给一张汇总表——因为最常见的真实情况不是「全坏」，
    而是「ChemDraw 那条能用、KingDraw 那条缺运行时」，这种半好状态下更该看到全貌。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1

.EXAMPLE
    .\install.ps1 -SkipRuntime      # 只装 ChemDraw 通道，不下载 10 MB 的 32 位运行时
#>
[CmdletBinding()]
param(
    [string]$Python,
    [switch]$SkipRuntime,
    [switch]$SkipDoctor
)

# Without this the Chinese output turns into question marks in most Windows
# terminals, which makes a failed step impossible to read.
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$results = [ordered]@{}
function Note($key, $ok, $detail) {
    $results[$key] = [pscustomobject]@{ Ok = $ok; Detail = $detail }
}

Write-Host ''
Write-Host 'chem-draw-tool 安装' -ForegroundColor Cyan
Write-Host ('目录: ' + $root)
Write-Host ''

# ---- 1. 解释器 ------------------------------------------------------------
if (-not $Python) {
    foreach ($candidate in @('python', 'py -3.11', 'py -3')) {
        $parts = $candidate.Split(' ')
        try {
            $probe = & $parts[0] $parts[1..($parts.Length-1)] -c "import sys;print(sys.version_info[0],sys.version_info[1],64 if sys.maxsize>2**32 else 32)" 2>$null
            if ($LASTEXITCODE -eq 0) { $Python = $candidate; break }
        } catch { }
    }
}
if (-not $Python) {
    Note 'python' $false '找不到 python / py，请先装 Python 3.9+ 并加入 PATH，或用 -Python 指定'
    Write-Host '找不到 Python，后面的步骤无法继续。' -ForegroundColor Red
    $results.GetEnumerator() | ForEach-Object { Write-Host ('  {0,-14} {1}' -f $_.Key, $_.Value.Detail) }
    exit 1
}
$verLine = (& cmd /c "$Python -c ""import sys;print('.'.join(map(str,sys.version_info[:3])))""" 2>$null)
$bitsLine = (& cmd /c "$Python -c ""import sys;print(64 if sys.maxsize>2**32 else 32)""" 2>$null)
Note 'python' $true ('{0} ({1} 位) — {2}' -f $Python, $bitsLine, $verLine)
if ($bitsLine -ne '64') {
    Write-Host '警告: 这个解释器不是 64 位，ChemDraw 通道会拒绝工作。' -ForegroundColor Yellow
}

# ---- 2. 依赖 --------------------------------------------------------------
Write-Host '正在安装依赖 (rdkit / pillow / pywin32) ...'
& cmd /c "$Python -m pip install --disable-pip-version-check -q -r requirements.txt" 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Note 'dependencies' $true 'rdkit / pillow / pywin32'
} else {
    Note 'dependencies' $false 'pip install 失败，手动跑: ' + $Python + ' -m pip install -r requirements.txt'
}

# ---- 3. 32 位运行时 -------------------------------------------------------
if ($SkipRuntime) {
    Note 'kingdraw-runtime' $true '跳过 (-SkipRuntime)'
} elseif (Test-Path 'runtime\py32\python.exe') {
    Note 'kingdraw-runtime' $true '已存在 runtime\py32\python.exe'
} else {
    Write-Host '正在下载 32 位 Python 运行时 (约 10 MB) ...'
    & cmd /c "$Python scripts/fetch_runtime.py" 2>&1 | Select-Object -Last 3 | ForEach-Object { Write-Host ('  ' + $_) }
    if (Test-Path 'runtime\py32\python.exe') {
        Note 'kingdraw-runtime' $true 'runtime\py32\python.exe'
    } else {
        Note 'kingdraw-runtime' $false '下载失败；只用 ChemDraw 通道可以忽略'
    }
}

# ---- 4. 两条通道体检 ------------------------------------------------------
if (-not $SkipDoctor) {
    Write-Host '正在体检 ChemDraw 通道 ...'
    & cmd /c "$Python bin\cli.py doctor cd --json" > $null 2>&1
    Note 'chemdraw' ($LASTEXITCODE -eq 0) $(if ($LASTEXITCODE -eq 0) { 'available' } else { '不可用，跑 doctor cd --json 看原因' })

    if (Test-Path 'runtime\py32\python.exe') {
        Write-Host '正在体检 KingDraw 通道 ...'
        & cmd /c "runtime\py32\python.exe bin\cli.py doctor kd --json" > $null 2>&1
        Note 'kingdraw' ($LASTEXITCODE -eq 0) $(if ($LASTEXITCODE -eq 0) { 'available' } else { '不可用，跑 doctor kd --json 看原因' })
    } else {
        Note 'kingdraw' $false '缺 runtime\py32'
    }
}

# ---- 汇总 ----------------------------------------------------------------
Write-Host ''
Write-Host '汇总' -ForegroundColor Cyan
foreach ($entry in $results.GetEnumerator()) {
    $mark = if ($entry.Value.Ok) { '[ok]  ' } else { '[--]  ' }
    $color = if ($entry.Value.Ok) { 'Green' } else { 'Yellow' }
    Write-Host ($mark + $entry.Key.PadRight(18) + $entry.Value.Detail) -ForegroundColor $color
}
Write-Host ''
$anyFailed = ($results.Values | Where-Object { -not $_.Ok }).Count -gt 0
if ($anyFailed) {
    Write-Host '有的步骤没成功。这不代表装坏了——只装一个软件时，另一条通道本来就该是红的。' -ForegroundColor Yellow
    Write-Host '下一步: python bin/cli.py doctor cd --json   （或 kd）看具体原因'
} else {
    Write-Host '两条通道都可用。试试: python examples/batch_identity.py' -ForegroundColor Green
}
exit $(if ($anyFailed) { 1 } else { 0 })