# Libra — Library Book Management System

A Python + Flask library management project built around DSA concepts.

## Features
- 800-book catalogue
- Sign up / sign in / sign out
- Profile dashboard
- Borrow and return books
- Exact borrowed date and time
- Exact due date and time (14 days)
- ₹5 fine per started late day
- Maximum 3 active books per member
- Search, category filtering and pagination
- Merge Sort / Binary Search / Stack / Queue DSA modules
- Responsive interface and custom Libra logo
- SQLite storage
- Gunicorn + Render deployment configuration

## Run locally
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app.py
```
Open http://127.0.0.1:5000

## Deploy
Push the project to GitHub and create a Render Web Service using:
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`

Set a strong `SECRET_KEY` environment variable. The included `render.yaml` can also be used with Render Blueprint deployment.

### Data note
SQLite is ideal for a student project and demo. On hosts with ephemeral filesystems, SQLite data can be reset after a redeploy. For a production-grade multi-user deployment, move the database to PostgreSQL.
