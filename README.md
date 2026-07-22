# InsightLedger

InsightLedger is a FastAPI and React workspace for ingesting financial reports, asking source-grounded questions, comparing verified company metrics, and generating financial visualizations.

## Run the project

Open two PowerShell terminals from the project root.

**Terminal 1 — API**

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn main:app --reload
```

Set `MISTRAL_API_KEY` in `.env` to use the report chatbot. The embedding model runs locally on CPU and is downloaded when the first report is indexed.

**Terminal 2 — React frontend**

```powershell
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The frontend calls the API at `http://127.0.0.1:8000` by default. To use a different API URL, copy `frontend/.env.example` to `frontend/.env` and update `VITE_API_BASE_URL`.

## Firebase Google login

1. In Firebase Console, open **Project settings** → **General** → **Your apps** and create or select a **Web app** for InsightLedger.
2. Copy the web app configuration values into `frontend/.env` using `frontend/.env.example` as the template.
3. In **Authentication** → **Settings** → **Authorized domains**, add your deployed frontend domain. `localhost` is already available for local development; add `127.0.0.1` if Firebase asks for it.
4. Keep Google enabled in **Authentication** → **Sign-in method**. The rail's login icon opens the Google account selector; after login, the icon changes to logout and shows the user avatar.

The Firebase client configuration is safe to use in the frontend, but never commit a `frontend/.env` file containing your project-specific values.

## Deploy

### Backend: Render

This repository includes `render.yaml` for a Render web service. Create a **Blueprint** from the GitHub repository and provide these values when prompted:

- `DATABASE_URL`: a PostgreSQL connection string. Use a managed PostgreSQL provider; SQLite cannot persist reliably on a free web service.
- `MISTRAL_API_KEY`: required for report-question answers.
- `CORS_ORIGINS`: your Vercel production URL, for example `https://insightledger.vercel.app`.

Render uses `uvicorn main:app --host 0.0.0.0 --port $PORT` and checks `/health`. The API URL will be `https://insightledger-api.onrender.com` (or the service name you choose). Render's free tier spins down after inactivity and has an ephemeral filesystem, so locally uploaded reports and Chroma vectors do not survive restarts. Use object storage and an external vector database before relying on uploads in production.

### Frontend: Vercel

Import the repository into Vercel and set the **Root Directory** to `frontend`. Vercel detects Vite; use `npm run build` and `dist` if it asks for build settings. Add these environment variables for Production (and Preview if desired):

- `VITE_API_BASE_URL`: the deployed Render URL, for example `https://insightledger-api.onrender.com`
- `VITE_FIREBASE_API_KEY`
- `VITE_FIREBASE_AUTH_DOMAIN`
- `VITE_FIREBASE_PROJECT_ID`
- `VITE_FIREBASE_STORAGE_BUCKET`
- `VITE_FIREBASE_MESSAGING_SENDER_ID`
- `VITE_FIREBASE_APP_ID`
- `VITE_FIREBASE_MEASUREMENT_ID` (optional)

After Vercel deploys, add its domain under Firebase Authentication's **Authorized domains**, then update Render's `CORS_ORIGINS` with that same URL and redeploy the API.

## API flow

1. `POST /documents/upload` uploads and indexes a PDF, TXT, or Markdown report.
2. `POST /ask` returns a grounded response with report citations.
3. `PUT /metrics` saves verified company metrics.
4. `GET /visualizations/types` lists available graph types: line, bar, grouped bar, histogram, pie chart, count plot, box plot, and heatmap. `POST /visualizations` returns a generated chart URL.
5. `POST /compare` compares saved financial metrics for two companies.

Open `http://127.0.0.1:8000/docs` for interactive API documentation.
