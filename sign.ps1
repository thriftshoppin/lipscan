# Signs a PRIVATE (unlisted) copy of the LipScan add-on with your addons.mozilla.org API key, for your own use.
# It never appears on addons.mozilla.org. RUN THIS YOURSELF: the key and secret are read into memory only and are never
# written to disk or shown to Claude. Get them at https://addons.mozilla.org/developers/addon/api/key/
# Every signing needs a new version number in capture\extension\manifest.json.
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
function Step($name, [scriptblock]$b) {
  Write-Host "== $name" -ForegroundColor Cyan
  & $b
  if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { Write-Host "FAIL: $name" -ForegroundColor Red; exit 1 }
  Write-Host "PASS: $name" -ForegroundColor Green
}
if (-not $env:WEB_EXT_API_KEY)    { $env:WEB_EXT_API_KEY = Read-Host 'JWT issuer (user:...)' }
if (-not $env:WEB_EXT_API_SECRET) {
  $s = Read-Host 'JWT secret' -AsSecureString
  $env:WEB_EXT_API_SECRET = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
}
$version = (Get-Content "$root\capture\extension\manifest.json" -Raw | ConvertFrom-Json).version
$out = Join-Path $root 'dist'
try {
  Step 'web-ext lint' { web-ext lint --source-dir "$root\capture\extension" }
  Step "sign $version (unlisted, private)" {
    web-ext sign --source-dir "$root\capture\extension" --artifacts-dir $out --channel=unlisted --approval-timeout 2700000
  }
  $xpi = Get-ChildItem $out -Filter *.xpi | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $xpi) { Write-Host 'FAIL: no .xpi produced (it may still be waiting for Mozilla; run this again later).' -ForegroundColor Red; exit 1 }
  $named = Join-Path $out "lipscan-$version.xpi"
  Copy-Item $xpi.FullName $named -Force
  Write-Host "Signed: $named" -ForegroundColor Green
  Write-Host 'To install: drag that file onto a Firefox window and click Add. Then copy the connection code from its toolbar popup into Claude Code.'
} finally {
  Remove-Item Env:WEB_EXT_API_SECRET, Env:WEB_EXT_API_KEY -ErrorAction SilentlyContinue
}
