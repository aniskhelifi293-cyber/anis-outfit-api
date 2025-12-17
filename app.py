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

# --- Configuration ---
PORT = int(os.environ.get('PORT', 5000))
BACKGROUND_FILENAME = "outfit.png"
IMAGE_TIMEOUT = 8
CANVAS_SIZE = (800, 800)
BACKGROUND_MODE = 'cover'  # 'cover' or 'contain'

app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=4)
session = requests.Session()

def fetch_player_info(uid: str):
    if not uid:
        return None
    player_info_url = f"https://birthdayspecialinfoapi.vercel.app/player-info?uid={uid}"
    try:
        resp = session.get(player_info_url, timeout=IMAGE_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        app.logger.error(f"Failed to fetch player info for UID {uid}: {e}")
        return None

def fetch_and_process_image(image_url: str, size: tuple = None):
    try:
        resp = session.get(image_url, timeout=IMAGE_TIMEOUT)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content)).convert("RGBA")
        if size:
            img = img.resize(size, Image.Resampling.LANCZOS)
        return img
    except Exception as e:
        app.logger.error(f"Failed to fetch/process image from {image_url}: {e}")
        return None

@app.route('/outfit-image', methods=['GET'])
def outfit_image():
    uid = request.args.get('uid')
    if not uid:
        return jsonify({'error': 'Missing uid parameter'}), 400

    player_data = fetch_player_info(uid)
    if player_data is None:
        return jsonify({'error': 'Failed to fetch player info. The UID might be invalid or the API is down.'}), 500

    outfit_ids = player_data.get("AccountProfileInfo", {}).get("EquippedOutfit", []) or []
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
                image_url = f'https://iconapi.wasmer.app/{oid}'
                img = fetch_and_process_image(image_url, size=(150, 150))
                if img:
                    return img  # Return the first found image
        
        # If no equipped item matches, use the fallback
        app.logger.warning(f"No item found for prefix '{config['prefix']}'. Using fallback '{config['fallback']}'.")
        image_url = f'https://iconapi.wasmer.app/{config["fallback"]}'
        return fetch_and_process_image(image_url, size=(150, 150))

    # Fetch all outfit images concurrently
    futures = [executor.submit(find_and_fetch_image, cfg) for cfg in outfit_config]

    # Load local background image
    bg_path = os.path.join(app.static_folder or '', BACKGROUND_FILENAME)
    try:
        background_image = Image.open(bg_path).convert("RGBA")
    except FileNotFoundError:
        app.logger.error(f"CRITICAL: Background image not found at {bg_path}")
        return jsonify({'error': 'Server configuration error: Background image not found.'}), 500
    except Exception as e:
        app.logger.error(f"Failed to open background image: {e}")
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=True)

# by Saurabh 💀
# Tg-@Phantom4ura
