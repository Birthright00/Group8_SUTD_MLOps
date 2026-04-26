"""
Local proxy server to bypass CORS issues with Modal cold starts.

This proxy:
1. Accepts requests from your frontend without CORS restrictions
2. Forwards them to Modal endpoints
3. Waits for Modal to cold start (no browser timeout)
4. Returns the response to your frontend

Usage:
    python proxy_server.py

The server automatically finds an available port and displays it on startup.
"""
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import sys

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

MODAL_ENDPOINTS = {
    'analyze': 'https://raintail0025--interior-design-complete-complete-pipeline.modal.run/',
    'chat': 'https://raintail0025--interior-design-complete-chat.modal.run/',
    'edit': 'https://raintail0025--interior-design-complete-edit-image.modal.run/',
}

@app.route('/api/analyze', methods=['POST', 'OPTIONS'])
def analyze():
    if request.method == 'OPTIONS':
        # Handle preflight request immediately
        return '', 200

    print("[PROXY] Received request from frontend")
    data = request.json

    print("[PROXY] Forwarding to Modal (this may take 10-20 minutes on cold start)...")
    print(f"[PROXY] generate_images={data.get('generate_images')}")

    try:
        # Forward to Modal with long timeout.
        # Must match the frontend fetch abort in frontend/src/utils/api.js and
        # Modal's @app.function(timeout=...) in modal_updated_complete.py.
        response = requests.post(
            MODAL_ENDPOINTS['analyze'],
            json=data,
            timeout=3600  # 60 minutes
        )

        print(f"[PROXY] Got response from Modal: {response.status_code}")

        response_data = response.json()

        # Debug: Log the structure
        if isinstance(response_data, dict):
            print(f"[PROXY] Response has keys: {list(response_data.keys())}")
            if 'edited_images' in response_data:
                edited_imgs = response_data['edited_images']
                print(f"[PROXY] edited_images type: {type(edited_imgs)}")
                if isinstance(edited_imgs, dict):
                    print(f"[PROXY] edited_images keys: {list(edited_imgs.keys())}")
                    for obj_name, obj_data in edited_imgs.items():
                        print(f"[PROXY]   {obj_name}: type={type(obj_data)}")
                        if isinstance(obj_data, dict):
                            print(f"[PROXY]     keys: {list(obj_data.keys())}")

        return jsonify(response_data), response.status_code

    except requests.exceptions.Timeout:
        print("[PROXY] ERROR: Timeout after 60 minutes")
        return jsonify({"error": "Request timeout after 60 minutes"}), 504

    except Exception as e:
        print(f"[PROXY] ERROR: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/chat', methods=['POST', 'OPTIONS'])
def chat():
    if request.method == 'OPTIONS':
        return '', 200

    data = request.json

    try:
        response = requests.post(
            MODAL_ENDPOINTS['chat'],
            json=data,
            timeout=300
        )
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def find_free_port(start=4000, end=4100):
    """Find an available port in the given range."""
    import socket
    for port in range(start, end):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('0.0.0.0', port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"No free port found in range {start}-{end}")

if __name__ == '__main__':
    import os
    port = find_free_port()

    # Write port to file so frontend can read it
    port_file = os.path.join(os.path.dirname(__file__), '.proxy-port')
    with open(port_file, 'w') as f:
        f.write(str(port))

    print("=" * 60)
    print("CORS Proxy Server Starting...")
    print("=" * 60)
    print(f"\nRunning on port: {port}")
    print("Port saved to .proxy-port for frontend auto-discovery")
    print("\nPress Ctrl+C to stop")
    print("=" * 60)

    # Check if Flask-CORS is installed
    try:
        import flask_cors
    except ImportError:
        print("\nWARNING: Flask-CORS not installed!")
        print("Install with: pip install flask flask-cors")
        sys.exit(1)

    app.run(host='0.0.0.0', port=port, debug=False)
