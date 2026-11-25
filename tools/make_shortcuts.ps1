# PerfOSD 快捷方式生成器（本文件必须保存为 UTF-8 with BOM，否则 PowerShell 5.1 读中文会乱码）
$ErrorActionPreference = 'Stop'

$proj = Split-Path -Parent $PSScriptRoot
$main = Join-Path $proj 'main.py'
$icon = Join-Path $proj 'assets\icon.ico'

$pyw = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if ($pyw) { $exe = $pyw.Source } else { $exe = (Get-Command python.exe).Source }

Write-Host "解释器: $exe"
Write-Host "图标:   $icon"

$shell  = New-Object -ComObject WScript.Shell
$places = @($proj)
$desktop = [Environment]::GetFolderPath('Desktop')
if ($desktop -and (Test-Path $desktop)) { $places += $desktop }

$defs = @(
    @{ Name = 'PerfOSD 性能悬浮窗';         Args = "`"$main`"";             Desc = 'CPU / 内存 / GPU / FPS 实时悬浮窗' },
    @{ Name = 'PerfOSD 性能悬浮窗（管理员）'; Args = "`"$main`" --elevate"; Desc = '提权启动，启用 FPS 采集' }
)

foreach ($dir in $places) {
    foreach ($d in $defs) {
        $path = Join-Path $dir ($d.Name + '.lnk')
        $lnk = $shell.CreateShortcut($path)
        $lnk.TargetPath       = $exe
        $lnk.Arguments        = $d.Args
        $lnk.WorkingDirectory = $proj
        $lnk.IconLocation     = "$icon,0"
        $lnk.Description      = $d.Desc
        $lnk.WindowStyle      = 7          # 最小化，避免 pythonw 也闪一下
        $lnk.Save()
        Write-Host ("已创建: " + $path)
    }
}

Write-Host ''
Write-Host '完成。桌面和本目录都有带图标的快捷方式了。'
