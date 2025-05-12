# 📁 Rclone Remote File Indexer & Search (Flask App)

A web-based tool for browsing, indexing, and searching files from any [rclone](https://rclone.org/) configured remote. Designed for persistent offline file search after scanning various directories and remotes.

---

## ✅ Features

- 🗂 **Browse `rclone` remotes** and subdirectories visually
- 📡 **Reads from existing rclone config** – no need to enter remotes manually
- 🧭 **Breadcrumb navigation** with 🏠 root awareness
- 🧠 **"Last Scanned" status** shown for every folder
- 🔁 **Scan & index folders recursively** with progress feedback
- 📦 **Displays total indexed files** (live)
- ⏹️ **Stop scans anytime**, saving what was indexed up to that point
- 🔍 **Search any part of a filename** and get full remote path results (powered by SQLite FTS5 full-text search)
- 🔎 Search results **display exact match count**
- 🧭 **Tabbed navigation** separates Scanning & Indexing from Searching
- 💾 **Persistent database** using SQLite to accumulate file listings across multiple scans
- 🧹 **Clear entire database** with one button (and confirmation)
- 🧪 **Database view mode** to view raw file listings from the database without searching
- 🌐 **Flask-based UI** with live updates and folder context awareness

---

## 📌 Intended Use Case

> You want to scan files from various remotes (e.g. HTTP, SFTP, Google Drive), **save listings** of those directories locally, and later be able to **search filenames across all indexed sites**, even when the remote is no longer accessible or you're offline.

---

## 🛠 Requirements

- Python 3.8+
- `rclone` installed and in your system's PATH
- Existing `rclone.conf` with configured remotes (e.g. in `~/.config/rclone/rclone.conf` or `C:\Users\YourName\.config\rclone\rclone.conf`)
- Flask
- ijson

---

## 🔧 Setup

1. **Clone the repo**

```bash
git clone https://github.com/yourname/rclone-file-indexer.git
cd rclone-file-indexer
```

2. **Install Python dependencies**

```bash
pip install flask ijson
```

3. **Run the app**

```bash
python app.py
```

Then open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

---

## 🚀 Usage

1. Start at the **"Scanning & Indexing"** tab
2. **Select a remote** from your `rclone.conf`
3. Use the **folder browser** to navigate to the level you want to index
4. Click **"Start Scan"** or **"Rescan This Folder"** (depending on whether it's been scanned before)
5. Watch the **progress panel** update in real-time
6. Go to the **"Search Files"** tab
7. Use the search box to **look for any filenames** you've indexed so far (literal search)

---

## 💡 Tips

- You can stop a scan mid-process using the “Stop” button; any files discovered up to that point will still be saved
- Multiple scans of different folders/remotes will **accumulate** in the database — nothing gets wiped
- Want a fresh start? Use the **"Clear Database"** button
- Use **"View Database Listings"** for troubleshooting raw data

---

## 🧱 Tech Stack

- Python 3
- Flask (UI + routing)
- SQLite (embedded DB)
- Rclone (for all remote interactions)

---

## 📂 File Structure

```bash
├── app.py           # Main Flask application
├── database.db      # SQLite database (created at runtime)
├── templates/
│   └── index.html   # Main HTML interface
├── README.md
├── rclone_errors.log # Logs any rclone errors during scans
```

---

## 🛣 Roadmap Ideas

- [ ] Export search results to `.txt`, `.csv`, or `.json`
- [ ] Filter by directory or remote in search
- [ ] Paginate large search result sets
- [ ] Run in background (daemon mode) and queue jobs
- [ ] Authentication layer
- [ ] Add a new tab "search from fixDAT" - Allow uploading a fixDAT - and have it search for the exact filenames (remove) extensions.
- [ ] Add checkbox next to files that you have searched for to get added to "queue" for download
- [ ] Test on all platforms - "Since it's Python, it works on both Linux and Windows (and probably Mac too, but I haven't tested it)
- [ ] Add a check for rclone configs - and if none - state how to add one
- [ ] Add ability to filter search results on search tab
