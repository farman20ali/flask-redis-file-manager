# Flask Redis File Manager

This project is a Flask web application for uploading, saving, downloading, renaming, and managing text and file data using Redis as a backend. It supports both single file and folder uploads, with file data stored in Redis in base64-encoded chunks.

## Features
- Upload and save text or files to Redis
- Download and retrieve saved text or files
- Rename and overwrite files in Redis
- List available files for download
- Admin and user roles for file listing
- Handles large files by chunking

## Requirements
- Python 3.8+
- Redis server
- Docker (optional, for containerized deployment)

## Installation
1. **Clone the repository:**
   ```bash
   git clone <your-repo-url>
   cd flask-app
   ```
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Configure Environment Variables:**
   - Copy `.env.example` to `.env`:
     ```bash
     cp .env.example .env
     ```
   - Edit `.env` and update the following variables:
     - `FLASK_SECRET_KEY`: Change to a strong random secret key
     - `REDIS_HOST`: Your Redis server hostname/IP
     - `REDIS_PORT`: Your Redis server port (default: 6379)
     - `REDIS_PASSWORD`: Your Redis password (leave empty if none)
     - `DEFAULT_USER`: Default username for file operations
     - `DEFAULT_ROLE`: User role (admin or user)
   
4. **Start your Redis server:**
   - Make sure Redis is running and accessible at the configured host and port

## Running the App
```bash
python app.py
```
The app will be available at `http://localhost:5000` by default.

## Using Docker
To run the app and Redis using Docker Compose:
```bash
docker-compose up --build
```

## Project Structure
- `app.py` - Main Flask application
- `redis_client.py` - Redis client wrapper
- `file_python.py` - File handling utilities
- `templates/` - HTML templates
- `requirements.txt` - Python dependencies
- `dockerfile` - Docker image for Flask app
- `docker-compose.yml` - Multi-container setup (Flask + Redis)

## Notes
- Uploaded files are stored in Redis as base64-encoded strings, chunked for large files.
- The app uses a simple admin/user role system for file listing.
- Secret keys and passwords should be managed securely in production (use environment variables or `.env` files).

## License
MIT License
