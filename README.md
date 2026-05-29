# Flask Redis File Manager

This project is a Flask web application for uploading, saving, downloading, renaming, and managing text and file data using Redis as a backend. It supports single file and folder uploads, session-based login, guest access, admin user management, QR share links, file passwords, and expiry controls.

## Features
- Upload and save text or files to Redis
- Download and retrieve saved text or files
- Rename and overwrite files in Redis
- List available files for download
- Admin and user roles for file listing
- Handles large files by chunking
- Guest login for read/write use without a password
- Admin user management for creating, updating, disabling, and deleting users
- Per-file password protection and expiration
- QR code share links for direct file access
- Public files that guests can browse and download
- Theme switching for default, light, and calm layouts
- Searchable owner selection instead of typing usernames manually
- Expiry controls for no expiry, quick hours, or custom date/time

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
    - For an existing local Redis server, create a local env file:
       ```bash
       make env-local
       ```
    - To start a new Redis container for local development and write matching env values:
       ```bash
       make setup
       ```
    - To prepare Docker Compose settings instead:
       ```bash
       make env-docker
       ```

4. **Choose a Redis source:**
   - Use an already running Redis instance by setting `REDIS_HOST`, `REDIS_PORT`, and `REDIS_PASSWORD` in `.env`
   - Or create a new local Redis container with `make redis-up`
   - Or remove that Redis container and its data with `make redis-uninstall`
   - Or let Docker Compose start Redis with the app using `make deploy-docker`

## Running the App
```bash
python app.py
```
The app will be available at `http://localhost:5000` by default.

### Makefile shortcuts
- `make deploy-local` - prepare env for an existing local Redis instance and start the app
- `make setup-local` - same as local deploy, but starts the app in the background
- `make deploy-new-redis` - write local env values, install dependencies, start a Redis container, and start the app in the background
- `make redis-uninstall` - stop and remove the local Redis container and its data volume
- `make setup` - write local env values, install dependencies, start a Redis container, and start the app in the foreground
- `make start-local` - start the app in the background for easier stopping later
- `make stop-local` - stop the background local app
- `make uninstall-local` - stop the local app and remove generated `.env` and log files
- `make deploy-docker` - write Docker env values and start the app with Redis in Compose
- `make stop-docker` - stop the Docker deployment
- `make uninstall-docker` - stop Docker and remove its Compose-managed resources

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
