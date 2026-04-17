# Deployment

This project contains:

- a FastAPI backend in `app/`
- a static frontend in `static/`
- a Capacitor wrapper for Android and iOS

## Web Deployment

The simplest deployment path is to use the included [Dockerfile](/Users/zillurrahman/Desktop/Desktop/zillur/work/stock/myfirst_website/Dockerfile:1).

### What to deploy

- Expose the app with:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

- The frontend is served by FastAPI at:

```text
/static/index.html
```

### Required files

- [requirements.txt](/Users/zillurrahman/Desktop/Desktop/zillur/work/stock/myfirst_website/requirements.txt:1)
- [Dockerfile](/Users/zillurrahman/Desktop/Desktop/zillur/work/stock/myfirst_website/Dockerfile:1)
- [.dockerignore](/Users/zillurrahman/Desktop/Desktop/zillur/work/stock/myfirst_website/.dockerignore:1)
- [render.yaml](/Users/zillurrahman/Desktop/Desktop/zillur/work/stock/myfirst_website/render.yaml:1)
- [railway.json](/Users/zillurrahman/Desktop/Desktop/zillur/work/stock/myfirst_website/railway.json:1)

### Render

Based on Render's Docker deployment flow and FastAPI deployment guidance, this repo is ready to deploy as a Docker-based web service using the included `Dockerfile` and `render.yaml`.

Recommended flow:

1. Push this repo to GitHub.
2. Create a new Web Service on Render.
3. Connect the repo.
4. Render should detect the Docker setup, or you can explicitly choose Docker.
5. After deploy, visit `/static/index.html` on the Render URL.

### Railway

Based on Railway's Dockerfile and config-as-code docs, this repo is ready to deploy with the included `Dockerfile` and `railway.json`.

Recommended flow:

1. Push this repo to GitHub.
2. Create a new Railway service from the repo.
3. Railway should build from the root `Dockerfile`.
4. After deploy, visit `/static/index.html` on the Railway URL.

### Scheduler for actual prices

Run this command every weekday at 16:00 Oslo time:

```bash
python3 app/update_actual_prices.py
```

If your host only supports UTC schedules, convert Oslo time accordingly for daylight saving.

## Android and iOS

The project includes Capacitor config and a package manifest:

- [package.json](/Users/zillurrahman/Desktop/Desktop/zillur/work/stock/myfirst_website/package.json:1)
- [capacitor.config.json](/Users/zillurrahman/Desktop/Desktop/zillur/work/stock/myfirst_website/capacitor.config.json:1)
- [MOBILE_APP.md](/Users/zillurrahman/Desktop/Desktop/zillur/work/stock/myfirst_website/MOBILE_APP.md:1)

Native project folders have now been generated:

- `android/`
- `ios/`

Before building mobile apps, set the deployed backend URL in [static/config.js](/Users/zillurrahman/Desktop/Desktop/zillur/work/stock/myfirst_website/static/config.js:1).

## App Stores

Publishing requires your own:

- Apple Developer account for iOS
- Google Play Console account for Android

This workspace can prepare the project, but store submission itself must be done with your signing credentials and store accounts.
