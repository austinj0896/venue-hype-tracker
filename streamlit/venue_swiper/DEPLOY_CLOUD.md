# Streamlit Community Cloud deploy checklist

## 1. GitHub (one time)

From CMD in the project root:

```bat
cd c:\Users\Austin\Documents\CursorProjects\venue_hype_tracker
git init
git add .
git commit -m "Venue hype tracker with Streamlit Cloud app"
```

Create an empty repo on GitHub (no README), then:

```bat
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git branch -M main
git push -u origin main
```

## 2. Streamlit Community Cloud

1. Open https://share.streamlit.io
2. **Create app**
3. Repository: your GitHub repo
4. Branch: `main`
5. **Main file path:** `streamlit/venue_swiper/streamlit_app.py`
6. **App URL (optional):** e.g. `vesper-manhattan-beach`

Advanced settings:

- **Python version:** 3.11
- **Requirements file:** `streamlit/venue_swiper/requirements.txt`

## 3. Secrets (App settings -> Secrets)

Paste (use your real Snowflake values):

```toml
[connections.snowflake]
account = "YOUR_ACCOUNT_IDENTIFIER"
user = "VENUE_SWIPER_SVC"
password = "YOUR_SERVICE_USER_PASSWORD"
role = "VENUE_SWIPER_APP"
warehouse = "VENUE_HYPE_WH"
database = "VENUE_HYPE"
schema = "APP"
```

Save. The app reboots automatically.

## 4. Share

Send friends the `https://YOUR-APP-NAME.streamlit.app` URL.
They enter an email inside the app — no Snowflake login.

## 5. Local test (optional)

```bat
copy streamlit\venue_swiper\.streamlit\secrets.toml.example streamlit\venue_swiper\.streamlit\secrets.toml
```

Edit `secrets.toml`, then:

```bat
scripts\run_venue_swiper_local.bat
```
