$ErrorActionPreference = "Stop"
$imageName = if ($env:IMAGE_NAME) { $env:IMAGE_NAME } else { "ksp-crime-intelligence-v8:1.0.0" }
$archiveName = if ($env:ARCHIVE_NAME) { $env:ARCHIVE_NAME } else { "ksp-crime-intelligence-v8-amd64.tar" }
docker build --platform linux/amd64 -t $imageName .
docker save -o $archiveName $imageName
Write-Host "Created Docker archive: $archiveName"
Write-Host "In Catalyst CLI choose AppSail -> Docker Image -> Docker Archive and select this TAR file."
