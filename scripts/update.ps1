# Install a new JobFinder build over an existing one, keeping her data.
#
#   powershell -ExecutionPolicy Bypass -File scripts\update.ps1 `
#       -NewExe C:\path\to\JobFinder.exe -InstallDir C:\Users\Her\JobFinder
#
# The work is in jobfinder.packaging.apply_update, which is where the tests are.
# This file only carries the two paths across.

param(
    [Parameter(Mandatory = $true)][string]$NewExe,
    [Parameter(Mandatory = $true)][string]$InstallDir
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

python -c @"
import sys
sys.path.insert(0, r'$repo\src')
from jobfinder.packaging import UpdateRefused, apply_update

try:
    target = apply_update(r'$NewExe', r'$InstallDir')
except UpdateRefused as refused:
    print(refused)
    raise SystemExit(1)
print(f'Updated: {target}')
print('Her data, CV and keys were not touched. The build it replaced is kept as')
print(f'{target}.previous, in case this one misbehaves.')
"@
