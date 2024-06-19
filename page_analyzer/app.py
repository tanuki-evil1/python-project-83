import bs4.element
import psycopg2
import requests
import os
import validators
from psycopg2 import extras
from datetime import datetime
from dotenv import load_dotenv
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from flask import (Flask,
                   render_template,
                   request,
                   redirect,
                   url_for,
                   flash,
                   get_flashed_messages)

load_dotenv()
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
DATABASE_URL = os.getenv('DATABASE_URL')


def formatter(string: str) -> str:
    if isinstance(string, bs4.element.Tag):
        string = string.get_text()

    if string is None:
        return ''
    elif len(string) > 255:
        return string[:252] + '...'
    else:
        return string


@app.route('/')
def index():
    return render_template('index.html')


@app.get('/urls')
def get_urls():
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor(cursor_factory=extras.DictCursor) as cur:
            cur.execute("""
            WITH pre_result AS (
                SELECT
                    MAX(url_checks.id) AS last_id,
                    urls.id,
                    urls.name
                FROM urls
                LEFT JOIN url_checks ON urls.id = url_checks.url_id
                GROUP BY urls.id, urls.name)

            SELECT
                pre_result.id,
                pre_result.name,
                url_checks.created_at,
                url_checks.status_code
            FROM pre_result
            LEFT JOIN url_checks ON pre_result.last_id = url_checks.id
            ORDER BY pre_result.id DESC;
            """)
            urls = cur.fetchall()
    return render_template('urls.html', urls=urls)


@app.post('/urls')
def post_urls():
    url = request.form.get('url')
    if validators.url(url):
        parsed_url = urlparse(url)
        normalized_url = f'{parsed_url.scheme}://{parsed_url.hostname}'
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor(cursor_factory=extras.DictCursor) as cur:
                cur.execute("""
                    SELECT id, name
                    FROM urls
                    WHERE name = %s
                    """, (normalized_url,))
                f_url = cur.fetchone()
                if f_url and f_url['name'] == normalized_url:
                    flash('Страница уже существует', 'info')
                    return redirect(url_for('get_url', url_id=f_url['id']), 302)
                else:
                    cur.execute("""
                    INSERT INTO urls (name, created_at) VALUES (%s, %s);""",
                                (normalized_url, datetime.now()))
                    cur.execute('SELECT id FROM urls ORDER BY id DESC LIMIT 1;')
                    url_id = cur.fetchone()[0]
                    flash('Страница успешно добавлена', 'success')
                    return redirect(url_for('get_url', url_id=url_id), 302)
    else:
        flash('Некорректный URL', 'danger')
        flashed_messages = get_flashed_messages(with_categories=True)[0]
        msg = {'type': flashed_messages[0], 'msg': flashed_messages[1]}
        return render_template('index.html', url=url, messages=msg), 422


@app.get('/urls/<int:url_id>')
def get_url(url_id: int):
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor(cursor_factory=extras.DictCursor) as cur:
            cur.execute('SELECT * FROM urls WHERE id = %s;', (url_id,))
            url = cur.fetchone()
            cur.execute('SELECT * '
                        'FROM url_checks '
                        'WHERE url_id = %s '
                        'ORDER BY id DESC;',
                        (url_id,))
            checks = cur.fetchall()
    flashed_messages = get_flashed_messages(with_categories=True)
    if flashed_messages:
        msg = {'type': flashed_messages[0][0], 'msg': flashed_messages[0][1]}
    else:
        msg = ''
    return render_template('url.html', url=url, checks=checks, messages=msg)


@app.post('/urls/<int:url_id>/checks')
def post_url(url_id: int):
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM urls WHERE id = %s;', (url_id,))
            url = cur.fetchone()[1]
            response = requests.get(url)
            try:
                response.raise_for_status()
                soup = BeautifulSoup(response.content, 'html.parser')

                status_code = response.status_code
                title = formatter(soup.find('title'))
                description = soup.find('meta', attrs={'name': 'description'})
                description = formatter(description.get('content'))
                h1 = formatter(soup.find('h1'))

                cur.execute("""
                INSERT INTO url_checks
                (url_id, h1, title, status_code, description, created_at)
                VALUES
                (%s, %s, %s, %s, %s, %s);
                """,
                            (url_id,
                             h1,
                             title,
                             status_code,
                             description,
                             datetime.now()))
                flash('Страница успешно проверена', 'success')
            except requests.HTTPError:
                flash('Произошла ошибка при проверке', 'danger')
    return redirect(url_for('get_url', url_id=url_id), 302)
