from __future__ import annotations
import os

DB_HOST = os.getenv("DB_HOST", "mysql-test")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", os.getenv("MYSQL_DATABASE", "recipe_ai"))
DB_USER = os.getenv("DB_USER", os.getenv("MYSQL_USER", "recipe_app"))
DB_PASSWORD = os.getenv("DB_PASSWORD", os.getenv("MYSQL_PASSWORD", ""))
