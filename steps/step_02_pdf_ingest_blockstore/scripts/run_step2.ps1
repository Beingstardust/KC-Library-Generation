Param(
  [Parameter(Mandatory=$true)]
  [string]$PdfFile,

  [Parameter(Mandatory=$false)]
  [string]$DocId = "",

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

$repoRoot = (Resolve-Path ".").Path
$env:MINERU_TOOLS_CONFIG_JSON = Join-Path $repoRoot "data\cache\mineru\mineru.json"
$env:MINERU_MODEL_SOURCE = "local"

$env:HF_HOME = Join-Path $repoRoot "data\cache\hf_home"
$env:HF_HUB_CACHE = Join-Path $repoRoot "data\cache\hf_home\hub"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"

$env:YOLO_CONFIG_DIR = Join-Path $repoRoot "data\cache\ultralytics"
$inputDirPath = Join-Path $repoRoot $InputDir
$pdfPath = Join-Path $inputDirPath $PdfFile

if (!(Test-Path -LiteralPath $inputDirPath)) {
  Write-Host "ERROR: Folder not found: $inputDirPath"
  exit 1
}

if (!(Test-Path -LiteralPath $pdfPath)) {
  Write-Host "ERROR: PDF not found at: $pdfPath"
  Write-Host ""
  Write-Host "Available PDFs in ${InputDir}:"
  Get-ChildItem -LiteralPath $inputDirPath -File |
    Where-Object { $_.Extension -ieq ".pdf" } |
    Sort-Object Name |
    Select-Object -ExpandProperty Name
  exit 1
}

if ($DocId -eq "") {
  $stem = [System.IO.Path]::GetFileNameWithoutExtension($PdfFile)
  $DocId = "DM2_" + (ConvertTo-SafeDocId $stem)
}

$configPath = Join-Path $repoRoot $Config
if (!(Test-Path $configPath)) {
  Write-Host "ERROR: Config not found at: $configPath"
  exit 1
}

Write-Host "Running Step 2 ingest..."
Write-Host "  PDF   : $pdfPath"
Write-Host "  doc_id: $DocId"
Write-Host "  config: $configPath"

python steps/step_02_pdf_ingest_blockstore/scripts/run_step2.py `
  --config $Config `
  --pdf $pdfPath `
  --doc-id $DocId

if ($LASTEXITCODE -ne 0) {
  Write-Host "Step 2 failed with exit code $LASTEXITCODE"
  exit $LASTEXITCODE
}

Write-Host "Step 2 finished."

