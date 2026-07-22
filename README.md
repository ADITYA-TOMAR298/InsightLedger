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

## Deploy to one Vercel project

The root `vercel.json` builds the React app and deploys `app/app.py` as the FastAPI Function in the **same Vercel project**. The FastAPI Function serves the built frontend and handles same-origin `/api/*` requests, so do not set `VITE_API_BASE_URL` for this configuration.

1. Push this repository to GitHub, then import it in Vercel as one project. Leave **Root Directory** set to the repository root (`.`).
2. Vercel reads `vercel.json`; it runs `cd frontend && npm ci && npm run build`. The resulting `frontend/dist` files are bundled with the FastAPI Function, which serves the site and its `/api/*` endpoints. Do not override the build command in the Vercel dashboard.
3. Add these environment variables for Production (and Preview if desired):

- `VITE_FIREBASE_API_KEY`
- `VITE_FIREBASE_AUTH_DOMAIN`
- `VITE_FIREBASE_PROJECT_ID`
- `VITE_FIREBASE_STORAGE_BUCKET`
- `VITE_FIREBASE_MESSAGING_SENDER_ID`
- `VITE_FIREBASE_APP_ID`
- `VITE_FIREBASE_MEASUREMENT_ID` (optional)
- `MISTRAL_API_KEY` (required for report-question answers)
- `CORS_ORIGINS` (optional for the same-project setup; use this only when an external frontend URL must call the API)

4. Deploy, then open `https://your-project.vercel.app/api/health`. It should return `{"status":"ok"}`. Open the site root to use the React app.
5. Add the deployed Vercel domain (without `https://`) to Firebase Authentication's **Authorized domains**.

### Important Vercel limits

Vercel Functions have an ephemeral `/tmp` filesystem. Uploaded reports, SQLite data, and generated charts can disappear whenever a function instance is replaced; they are not production persistence. Store those in external services before relying on this app for real data. This Vercel-compatible build uses lightweight lexical report retrieval and SVG charts instead of a local ML embedding model, vector database, and plotting stack; Mistral still generates grounded answers.

## API flow

1. `POST /documents/upload` uploads and indexes a PDF, TXT, or Markdown report.
2. `POST /ask` returns a grounded response with report citations.
3. `PUT /metrics` saves verified company metrics.
4. `GET /visualizations/types` lists available graph types: line, bar, grouped bar, histogram, pie chart, count plot, box plot, and heatmap. `POST /visualizations` returns a generated chart URL.
5. `POST /compare` compares saved financial metrics for two companies.

Open `http://127.0.0.1:8000/docs` for interactive API documentation.
