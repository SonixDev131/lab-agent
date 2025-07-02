# PowerShell script to fix screenshot issues for Windows services
# Chạy với quyền Administrator

Write-Host "=== Agent Screenshot Service Fix ===" -ForegroundColor Green
Write-Host "Checking and fixing common screenshot issues..." -ForegroundColor Yellow

# 1. Check current service configuration
$serviceName = "agent"
Write-Host "`n1. Checking service configuration..." -ForegroundColor Cyan

try {
    $service = Get-Service -Name $serviceName -ErrorAction Stop
    Write-Host "Service Status: $($service.Status)" -ForegroundColor Green
    
    # Get service details
    $serviceDetails = Get-WmiObject -Class Win32_Service -Filter "Name='$serviceName'"
    Write-Host "Service Type: $($serviceDetails.ServiceType)" -ForegroundColor Green
    Write-Host "Desktop Interaction: $($serviceDetails.DesktopInteract)" -ForegroundColor Green
    
} catch {
    Write-Host "ERROR: Service '$serviceName' not found!" -ForegroundColor Red
    exit 1
}

# 2. Check current session info
Write-Host "`n2. Checking session information..." -ForegroundColor Cyan
$currentSession = (quser) | Where-Object {$_ -match $env:USERNAME}
if ($currentSession) {
    Write-Host "Current user session: $currentSession" -ForegroundColor Green
} else {
    Write-Host "WARNING: No active user session detected" -ForegroundColor Yellow
}

# 3. Check display configuration
Write-Host "`n3. Checking display configuration..." -ForegroundColor Cyan
try {
    $displays = Get-WmiObject -Class Win32_DesktopMonitor
    foreach ($display in $displays) {
        Write-Host "Monitor: $($display.DeviceID) - $($display.ScreenWidth)x$($display.ScreenHeight)" -ForegroundColor Green
    }
} catch {
    Write-Host "WARNING: Could not retrieve display information" -ForegroundColor Yellow
}

# 4. Fix service configuration
Write-Host "`n4. Fixing service configuration..." -ForegroundColor Cyan

# Stop service
Write-Host "Stopping service..." -ForegroundColor Yellow
try {
    Stop-Service -Name $serviceName -Force
    Write-Host "Service stopped successfully" -ForegroundColor Green
} catch {
    Write-Host "WARNING: Could not stop service: $($_.Exception.Message)" -ForegroundColor Yellow
}

# Configure service for desktop interaction
Write-Host "Configuring service for desktop interaction..." -ForegroundColor Yellow
try {
    # Method 1: Using sc command
    $result = & sc.exe config $serviceName type= interact type= own
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Service configured for desktop interaction" -ForegroundColor Green
    } else {
        Write-Host "WARNING: Failed to configure desktop interaction" -ForegroundColor Yellow
    }
    
    # Method 2: Set service to run in user context (alternative)
    Write-Host "Setting service logon account..." -ForegroundColor Yellow
    $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    # Note: This would require password input in production
    # & sc.exe config $serviceName obj= $currentUser password= "PASSWORD"
    
} catch {
    Write-Host "ERROR: Failed to configure service: $($_.Exception.Message)" -ForegroundColor Red
}

# 5. Check Windows policies
Write-Host "`n5. Checking Windows policies..." -ForegroundColor Cyan
try {
    $policy = Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Windows" -Name "NoInteractiveServices" -ErrorAction SilentlyContinue
    if ($policy -and $policy.NoInteractiveServices -eq 1) {
        Write-Host "WARNING: Interactive services are disabled by policy" -ForegroundColor Yellow
        Write-Host "Enabling interactive services..." -ForegroundColor Yellow
        Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Windows" -Name "NoInteractiveServices" -Value 0
        Write-Host "Interactive services enabled (restart required)" -ForegroundColor Green
    } else {
        Write-Host "Interactive services policy: OK" -ForegroundColor Green
    }
} catch {
    Write-Host "WARNING: Could not check interactive services policy" -ForegroundColor Yellow
}

# 6. Test screenshot function
Write-Host "`n6. Testing screenshot capability..." -ForegroundColor Cyan
try {
    Add-Type -AssemblyName System.Drawing
    Add-Type -AssemblyName System.Windows.Forms
    
    $screen = [System.Windows.Forms.Screen]::PrimaryScreen
    $bounds = $screen.Bounds
    Write-Host "Primary screen: $($bounds.Width)x$($bounds.Height)" -ForegroundColor Green
    
    # Try to take a test screenshot
    $bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
    $graphics.Dispose()
    $bitmap.Dispose()
    
    Write-Host "Screenshot test: SUCCESS" -ForegroundColor Green
} catch {
    Write-Host "Screenshot test: FAILED - $($_.Exception.Message)" -ForegroundColor Red
}

# 7. Start service
Write-Host "`n7. Starting service..." -ForegroundColor Cyan
try {
    Start-Service -Name $serviceName
    Write-Host "Service started successfully" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Could not start service: $($_.Exception.Message)" -ForegroundColor Red
}

# 8. Summary and recommendations
Write-Host "`n=== SUMMARY AND RECOMMENDATIONS ===" -ForegroundColor Green
Write-Host "If screenshot issues persist, try:" -ForegroundColor Yellow
Write-Host "1. Restart Windows (for policy changes to take effect)" -ForegroundColor White
Write-Host "2. Ensure user is logged in and screen is unlocked" -ForegroundColor White
Write-Host "3. Check graphics drivers are up to date" -ForegroundColor White
Write-Host "4. Run service as current user instead of Local System" -ForegroundColor White
Write-Host "5. Consider using alternative screenshot methods (Windows API)" -ForegroundColor White
Write-Host "`nScript completed!" -ForegroundColor Green 