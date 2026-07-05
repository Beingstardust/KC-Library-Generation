Param(
  [Parameter(Mandatory=$false)]
  [string]$Config = "steps/step_02_pdf_ingest_blockstore/resources/step2.default.yaml",

  [Parameter(Mandatory=$false)]
  [string]$InputDir = "data/input/course_materials"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function ConvertTo-SafeDocId([string]$s) {
  $s = $s -replace "[^A-Za-z0-9_]", "_"
  $s = $s -replace "_{2,}", "_"
  $s = $s.Trim("_")
  if ([string]::IsNullOrWhiteSpace($s)) {
    return "DOC"
  }
  return $s
}

function Get-StringHashHex([string]$s) {
  $sha1 = [System.Security.Cryptography.SHA1]::Create()
  try {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($s)
    $hash = $sha1.ComputeHash($bytes)
    return ([System.BitConverter]::ToString($hash)).Replace("-", "")
  }
  finally {
    $sha1.Dispose()
  }
}

function Get-DocIdAssignments([System.IO.FileInfo[]]$Files) {
  $filesArray = @($Files | Sort-Object Name, FullName)
  $groups = @{}

  foreach ($f in $filesArray) {
    $stem = [System.IO.Path]::GetFileNameWithoutExtension($f.Name)
    $baseDocId = "DM2_" + (ConvertTo-SafeDocId $stem)
    if (-not $groups.ContainsKey($baseDocId)) {
      $groups[$baseDocId] = @()
    }
    $groups[$baseDocId] += $f
  }

  $docIdsByPath = @{}
  foreach ($baseDocId in ($groups.Keys | Sort-Object)) {
    $groupFiles = @($groups[$baseDocId] | Sort-Object Name, FullName)
    if ($groupFiles.Count -eq 1) {
      $docIdsByPath[$groupFiles[0].FullName] = $baseDocId
      continue
    }

    foreach ($f in $groupFiles) {
      $hashSuffix = (Get-StringHashHex $f.Name).Substring(0, 8)
      $docIdsByPath[$f.FullName] = "${baseDocId}_${hashSuffix}"
    }
  }

  return $docIdsByPath
}

$repoRoot = (Resolve-Path ".").Path
$env:MINERU_TOOLS_CONFIG_JSON = Join-Path $repoRoot "data\cache\mineru\mineru.json"
$env:MINERU_MODEL_SOURCE = "local"

$env:HF_HOME = Join-Path $repoRoot "data\cache\hf_home"
$env:HF_HUB_CACHE = Join-Path $repoRoot "data\cache\hf_home\hub"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"

$env:YOLO_CONFIG_DIR = Join-Path $repoRoot "data\cache\ultralytics"
$pdfDir = Join-Path $repoRoot $InputDir

if (!(Test-Path -LiteralPath $pdfDir)) {
  Write-Host "ERROR: Folder not found: $pdfDir"
  exit 1
}

$files = @(Get-ChildItem -LiteralPath $pdfDir -File | Where-Object { $_.Extension -ieq ".pdf" } | Sort-Object Name, FullName)
if ($files.Count -eq 0) {
  Write-Host "ERROR: No PDFs found in: $pdfDir"
  exit 1
}

$docIdsByPath = Get-DocIdAssignments -Files $files

Write-Host "Scanning PDFs from: $pdfDir"

foreach ($f in $files) {
  $pdfPath = $f.FullName
  $docId = $docIdsByPath[$f.FullName]

  Write-Host ""
  Write-Host "==============================="
  Write-Host "PDF   : $($f.Name)"
  Write-Host "doc_id: $docId"
  Write-Host "==============================="

  python steps/step_02_pdf_ingest_blockstore/scripts/run_step2.py `
    --config $Config `
    --pdf $pdfPath `
    --doc-id $docId

  if ($LASTEXITCODE -ne 0) {
    Write-Host "FAILED on $($f.Name). Stopping."
    exit $LASTEXITCODE
  }
}

Write-Host ""
Write-Host "All PDFs ingested successfully."
