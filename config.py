import os
from pathlib import Path
import logging

# Get the data directory from an environment variable, defaulting to 'data'
# The Path object makes it easy to handle path operations robustly.
# The leading slash makes it an absolute path
DATA_DIR = Path(os.getenv('DATA_PATH', '/data'))

# Define full paths for the log file and database file
LOG_FILE = DATA_DIR / 'trading_bot.log'
DB_FILE = DATA_DIR / 'trading_state.db'

def setup_data_directory():
    """Creates the data directory if it doesn't exist."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        logging.info(f"Using data directory: {DATA_DIR.resolve()}")
    except Exception as e:
        logging.error(f"Could not create data directory {DATA_DIR.resolve()}: {e}")
        raise
