# Clear Football Photo Booth API 📸⚽

A high-performance Flask API for creating custom football-themed photo booth images. This service automatically removes backgrounds from user photos and overlays them onto premium football frames while maintaining strict resolution and aspect ratio.

## ✨ Features

- **Advanced AI Background Removal:** Uses `rembg` with Alpha Matting for high-accuracy subject extraction.
- **Strict Resolution:** Forces all outputs to **1536x1024** px without stretching the subject.
- **Dynamic Framing:** Choose from multiple football-themed background frames.
- **QR Code Integration:** Automatically generates a QR code on the final image for instant downloads.
- **Instant Processing:** Fast turnaround from upload to processed result.

## 🛠️ Tech Stack

- **Backend:** Flask (Python 3.13+)
- **Image Processing:** Pillow (PIL), OpenCV
- **AI Cutout:** Rembg (u2net)
- **QR Generation:** qrcode

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.13 or higher

### 2. Installation
```bash
# Clone the repository
git clone <repository-url>
cd clear_football-photboth

# Install dependencies
pip install -r requirements.txt
```

### 3. Setup
The application requires a `frames/` directory containing images named `frame_1.png` through `frame_6.png` with dimensions 1536x1024.

### 4. Hosting on cPanel (Shared Hosting)
1.  Upload all files to your cPanel directory (e.g., `public_html` or a subfolder).
2.  In cPanel, go to **Setup Python App**.
3.  Create a new application:
    *   **Python version:** 3.11 or higher.
    *   **Application root:** The folder where you uploaded the files.
    *   **Application URL:** Your domain or subdomain.
    *   **Application startup file:** `passenger_wsgi.py`.
    *   **Application Entry point:** `application`.
4.  Click **Run Pip Install** and select `requirements.txt`.
5.  **Restart** the application.

The `passenger_wsgi.py` file is already included and configured to work with Phusion Passenger.

### Process Image
`POST /process`

**Parameters (form-data):**
- `person_image` (File): JPG/PNG image of the user.
- `name` (Text): User's name.
- `number` (Text): User's ID or phone number.
- `image_set_background` (Text): Frame number (1-6). Default is 1.

**Response:**
```json
{
    "success": true,
    "message": "Image processed successfully",
    "output_file": "uuid_output.png",
    "download_url": "http://localhost:5000/download/uuid_output.png"
}
```

### Download Image
`GET /download/<filename>`

Returns the processed PNG image as a downloadable attachment.

### Health Check
`GET /health`

Returns `{"status": "healthy"}`.

## 🧪 Testing with Postman

A pre-configured Postman collection is included in the root directory: `postman_collection.json`. 
1. Open Postman.
2. Click **Import**.
3. Select `postman_collection.json`.
4. Set the `base_url` variable if your server is running on a different port.

## 📄 License
This project is for internal use.
