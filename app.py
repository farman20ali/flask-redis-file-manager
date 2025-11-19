from flask import Flask, request, redirect, render_template, send_file
from io import BytesIO
from redis_client import Redis
import base64 
from file_python import File
import os
from dotenv import load_dotenv
import logging
import re
from werkzeug.utils import secure_filename

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your_secret_key')

# Connect to Redis using environment variables
server_address = os.getenv('REDIS_HOST', 'localhost')
redis_port = os.getenv('REDIS_PORT', '6379')
redis_pass = os.getenv('REDIS_PASSWORD', None)
if redis_pass == '':
    redis_pass = None

# Application configuration
DEFAULT_USER = os.getenv('DEFAULT_USER', 'farman')
DEFAULT_ROLE = os.getenv('DEFAULT_ROLE', 'admin')
CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', 1048576))

redis_cli = Redis(server_address, redis_port, redis_pass)

file=File()

# Helper functions for input validation
def sanitize_filename(filename):
    """Sanitize filename to prevent path traversal and other attacks"""
    if not filename:
        return None
    # Use werkzeug's secure_filename and additional checks
    filename = secure_filename(filename)
    # Remove any remaining problematic characters
    filename = re.sub(r'[^\w\s\-\.]', '', filename)
    # Limit filename length
    if len(filename) > 255:
        filename = filename[:255]
    return filename if filename else None

def validate_send_to(send_to):
    """Validate send_to field to contain only alphanumeric characters and underscores"""
    if not send_to:
        return False
    # Only allow alphanumeric characters, underscores, and hyphens
    return bool(re.match(r'^[\w\-]+$', send_to))

def validate_text_input(text, max_length=1000000):
    """Validate text input"""
    if not text:
        return False
    if len(text) > max_length:
        return False
    return True

@app.route('/save-text', methods=['POST'])
def save_text():
    try:
        text = request.form.get('text', '')
        if not validate_text_input(text):
            logger.warning("Invalid text input received")
            return "Invalid text input! Text is required and must be under 1MB.", 400
        
        save_as_file = 'save_as_file' in request.form
        if save_as_file:
            filename = sanitize_filename("save-text.txt")
            send_to = request.form.get('send_to_save', '')
            
            if not validate_send_to(send_to):
                logger.warning(f"Invalid send_to value: {send_to}")
                return "Invalid send_to! Please provide valid alphanumeric value.", 400
            
            encoded_data = base64.b64encode(text.encode('utf-8')).decode('utf-8')
            # Convert file to bytes 
            data_length = len(encoded_data)

            # Get send_to from form or session (assuming send_to input is required)
            
            key = f"file_{send_to}_{filename}"
            # Check if file exists in Redis
            if redis_cli.key_exists(key):
                return render_template('file_exists.html', send_to=send_to, filename=filename, encoded_data=encoded_data)
            for i in range(0, data_length, CHUNK_SIZE):
                redis_cli.appendRpush(key, encoded_data[i:i+CHUNK_SIZE])
            message=f"File '{filename}' uploaded successfully!" 
            options = update_file_list(DEFAULT_USER, DEFAULT_ROLE)
            return render_template('index.html', options=options, message=message,retrieved_text=getText())
        
        redis_cli.setKey('saved_text', text)
        options = update_file_list(DEFAULT_USER, DEFAULT_ROLE)
        return render_template('index.html', options=options, message="Text saved successfully!",retrieved_text=getText())
    except Exception as e:
        logger.error(f"Error in save_text: {e}")
        return "An error occurred while saving text.", 500

def getText():
    text = redis_cli.getKey('saved_text')
    if not text:
        text = "No text found in Redis."
    return text

@app.route('/download-text', methods=['POST'])
def download_retrieved_text():
    retrieved_text = request.form['retrieved_text']
    return send_file(BytesIO(retrieved_text.encode()), as_attachment=True, download_name='retrieved_text.txt', mimetype='text/plain')


@app.route('/get-text', methods=['GET'])
def get_text():
    options = update_file_list(DEFAULT_USER, DEFAULT_ROLE)
    return render_template('index.html', options=options, message=None,retrieved_text=getText())

def update_file_list(send_to,role):
    if not redis_cli.isConnected():
        redis_cli.connect()
        if not redis_cli.isConnected():
             return None
    if role=="admin":
        pattern = "file_"+"*"+"_*"
    else:
        pattern = "file_*"+""+send_to+""+"_*"
 
    result = redis_cli.getAllKeys(pattern)
    options={}
    for file_key in result:

        # new_list = file_key.split("_")
        # file_name = "_".join(new_list[2:])
        options[file_key]=file_key
    return options

 
@app.route('/download', methods=['POST'])
def download():
    try:
        selected_option = request.form.get('selected_option', '')
        if not selected_option:
            logger.warning("No file selected for download")
            return 'No file selected', 400
        
        # Validate the selected option format
        if not selected_option.startswith('file_'):
            logger.warning(f"Invalid file key format: {selected_option}")
            return 'Invalid file selection', 400
        
        # Get corresponding value
        # Perform an action based on the selected option (replace with your logic)
        encoded_data_list = redis_cli.getKey(selected_option)
        if encoded_data_list is None:
            logger.warning(f"File not found: {selected_option}")
            return 'File not found', 404
        
        # Assuming the data is stored as a list of base64 strings in Redis
        encoded_data = ""
        for data in encoded_data_list:
            encoded_data += data
        decoded_data = base64.b64decode(encoded_data.encode())
        filename = "_".join(selected_option.split("_")[2:])
        filename = sanitize_filename(filename) if filename else "download"
        
        # Use a BytesIO stream to send the decoded data as a file
        return send_file(BytesIO(decoded_data), as_attachment=True, download_name=filename)
    except Exception as e:
        logger.error(f"Error in download: {e}")
        return "An error occurred while downloading the file.", 500

@app.route('/overwrite', methods=['POST'])
def overwrite():
    try:
        send_to = request.form.get('send_to', '')
        filename = request.form.get('filename', '')
        encoded_data = request.form.get('encoded_data', '')
        
        if not validate_send_to(send_to):
            logger.warning(f"Invalid send_to in overwrite: {send_to}")
            return "Invalid send_to value", 400
        
        filename = sanitize_filename(filename)
        if not filename:
            logger.warning("Invalid filename in overwrite")
            return "Invalid filename", 400
        
        key = f"file_{send_to}_{filename}"

        # Remove existing file data
        redis_cli.deleteKey(key)

        # Save data to Redis in chunks
        data_length = len(encoded_data)
        for i in range(0, data_length, CHUNK_SIZE):
            redis_cli.appendRpush(key, encoded_data[i:i+CHUNK_SIZE])

        options = update_file_list(DEFAULT_USER, DEFAULT_ROLE)
        return render_template('index.html', options=options, message=f"File '{filename}' overwritten successfully!",retrieved_text=getText())
    except Exception as e:
        logger.error(f"Error in overwrite: {e}")
        return "An error occurred while overwriting the file.", 500


@app.route('/rename', methods=['POST'])
def rename():
    try:
        send_to = request.form.get('send_to', '')
        encoded_data = request.form.get('encoded_data', '')
        new_filename = request.form.get('new_filename', '')
        
        if not validate_send_to(send_to):
            logger.warning(f"Invalid send_to in rename: {send_to}")
            return "Invalid send_to value", 400
        
        new_filename = sanitize_filename(new_filename)
        if not new_filename:
            logger.warning("Invalid new filename in rename")
            return "New filename required! Please provide a valid filename.", 400
        
        key = f"file_{send_to}_{new_filename}"

        if redis_cli.key_exists(key):
            return render_template('file_exists.html', send_to=send_to, filename=new_filename, encoded_data=encoded_data)

        # Save data to Redis in chunks
        data_length = len(encoded_data)
        for i in range(0, data_length, CHUNK_SIZE):
            redis_cli.appendRpush(key, encoded_data[i:i+CHUNK_SIZE])

        return render_template('index.html', options=update_file_list(DEFAULT_USER, DEFAULT_ROLE), message=f"File '{new_filename}' renamed and uploaded successfully!",retrieved_text=getText())
    except Exception as e:
        logger.error(f"Error in rename: {e}")
        return "An error occurred while renaming the file.", 500
 

 
@app.route('/', methods=['GET', 'POST'])
def index():
    options=update_file_list(DEFAULT_USER, DEFAULT_ROLE)
    if request.method == 'POST':
        try:
            send_to = request.form.get('send_to', '')
            if not validate_send_to(send_to):
                logger.warning(f"Invalid send_to in index: {send_to}")
                return "send_to required! Please provide a valid alphanumeric value.", 400
            
            encoded_data=None
            filename=None
            
            # Check if file is uploaded
            # Check if the post request has the file part
            if 'folder' in request.files:
                files = request.files.getlist('folder')
                encoded_data = file.zip_in_memory_fileStorage(files)
                filename = request.form.get('filename', '')
                if filename:
                    filename = sanitize_filename(filename)
                    if filename:
                        filename = filename + ".zip"
            elif 'file' in request.files:
                uploaded_file = request.files['file']
                if uploaded_file.filename:
                    filename = sanitize_filename(uploaded_file.filename)
                    encoded_data = base64.b64encode(uploaded_file.read()).decode('utf-8')
            
            if encoded_data is None:
                logger.warning("No file uploaded")
                return 'No file uploaded. Please select a file.', 400
            if not filename:
                logger.warning("Invalid filename")
                return 'Invalid filename. Please provide a valid file.', 400

            # Convert file to bytes
            data_length = len(encoded_data)

            # Get send_to from form or session (assuming send_to input is required)
            
            key = f"file_{send_to}_{filename}"
            # Check if file exists in Redis
            if redis_cli.key_exists(key):
                return render_template('file_exists.html', send_to=send_to, filename=filename, encoded_data=encoded_data)
            # Efficiently save data to Redis in chunks
            for i in range(0, data_length, CHUNK_SIZE):
                redis_cli.appendRpush(key, encoded_data[i:i+CHUNK_SIZE])
 
            logger.info(f"File '{filename}' uploaded successfully for {send_to}")
            return f"File '{filename}' uploaded successfully!"
        except Exception as e:
            logger.error(f"Error in index upload: {e}")
            return "An error occurred while uploading the file.", 500

    # Render the template with options for the dropdown initially
    return render_template('index.html', options=options, message=None,retrieved_text=getText())

if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', 5000))
    app.run(debug=debug_mode, host=host, port=port)