param([switch]$CheckOnly, [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot), [string]$PackageCache = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$Config = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'runtime.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$Requirements = Join-Path $PSScriptRoot 'requirements.lock.txt'
$Venv = Join-Path $ProjectRoot 'myenv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$LogDir = Join-Path $ProjectRoot 'logs\environment_setup'
$Log = Join-Path $LogDir 'latest.log'
if (-not $PackageCache) { $PackageCache = Join-Path $LogDir 'pipcache' }
$TempInstaller = $null
$Lock = $null
$OldNoBytecode = $env:PYTHONDONTWRITEBYTECODE
$OldNoUserSite = $env:PYTHONNOUSERSITE
$OldPythonUtf8 = $env:PYTHONUTF8
$OldPythonIoEncoding = $env:PYTHONIOENCODING
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding

function Say([string]$Message) {
    Write-Host $Message
    if (-not $CheckOnly) { Add-Content -LiteralPath $Log -Value $Message -Encoding UTF8 }
}

function Encode-PythonCode([string]$Code) {
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Code))
    return "import base64;exec(base64.b64decode('$encoded'))"
}

function Probe-Python([string]$Exe) {
    if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) { return $false }
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $probeCode = Encode-PythonCode 'import sys,struct; print("%s;%s" % (".".join(map(str,sys.version_info[:3])), struct.calcsize("P")*8))'
        $info = & $Exe -I -B -c $probeCode 2>$null
        return ($LASTEXITCODE -eq 0 -and (($info -join '').Trim() -eq "$($Config.python_version);64"))
    } finally { $ErrorActionPreference = $old }
}

function Invoke-Python([string]$Exe, [string[]]$Arguments) {
    $Arguments = @('-X', 'utf8') + @($Arguments)
    for ($i = 0; $i -lt $Arguments.Length - 1; $i++) {
        if ($Arguments[$i] -eq '-c') { $Arguments[$i+1] = Encode-PythonCode $Arguments[$i+1]; break }
    }
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Exe @Arguments 2>&1 | ForEach-Object { Say ([string]$_) }
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $old }
    if ($code -ne 0) { throw "Python command failed (exit $code): $($Arguments -join ' ')" }
}

function Download-File([string]$Uri, [string]$Destination) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $Destination -TimeoutSec 120
            return
        } catch {
            if ($attempt -eq 3) { throw }
            Say "Download retry $attempt/3 ..."
        }
    }
}

try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'This package requires 64-bit Windows.' }
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'base.txt') -PathType Leaf)) {
        throw 'Extract the package into the Golden_Bull_Projects root (the folder containing base.txt).'
    }
    if ((Get-FileHash -LiteralPath $Requirements -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Config.requirements_sha256) {
        throw 'The dependency lock file does not match runtime.json. Re-extract the complete package.'
    }
    if (-not $CheckOnly) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
        $Lock = [IO.File]::Open((Join-Path $LogDir 'setup.lock'), [IO.FileMode]::OpenOrCreate,
                              [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        Set-Content -LiteralPath $Log -Value 'Golden Bull environment setup' -Encoding UTF8
    }
    Say "Python version: $($Config.python_version) x64"
    Say "Environment: $Venv"

    if (Test-Path -LiteralPath $Venv) {
        if ((Get-Item -LiteralPath $Venv).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'myenv is a link or junction; it has been preserved. Use an ordinary project directory.'
        }
        if (-not (Probe-Python $VenvPython)) {
            throw 'Existing myenv is unusable or uses a different Python version. It has been preserved. Rename it before rebuilding.'
        }
        Say 'Existing myenv matches the selected Python version.'
    } else {
        if ($CheckOnly) { throw 'myenv is missing. Double-click the setup launcher to create it.' }
        # Reuse only the exact x64 version; never invoke Windows Store aliases.
        $Candidates = @(
            (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
            (Join-Path $env:LOCALAPPDATA "GoldenBullPython\$($Config.python_version)\python.exe"),
            (Join-Path $env:ProgramFiles 'Python311\python.exe')
        )
        $BasePython = $null
        foreach ($candidate in $Candidates) {
            if (Probe-Python $candidate) { $BasePython = $candidate; break }
        }
        if ($null -eq $BasePython) {
            $InstallDir = Join-Path $env:LOCALAPPDATA "GoldenBullPython\$($Config.python_version)"
            New-Item -ItemType Directory -Path (Join-Path $LogDir 'downloads') -Force | Out-Null
            $TempInstaller = Join-Path $LogDir "downloads\python-$($Config.python_version)-amd64.exe"
            Say 'Downloading the selected Python installer from python.org ...'
            Download-File $Config.python_installer_url $TempInstaller
            $sig = Get-AuthenticodeSignature -LiteralPath $TempInstaller
            if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'CN=Python Software Foundation(?:,|$)') {
                throw 'Python installer signature verification failed; installation was not started.'
            }
            Say 'Installing Python for the current Windows user ...'
            $installArgs = @('/quiet', 'InstallAllUsers=0', 'Include_launcher=0', 'Include_doc=0',
                             'Include_test=0', 'Include_tcltk=1', 'PrependPath=0', 'AppendPath=0',
                             'AssociateFiles=0', 'Shortcuts=0', ('TargetDir="{0}"' -f $InstallDir))
            $process = Start-Process -FilePath $TempInstaller -ArgumentList $installArgs -Wait -PassThru -WindowStyle Hidden
            if ($process.ExitCode -notin @(0,3010)) {
                throw "Python installation failed (exit $($process.ExitCode)); check the installer result before retrying. Existing myenv has been preserved."
            }
            $BasePython = Join-Path $InstallDir 'python.exe'
            if (-not (Probe-Python $BasePython)) { throw 'The installed Python version does not match the package.' }
        }
        Say 'Creating myenv ...'
        Invoke-Python $BasePython @('-I', '-B', '-m', 'venv', $Venv)
        if (-not (Probe-Python $VenvPython)) { throw 'myenv version verification failed.' }
    }

    $verifyCode = @'
import importlib.metadata as m, pathlib, sys
bad=[]
for line in pathlib.Path(sys.argv[1]).read_text(encoding="utf-8-sig").splitlines():
    if not line.strip() or line.startswith("#"): continue
    name,version=line.split("==",1)
    try: actual=m.version(name)
    except m.PackageNotFoundError: actual="missing"
    if actual!=version: bad.append(f"{name}: {actual} -> {version}")
if bad: print("\n".join(bad))
sys.exit(bool(bad))
'@
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $missing = & $VenvPython -I -B -c (Encode-PythonCode $verifyCode) $Requirements 2>&1
        $needsInstall = $LASTEXITCODE -ne 0
    } finally { $ErrorActionPreference = $old }
    if ($needsInstall) {
        if ($CheckOnly) { throw "Missing or different dependency versions:`n$($missing -join "`n")" }
        Say 'Installing the locked dependency versions from PyPI ...'
        # Build source-only packages as wheels; avoid legacy setup.py record encoding on Chinese paths.
        Invoke-Python $VenvPython @('-I', '-B', '-m', 'pip', '--isolated', 'install', '--disable-pip-version-check',
                                   '--index-url', 'https://pypi.org/simple', '--cache-dir', $PackageCache,
                                   '--timeout', '60', '--retries', '3', "wheel==$($Config.bootstrap_wheel_version)")
        Invoke-Python $VenvPython @('-I', '-B', '-m', 'pip', '--isolated', 'install', '--disable-pip-version-check',
                                   '--index-url', 'https://pypi.org/simple', '--timeout', '60', '--retries', '3',
                                   '--cache-dir', $PackageCache, '-r', $Requirements)
    } else { Say 'All locked dependencies are already installed.' }
    Invoke-Python $VenvPython @('-I', '-B', '-c', $verifyCode, $Requirements)
    Invoke-Python $VenvPython @('-I', '-B', '-m', 'pip', '--isolated', 'check')
    $smoke = 'import sys; sys.path.insert(0,sys.argv[1]); import tkinter,pandas,openpyxl,matplotlib,duckdb,customtkinter; from userlib.tools import chunks_apart; print("Project imports PASS")'
    Invoke-Python $VenvPython @('-I', '-B', '-c', $smoke, $ProjectRoot)
    if (-not $CheckOnly) {
        [ordered]@{status='PASS'; python_version=$Config.python_version; interpreter=$VenvPython;
            dependency_lock_sha256=$Config.requirements_sha256;
            validated_at=(Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz')} |
            ConvertTo-Json | Set-Content -LiteralPath (Join-Path $LogDir 'latest.json') -Encoding UTF8
    }
    Say 'Environment ready. Use myenv\Scripts\python.exe for this project.'
} catch {
    Write-Host "SETUP FAILED: $($_.Exception.Message)" -ForegroundColor Red
    if (-not $CheckOnly -and $null -ne $Lock -and (Test-Path -LiteralPath $LogDir)) {
        Add-Content -LiteralPath $Log -Value $_.Exception.Message -Encoding UTF8
        [ordered]@{status='FAILED'; error=$_.Exception.Message; validated_at=(Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz')} |
            ConvertTo-Json | Set-Content -LiteralPath (Join-Path $LogDir 'latest.json') -Encoding UTF8
    }
    exit 1
} finally {
    if ($null -ne $Lock) { $Lock.Dispose() }
    $env:PYTHONDONTWRITEBYTECODE = $OldNoBytecode
    $env:PYTHONNOUSERSITE = $OldNoUserSite
    $env:PYTHONUTF8 = $OldPythonUtf8
    $env:PYTHONIOENCODING = $OldPythonIoEncoding
    if ($null -ne $TempInstaller -and (Test-Path -LiteralPath $TempInstaller)) {
        $resolved = (Get-Item -LiteralPath $TempInstaller).FullName
        if ($resolved.StartsWith(($LogDir + '\'), [StringComparison]::OrdinalIgnoreCase) -and
            -not ((Get-Item -LiteralPath $resolved).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            Remove-Item -LiteralPath $resolved -Force
        }
    }
}
