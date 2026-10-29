param([string]$Doc, [string]$Out, [string]$Pdf = "")
$w = New-Object -ComObject Word.Application
$w.Visible = $false
$items = @()
try {
  $d = $w.Documents.Open($Doc, $false, $true)
  $d.Repaginate()
  foreach ($p in $d.Paragraphs) {
    $sn = $p.Style.NameLocal
    if ($sn -eq "Heading 1" -or $sn -eq "Heading 2" -or $sn -eq "Figure Caption" -or $sn -eq "Table Caption") {
      $r = $p.Range
      $items += [pscustomobject]@{
        style = $sn
        text  = ($r.Text -replace "[\r\n\a]", "").Trim()
        page  = [int]$r.Information(1)
        sect  = [int]$r.Sections.First.Index
      }
    }
  }
  $total = $d.ComputeStatistics(2)
  if ($Pdf -ne "") { $d.ExportAsFixedFormat($Pdf, 17) }
  $d.Close($false)
} finally { $w.Quit() }
@{ total = $total; items = $items } | ConvertTo-Json -Depth 4 | Out-File -FilePath $Out -Encoding utf8
"pages=$total items=$($items.Count)"
