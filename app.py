from flask import Flask, request, jsonify, send_file, render_template, session as flask_session
from flask_cors import CORS
from werkzeug.utils import secure_filename
import os
import cv2
import numpy as np
from rembg import remove, new_session
from PIL import Image, ImageDraw, ImageFont
import qrcode
import uuid
import io
import logging
import traceback
import zipfile
from datetime import datetime

# 1. SETUP LOGGING
# In cPanel, logs are your best friend since you can't see the console easily.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
logging.basicConfig(
    filename=os.path.join(BASE_DIR, 'app_debug.log'),
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'super-secret-clear-men-key-123'
CORS(app)

# 2. CONFIGURATION
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
OUTPUT_FOLDER = os.path.join(BASE_DIR, 'outputs')
FRAMES_FOLDER = os.path.join(BASE_DIR, 'frames')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

# Ensure folders exist with correct permissions for web server
for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, FRAMES_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder, mode=0o755, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['FRAMES_FOLDER'] = FRAMES_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB limit

# Global variable for the rembg session (renamed to avoid conflict with Flask session)
rembg_session = None

def get_session():
    """Lazy-load the rembg session to prevent startup hangs"""
    global rembg_session
    if rembg_session is None:
        try:
            logger.info("Initializing Rembg session (u2netp)...")
            # Using 'u2netp' because it's significantly smaller (4MB vs 170MB)
            # and much faster to load/download on standard servers.
            rembg_session = new_session("u2netp")
            logger.info("Rembg session initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Rembg session: {e}")
    return rembg_session

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def remove_background(image_path):
    """Remove background from image with memory-safe optimizations"""
    logger.info(f"Removing background for: {image_path}")
    
    # Open image
    img = Image.open(image_path)
    
    # OPTIMIZATION: If the uploaded image is significantly larger than our target,
    # resize it down BEFORE background removal to save massive amounts of RAM.
    max_dim = 2000 
    if max(img.size) > max_dim:
        logger.info(f"Image too large ({img.size}), resizing to {max_dim}px for processing...")
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
    
    # Convert to bytes for rembg
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    input_data = img_byte_arr.getvalue()
    
    # Process
    output_data = remove(
        input_data,
        session=get_session(),
        alpha_matting=True,
        alpha_matting_foreground_threshold=240,
        alpha_matting_background_threshold=10,
        alpha_matting_erode_size=10
    )
    
    return Image.open(io.BytesIO(output_data)).convert("RGBA")

def fit_person_to_frame(person_image, frame_image):
    """Fit person to strict 1024x1536 frame while keeping aspect ratio intact and aligning to bottom"""
    target_width, target_height = 1024, 1536
    
    # 1. Prepare Frame (The Background)
    if frame_image.size != (target_width, target_height):
        frame_image = frame_image.resize((target_width, target_height), Image.Resampling.LANCZOS)
    result = frame_image.copy().convert("RGBA")
    
    # 2. Prepare Person (The Subject)
    # CROP transparent margins to remove any natural gaps from the original photo
    bbox = person_image.getbbox()
    if bbox:
        person_image = person_image.crop(bbox)
        
    person_width, person_height = person_image.size
    person_ratio = person_width / person_height
    target_ratio = target_width / target_height
    
    # Calculate scale to fit within frame (usually we want to fit width or height)
    # Reduced size to 85% of frame dimensions for better aesthetics
    scale_factor = 0.85
    
    if person_ratio > target_ratio:
        # Subject is wider than frame ratio
        new_width = int(target_width * scale_factor)
        new_height = int(new_width / person_ratio)
    else:
        # Subject is taller than frame ratio (standard case)
        new_height = int(target_height * scale_factor)
        new_width = int(new_height * person_ratio)
    
    person_resized = person_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    # 3. Overlay (Center horizontally, align to BOTTOM)
    x_offset = (target_width - new_width) // 2
    y_offset = target_height - new_height
    
    result.paste(person_resized, (x_offset, y_offset), person_resized)
    return result

def generate_qr_code(download_url):
    """Generate QR code for download URL"""
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(download_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").resize((150, 150))
    return qr_img.convert("RGBA")

@app.route('/process', methods=['POST'])
def process_image():
    input_path = None
    try:
        # 1. Validation
        if 'person_image' not in request.files:
            return jsonify({'error': 'No image file provided'}), 400
        
        person_file = request.files['person_image']
        if person_file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
        
        if not allowed_file(person_file.filename):
            return jsonify({'error': 'Invalid file type. Use JPG or PNG.'}), 400
            
        bg_choice = request.form.get('image_set_background', '1')
        
        # 2. Save Upload
        unique_id = str(uuid.uuid4())[:8]
        filename = secure_filename(f"{unique_id}_{person_file.filename}")
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        person_file.save(input_path)
        
        # 3. Background Removal
        person_no_bg = remove_background(input_path)
        
        # 4. Load Frame
        frame_path = os.path.join(app.config['FRAMES_FOLDER'], f'frame_{bg_choice}.png')
        if not os.path.exists(frame_path):
            # Fallback to frame 1 if not found
            frame_path = os.path.join(app.config['FRAMES_FOLDER'], 'frame_1.png')
            
        if not os.path.exists(frame_path):
            return jsonify({'error': 'Background frame not found on server'}), 404
            
        frame_image = Image.open(frame_path)
        
        # 5. Composite
        final_image = fit_person_to_frame(person_no_bg, frame_image)
        
        # 6. Add QR Code
        base_url = request.host_url.rstrip('/')
        output_filename = f"{unique_id}_output.png"
        qr_code = generate_qr_code(f"{base_url}/download/{output_filename}")
        
        # Position QR at bottom right
        img_w, img_h = final_image.size
        qr_w, qr_h = qr_code.size
        final_image.paste(qr_code, (img_w - qr_w - 20, img_h - qr_h - 20), qr_code)
        
        # 7. Final Conversion and Save
        # Ensure RGB format for standard PNG compatibility
        final_rgb = Image.new('RGB', final_image.size, (255, 255, 255))
        final_rgb.paste(final_image, mask=final_image.split()[3])
        
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
        final_rgb.save(output_path, 'PNG')
        
        return jsonify({
            'success': True,
            'output_file': output_filename,
            'download_url': f"{base_url}/download/{output_filename}"
        })
        
    except Exception as e:
        error_msg = traceback.format_exc()
        logger.error(f"Processing Error:\n{error_msg}")
        return jsonify({'error': str(e), 'details': 'Check app_debug.log on server'}), 500
    
    finally:
        # Cleanup upload to save space on cPanel
        # Commeted out as per user request to keep original images
        # if input_path and os.path.exists(input_path):
        #     os.remove(input_path)
        pass

@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    file_path = os.path.join(app.config['OUTPUT_FOLDER'], filename)
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    
    # Allow inline viewing for the admin panel
    as_attachment = request.args.get('inline') != 'true'
    return send_file(file_path, as_attachment=as_attachment)

@app.route('/view-upload/<filename>', methods=['GET'])
def view_upload(filename):
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    
    # Allow inline viewing for the admin panel
    as_attachment = request.args.get('inline') != 'true'
    return send_file(file_path, as_attachment=as_attachment)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'online', 'memory_info': 'Check cPanel dashboard'}), 200

# --- ADMIN PANEL ROUTES ---

@app.route('/admin')
def admin_page():
    return render_template('admin.html')

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    
    if email == "admin@clearmen.xri" and password == "ADMINclear":
        flask_session['admin_logged_in'] = True
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

@app.route('/api/admin/images', methods=['GET'])
def list_images():
    if not flask_session.get('admin_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
        
    try:
        outputs = []
        for filename in os.listdir(app.config['OUTPUT_FOLDER']):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                file_path = os.path.join(app.config['OUTPUT_FOLDER'], filename)
                outputs.append({
                    'filename': filename,
                    'url': f"/download/{filename}",
                    'timestamp': os.path.getmtime(file_path)
                })
        
        uploads = []
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                uploads.append({
                    'filename': filename,
                    'url': f"/view-upload/{filename}",
                    'timestamp': os.path.getmtime(file_path)
                })
        
        # Sort both by timestamp descending (newest first)
        outputs.sort(key=lambda x: x['timestamp'], reverse=True)
        uploads.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return jsonify({
            'outputs': outputs,
            'uploads': uploads
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    flask_session.pop('admin_logged_in', None)
    return jsonify({'success': True})

@app.route('/api/admin/delete-images', methods=['POST'])
def delete_images():
    if not flask_session.get('admin_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    filenames = data.get('filenames', [])
    category = data.get('category') # 'outputs' or 'uploads'
    
    if not filenames or category not in ['outputs', 'uploads']:
        return jsonify({'error': 'Invalid request'}), 400
        
    folder = app.config['OUTPUT_FOLDER'] if category == 'outputs' else app.config['UPLOAD_FOLDER']
    
    deleted_count = 0
    errors = []
    
    for filename in filenames:
        # Security check: ensure no directory traversal
        filename = os.path.basename(filename)
        file_path = os.path.join(folder, filename)
        
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                deleted_count += 1
        except Exception as e:
            errors.append(f"Failed to delete {filename}: {str(e)}")
            
    return jsonify({
        'success': True, 
        'deleted_count': deleted_count,
        'errors': errors
    })

@app.route('/api/admin/bulk-download', methods=['POST'])
def bulk_download():
    if not flask_session.get('admin_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
        
    data = request.json
    filenames = data.get('filenames', [])
    category = data.get('category')
    
    if not filenames or category not in ['outputs', 'uploads']:
        return jsonify({'error': 'Invalid request'}), 400
        
    folder = app.config['OUTPUT_FOLDER'] if category == 'outputs' else app.config['UPLOAD_FOLDER']
    
    # Create ZIP in memory
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w') as zf:
        for filename in filenames:
            filename = os.path.basename(filename)
            file_path = os.path.join(folder, filename)
            if os.path.exists(file_path):
                zf.write(file_path, filename)
                
    memory_file.seek(0)
    
    zip_filename = f"bulk_{category}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=zip_filename
    )

if __name__ == '__main__':
    app.run(debug=True, port=5000)