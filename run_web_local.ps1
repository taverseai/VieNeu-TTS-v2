param(
    [switch]$Check
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$storageRoot = Join-Path $projectRoot '.runtime'

# Set paths BEFORE uv installs packages or Python imports cache-aware libraries.
# These variables affect only this process and its children.
$localPaths = [ordered]@{
    UV_CACHE_DIR = 'uv-cache'
    UV_PYTHON_INSTALL_DIR = 'python'
    UV_PYTHON_CACHE_DIR = 'python-cache'
    UV_PYTHON_BIN_DIR = 'python-bin'
    UV_TOOL_DIR = 'uv-tools'
    UV_TOOL_BIN_DIR = 'uv-bin'
    UV_CREDENTIALS_DIR = 'uv-credentials'
    HF_HOME = 'huggingface'
    HF_HUB_CACHE = 'huggingface/hub'
    HUGGINGFACE_HUB_CACHE = 'huggingface/hub'
    HF_XET_CACHE = 'huggingface/xet'
    HF_ASSETS_CACHE = 'huggingface/assets'
    HF_MODULES_CACHE = 'huggingface/modules'
    TORCH_HOME = 'torch'
    TORCH_EXTENSIONS_DIR = 'torch-extensions'
    TORCHINDUCTOR_CACHE_DIR = 'torchinductor'
    TRITON_CACHE_DIR = 'triton'
    CUDA_CACHE_PATH = 'cuda'
    NUMBA_CACHE_DIR = 'numba'
    MPLCONFIGDIR = 'matplotlib'
    PIP_CACHE_DIR = 'pip-cache'
    XDG_CACHE_HOME = 'cache'
    XDG_CONFIG_HOME = 'config'
    XDG_DATA_HOME = 'data'
    VIENEU_HOME = 'vieneu'
    GRADIO_TEMP_DIR = 'gradio'
    TEMP = 'tmp'
    TMP = 'tmp'
    TMPDIR = 'tmp'
}

$previousValues = @{}
try {
    foreach ($entry in $localPaths.GetEnumerator()) {
        $previousValues[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key, 'Process')
        $path = Join-Path $storageRoot $entry.Value
        New-Item -ItemType Directory -Path $path -Force | Out-Null
        [Environment]::SetEnvironmentVariable($entry.Key, $path, 'Process')
    }
    $previousValues['UV_PROJECT_ENVIRONMENT'] = [Environment]::GetEnvironmentVariable('UV_PROJECT_ENVIRONMENT', 'Process')
    [Environment]::SetEnvironmentVariable('UV_PROJECT_ENVIRONMENT', (Join-Path $projectRoot '.venv'), 'Process')

    Write-Host "Project: $projectRoot"
    Write-Host "Cache, downloads and temporary files: $storageRoot"
    if ($Check) {
        foreach ($key in $localPaths.Keys) {
            Write-Host "$key=$([Environment]::GetEnvironmentVariable($key, 'Process'))"
        }
        return
    }

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw 'uv was not found in PATH. Run this launcher from the terminal where uv is installed.'
    }
    Push-Location -LiteralPath $projectRoot
    try {
        & uv run --extra cuda vieneu-web
        if ($LASTEXITCODE -ne 0) {
            throw "VieNeu web exited with code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    foreach ($key in $previousValues.Keys) {
        [Environment]::SetEnvironmentVariable($key, $previousValues[$key], 'Process')
    }
}
