param(
    [Parameter(Mandatory = $true)][string]$InputDocx,
    [Parameter(Mandatory = $true)][string]$OutputPdf
)

$ErrorActionPreference = 'Stop'

$inputPath = (Resolve-Path -LiteralPath $InputDocx).Path
$outputDirectory = Split-Path -Parent $OutputPdf
if (-not (Test-Path -LiteralPath $outputDirectory)) {
    New-Item -ItemType Directory -Path $outputDirectory | Out-Null
}
$outputPath = [System.IO.Path]::GetFullPath($OutputPdf)
$word = $null
$document = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $document = $word.Documents.Open($inputPath, $false, $true)
    $document.ExportAsFixedFormat($outputPath, 17)
}
finally {
    if ($document) { $document.Close($false) }
    if ($word) { $word.Quit() }
}
