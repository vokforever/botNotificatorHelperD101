# PowerShell script to kill all Python processes
Write-Host "Stopping all Python processes..." -ForegroundColor Yellow

try {
    # Get all Python processes
    $pythonProcesses = Get-Process python -ErrorAction SilentlyContinue
    
    if ($pythonProcesses) {
        Write-Host "Found $($pythonProcesses.Count) Python process(es):" -ForegroundColor Cyan
        foreach ($proc in $pythonProcesses) {
            Write-Host "  - PID: $($proc.Id), Name: $($proc.ProcessName)" -ForegroundColor Gray
        }
        
        # Force kill all Python processes
        $pythonProcesses | Stop-Process -Force
        Write-Host "All Python processes have been stopped." -ForegroundColor Green
    } else {
        Write-Host "No Python processes found." -ForegroundColor Green
    }
    
    # Also check for pythonw processes
    $pythonwProcesses = Get-Process pythonw -ErrorAction SilentlyContinue
    if ($pythonwProcesses) {
        Write-Host "Found $($pythonwProcesses.Count) pythonw process(es):" -ForegroundColor Cyan
        foreach ($proc in $pythonwProcesses) {
            Write-Host "  - PID: $($proc.Id), Name: $($proc.ProcessName)" -ForegroundColor Gray
        }
        
        # Force kill all pythonw processes
        $pythonwProcesses | Stop-Process -Force
        Write-Host "All pythonw processes have been stopped." -ForegroundColor Green
    }
    
} catch {
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "Process cleanup completed." -ForegroundColor Green
Write-Host "Press any key to continue..." -ForegroundColor Yellow
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
