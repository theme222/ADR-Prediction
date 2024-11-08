from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from TechnicalToolsV2 import log, sha256
from file_handler import transform_file_for_igv, connect, disconnect, get_range_of_bam_file, get_adr, run, \
    get_status_code, set_status_code, run_hla_la, format_hla_la, is_available, set_available
from time import time, sleep
import secrets
import shutil
import sqlite3
import os
import threading
import re

DATABASE_NAME = "users.db"  # go change in file_handler.py as well
SESSION_DURATION = 1000000  # Seconds

# status codes
IDLE = 0
WORKING = 1
COMPLETED = 2

CURRENT_FILE_DIRECTORY = os.path.dirname(os.path.abspath(__file__))  # home/sirat/Code/ADR-Prediction/WebBackend/
TYPING_TOOLS = ['hla_la', 'optitype', 'hisat_genotype', 'snp_bridge']
ASSOCIATED_FILETYPES = ['.bam', '.bam.bai', '.fq', '.sam']
SINGLE_USE_TOKENS = {}  # token used for downloading user data from server
app = Flask(__name__)
CORS(app)


def remove_token(token):
    sleep(600)
    try:
        del SINGLE_USE_TOKENS[token]
    except KeyError:
        pass


def check_valid_filename(name):
    max_size = 100
    char_list = ['!', '@', '#', '$', '%', '^', '&', '*', '(', ')', "'", '"', '<', '>', '/', '?', '[', ']', '|', ',',
                 '|', '\\', '-', '=', ':', '{', '}', '`', '~', ' ']
    pattern = re.compile('[' + re.escape(''.join(char_list)) + ']')

    # Check if the filename contains any character from the list
    if pattern.search(name) or len(name) > max_size:
        return False
    else:
        return True


def generate_session_cookie():
    return f"{secrets.token_hex(16)}__{int(time())}"


def get_account_info_from_db(cookie):
    connection, cursor = connect()
    cursor.execute("SELECT id,name,email FROM Users WHERE id = (SELECT user_id FROM Sessions WHERE token = ?)",
                   (cookie,))
    info = cursor.fetchone()
    disconnect(connection, cursor)
    return info


def signup_into_database(name, email, password):
    connection, cursor = connect()
    hashed_password = password

    cursor.execute(
        "INSERT INTO Users (name, email, password_hash) VALUES (?,?,?);",
        (name, email, hashed_password)
    )

    disconnect(connection, cursor)


def check_value_in_column_exists(value, column_name):
    connection, cursor = connect()
    cursor.execute(f"SELECT EXISTS(SELECT 1 FROM Users WHERE {column_name} = ?) ", (value,))
    exists = cursor.fetchone()[0]
    disconnect(connection, cursor)
    return exists == 1


@app.route('/api/signup', methods=['POST'])
def api_signup_handler():
    data = request.json
    log("Received signup data:", logtitle="POST REQUEST", var=data, color='yellow')

    signup_into_database(data['name'], data['email'], data['password'])

    return jsonify({"message": "Recieved Info!"})


@app.route('/api/login', methods=['POST'])
def api_login_handler():
    data = request.json
    log("Received login data:", logtitle="POST REQUEST", var=data, color='yellow')

    if check_value_in_column_exists(data["email"], "email"):
        connection, cursor = connect()
        cursor.execute(f"SELECT id,password_hash FROM Users WHERE email = ? ", (data["email"],))
        user_id, password = cursor.fetchone()
        disconnect(connection, cursor)
        if password == data["password"]:
            session_cookie = generate_session_cookie()

            connection, cursor = connect()
            cursor.execute(f"INSERT INTO Sessions (user_id,token,start_time,duration) VALUES (?,?,?,?)",
                           (user_id, session_cookie, int(time()), SESSION_DURATION))
            disconnect(connection, cursor)
            log("Created cookie : ", var=session_cookie, color="green", logtitle="COOKIE MONSTER")
            return jsonify({"success": True, "sessionCookie": session_cookie, "duration": SESSION_DURATION})

    return jsonify({"success": False, "sessionCookie": None})


@app.route('/api/checkEmail', methods=['POST'])
def api_check_same_email():
    data = request.json
    log("Received check email data:", logtitle="POST REQUEST", var=data, color='yellow')
    return jsonify({"value": check_value_in_column_exists(data["email"], "email")})


@app.route('/api/getAccountInfo', methods=['POST'])
def api_get_account_info():
    data = request.json
    log("Requesting account info : ", logtitle="POST REQUEST", var=data, color='yellow')
    # Check if session cookie exists
    try:
        data["session_cookie"]
    except KeyError:
        return jsonify({"id": None, "name": None, "email": None})

    # Getting account info
    info = get_account_info_from_db(data['session_cookie'])

    if info:
        user_id, name, email = info
        return jsonify({"id": user_id, "name": name, "email": email})
    else:
        log("Can't find cookie", logtitle="error", color="red")
        return "Invalid session cookie", 401


@app.route('/api/getSequences', methods=['POST'])
def api_get_sequences():
    data = request.json
    log("Requesting sequences list : ", logtitle="POST REQUEST", var=data, color='yellow')

    # Check if session cookie exists
    try:
        data["session_cookie"]
    except KeyError:
        return "No session cookie", 400

    # Getting account info
    info = get_account_info_from_db(data['session_cookie'])

    if not info:
        log("Can't find cookie", logtitle="error", color="red")
        return "Invalid session cookie", 401

    user_id, name, email = info
    connection, cursor = connect()
    cursor.execute(
        "SELECT id,label,upload_time,igv,hla_la,hisat_genotype,optitype FROM User_sequences WHERE user_id = ?",
        (user_id,))

    return jsonify({"list": cursor.fetchall()})


@app.route('/api/uploadFile', methods=['POST'])
def api_upload_file():
    if 'file' not in request.files:
        return 'No file part', 400

    file = request.files['file']

    if file.filename == '':
        return 'No selected file', 400

    log("Requesting to upload file : ", logtitle="POST REQUEST", var=file.filename, color='yellow')

    # get account info
    cookie = request.headers.get('Authorization').split('Bearer ')[-1]
    info = get_account_info_from_db(cookie)

    if not info:
        log("Invalid cookie", logtitle='error', color='red')
        return "Invalid session cookie", 401

    user_id, name, email = info

    # Make parent directory with user_id
    directory = f"{CURRENT_FILE_DIRECTORY}/uploads/{user_id}"

    if not os.path.exists(directory):
        os.makedirs(directory)
        log(f"Directory '{directory}' created.")

    filename = file.filename  # sequence label
    # make sure it doesnt contain random symbol stuff
    if not check_valid_filename(filename):
        return "Do not use symbols in the label", 400

    # Make sequence directory with label

    # make sure it doesn't override itself
    while os.path.exists(f"{CURRENT_FILE_DIRECTORY}/uploads/{user_id}/{filename}"):
        filename += f'_{secrets.token_hex(1)}'

    directory = f"{CURRENT_FILE_DIRECTORY}/uploads/{user_id}/{filename}"
    os.makedirs(directory)
    log(f"Directory '{directory}' created.")

    # Save the uploaded file to a designated location
    file.save(f'{directory}/{filename}.fq')
    connection, cursor = connect()
    cursor.execute("INSERT INTO User_sequences (user_id,label) VALUES (?,?)", (user_id, filename))
    disconnect(connection, cursor)

    threading.Thread(target=transform_file_for_igv, args=(f"uploads/{user_id}/{filename}", filename, user_id)).start()
    return 'File uploaded successfully', 200


@app.route('/api/run/hla_la', methods=['POST'])
def api_run_hla_la():
    log("Requesting to run HLA-LA : ", logtitle="POST REQUEST", color='yellow')

    # get account info
    cookie = request.json['session_cookie']
    info = get_account_info_from_db(cookie)

    if not info:
        log("Invalid cookie", logtitle='error', color='red')
        return "Invalid session cookie", 401

    user_id, name, email = info
    label = request.json["label"]

    status = get_status_code(label, "hla_la", user_id)

    if status == COMPLETED:
        return 'File already processed', 200
    elif status == WORKING:
        return 'File being processed', 200

    if not is_available():
        return "Another instance of HLA*LA is being ran please try again later", 200

    threading.Thread(target=run_hla_la, args=(f"uploads/{user_id}/{label}", label, user_id)).start()
    return 'Running HLA-LA', 200


@app.route('/api/requestFile/igv', methods=['POST'])
def api_request_file_igv():
    sequence_label = request.json["label"]
    cookie = request.json['session_cookie']

    log("Requesting file with label", var=sequence_label, logtitle='POST REQUEST', color='yellow')
    # get user_id
    info = get_account_info_from_db(cookie)

    if not info:
        log("Invalid cookie", logtitle='error', color='red')
        return "Invalid session cookie", 401

    user_id, name, email = info
    directory = f"{CURRENT_FILE_DIRECTORY}/uploads/{user_id}/{sequence_label}/igv"

    if not os.path.exists(directory):
        log("Path doesn't exist", logtitle="error", color='red')
        return "No file found", 400

    if not os.path.isfile(directory + "/" + sequence_label + '.bam') or not os.path.isfile(
            directory + "/" + sequence_label + '.bam.bai'):
        return "File isn't ready for view yet", 504

    # creating tokens for the two files requested (.bam, .bam.bai)
    token_bam = secrets.token_urlsafe(16)
    token_bam_bai = secrets.token_urlsafe(16)
    SINGLE_USE_TOKENS[token_bam] = directory + "/" + sequence_label + ".bam"
    SINGLE_USE_TOKENS[token_bam_bai] = directory + "/" + sequence_label + ".bam.bai"

    # remove the tokens in 10 minutes parallel
    threading.Thread(target=remove_token, args=(token_bam,)).start()
    threading.Thread(target=remove_token, args=(token_bam_bai,)).start()

    return jsonify({"token_bam": token_bam,
                    "token_bam_bai": token_bam_bai,
                    "range": get_range_of_bam_file(directory + "/" + sequence_label + ".bam")})


@app.route('/api/getResults/hla_la', methods=['POST'])
def api_get_typing_results():
    sequence_label = request.json["label"]
    cookie = request.json['session_cookie']

    log("Requesting typing results with label :", var=sequence_label, logtitle='POST REQUEST', color='yellow')

    # get user_id
    info = get_account_info_from_db(cookie)

    if not info:
        log("Invalid cookie", logtitle='error', color='red')
        return "Invalid session cookie", 401

    user_id, name, email = info

    if get_status_code(sequence_label, "hla_la", user_id) != 2:
        return jsonify([]), 200

    alleles = format_hla_la(f"/app/uploads/{user_id}/{sequence_label}/hla_la/out/hla/R1_bestguess_G.txt")
    return_list = []
    for allele in alleles:
        return_list.extend(get_adr(allele))

    return jsonify(return_list)


@app.route('/api/deleteSequence', methods=['POST'])
def api_delete_sequence():
    sequence_label = request.json["label"]
    cookie = request.json['session_cookie']
    log(f"Receiving delete sequence request with label :", var=sequence_label, logtitle="post request", color='yellow')

    # get user_id
    info = get_account_info_from_db(cookie)

    if not info:
        log("Invalid cookie", logtitle='error', color='red')
        return "Invalid session cookie", 401

    user_id, name, email = info

    directory = f"{CURRENT_FILE_DIRECTORY}/uploads/{user_id}/{sequence_label}"
    shutil.rmtree(directory)
    log("Removed directory :", var=directory, logtitle="DELETE", color="red")

    connection, cursor = connect()
    cursor.execute("DELETE FROM User_sequences WHERE user_id=? AND label=?", (user_id, sequence_label))
    disconnect(connection, cursor)
    return "Successfully removed file(s)", 200


@app.route('/download/<token>')
def download_data_from_token(token):
    log(f"Receiving download request with token {token}", logtitle="download request", color='yellow')
    try:
        file_dir = SINGLE_USE_TOKENS[token]
        return send_file(file_dir)
    except KeyError:
        return "Invalid token", 400


@app.route('/reference/chr6.fa.fai')
def file_chr6_fa_fai():
    # Path to your sequence file
    sequence_file = 'references/chr6.fa.fai'

    # Use Flask's send_file function to send the file as a response
    return send_file(sequence_file)


@app.route('/reference/chr6.fa')
def file_chr6_fa():
    # Path to your sequence file
    sequence_file = 'references/chr6.fa'

    # Use Flask's send_file function to send the file as a response
    return send_file(sequence_file)


@app.route('/')
def hello():
    set_available()
    return "<b>Just checking if the backend works or not lol nice port number am I right :)</b>"


if __name__ == '__main__':
    app.run(debug=True, port=7000, host="0.0.0.0")
