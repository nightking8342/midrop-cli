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

# Skill — link rather than copy, so editing skill/ in the repo takes effect at
# once. A stale copy is worse than no skill: it kept telling agents to pass
# --mode rpa long after that mode was deleted.
# Symlink needs admin/developer mode; junction does not, and reads identically.
$skillSrc = Join-Path $Root "skill"
$skillDst = Join-Path $env:USERPROFILE ".claude\skills\midrop-cli"

$existing = Get-Item $skillDst -Force -ErrorAction SilentlyContinue
if ($existing) {
  if ($existing.LinkType) {
    if ($existing.Target -contains $skillSrc) {
      Write-Host "Skill already linked: $skillDst -> $skillSrc"
      $skillDone = $true
    } else {
      (Get-Item $skillDst -Force).Delete()
    }
  } else {
    # Plain directory from an older install — keep it aside, don't silently drop it
    $bak = "$skillDst.bak-copy"
    if (Test-Path $bak) { Remove-Item $bak -Recurse -Force }
    Move-Item $skillDst $bak
    Write-Host "Previous skill copy moved to: $bak"
  }
}

if (-not $skillDone) {
  try {
    New-Item -ItemType SymbolicLink -Path $skillDst -Target $skillSrc -ErrorAction Stop | Out-Null
    Write-Host "Skill linked (symlink): $skillDst -> $skillSrc"
  } catch {
    New-Item -ItemType Junction -Path $skillDst -Target $skillSrc | Out-Null
    Write-Host "Skill linked (junction): $skillDst -> $skillSrc"
  }
}

Write-Host ""
Write-Host "Verify (new terminal if PATH just changed):"
Write-Host "  midrop doctor --format json"
Write-Host "  midrop config set default_device Fold"
