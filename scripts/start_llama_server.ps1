param(
    [string]$LlamaCppDir = "D:\llama-cpp",
    [string]$ModelPath = "D:\models\gemma-4-E2B-it-Q4_K_M.gguf",
    [string]$MmprojPath = "D:\models\mmproj-F16.gguf",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8080,
    [int]$CtxSize = 8192
)

$ServerExe = Join-Path $LlamaCppDir "llama-server.exe"

if (-not (Test-Path $ServerExe)) {
    Write-Error "llama-server.exe not found at: $ServerExe"
    exit 1
}

if (-not (Test-Path $ModelPath)) {
    Write-Error "Model file not found at: $ModelPath"
    exit 1
}

$ArgsList = @(
    "-m", $ModelPath,
    "--host", $HostAddress,
    "--port", "$Port",
    "-c", "$CtxSize",
    "--jinja",
    "--reasoning-budget", "0",
    "--timeout", "600"
)

if (Test-Path $MmprojPath) {
    $ArgsList += @("--mmproj", $MmprojPath)
    Write-Host "Starting Gemma 4 multimodal llama-server (text + image + audio, thinking disabled) on http://${HostAddress}:${Port} ..." -ForegroundColor Cyan
} else {
    Write-Host "Starting Gemma 4 text-only llama-server on http://${HostAddress}:${Port} ..." -ForegroundColor Yellow
}

& $ServerExe @ArgsList
