import os
import psycopg
from psycopg.rows import dict_row

POSTGRES_URL = os.environ.get("POSTGRES_URL", "postgresql://localhost/sentinel")

def get_conn():
  return psycopg.connect(POSTGRES_URL, row_factory=dict_row, autocommit=True)