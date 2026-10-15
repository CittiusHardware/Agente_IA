$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$python = Join-Path $projectRoot ".venv-build\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    py -3.12 -m venv (Join-Path $projectRoot ".venv-build")
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "Não foi possível criar o ambiente .venv-build. Instale Python 3.12 e tente novamente."
}

& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Falha ao atualizar o pip." }
& $python -m pip install -e ".[interface]" pyinstaller pyinstaller-hooks-contrib
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependências do empacotamento." }
& $python -m PyInstaller --noconfirm --clean .\ComparadorPDF.spec
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar a pasta do aplicativo." }

Write-Host "Aplicativo gerado em: $projectRoot\dist\ComparadorPDF"
Write-Host "Execute ComparadorPDF.exe dentro dessa pasta para abrir a interface local."
