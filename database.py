import sqlite3
import logging
from config import DB_FILE

# The DB_FILE is now imported from the config module.

def initialize_db():
    """Creates the database and the positions table if they don't exist."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS positions (
        symbol TEXT PRIMARY KEY,
        in_position BOOLEAN NOT NULL,
        entry_price REAL NOT NULL,
        stop_loss_price REAL NOT NULL,
        take_profit_price REAL NOT NULL,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()
    logging.info("Database initialized.")

def save_position(symbol, in_position, entry_price, stop_loss_price, take_profit_price):
    """Saves or updates the state of a trading position."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO positions (symbol, in_position, entry_price, stop_loss_price, take_profit_price)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(symbol) DO UPDATE SET
        in_position=excluded.in_position,
        entry_price=excluded.entry_price,
        stop_loss_price=excluded.stop_loss_price,
        take_profit_price=excluded.take_profit_price,
        last_updated=CURRENT_TIMESTAMP
    """, (symbol, in_position, entry_price, stop_loss_price, take_profit_price))
    conn.commit()
    conn.close()

def load_position(symbol):
    """Loads the state for a given symbol."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM positions WHERE symbol = ?", (symbol,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None
