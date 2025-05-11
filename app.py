import os
import sqlite3
import subprocess
import threading
import configparser
import json
import ijson
from datetime import datetime
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
DB_NAME = 'database.db'
RCLONE_CONFIG_PATH = os.path.expanduser('~/.config/rclone/rclone.conf')

progress_lock = threading.Lock()
progress_buffer = []
running_thread = None
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
        conn.execute('''
            CREATE TABLE IF NOT EXISTS scan_log (
                remote TEXT,
                path TEXT,
                last_scanned TEXT,
                status TEXT,
                PRIMARY KEY (remote, path)
            )
        ''')
        conn.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
                filename,
                content='files',
                content_rowid='id'
            )
        ''')
        conn.commit()

def insert_files(remote, file_entries):
    global last_inserted_count
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        for remote, path, filename in file_entries:
            cur.execute("INSERT OR IGNORE INTO files (remote, path, filename) VALUES (?, ?, ?)", (remote, path, filename))
        conn.commit()

        cur.execute("""
            INSERT INTO files_fts(rowid, filename)
            SELECT id, filename FROM files
            WHERE id NOT IN (SELECT rowid FROM files_fts)
        """)
        conn.commit()
    last_inserted_count += len(file_entries)
def update_scan_log(remote, path, status):
    timestamp = datetime.utcnow().isoformat()
    path = path.strip('/')
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            INSERT INTO scan_log (remote, path, last_scanned, status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(remote, path) DO UPDATE SET
                last_scanned=excluded.last_scanned,
                status=excluded.status
        """, (remote, path, timestamp, status))
        conn.commit()

def get_last_scan(remote, path):
    path = path.strip('/')
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute(
            "SELECT last_scanned, status FROM scan_log WHERE remote = ? AND path = ?",
            (remote, path)
        )
        row = cursor.fetchone()
        return (row[0], row[1]) if row else (None, None)

def search_files(query):
    # Escape any internal double quotes
    safe_query = query.replace('"', '""')
    # Wrap in double quotes for exact literal match
    safe_query = f'"{safe_query}"'
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute("""
            SELECT f.remote, f.path
            FROM files_fts AS fts
            JOIN files AS f ON fts.rowid = f.id
            WHERE fts.filename MATCH ?
        """, (safe_query,))
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
    global progress_buffer, stop_requested, last_inserted_count

    with progress_lock:
        progress_buffer = ["Fetching file list (streaming)..."]
        stop_requested = False
        last_inserted_count = 0

    full_path = f"{remote}:{path}" if path else f"{remote}:"
    path_prefix = path.rstrip('/') if path else ''
    already_scanned = set()
    file_entries = []
    file_count = 0

    process = subprocess.Popen(
        ['rclone', 'lsjson', '--recursive', '--files-only', full_path],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace'
    )

    try:
        for obj in ijson.items(process.stdout, 'item'):
            if stop_requested:
                process.terminate()
                update_scan_log(remote, path, 'partial')
                return

            if not obj.get('IsDir'):
                fullpath = f"{path_prefix}/{obj['Path']}" if path else obj['Path']
                filename = os.path.basename(obj['Path'])
                folder_path = os.path.dirname(fullpath).strip('/')

                file_entries.append((remote, fullpath, filename))
                file_count += 1

                if folder_path not in already_scanned:
                    update_scan_log(remote, folder_path, 'complete')
                    already_scanned.add(folder_path)

                if file_count % 10 == 0:
                    with progress_lock:
                        progress_buffer.append(f"🔄 {file_count} files scanned...")
                        progress_buffer = progress_buffer[-10:]

                if len(file_entries) >= 100:
                    insert_files(remote, file_entries)
                    file_entries.clear()

        if file_entries:
            insert_files(remote, file_entries)

        update_scan_log(remote, path, 'complete')

    except Exception as e:
        with progress_lock:
            progress_buffer.append(f"[ERROR] Streaming failed: {e}")
        update_scan_log(remote, path, 'partial')
        return

    with progress_lock:
        progress_buffer.append(f"✅ Indexing complete. {last_inserted_count} new files inserted into database.")

@app.route('/')
def index():
    remotes = list_rclone_remotes()
    return render_template('index.html', remotes=remotes, selected_remote=None, selected_folder=None,
                           last_scanned=None, scan_status=None)

@app.route('/browse_dir', methods=['POST'])
def browse_dir():
    remote = request.form['remote']
    path = request.form.get('path', '').strip('/')
    entries = list_rclone_contents(remote, path)
    last_scanned, scan_status = get_last_scan(remote, path)
    return jsonify(entries=entries, last_scanned=last_scanned, scan_status=scan_status)

@app.route('/start_fetch', methods=['POST'])
def start_fetch():
    global running_thread
    remote = request.form['remote']
    path = request.form.get('folder', '').strip('/')
    running_thread = threading.Thread(target=fetch_files_background, args=(remote, path))
    running_thread.start()
    return jsonify(status="started")

@app.route('/stop_fetch', methods=['POST'])
def stop_fetch():
    global stop_requested
    stop_requested = True
    return jsonify(status="stopped", inserted=last_inserted_count)

@app.route('/progress')
def progress():
    with progress_lock:
        return jsonify(lines=progress_buffer)
@app.route('/file_count')
def file_count():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM files")
        count = cursor.fetchone()[0]
    return jsonify(count=count)

@app.route('/search', methods=['POST'])
def search():
    query = request.form['query']
    remote = request.form.get('remote', '')
    folder = request.form.get('folder', '')
    results = search_files(query)
    remotes = list_rclone_remotes()
    last_scanned, scan_status = get_last_scan(remote, folder)
    return render_template('index.html', remotes=remotes, results=results, query=query,
                           selected_remote=remote, selected_folder=folder,
                           last_scanned=last_scanned, scan_status=scan_status)

@app.route('/clear_db', methods=['GET', 'POST'])
def clear_db():
    if request.method == 'POST':
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("DELETE FROM files")
            conn.execute("DELETE FROM scan_log")
            conn.execute("DELETE FROM files_fts")
            conn.commit()
        return """
            <a href="/">🔙 Back to App</a>
            <h3>✅ Database cleared.</h3>
            <a href="/">🔙 Back to App</a>
        """
    return """
        <a href="/">🔙 Back to App</a>
        <h3>⚠️ Are you sure you want to clear the entire database?</h3>
        <form method="post">
            <button type="submit">Yes, clear it</button>
            <a href="/"><button type="button">Cancel</button></a>
        </form>
        <a href="/">🔙 Back to App</a>
    """
@app.route('/rebuild_fts')
def rebuild_fts():
    with sqlite3.connect(DB_NAME) as conn:
        # Drop and recreate the FTS table
        conn.execute("DROP TABLE IF EXISTS files_fts;")
        conn.execute("""
            CREATE VIRTUAL TABLE files_fts USING fts5(
                filename,
                content='files',
                content_rowid='id'
            );
        """)
        # Repopulate it from the main files table
        conn.execute("""
            INSERT INTO files_fts(rowid, filename)
            SELECT id, filename FROM files;
        """)
        conn.commit()
    return """
        <h3>✅ FTS index rebuilt from files table.</h3>
        <a href="/">🔙 Back to App</a>
    """


@app.route('/debug_db')
def debug_db():
    limit_param = request.args.get('limit', '100')
    remote_param = request.args.get('remote', '')

    try:
        limit = int(limit_param) if limit_param.lower() != 'all' else None
    except ValueError:
        limit = 100
        limit_param = '100'

    with sqlite3.connect(DB_NAME) as conn:
        remotes = [row[0] for row in conn.execute("SELECT DISTINCT remote FROM files")]

        if remote_param:
            query = "SELECT remote, path, filename FROM files WHERE remote = ?"
            args = [remote_param]
        else:
            query = "SELECT remote, path, filename FROM files"
            args = []

        if limit is not None:
            query += f" LIMIT {limit}"

        cursor = conn.execute(query, args)
        rows = cursor.fetchall()

    if not rows:
        return f"""
            <h3>Database Listings</h3>
            <p><em>No files found for the selected filter.</em></p>
            <a href="/">🔙 Back to App</a>
        """

    limit_options = ['100', '500', '1000', '10000', 'ALL']
    limit_html = ''.join([
        f'<option value="{val}" {"selected" if val == limit_param else ""}>{val}</option>'
        for val in limit_options
    ])

    remote_html = ''.join([
        f'<option value="{r}" {"selected" if r == remote_param else ""}>{r}</option>'
        for r in remotes
    ])
    remote_html = f'<option value="" {"selected" if remote_param == "" else ""}>-- All Remotes --</option>' + remote_html

    select_form = f"""
        <form method="get" id="debugForm" style="margin-bottom: 10px;">
            <label for="remote">Remote:</label>
            <select name="remote" onchange="document.getElementById('debugForm').submit();">{remote_html}</select>

            <label for="limit" style="margin-left: 20px;">Show entries:</label>
            <select name="limit" onchange="document.getElementById('debugForm').submit();">{limit_html}</select>
        </form>
    """

    table = "<pre>" + "\n".join([f"{r} | {p} | {f}" for r, p, f in rows]) + "</pre>"

    return f"""
        <a href="/">🔙 Back to App</a>
        <h3>Database Listings</h3>
        {select_form}
        {table}
        <a href="/">🔙 Back to App</a>
    """

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
