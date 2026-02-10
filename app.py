from flask import Flask, request, jsonify, send_file
from werkzeug.utils import secure_filename
import os
import cv2
import numpy as np
from rembg import remove
from PIL import Image, ImageDraw, ImageFont
import qrcode
import uuid
import io

app = Flask(__name__)

# Configuration
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
FRAMES_FOLDER = 'frames'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

# Create necessary directories
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['FRAMES_FOLDER'] = FRAMES_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def remove_background(image_path):
    """Remove background from image using rembg with improved accuracy"""
    with open(image_path, 'rb') as input_file:
        input_image = input_file.read()
    
    # Using alpha_matting for more accurate edges
    output_image = remove(
        input_image,
        alpha_matting=True,
        alpha_matting_foreground_threshold=240,
        alpha_matting_background_threshold=10,
        alpha_matting_erode_size=10
    )
    return Image.open(io.BytesIO(output_image)).convert("RGBA")


def fit_person_to_frame(person_image, frame_image):
    """Fit person image to frame (1536x1024) while maintaining strict aspect ratio"""
    target_width, target_height = 1536, 1024
    
    # Ensure frame is the correct size
    if frame_image.size != (target_width, target_height):
        frame_image = frame_image.resize((target_width, target_height), Image.Resampling.LANCZOS)
    
    # Calculate aspect ratios
    person_width, person_height = person_image.size
    person_ratio = person_width / person_height
    target_ratio = target_width / target_height
    
    # Resize person to fit within target frame while maintaining aspect ratio
    if person_ratio > target_ratio:
        # Person is wider - scale by width
        new_width = target_width
        new_height = int(target_width / person_ratio)
    else:
        # Person is taller - scale by height
        new_height = target_height
        new_width = int(target_height * person_ratio)
    
    person_resized = person_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    # Create the result by starting with the frame as the base background
    result = frame_image.copy().convert("RGBA")
    
    # Center the person on the frame
    x_offset = (target_width - new_width) // 2
    y_offset = (target_height - new_height) // 2
    
    # Paste person image on top of the frame at center
    result.paste(person_resized, (x_offset, y_offset), person_resized)
    
    return result


def generate_qr_code(download_url, size=150):
    """Generate QR code for download URL"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
    )
    qr.add_data(download_url)
    qr.make(fit=True)
    
    qr_image = qr.make_image(fill_color="black", back_color="white")
    qr_image = qr_image.resize((size, size), Image.Resampling.LANCZOS)
    return qr_image.convert("RGBA")


def add_qr_to_image(image, qr_code, margin=20):
    """Add QR code to bottom right of image"""
    img_width, img_height = image.size
    qr_width, qr_height = qr_code.size
    
    # Calculate bottom right position
    x = img_width - qr_width - margin
    y = img_height - qr_height - margin
    
    # Paste QR code
    image.paste(qr_code, (x, y), qr_code)
    return image


@app.route('/process', methods=['POST'])
def process_image():
    try:
        # Validate request
        if 'person_image' not in request.files:
            return jsonify({'error': 'No image file provided'}), 400
        
        name = request.form.get('name', 'User')
        number = request.form.get('number', '')
        image_set_background = request.form.get('image_set_background', '1')
        
        person_file = request.files['person_image']
        
        if person_file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
        
        if not allowed_file(person_file.filename):
            return jsonify({'error': 'Invalid file type'}), 400
        
        # Save uploaded file
        filename = secure_filename(person_file.filename)
        unique_id = str(uuid.uuid4())[:8]
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{unique_id}_{filename}")
        person_file.save(input_path)
        
        # Remove background from user image
        person_no_bg = remove_background(input_path)
        
        # Load frame
        frame_number = int(image_set_background)
        if frame_number < 1 or frame_number > 6:
            frame_number = 1
        
        frame_path = os.path.join(app.config['FRAMES_FOLDER'], f'frame_{frame_number}.png')
        
        if not os.path.exists(frame_path):
            return jsonify({'error': f'Frame {frame_number} not found'}), 404
        
        frame_image = Image.open(frame_path).convert("RGBA")
        
        # Fit person to frame and overlay frame on top
        result_image = fit_person_to_frame(person_no_bg, frame_image)
        
        # Generate output filename
        output_filename = f"{unique_id}_output.png"
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
        
        # Generate QR code with download URL
        download_url = f"http://localhost:5000/download/{output_filename}"
        qr_code = generate_qr_code(download_url)
        
        # Add QR code to bottom right
        final_image = add_qr_to_image(result_image, qr_code)
        
        # Convert to RGB for PNG saving (remove alpha channel for final output)
        final_image_rgb = Image.new('RGB', final_image.size, (255, 255, 255))
        final_image_rgb.paste(final_image, mask=final_image.split()[3] if len(final_image.split()) == 4 else None)
        
        # Save final image
        final_image_rgb.save(output_path, 'PNG')
        
        # Clean up uploaded file
        os.remove(input_path)
        
        return jsonify({
            'success': True,
            'message': 'Image processed successfully',
            'name': name,
            'number': number,
            'output_file': output_filename,
            'download_url': download_url
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    try:
        file_path = os.path.join(app.config['OUTPUT_FOLDER'], filename)
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        
        return send_file(file_path, mimetype='image/png', as_attachment=True, download_name=filename)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy'}), 200


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)