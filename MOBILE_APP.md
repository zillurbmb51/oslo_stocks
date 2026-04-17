# Mobile App Setup

This project now includes a Capacitor scaffold so the existing web UI can be packaged for Android and iOS.

## Important

The app frontend is static, but the data API is served by the Python backend.  
For mobile builds, set the backend base URL in [static/config.js](/Users/zillurrahman/Desktop/Desktop/zillur/work/stock/myfirst_website/static/config.js:1).

Example:

```js
window.APP_API_BASE = "https://your-deployed-api.example.com";
```

## Setup

1. Install Node.js with `npm` available.
2. In the project root, run:

```bash
npm install
```

3. Add the native projects:

```bash
npx cap add android
npx cap add ios
```

4. Sync web assets:

```bash
npx cap sync
```

5. Open the native projects:

```bash
npx cap open android
npx cap open ios
```

## Notes

- `webDir` is set to `static`, so the current UI is packaged directly.
- The web app still works in the browser with same-origin API calls when `APP_API_BASE` is left empty.
- This workspace does not currently have `npm`, so the native projects were scaffolded conceptually but not installed or generated here.
