# sickw_api.py
import requests
import json
from config import SICKW_API_KEY, SICKW_API_URL
import logging

logger = logging.getLogger(__name__)

def get_sickw_services():
    params = {
        'action': 'services',
        'key': SICKW_API_KEY,
        'format': 'json' # Request JSON format for consistency
    }
    try:
        response = requests.get(SICKW_API_URL, params=params, timeout=30)
        response.raise_for_status() # Raise an exception for HTTP errors
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching SICKW services: {e}")
        return None

def check_imei_sickw(imei, service_id):
    params = {
        'format': 'BETA', # Request BETA format for more structured JSON
        'key': SICKW_API_KEY,
        'imei': imei,
        'service': service_id
    }
    try:
        response = requests.get(SICKW_API_URL, params=params, timeout=60)
        response.raise_for_status() # Raise an exception for HTTP errors (e.g., 4xx, 5xx)

        # --- ADD THESE DEBUG LINES ---
        logger.info(f"SICKW API Raw Response Status Code: {response.status_code}")
        logger.info(f"SICKW API Raw Response Content: {response.text}")
        # --- END DEBUG LINES ---

        data = response.json()
        return data
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error during IMEI check with SICKW: {e}")
        return {"status": "error", "result": f"Network error: {e}"}
    except json.JSONDecodeError as e:
        # This specific error indicates non-JSON response when .json() is called
        logger.error(f"JSON decoding error for IMEI {imei} from SICKW API: {e}")
        logger.error(f"Raw response that caused error: {response.text if 'response' in locals() else 'No response object'}")
        return {"status": "error", "result": "API returned invalid or empty data. Please check SICKW account status or try again."}
    except Exception as e:
        logger.error(f"An unexpected error occurred during SICKW API call: {e}")
        return {"status": "error", "result": f"An unexpected error occurred: {e}"}


def get_balance_sickw():
    params = {
        'action': 'balance',
        'key': SICKW_API_KEY
    }
    try:
        response = requests.get(SICKW_API_URL, params=params, timeout=10)
        response.raise_for_status()
        return float(response.text) # Balance is returned as plain text
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching SICKW balance: {e}")
        return None
    except ValueError:
        logger.error(f"Error converting SICKW balance to float. Response: {response.text}")
        return None