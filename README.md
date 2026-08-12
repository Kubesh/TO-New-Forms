# Treehouse Originals OLTP

Internal Streamlit app backed by a Neon Postgres database. No auth yet — local/dev use only.

## Requirements

Python 3.11+ (pinned via `.python-version`). The model layer uses modern
type-hint syntax (`str | None`) that requires 3.10+.

If you use `pyenv`:

```bash
pyenv install -s 3.11
```

On macOS without `pyenv`:

```bash
brew install python@3.11
```

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and set DATABASE_URL to your Neon connection string
```

If your existing `.venv` was created with an older Python, delete it and
recreate: `rm -rf .venv && python3.11 -m venv .venv`.

## Run migrations

```bash
alembic upgrade head
```

## Run the app

```bash
streamlit run app.py
```

## Project layout

```
app.py                     # entrypoint, sidebar navigation
src/db.py                  # engine/session setup (reads DATABASE_URL)
src/models.py               # SQLAlchemy models
src/services/                # query functions per domain
src/pages_app/               # Streamlit page functions per domain
migrations/                  # Alembic migrations
```

## Schema (Customers)

- `customer_types` — `customer_type_id`, `name`, `notes`, `created_at`, `updated_at`
- `customers` — `customer_id`, `customer_name`, `customer_type_id` (FK → customer_types), `parent_id` (self-FK → customers, for sub-accounts), billing/shipping address fields, `created_at`, `updated_at`
- `customer_contacts` — `contact_id`, `customer_id` (FK → customers), `contact_name`, `contact_phone`, `contact_notes`, `created_at`, `updated_at`

`updated_at` is maintained by a Postgres trigger (`set_updated_at()`), so it updates correctly regardless of which client writes the row.
