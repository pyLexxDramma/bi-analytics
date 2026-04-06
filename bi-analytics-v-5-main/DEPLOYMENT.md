# Deployment Guide

## Why Vercel Doesn't Work

Vercel is designed for static sites and serverless functions, not for long-running Python applications like Streamlit. Streamlit requires a persistent Python server, which doesn't fit Vercel's deployment model.

## Recommended: Streamlit Cloud (Free & Easy)

Streamlit Cloud is the easiest and most appropriate option for deploying Streamlit applications.

### Steps to Deploy on Streamlit Cloud:

1. **Push your code to GitHub** (if not already done):
   ```bash
   git push origin master
   ```

2. **Sign up for Streamlit Cloud**:
   - Go to https://share.streamlit.io/
   - Sign in with your GitHub account

3. **Deploy your app**:
   - Click "New app"
   - Select your repository: `mk-im/bi-analytics`
   - Select branch: `master`
   - Main file path: `project_visualization_app.py`
   - Click "Deploy!"

4. **Your app will be live** at: `https://your-app-name.streamlit.app`

## Alternative Deployment Options

### 1. Render (Free Tier Available)
- Go to https://render.com
- Create a new Web Service
- Connect your GitHub repository
- Build command: `pip install -r requirements.txt`
- Start command: `streamlit run project_visualization_app.py --server.port $PORT --server.address 0.0.0.0`

### 2. Railway (Free Trial)
- Go to https://railway.app
- Create a new project from GitHub
- Add a Python service
- Railway will auto-detect and deploy

### 3. Heroku (Paid, but has free alternatives)
- Requires a `Procfile` with: `web: streamlit run project_visualization_app.py --server.port=$PORT --server.address=0.0.0.0`
- Requires `setup.sh` for Streamlit configuration

### 4. DigitalOcean App Platform
- Similar to Render, supports Python apps
- Paid service with free trial

## Files Created for Deployment

- `requirements.txt` - Python dependencies (required for all platforms)
- `.streamlit/config.toml` - Streamlit configuration for headless deployment

## Secrets and first admin

- **No keys or passwords are stored in the repository.** Set them in the deployment environment.
- To create the initial superadmin on first run, set environment variables:
  - `DEFAULT_ADMIN_USERNAME` — login for the first admin
  - `DEFAULT_ADMIN_PASSWORD` — password (set only in env / secrets, never in code)
- Copy `.env.example` to `.env` for local runs; for Streamlit Cloud / Render / Railway, use the platform's "Secrets" or "Environment variables" UI.

## Notes

- All platforms require your code to be in a Git repository (GitHub, GitLab, or Bitbucket)
- Make sure `requirements.txt` is in the root of your repository
- The main Streamlit file should be clearly named (e.g., `project_visualization_app.py`)















