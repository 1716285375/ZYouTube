# Stop development servers

Write-Host "Stopping development servers..." -ForegroundColor Yellow

# Function to kill process by port
function Stop-ProcessByPort {
    param([int]$Port)
    
    try {
        $connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Where-Object { $_.State -eq "Listen" }
        foreach ($conn in $connections) {
            $pid = $conn.OwningProcess
            if ($pid) {
                Write-Host "Stopping process $pid on port $Port..." -ForegroundColor Cyan
                Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {
        # Fallback: use netstat
        $netstatOutput = netstat -ano | Select-String ":$Port.*LISTENING"
        foreach ($line in $netstatOutput) {
            $pid = ($line -split '\s+')[-1]
            if ($pid -match '^\d+$') {
                Write-Host "Stopping process $pid on port $Port..." -ForegroundColor Cyan
                Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

# Stop backend (port 8866)
Stop-ProcessByPort -Port 8866

# Stop frontend (port 5173)
Stop-ProcessByPort -Port 5173

# Also try to kill by process name as fallback
Get-Process python* -ErrorAction SilentlyContinue | Where-Object {
    try {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
        $cmdLine -like "*uvicorn*" -or $cmdLine -like "*app.main*"
    } catch {
        $false
    }
} | ForEach-Object {
    Write-Host "Stopping Python/uvicorn process (PID: $($_.Id))..." -ForegroundColor Cyan
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}

# Kill node processes that might be running vite
Get-Process node -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
        if ($cmdLine -like "*vite*" -or $cmdLine -like "*frontend*") {
            Write-Host "Stopping Node.js/Vite process (PID: $($_.Id))..." -ForegroundColor Cyan
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        }
    } catch {
        # If we can't check command line, skip
    }
}

Write-Host "Done. All development servers stopped." -ForegroundColor Green

