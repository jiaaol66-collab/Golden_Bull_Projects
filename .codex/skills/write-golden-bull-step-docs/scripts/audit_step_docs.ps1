param(
    [Parameter(Mandatory=$true)][string]$WorkspaceRoot,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem

$root = (Resolve-Path -LiteralPath $WorkspaceRoot).Path
$docs = Get-ChildItem -LiteralPath $root -Recurse -Filter '*.docx' |
    Where-Object { $_.FullName -notlike '*\资料\*' }

$results = @()
$blocking = 0

foreach ($doc in $docs) {
    $issues = [System.Collections.Generic.List[string]]::new()
    $warnings = [System.Collections.Generic.List[string]]::new()
    $zip = $null
    try {
        $zip = [IO.Compression.ZipFile]::OpenRead($doc.FullName)
        $documentEntry = $zip.GetEntry('word/document.xml')
        $relsEntry = $zip.GetEntry('word/_rels/document.xml.rels')
        if (-not $documentEntry -or -not $relsEntry) {
            $issues.Add('缺少 document.xml 或 document.xml.rels')
            throw 'missing core OOXML'
        }

        $reader = [IO.StreamReader]::new($documentEntry.Open())
        $documentXml = $reader.ReadToEnd(); $reader.Dispose()
        $reader = [IO.StreamReader]::new($relsEntry.Open())
        $relsXml = $reader.ReadToEnd(); $reader.Dispose()
        [xml]$null = $documentXml
        [xml]$null = $relsXml

        $plain = [Net.WebUtility]::HtmlDecode(
            ($documentXml -replace '</w:p>', "`n" -replace '<[^>]+>', '')
        )
        $lines = $plain -split "`r?`n" | ForEach-Object { $_.Trim() } |
            Where-Object { $_ }

        if ($plain -match 'Briefly explanation|Guidelines|\{file\d|purpose\d') {
            $issues.Add('存在模板占位内容')
        }
        if ($plain -match '适用工作区|手把手') {
            $issues.Add('存在禁止措辞：适用工作区/手把手')
        }
        if ($plain -match '(?<![_\d])20\d{2}年') {
            $issues.Add('正文含具体年份示例，应改用 {YR}')
        }
        if ($plain -match '打开已处理|打开年度已处理|打开公共数据/20\d{2}') {
            $issues.Add('含仅用于打开年度目录的非必要链接文案')
        }

        $titleCount = [regex]::Matches($documentXml, '<w:pStyle w:val="Title"').Count
        if ($titleCount -ne 1) { $issues.Add("Title 段落数量为 $titleCount，应为1") }
        if ($documentXml -notmatch '<w:pStyle w:val="Title"[\s\S]{0,600}<w:b[ /]') {
            $issues.Add('主标题未明确加粗')
        }
        if ($documentXml -notmatch '<w:pStyle w:val="Heading1"[\s\S]{0,600}<w:b[ /]') {
            $issues.Add('一级标题未明确加粗')
        }

        $heading1Count = [regex]::Matches($documentXml, '<w:pStyle w:val="Heading1"').Count
        $heading2Count = [regex]::Matches($documentXml, '<w:pStyle w:val="Heading2"').Count
        if ($heading1Count -lt 2) {
            $warnings.Add("一级标题仅 $heading1Count 个，需确认步骤说明是否具备足够结构")
        }
        if ($plain.Length -gt 1200 -and $heading2Count -eq 0) {
            $warnings.Add('正文较长但没有二级标题，需确认层级是否便于操作人员扫描')
        }

        $operatorSections = @('步骤作用', '外部数据准备', '文件搜索顺序', '处理逻辑', '数据库输出', '文件输出', '运行方法', '常见问题', '运行前审核', '结果审核')
        $operatorSectionCount = 0
        foreach ($sectionName in $operatorSections) {
            if ($plain.Contains($sectionName)) { $operatorSectionCount++ }
        }
        if ($plain.Length -gt 900 -and $operatorSectionCount -lt 3) {
            $warnings.Add('长篇步骤说明缺少操作手册式章节；请确认目的、输入/搜索、处理、输出、运行与故障恢复是否易于定位')
        }

        if ($plain -match '000906' -and $plain -match '中证500' -and $plain -notmatch '中证800|不得|不能|请勿|不使用') {
            $warnings.Add('同时出现 000906 与中证500，但未明确二者不可替代；请核对指数口径')
        }

        $normalized = @{}
        foreach ($line in $lines) {
            $key = $line.ToLowerInvariant()
            $key = $key -replace '20\d{2}|\{yr\}', '<year>'
            $key = $key -replace '^\d+[.、）)]\s*', ''
            $key = $key -replace '[\s，。；：、“”‘’（）()【】\[\]/\\_-]', ''
            if ($key.Length -lt 12) { continue }
            if ($normalized.ContainsKey($key)) {
                $warnings.Add("疑似重复段落：$line")
            } else {
                foreach ($existingKey in @($normalized.Keys)) {
                    $shorter = [Math]::Min($key.Length, $existingKey.Length)
                    if ($shorter -ge 20 -and
                        ($key.Contains($existingKey) -or $existingKey.Contains($key))) {
                        $warnings.Add("疑似包含式重复：$line")
                        break
                    }
                }
                $normalized[$key] = $line
            }
        }

        $localLinks = [regex]::Matches($relsXml, 'Target="(file:///[^\"]+)"')
        if ($localLinks.Count -eq 0 -and $doc.Name -notmatch '总览') {
            $issues.Add('未发现对应代码的本地超链接')
        }
        foreach ($match in $localLinks) {
            $uriText = [Net.WebUtility]::HtmlDecode($match.Groups[1].Value)
            try {
                $localPath = [uri]::UnescapeDataString(([uri]$uriText).LocalPath)
                if (-not (Test-Path -LiteralPath $localPath)) {
                    $issues.Add("失效本地链接：$localPath")
                }
            } catch {
                $issues.Add("无法解析本地链接：$uriText")
            }
        }

        if ($plain.Length -lt 250) { $warnings.Add('正文较短，需人工确认是否覆盖输入、人工步骤、输出和故障处理') }
    } catch {
        if ($issues.Count -eq 0) { $issues.Add("DOCX读取失败：$($_.Exception.Message)") }
    } finally {
        if ($zip) { $zip.Dispose() }
    }

    $blocking += $issues.Count
    $results += [pscustomobject]@{
        document = $doc.FullName
        blocking_issues = @($issues)
        warnings = @($warnings)
        passed = ($issues.Count -eq 0)
    }
}

$summary = [pscustomobject]@{
    workspace = $root
    documents = $results.Count
    blocking_issue_count = $blocking
    passed = ($blocking -eq 0)
    results = $results
}

if ($Json) {
    $summary | ConvertTo-Json -Depth 6
} else {
    foreach ($result in $results) {
        $status = if ($result.passed) { 'PASS' } else { 'FAIL' }
        Write-Output "[$status] $($result.document)"
        foreach ($issue in $result.blocking_issues) { Write-Output "  ERROR: $issue" }
        foreach ($warning in $result.warnings) { Write-Output "  WARN:  $warning" }
    }
    Write-Output "Documents: $($results.Count); Blocking issues: $blocking"
}

if ($blocking -gt 0) { exit 1 }
