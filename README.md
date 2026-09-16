# Wolt Image Tool

Upload an Excel file (column A = image links, column B = SKUs) and get back a ZIP of
renamed, resized product images. No terminal or Python required from the person using it.

Ports the logic from the team's `ImgDownloader.py` / `resizer.py` scripts (concurrent
download with retries, solid-background stripping, proportional scale-and-pad onto a
fixed canvas) into a small FastAPI + vanilla-JS web app.

## Run it locally

```bash
cd "WebApp - Wolt Images"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Then open http://localhost:8000

## How it works

1. **Upload**: drag in an `.xlsx`/`.xls` file. The first two columns are read
   positionally (image URL, then SKU) regardless of their header text.
2. **Configure**: choose whether to prefix filenames, and the output size
   (default 2880 × 1620, or a custom width/height).
3. **Process**: the server downloads and resizes images concurrently (20 workers),
   shows live progress, and offers a ZIP download when done. Rows that fail
   (bad link, broken image, etc.) are reported individually without failing the whole batch.

Job files live under `.jobs/` (gitignored) and are cleaned up automatically after 2 hours.

## Deployment

This is built to run anywhere Python 3.9+ runs, with no build step. For the team-wide
rollout this will be deployed on **Zerobox** (DoorDash's internal app platform) rather
than an external host like Firebase/Supabase, per company policy for internal tools.
