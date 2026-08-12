# Treehouse Originals OLTP

Internal Streamlit app backed by a Neon Postgres database. No auth yet — local/dev use only.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and set DATABASE_URL to your Neon connection string
```

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
