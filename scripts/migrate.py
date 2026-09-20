"""Corre contra DATABASE_URL las migraciones de sql/migrations/ que falten.

Mismo patron que hwc-rotacion-turnos-dev: una tabla schema_migrations lleva
registro de que archivos ya se aplicaron, y cada archivo nuevo se aplica una
sola vez, en orden alfabetico (por eso el prefijo numerico en el nombre).

Uso:
    python scripts/migrate.py
"""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "sql" / "migrations"


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    conn = psycopg.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename    TEXT PRIMARY KEY,
                    applied_en  TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute("SELECT filename FROM schema_migrations")
            applied = {row[0] for row in cur.fetchall()}
        conn.commit()

        pendientes = [p for p in sorted(MIGRATIONS_DIR.glob("*.sql")) if p.name not in applied]
        if not pendientes:
            print("Sin migraciones pendientes.")
            return

        for path in pendientes:
            sql = path.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,))
            conn.commit()
            print(f"Aplicada: {path.name}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
