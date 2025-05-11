import os
import sqlite3
import subprocess
import threading
import configparser
import json
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
DB_NAME = 'database.db'
RCLONE_CONFIG_PATH = os.path.expanduser('~/.config/rclone/rclone.conf')

progress_lock = threading.Lock()
progress_buffer = []
running_thread = None
log_process = None
stop_requested = False
last_inserted_count = 0


def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY,
                remote TEXT,
                path TEXT,
                filename TEXT,
                UNIQUE(remote, path)
            )
        ''')
        conn.commit()


def insert_files(remote, file_entries):
    global last_inserted_count
    with sqlite3.connect(DB_NAME) as conn:
        conn.executemany("""
            INSERT OR IGNORE INTO files (remote, path, filename)
            VALUES (?, ?, ?)
        """, file_entries)
        conn.commit()
    last_inserted_count = len(file_entries)


def search_files(query):
    query = f"%{query.lower()}%"
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute("SELECT remote, path FROM files WHERE LOWER(filename) LIKE ?", (query,))
        return cursor.fetchall()


def list_rclone_remotes():
    config = configparser.ConfigParser()
    config.read(RCLONE_CONFIG_PATH)
    return config.sections()


def list_rclone_contents(remote, path):
    try:
        full_path = f"{remote}:{path}" if path else f"{remote}:"
        output = subprocess.check_output(
            ['rclone', 'lsjson', full_path],
            stderr=subprocess.DEVNULL,
            text=True
        )
        return json.loads(output)
    except Exception as e:
        print(f"[ERROR] Failed to list directory contents: {e}")
        return []


def fetch_files_background(remote, path):
    global progress_buffer, log_process, stop_requested, last_inserted_count

    with progress_lock:
        progress_buffer = ["Fetching file list..."]
        stop_requested = False
        last_inserted_count = 0

    try:
        full_path = f"{remote}:{path}" if path else f"{remote}:"
        output = subprocess.check_output(
            ['rclone', 'lsjson', '--recursive', '--files-only', full_path],
            stderr=subprocess.DEVNULL,
            text=True
        )
        files_json = json.loads(output)

        path_prefix = path.rstrip('/')
        file_entries = [
            (
                remote,
                f"{path_prefix}/{file['Path']}" if path else file['Path'],
                os.path.basename(file['Path'])
            )
            for file in files_json if not file.get('IsDir')
        ]
        insert_files(remote, file_entries)
    except Exception as e:
        with progress_lock:
            progress_buffer.append(f"[ERROR] Failed to parse rclone JSON: {e}")
        return

    def stream_logs():
        global progress_buffer, log_process
        for line in log_process.stdout:
            if stop_requested:
                break
            with progress_lock:
                progress_buffer.append(line.strip())
                progress_buffer = progress_buffer[-10:]

    log_process = subprocess.Popen(
        ['rclone', 'lsf', '-v', '--recursive', '--files-only', full_path],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    log_thread = threading.Thread(target=stream_logs)
    log_thread.start()
    log_thread.join()

    with progress_lock:
        progress_buffer.append(f"✅ Indexing complete. {last_inserted_count} new files inserted into database.")


@app.route('/')
def index():
    remotes = list_rclone_remotes()
    return render_template('index.html', remotes=remotes)


@app.route('/browse_dir', methods=['POST'])
def browse_dir():
    remote = request.form['remote']
    path = request.form.get('path', '')
    entries = list_rclone_contents(remote, path)
    return jsonify(entries=entries)


@app.route('/start_fetch', methods=['POST'])
def start_fetch():
    global running_thread
    remote = request.form['remote']
    path = request.form.get('folder', '')
    running_thread = threading.Thread(target=fetch_files_background, args=(remote, path))
    running_thread.start()
    return jsonify(status="started")


@app.route('/stop_fetch', methods=['POST'])
def stop_fetch():
    global stop_requested, log_process, last_inserted_count
    stop_requested = True
    if log_process:
        log_process.terminate()
        log_process = None
    return jsonify(status="stopped", inserted=last_inserted_count)


@app.route('/progress')
def progress():
    with progress_lock:
        return jsonify(lines=progress_buffer)


@app.route('/search', methods=['POST'])
def search():
    query = request.form['query']
    remote = request.form.get('remote', '')
    folder = request.form.get('folder', '')
    results = search_files(query)
    remotes = list_rclone_remotes()
    return render_template('index.html', remotes=remotes, results=results, query=query,
                           selected_remote=remote, selected_folder=folder)


@app.route('/clear_db', methods=['GET', 'POST'])
def clear_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM files")
        conn.commit()
    return "✅ Database cleared."


@app.route('/debug_db')
def debug_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute("SELECT remote, path, filename FROM files LIMIT 100")
        rows = cursor.fetchall()
    return "<pre>" + "\n".join([f"{r} | {p} | {f}" for r, p, f in rows]) + "</pre>"


if __name__ == '__main__':
    init_db()
    app.run(debug=True)