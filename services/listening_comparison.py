"""On-demand comparisons of two equal listening windows using actual history."""

from datetime import datetime, timedelta, timezone


_DAYS = {'week': 7, 'month': 30, 'year': 365}


def _stamp(moment):
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def listening_comparison(db, period='week', utc_offset_minutes=180, *, now=None, timezone_name=None):
    if period not in _DAYS:
        raise ValueError('Выберите неделю, месяц или год')
    offset = int(utc_offset_minutes)
    if not -720 <= offset <= 840:
        raise ValueError('Некорректный часовой пояс')
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    days = _DAYS[period]
    current_start = moment - timedelta(days=days)
    previous_start = current_start - timedelta(days=days)
    modifier = f'{offset:+d} minutes'
    day_expression = 'date(played_at, ?)'
    day_parameters = (modifier,)
    if timezone_name:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            zone = ZoneInfo(str(timezone_name))
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError('Некорректный часовой пояс') from exc
        def local_day(stamp):
            dt = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
            return dt.replace(tzinfo=timezone.utc).astimezone(zone).date().isoformat() if dt.tzinfo is None else dt.astimezone(zone).date().isoformat()
        db.conn.create_function('_nedotify_local_day', 1, local_day, deterministic=True)
        day_expression, day_parameters = '_nedotify_local_day(played_at)', ()

    def summarize(start, end):
        bounds = (_stamp(start), _stamp(end))
        totals = db.conn.execute('''
            SELECT COUNT(*) AS plays, COALESCE(SUM(MAX(0, duration_listened)), 0) AS seconds,
                   COUNT(DISTINCT track_id) AS tracks
            FROM history WHERE played_at >= ? AND played_at < ? AND duration_listened > 0
        ''', bounds).fetchone()
        artists = [dict(row) for row in db.conn.execute('''
            SELECT t.artist, COUNT(*) AS plays, SUM(h.duration_listened) AS seconds
            FROM history h JOIN tracks t ON t.id = h.track_id
            WHERE h.played_at >= ? AND h.played_at < ? AND h.duration_listened > 0
              AND TRIM(COALESCE(t.artist, '')) != '' AND LOWER(t.artist) != 'unknown artist'
            GROUP BY LOWER(TRIM(t.artist)) ORDER BY seconds DESC, plays DESC, t.artist LIMIT 10
        ''', bounds)]
        daily = [dict(row) for row in db.conn.execute(f'''
            SELECT {day_expression} AS day, COUNT(*) AS plays, SUM(duration_listened) AS seconds
            FROM history WHERE played_at >= ? AND played_at < ? AND duration_listened > 0
            GROUP BY day ORDER BY day
        ''', (*day_parameters, *bounds))]
        return {'start': start.isoformat(), 'end': end.isoformat(),
                'plays': int(totals['plays']), 'seconds': round(float(totals['seconds']), 2),
                'tracks': int(totals['tracks']), 'top_artists': artists, 'daily': daily}

    current, previous = summarize(current_start, moment), summarize(previous_start, current_start)
    deltas = {}
    for key in ('plays', 'seconds', 'tracks'):
        before, after = previous[key], current[key]
        percent = round((after - before) / before * 100, 1) if before else None
        deltas[key] = {'absolute': round(after - before, 2), 'percent': percent}
    new_artists = [dict(row) for row in db.conn.execute('''
        WITH prior AS MATERIALIZED (
            SELECT DISTINCT LOWER(TRIM(older.artist)) AS artist
            FROM history old JOIN tracks older ON older.id = old.track_id
            WHERE old.played_at < ? AND old.duration_listened > 0)
        SELECT t.artist, SUM(h.duration_listened) AS seconds
        FROM history h JOIN tracks t ON t.id = h.track_id
        WHERE h.played_at >= ? AND h.played_at < ? AND h.duration_listened > 0
          AND TRIM(COALESCE(t.artist, '')) != '' AND LOWER(t.artist) != 'unknown artist'
          AND LOWER(TRIM(t.artist)) NOT IN (SELECT artist FROM prior WHERE artist IS NOT NULL)
        GROUP BY LOWER(TRIM(t.artist)) ORDER BY seconds DESC, t.artist LIMIT 10
    ''', (_stamp(current_start), _stamp(current_start), _stamp(moment)))]
    returning_artists = [dict(row) for row in db.conn.execute('''
        WITH prior AS MATERIALIZED (
            SELECT DISTINCT LOWER(TRIM(older.artist)) AS artist
            FROM history old JOIN tracks older ON older.id = old.track_id
            WHERE old.played_at < ? AND old.duration_listened > 0),
        recent AS MATERIALIZED (
            SELECT DISTINCT LOWER(TRIM(familiar.artist)) AS artist
            FROM history h JOIN tracks familiar ON familiar.id = h.track_id
            WHERE h.played_at >= ? AND h.played_at < ? AND h.duration_listened > 0)
        SELECT t.artist, SUM(h.duration_listened) AS seconds
        FROM history h JOIN tracks t ON t.id = h.track_id
        WHERE h.played_at >= ? AND h.played_at < ? AND h.duration_listened > 0
          AND TRIM(COALESCE(t.artist, '')) != '' AND LOWER(t.artist) != 'unknown artist'
          AND LOWER(TRIM(t.artist)) IN (SELECT artist FROM prior)
          AND LOWER(TRIM(t.artist)) NOT IN (SELECT artist FROM recent WHERE artist IS NOT NULL)
        GROUP BY LOWER(TRIM(t.artist)) ORDER BY seconds DESC, t.artist LIMIT 10
    ''', (_stamp(previous_start), _stamp(previous_start), _stamp(current_start), _stamp(current_start), _stamp(moment)))]
    return {'period': period, 'days': days, 'utc_offset_minutes': offset, 'timezone_name': timezone_name,
            'current': current, 'previous': previous, 'delta': deltas, 'new_artists': new_artists,
            'returning_artists': returning_artists}
