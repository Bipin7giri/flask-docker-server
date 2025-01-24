import os
import shutil
import logging
import subprocess
from flask import Flask, request, jsonify

app = Flask(__name__)

# Configuration
UPLOAD_FOLDER = './uploads'
BUILD_FOLDER = './builds'
ALLOWED_EXTENSIONS = {'zip'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(BUILD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Logging
logging.basicConfig(level=logging.INFO)


def allowed_file(filename):
    """Check if the uploaded file has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def find_file(root_path, filename):
    """Recursively search for a file in the given root path."""
    for root, _, files in os.walk(root_path):
        if filename in files:
            return os.path.join(root, filename)
    return None


@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file upload and Docker build."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file part in the request'}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if file and allowed_file(file.filename):
        # Save the uploaded file
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(filepath)
        logging.info(f"File saved at {filepath}")

        # Extract the ZIP file
        extract_path = os.path.join(BUILD_FOLDER, os.path.splitext(file.filename)[0])
        shutil.unpack_archive(filepath, extract_path)
        logging.info(f"File extracted to {extract_path}")

        # Recursively search for package.json
        package_json_path = find_file(extract_path, 'package.json')
        if not package_json_path:
            return jsonify({'error': 'package.json not found in the extracted ZIP.'}), 400

        # Ensure Dockerfile exists or create it
        dockerfile_path = os.path.join(os.path.dirname(package_json_path), 'Dockerfile')
        if not os.path.exists(dockerfile_path):
            with open(dockerfile_path, 'w') as dockerfile:
                dockerfile.write("""
                FROM node:16
                WORKDIR /app
                COPY package*.json ./
                RUN npm install
                COPY . .
                EXPOSE 3000
                CMD ["npm", "start"]
                """)
            logging.info(f"Dockerfile created at {dockerfile_path}")

        # Build and run the Docker container
        image_name = f"{os.path.splitext(file.filename)[0].lower()}-image"
        container_name = f"{os.path.splitext(file.filename)[0].lower()}-container"

        try:
            # Build the Docker image
            build_process = subprocess.run(
                ["docker", "build", "-t", image_name, os.path.dirname(package_json_path)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            logging.info(f"Docker Build Output: {build_process.stdout.decode()}")
            logging.error(f"Docker Build Error: {build_process.stderr.decode()}")

            # Stop and remove the container if it's already running
            subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            # Run the Docker container
            run_process = subprocess.run(
                ["docker", "run", "-d", "--name", container_name, "-p", "3000:3000", image_name],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            logging.info(f"Docker Run Output: {run_process.stdout.decode()}")
            logging.error(f"Docker Run Error: {run_process.stderr.decode()}")

            return jsonify({
                'message': 'File uploaded and Docker container started successfully',
                'docker_image': image_name,
                'docker_container': container_name
            }), 200

        except subprocess.CalledProcessError as e:
            logging.error(f"Subprocess Error: {str(e)}")
            return jsonify({'error': f'Docker error: {e.stderr.decode()}'}), 500

    return jsonify({'error': 'Invalid file format. Only .zip files are allowed.'}), 400


if __name__ == '__main__':
    app.run(debug=True)
