# by Saurabh 💀
# Tg-@Phantom4ura
# Public API - No key required - Optimized for Render.com
# FIXED: Logic for fetching outfit items

import os
from flask import Flask, request, jsonify, send_file
import requests
from PIL import Image
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
import logging
from functools import wraps
import time
import urllib3
import json

# --- Configuration ---
PORT = int(os.environ.get('PORT', 5000))
BACKGROUND_FILENAME = "outfit.png"
IMAGE_TIMEOUT = 15  # Increased timeout
API_TIMEOUT = 15    # Separate timeout for API calls
CANVAS_SIZE = (800, 800)
BACKGROUND_MODE = 'cover'  # 'cover' or 'contain'
API_BASE_URL = "https://ff-api-anis.onrender.com"
ICON_API_BASE_URL = "https://iconapi.wasmer.app"

# Disable SSL warnings (not recommended for production)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=4)
session = requests.Session()

# Configure session with retry strategy
retry_strategy = requests.adapters.Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = requests.adapters.HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)

# Rate limiting decorator
def rate_limit(max_calls=10, period=60):
    calls = []
    
    @wraps(rate_limit)
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            now = time.time()
            # Remove calls older than the period
            calls[:] = [call_time for call_time in calls if now - call_time < period]
            
            if len(calls) >= max_calls:
                return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429
                
            calls.append(now)
            return f(*args, **kwargs)
        return wrapper
    return decorator

def fetch_player_info(uid: str):
    if not uid:
        return None
    
    # Try multiple times with different approaches
    for attempt in range(3):
        try:
            player_info_url = f"{API_BASE_URL}/check?uid={uid}"
            
            # First attempt with standard timeout
            resp = session.get(player_info_url, timeout=API_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            
            # Log the structure of the response to understand it better
            logger.info(f"API response structure for UID {uid}: {list(data.keys()) if isinstance(data, dict) else type(data)}")
            
            # Try different possible paths to outfit data
            outfit_ids = []
            
            # Try the formatted response path
            if isinstance(data, dict):
                # Try the path: formatted_response.AccountProfileInfo.EquippedOutfit
                outfit_ids = data.get("formatted_response", {}).get("AccountProfileInfo", {}).get("EquippedOutfit", [])
                
                # If not found, try the raw API response path
                if not outfit_ids:
                    outfit_ids = data.get("raw_api_response", {}).get("profileInfo", {}).get("clothes", [])
                
                # If we found outfit IDs, add them to the response
                if outfit_ids:
                    logger.info(f"Found {len(outfit_ids)} outfit items: {outfit_ids}")
                    data["_extracted_outfits"] = outfit_ids
                else:
                    logger.warning(f"No outfit data found in API response for UID {uid}")
                    # Log a sample of the response for debugging
                    logger.debug(f"API response sample: {json.dumps(data, indent=2, default=str)[:500]}...")
            
            return data
            
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout on attempt {attempt + 1} for UID {uid}")
            if attempt == 2:  # Last attempt
                # Try with longer timeout and verify=False (not recommended for production)
                try:
                    resp = session.get(player_info_url, timeout=30, verify=False)
                    resp.raise_for_status()
                    return resp.json()
                except Exception as e:
                    logger.error(f"Final attempt failed for UID {uid}: {e}")
                    return None
                    
        except Exception as e:
            logger.error(f"Failed to fetch player info for UID {uid} on attempt {attempt + 1}: {e}")
            if attempt == 2:  # Last attempt
                return None
            
            # Wait before retrying
            time.sleep(2 ** attempt)  # Exponential backoff

def fetch_and_process_image(image_url: str, size: tuple = None):
    try:
        resp = session.get(image_url, timeout=IMAGE_TIMEOUT)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content)).convert("RGBA")
        if size:
            img = img.resize(size, Image.Resampling.LANCZOS)
        return img
    except Exception as e:
        logger.error(f"Failed to fetch/process image from {image_url}: {e}")
        return None

@app.route('/ping')
def ping():
    return jsonify({"status": "alive"}), 200
@app.route('/outfit-image', methods=['GET'])
@rate_limit(max_calls=10, period=60)
def outfit_image():
    uid = request.args.get('uid')
    if not uid:
        return jsonify({'error': 'Missing uid parameter'}), 400

    player_data = fetch_player_info(uid)
    if player_data is None:
        return jsonify({'error': 'Failed to fetch player info. The UID might be invalid or the API is down.'}), 500

    # Try to get outfit IDs from the extracted data or from the original paths
    outfit_ids = player_data.get("_extracted_outfits", [])
    
    if not outfit_ids:
        outfit_ids = player_data.get("formatted_response", {}).get("AccountProfileInfo", {}).get("EquippedOutfit", [])
    
    if not outfit_ids:
        outfit_ids = player_data.get("raw_api_response", {}).get("profileInfo", {}).get("clothes", [])
    
    # Convert to list if it's not already
    if not isinstance(outfit_ids, list):
        outfit_ids = [outfit_ids]
    
    # Filter out non-numeric values
    outfit_ids = [oid for oid in outfit_ids if isinstance(oid, (int, str)) and str(oid).isdigit()]
    
    if not outfit_ids:
        return jsonify({'error': 'Player has no equipped outfits.'}), 404

    # --- FIXED LOGIC ---
    # Each item now has a unique prefix to search for.
    # This prevents conflicts where the same ID prefix is used for multiple slots.
    outfit_config = [
        {'prefix': '211', 'fallback': '211000000'}, # Head
        {'prefix': '214', 'fallback': '214000000'}, # Faceprint
        {'prefix': '208', 'fallback': '208000000'}, # Mask (Corrected from 211)
        {'prefix': '203', 'fallback': '203000000'}, # Top
        {'prefix': '204', 'fallback': '204000000'}, # Bottom
        {'prefix': '205', 'fallback': '205000000'}, # Shoes
        {'prefix': '212', 'fallback': '212000000'}  # Emote (Corrected from 203)
    ]

    # Convert all outfit IDs to strings once for efficiency
    str_outfit_ids = [str(oid) for oid in outfit_ids]

    def find_and_fetch_image(config):
        """Find the first outfit ID matching the prefix and fetch its image."""
        for oid in str_outfit_ids:
            if oid.startswith(config['prefix']):
                image_url = f'{ICON_API_BASE_URL}/{oid}'
                img = fetch_and_process_image(image_url, size=(150, 150))
                if img:
                    return img  # Return the first found image
        
        # If no equipped item matches, use the fallback
        logger.warning(f"No item found for prefix '{config['prefix']}'. Using fallback '{config['fallback']}'.")
        image_url = f'{ICON_API_BASE_URL}/{config["fallback"]}'
        return fetch_and_process_image(image_url, size=(150, 150))

    # Fetch all outfit images concurrently
    futures = [executor.submit(find_and_fetch_image, cfg) for cfg in outfit_config]

    # Load local background image
    bg_path = os.path.join(app.static_folder or '', BACKGROUND_FILENAME)
    try:
        background_image = Image.open(bg_path).convert("RGBA")
    except FileNotFoundError:
        logger.error(f"CRITICAL: Background image not found at {bg_path}")
        return jsonify({'error': 'Server configuration error: Background image not found.'}), 500
    except Exception as e:
        logger.error(f"Failed to open background image: {e}")
        return jsonify({'error': 'Failed to process background image.'}), 500

    bg_w, bg_h = background_image.size

    # Determine canvas size & scale mode
    if CANVAS_SIZE is None:
        canvas_w, canvas_h = bg_w, bg_h
        scale_x = scale_y = 1.0
        new_w, new_h = bg_w, bg_h
        background_resized = background_image
        offset_x, offset_y = 0, 0
    else:
        canvas_w, canvas_h = CANVAS_SIZE
        if BACKGROUND_MODE == 'contain':
            scale = min(canvas_w / bg_w, canvas_h / bg_h)
        else:  # 'cover'
            scale = max(canvas_w / bg_w, canvas_h / bg_h)
        new_w = max(1, int(bg_w * scale))
        new_h = max(1, int(bg_h * scale))
        background_resized = background_image.resize((new_w, new_h), Image.Resampling.LANCZOS)

        offset_x = (canvas_w - new_w) // 2
        offset_y = (canvas_h - new_h) // 2
        scale_x = new_w / bg_w
        scale_y = new_h / bg_h

    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 255))
    canvas.paste(background_resized, (offset_x, offset_y), background_resized)

    # Positions correspond to the order in outfit_config
    positions = [
        {'x': 350, 'y': 30, 'height': 150, 'width': 150},   # Head
        {'x': 575, 'y': 130, 'height': 150, 'width': 150},  # Faceprint
        {'x': 665, 'y': 350, 'height': 150, 'width': 150},  # Mask
        {'x': 575, 'y': 550, 'height': 150, 'width': 150},  # Top
        {'x': 350, 'y': 654, 'height': 150, 'width': 150},  # Bottom
        {'x': 135, 'y': 570, 'height': 150, 'width': 150},  # Shoes
        {'x': 135, 'y': 130, 'height': 150, 'width': 150}   # Emote
    ]

    for idx, future in enumerate(futures):
        outfit_img = future.result()
        if not outfit_img:
            continue
        pos = positions[idx]
        paste_x = offset_x + int(pos['x'] * scale_x)
        paste_y = offset_y + int(pos['y'] * scale_y)
        paste_w = max(1, int(pos['width'] * scale_x))
        paste_h = max(1, int(pos['height'] * scale_y))

        resized = outfit_img.resize((paste_w, paste_h), Image.Resampling.LANCZOS)
        canvas.paste(resized, (paste_x, paste_y), resized)

    output = BytesIO()
    canvas.save(output, format='PNG')
    output.seek(0)
    return send_file(output, mimetype='image/png')

# Health check endpoint for Render
@app.route('/healthz', methods=['GET'])
def health_check():
    return "OK", 200

# Add a new endpoint to get player info directly
@app.route('/player-info', methods=['GET'])
@rate_limit(max_calls=10, period=60)
def player_info():
    uid = request.args.get('uid')
    if not uid:
        return jsonify({'error': 'Missing uid parameter'}), 400

    player_data = fetch_player_info(uid)
    if player_data is None:
        return jsonify({'error': 'Failed to fetch player info. The UID might be invalid or the API is down.'}), 500
    
    return jsonify(player_data)

# Add a debug endpoint to see the raw API response
@app.route('/debug-info', methods=['GET'])
def debug_info():
    uid = request.args.get('uid')
    if not uid:
        return jsonify({'error': 'Missing uid parameter'}), 400

    player_data = fetch_player_info(uid)
    if player_data is None:
        return jsonify({'error': 'Failed to fetch player info. The UID might be invalid or the API is down.'}), 500
    
    # Return the full response for debugging
    return jsonify({
        'uid': uid,
        'response_structure': list(player_data.keys()) if isinstance(player_data, dict) else type(player_data),
        'extracted_outfits': player_data.get("_extracted_outfits", []),
        'formatted_outfits': player_data.get("formatted_response", {}).get("AccountProfileInfo", {}).get("EquippedOutfit", []),
        'raw_outfits': player_data.get("raw_api_response", {}).get("profileInfo", {}).get("clothes", []),
        'full_response': player_data
    })

# Add a root endpoint with API documentation
@app.route('/', methods=['GET'])
def api_documentation():
    return jsonify({
        'name': 'Free Fire Outfit API',
        'version': '1.0',
        'endpoints': {
            '/outfit-image': {
                'method': 'GET',
                'params': {'uid': 'Player UID (required)'},
                'description': 'Returns an image with the player\'s equipped outfit items'
            },
            '/player-info': {
                'method': 'GET',
                'params': {'uid': 'Player UID (required)'},
                'description': 'Returns player information including equipped outfits'
            },
            '/debug-info': {
                'method': 'GET',
                'params': {'uid': 'Player UID (required)'},
                'description': 'Returns debug information about the API response structure'
            },
            '/healthz': {
                'method': 'GET',
                'params': {},
                'description': 'Health check endpoint for monitoring'
            }
        }
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=False)

# by Saurabh 💀
# Tg-@Phantom4ura
