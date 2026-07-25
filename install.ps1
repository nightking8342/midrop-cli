#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) { Write-Error "python not found in PATH"; exit 1 }

# User PATH
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }
$parts = $userPath -split ";" | Where-Object { $_ }
if ($parts -notcontains $Root) {
  $newPath = if ($userPath.Trim().Length -eq 0) { $Root } else { "$userPath;$Root" }
  [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
  $env:Path = "$Root;$env:Path"
  Write-Host "Added to User PATH: $Root"
} else {
  Write-Host "Already on User PATH: $Root"
}

# Skill
$skillSrc = Join-Path $Root "skill"
$skillDst = Join-Path $env:USERPROFILE ".claude\skills\midrop-cli"
New-Item -ItemType Directory -Force -Path $skillDst | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $skillDst "references") | Out-Null
Copy-Item (Join-Path $skillSrc "SKILL.md") (Join-Path $skillDst "SKILL.md") -Force
Copy-Item (Join-Path $skillSrc "references\cli-contract.md") (Join-Path $skillDst "references\cli-contract.md") -Force
Write-Host "Skill installed: $skillDst"

Write-Host ""
Write-Host "Verify (new terminal if PATH just changed):"
Write-Host "  midrop doctor --format json"
Write-Host "  midrop config set default_device Fold"
