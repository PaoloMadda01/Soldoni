# Build dell'eseguibile Soldoni (onedir) con PyInstaller.
& "$PSScriptRoot\setup.cmd"
if ($LASTEXITCODE -ne 0) { Write-Error "setup fallito"; exit 1 }
& "$PSScriptRoot\.venv\Scripts\python.exe" -m PyInstaller --noconfirm soldoni_desktop.spec
if ($LASTEXITCODE -ne 0) { Write-Error "build fallita"; exit 1 }
Write-Host "Fatto. Eseguibile: dist/Soldoni/Soldoni.exe"
