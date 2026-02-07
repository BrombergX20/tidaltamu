# S3-backed History Searcher (local workspace)

This project contains a small frontend and a FastAPI backend that uploads files to an existing S3 bucket and lists them.

Setup

1. Set environment variables (Windows PowerShell example). Do NOT hardcode credentials in the repository — use Amplify Console environment variables or the AWS credentials chain:

```powershell
$env:BUCKET_NAME="tidaltamufiles"
# Use `S3_REGION` (or `REGION`) for Amplify, since env vars cannot start with `AWS`:
$env:S3_REGION="us-west-2"  # optional
# Credentials should be provided by the environment or IAM role; avoid setting long-term keys here in the repo.
```

2. Install dependencies (recommended to use a virtualenv):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. Run the backend:

```powershell
uvicorn api:app --reload
```

4. Hosting on AWS Amplify (recommended for static frontend):

- Deploy the static files (`index.html`, `upload.html`, `saved.html`, `script.js`, etc.) to an Amplify Hosting app.
- Deploy the backend API separately (Amplify supports Functions/Lambda or you can use App Runner/Elastic Beanstalk). If you deploy the API to a different origin, set a global `window.API_BASE` before loading `script.js` in your HTML or update `API_BASE` in `script.js` at build time.

Example (inline in HTML) before including `script.js`:

```html
<script>window.API_BASE = 'https://your-api-endpoint.example.com'</script>
<script src="script.js"></script>
```

In Amplify Console, add environment variables `BUCKET_NAME` and `S3_REGION` (or `REGION`) to the backend function or service and ensure the function's IAM role has S3 permissions (`s3:PutObject`, `s3:ListBucket`, `s3:GetObject`).

Notes

- Credentials are taken from the environment or the AWS credentials chain. Do not hardcode secrets.
- The backend returns presigned GET URLs valid for 1 hour.
- Deleting objects from S3 is intentionally not implemented in this demo; you can add a DELETE endpoint if needed.
