"""Persistent download state using the database manager's existing write lock."""

class DownloadStore:
    _COLUMNS = {
        'downloaded_bytes': 'INTEGER NOT NULL DEFAULT 0',
        'total_bytes': 'INTEGER NOT NULL DEFAULT 0',
        'error': "TEXT NOT NULL DEFAULT ''",
        'attempt': 'INTEGER NOT NULL DEFAULT 0',
        'resume_on_restart': 'INTEGER NOT NULL DEFAULT 0',
        'job_id': "TEXT NOT NULL DEFAULT ''",
        'phase': "TEXT NOT NULL DEFAULT 'queued'",
        'warning': "TEXT NOT NULL DEFAULT ''",
        'error_code': "TEXT NOT NULL DEFAULT ''",
        'options': "TEXT NOT NULL DEFAULT '{}'",
    }

    def __init__(self, database):
        self.database = database
        with database._write_lock:
            with database.conn:
                existing = {row[1] for row in database.conn.execute('PRAGMA table_info(download_queue)')}
                for name, definition in self._COLUMNS.items():
                    if name not in existing:
                        database.conn.execute(f'ALTER TABLE download_queue ADD COLUMN {name} {definition}')
                import uuid
                for row in database.conn.execute("SELECT track_id FROM download_queue WHERE job_id = ''").fetchall():
                    database.conn.execute('UPDATE download_queue SET job_id = ? WHERE track_id = ?', (uuid.uuid4().hex, row[0]))

    def update(self, track_id, **values):
        allowed = set(self._COLUMNS) | {'status'}
        values = {name: value for name, value in values.items() if name in allowed}
        if not values:
            return
        with self.database._write_lock:
            with self.database.conn:
                assignments = ', '.join(f'{name} = ?' for name in values)
                guard = " AND status != 'completed'" if values.get('status') in ('cancelled', 'failed', 'paused') else ''
                self.database.conn.execute(f'UPDATE download_queue SET {assignments} WHERE track_id = ?{guard}',
                                           (*values.values(), track_id))

    def get(self, track_id):
        row = self.database.conn.execute('SELECT * FROM download_queue WHERE track_id = ?', (track_id,)).fetchone()
        return dict(row) if row else {}

    def rows(self, statuses=None, limit=500):
        where = ''
        parameters = []
        if statuses:
            where = 'WHERE queue.status IN (' + ','.join('?' for _ in statuses) + ')'
            parameters.extend(statuses)
        parameters.append(max(1, min(int(limit), 5000)))
        rows = self.database.conn.execute(
                'SELECT queue.*, tracks.title, tracks.artist FROM download_queue AS queue '
                'LEFT JOIN tracks ON tracks.id = queue.track_id ' + where +
                " ORDER BY CASE queue.status WHEN 'downloading' THEN 0 WHEN 'pending' THEN 1 "
                "WHEN 'paused' THEN 2 WHEN 'failed' THEN 3 ELSE 4 END, queue.id DESC LIMIT ?",
                parameters,
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item['job_id'] = item.get('job_id') or str(item['id'])
            item['stage'] = item['phase'] if item['status'] == 'downloading' else ('queued' if item['status'] == 'pending' else item['status'])
            total = int(item.get('total_bytes') or 0)
            downloaded = int(item.get('downloaded_bytes') or 0)
            item['percent'] = 100 if item['status'] == 'completed' else (
                min(99, round(downloaded * 100 / total)) if total > 0 else None
            )
            result.append(item)
        return result

    def recover(self):
        with self.database._write_lock:
            with self.database.conn:
                self.database.conn.execute(
                    "UPDATE download_queue SET status = 'pending', resume_on_restart = 0 "
                    "WHERE status = 'downloading' OR resume_on_restart = 1"
                )

    def preserve_shutdown(self):
        with self.database._write_lock:
            with self.database.conn:
                self.database.conn.execute(
                    "UPDATE download_queue SET resume_on_restart = 1 WHERE status IN ('pending', 'downloading')"
                )
