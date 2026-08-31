$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$pool = Join-Path $repoRoot "analytics\datasets\graph-relevance-v6-blind\query_candidate_pool.csv"
$blindDir = Join-Path $repoRoot "outputs\graph-relevance-v6-blind"
$packageDir = Join-Path $repoRoot "outputs\graph-rag-v6-researcher-package-20260830"
$builder = Join-Path $repoRoot "scripts\build_graph_relevance_annotation_workbook.mjs"
$guide = Join-Path $repoRoot "docs\product\Graph-RAG-v6-专业研究员独立盲标说明.md"

& $python -m analytics.pipelines.prepare_graph_relevance_v6_pool --output $pool
& $python -m analytics.pipelines.graph_relevance_v4 freeze `
    --source $pool `
    --output-dir $blindDir `
    --gold-version graph-relevance-v6-blind
& $python -m analytics.pipelines.graph_relevance_v4 lock-model --package-dir $blindDir

$env:GRAPH_RAG_VERSION = "v6"
$env:GRAPH_RAG_PACKAGE_DATE = "20260830"
$env:GRAPH_RAG_SOURCE_CSV = Join-Path $blindDir "researcher\annotation.csv"
$env:GRAPH_RAG_OUTPUT_DIR = $packageDir
$env:GRAPH_RAG_PREVIEW_DIR = Join-Path $repoRoot ".codex_tmp\v6_annotation_workbook\previews"
& node $builder

$inspectSidecar = Join-Path $packageDir "Graph-RAG-v6_专业研究员独立盲标工作簿.xlsx.inspect.ndjson"
if (Test-Path -LiteralPath $inspectSidecar) {
    Remove-Item -LiteralPath $inspectSidecar
}

Copy-Item -LiteralPath $guide -Destination (Join-Path $packageDir "00_专业研究员独立盲标说明.md")
Copy-Item -LiteralPath (Join-Path $blindDir "researcher\annotation.csv") `
    -Destination (Join-Path $packageDir "Graph-RAG-v6_专业研究员独立盲标原始表.csv")
Copy-Item -LiteralPath (Join-Path $blindDir "blind_manifest.json") -Destination $packageDir
Copy-Item -LiteralPath (Join-Path $blindDir "model_lock.json") -Destination $packageDir

$zipPath = "$packageDir.zip"
Compress-Archive -Path (Join-Path $packageDir "*") -DestinationPath $zipPath -Force
Write-Host "v6 blind package ready: $packageDir"
Write-Host "zip: $zipPath"
