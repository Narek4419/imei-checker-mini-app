# test_bot.py
print("Test script started.")

try:
    import sqlite3
    print("sqlite3 imported successfully.")
except Exception as e:
    print(f"Error importing sqlite3: {e}")

try:
    from telegram import Update
    print("python-telegram-bot imported successfully.")
except Exception as e:
    print(f"Error importing python-telegram-bot: {e}")

print("Test script finished.")
