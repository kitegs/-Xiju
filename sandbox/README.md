# Python analysis sandbox

Build the image only when Docker Desktop is available:

```powershell
docker build -t aibi-python-sandbox:2026.08 .\sandbox
```

Then set these variables before starting the API:

```powershell
$env:AIBI_SANDBOX_ENABLED = "true"
$env:AIBI_SANDBOX_IMAGE = "aibi-python-sandbox:2026.08"
```

The API never falls back to executing generated Python on the host. Each run
receives only one copied dataset under `/data`, has no network, uses a read-only
root filesystem, drops capabilities, and is limited by CPU, memory, PIDs and time.
