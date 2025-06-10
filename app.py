import os
import logging
import MySQLdb
from flask import Flask, request, render_template, session, redirect, url_for, flash, jsonify
from flask_mysqldb import MySQL
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
import random
import uuid

# 로깅 설정
logging.basicConfig(filename='crawler.log', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Flask 앱 설정
load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', os.urandom(24).hex())

# MySQL 설정
app.config['MYSQL_HOST'] = os.getenv('DB_HOST')
app.config['MYSQL_USER'] = os.getenv('DB_USER')
app.config['MYSQL_PASSWORD'] = os.getenv('DB_PASS')
app.config['MYSQL_DB'] = os.getenv('DB_NAME')
app.config['MYSQL_PORT'] = int(os.getenv('DB_PORT', 3306))
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

mysql = MySQL(app)
bcrypt = Bcrypt(app)

def store_recommendations(user_id, article_ids, batch_id=None, algorithm_version='keyword_v1'):
    """
    사용자에게 추천된 기사 목록을 recommended_articles 테이블에 저장합니다.
    이전 추천을 삭제하지 않고 새 이력을 추가합니다.
    """
    try:
        conn = mysql.connection.cursor().connection
        cur = conn.cursor()
        session_id = str(uuid.uuid4())[:8] if batch_id is None else batch_id

        for rank, article_id in enumerate(article_ids, 1):
            try:
                cur.execute(
                    """
                    INSERT INTO recommended_articles 
                    (user_id, article_id, recommendation_rank, recommendation_score, recommended_at, batch_id, recommendation_algorithm_version, recommendation_session_id)
                    VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s)
                    """,
                    (user_id, article_id, rank, 1.0 / rank, batch_id, algorithm_version, session_id)
                )
            except MySQLdb.Error as e:
                if "1062" in str(e):  # Duplicate entry
                    logger.debug(f"Recommendation already exists for user {user_id}, article {article_id}. Skipping.")
                else:
                    raise e
        conn.commit()
        logger.info(f"Stored {len(article_ids)} recommendations for user {user_id}, batch_id={batch_id}, session_id={session_id}")
    except MySQLdb.Error as e:
        logger.error(f"Error storing recommendations for user {user_id}: {str(e)}")
        if conn:
            conn.rollback()
    finally:
        if cur:
            cur.close()

def get_recommended_articles(user_id):
    """recommended_articles에서 추천 조회
    - user_id: 현재 사용자 ID
    - 순위 기준으로 상위 10개 기사 반환
    - 참고: 현재는 키워드 추천으로 대체되었으나, 호환성을 위해 남겨둠"""
    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT a.id, a.title, a.summary, a.category, a.published_at, a.url
            FROM recommended_articles ra
            JOIN articles a ON ra.article_id = a.id
            WHERE ra.user_id = %s
            ORDER BY ra.recommendation_rank
            LIMIT 10
        """, (user_id,))
        articles = cur.fetchall()
        logger.debug(f"Retrieved {len(articles)} recommendations for user {user_id}")
        return articles
    except MySQLdb.Error as e:
        logger.error(f"Error getting recommended articles: {str(e)}")
        return []
    finally:
        cur.close()

def get_keyword_recommendations(user_id, batch_id=None):
    """키워드 기반 추천
    - user_id: 현재 사용자 ID
    - 검색어, 행동 로그, 피드백을 기반으로 기사 추천"""
    cur = None
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT COUNT(*) AS count FROM user_searches WHERE user_id = %s", (user_id,))
        search_count = cur.fetchone()['count']
        cur.execute("SELECT COUNT(*) AS count FROM user_article_log WHERE user_id = %s", (user_id,))
        action_count = cur.fetchone()['count']
        logger.debug(f"User {user_id}: searches={search_count}, actions={action_count}")

        if search_count < 3 and action_count < 3:
            logger.debug(f"Insufficient data for user {user_id}, returning popular articles")
            cur.execute("""
                SELECT a.id, a.title, a.summary, a.category, a.published_at, a.url
                FROM articles a
                LEFT JOIN user_article_log ual ON a.id = ual.article_id
                GROUP BY a.id
                ORDER BY COUNT(ual.id) DESC, a.published_at DESC
                LIMIT 10
            """)
            articles = cur.fetchall()
            logger.debug(f"Popular articles returned: {len(articles)}")
            return articles

        cur.execute("""
            SELECT search_term, COUNT(*) as frequency
            FROM user_searches
            WHERE user_id = %s
            GROUP BY search_term
            ORDER BY frequency DESC
            LIMIT 5
        """, (user_id,))
        search_keywords = [(row['search_term'], row['frequency']) for row in cur.fetchall()]
        logger.debug(f"Search keywords: {search_keywords}")

        cur.execute("""
            SELECT k.keyword_text, COUNT(*) as weight
            FROM user_article_log ual
            JOIN article_keywords ak ON ual.article_id = ak.article_id
            JOIN keywords k ON ak.keyword_id = k.id
            WHERE ual.user_id = %s AND ual.action_type IN ('view', 'read', 'click_external_link')
            GROUP BY k.keyword_text
            ORDER BY weight DESC
            LIMIT 5
        """, (user_id,))
        action_keywords = [(row['keyword_text'], row['weight'] * 0.5) for row in cur.fetchall()]
        logger.debug(f"Action keywords: {action_keywords}")

        cur.execute("""
            SELECT k.keyword_text, uf.feedback_type
            FROM user_feedback uf
            JOIN article_keywords ak ON uf.article_id = ak.article_id
            JOIN keywords k ON ak.keyword_id = k.id
            WHERE uf.user_id = %s
        """, (user_id,))
        feedback_keywords = cur.fetchall()
        logger.debug(f"Feedback keywords: {len(feedback_keywords)}")

        keyword_weights = {}
        for keyword, weight in search_keywords:
            keyword_weights[keyword] = keyword_weights.get(keyword, 0) + weight
        for keyword, weight in action_keywords:
            keyword_weights[keyword] = keyword_weights.get(keyword, 0) + weight
        for row in feedback_keywords:
            keyword = row['keyword_text']
            weight = 2 if row['feedback_type'] == 'like' else -2
            keyword_weights[keyword] = keyword_weights.get(keyword, 0) + weight

        keywords = sorted([(k, w) for k, w in keyword_weights.items() if w > 0], key=lambda x: x[1], reverse=True)[:5]
        logger.debug(f"Final keywords: {keywords}")

        if not keywords:
            logger.debug(f"No keywords, returning popular articles")
            cur.execute("""
                SELECT a.id, a.title, a.summary, a.category, a.published_at, a.url
                FROM articles a
                LEFT JOIN user_article_log ual ON a.id = ual.article_id
                GROUP BY a.id
                ORDER BY COUNT(ual.id) DESC, a.published_at DESC
                LIMIT 10
            """)
            articles = cur.fetchall()
            logger.debug(f"Popular articles returned: {len(articles)}")
            return articles

        selected_keywords = random.choices([k for k, w in keywords], weights=[w for k, w in keywords], k=3)
        cur.execute("SELECT article_id FROM user_feedback WHERE user_id = %s AND feedback_type = 'dislike'", (user_id,))
        disliked_article_ids = [row['article_id'] for row in cur.fetchall()]

        recommended_articles = []
        for keyword in selected_keywords:
            cur.execute(f"""
                SELECT a.id, a.title, a.summary, a.category, a.published_at, a.url
                FROM articles a
                JOIN article_keywords ak ON a.id = ak.article_id
                JOIN keywords k ON ak.keyword_id = k.id
                WHERE k.keyword_text = %s AND a.id NOT IN ({','.join(map(str, disliked_article_ids)) if disliked_article_ids else '0'})
                ORDER BY a.published_at DESC
                LIMIT 3
            """, (keyword,))
            articles = cur.fetchall()
            recommended_articles.extend(articles)
            if len(recommended_articles) >= 10:
                break

        seen_ids = set()
        unique_articles = []
        for article in recommended_articles:
            if article['id'] not in seen_ids:
                unique_articles.append(article)
                seen_ids.add(article['id'])
            if len(unique_articles) >= 10:
                break
        logger.debug(f"Unique articles generated: {len(unique_articles)}")

        # 추천 결과를 recommended_articles에 저장
        article_ids = [article['id'] for article in unique_articles]
        store_recommendations(user_id, article_ids, batch_id=batch_id, algorithm_version='keyword_v1')

        logger.info(f"Keyword recommendations for user {user_id}: {len(unique_articles)} articles")
        return unique_articles
    except MySQLdb.Error as e:
        logger.error(f"Error getting keyword recommendations: {str(e)}")
        return []
    finally:
        if cur:
            cur.close()

def log_user_action(user_id, article_id, action_type, read_time=None, scroll_depth=None):
    """사용자 행동 로깅
    - user_id: 현재 사용자 ID
    - article_id: 기사 ID
    - action_type: 행동 유형 (view, read 등)
    - read_time, scroll_depth: 추가 데이터 (선택)"""
    logger.debug(f"Logging action: user_id={user_id}, article_id={article_id}, action_type={action_type}")
    try:
        cur = mysql.connection.cursor()
        scroll_depth = float(scroll_depth) if scroll_depth is not None else None
        cur.execute("""
            INSERT INTO user_article_log (user_id, article_id, action_type, read_time, scroll_depth)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, article_id, action_type, read_time, scroll_depth))
        mysql.connection.commit()
        logger.debug(f"Action logged: {action_type}")
    except MySQLdb.Error as e:
        mysql.connection.rollback()
        logger.error(f"Error logging action: {str(e)}")
    finally:
        cur.close()

@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    # LightFM 대신 키워드 추천만 사용
    keyword_articles = get_keyword_recommendations(session['user_id'])
    logger.debug(f"Home rendered for user {session['user_id']}: Keyword={len(keyword_articles)}")
    return render_template('home.html', username=session['username'], articles=[],
                           keyword_articles=keyword_articles)  # lightfm_articles 제거

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        username = request.form['username']
        password = request.form['password']
        password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
        try:
            cur = mysql.connection.cursor()
            cur.execute(
                "INSERT INTO users (email, username, password_hash) VALUES (%s, %s, %s)",
                (email, username, password_hash)
            )
            mysql.connection.commit()
            flash('회원가입 성공! 로그인해주세요.', 'success')
            return redirect(url_for('login'))
        except MySQLdb.IntegrityError:
            mysql.connection.rollback()
            flash('이메일이 이미 존재합니다.', 'error')
        except MySQLdb.Error as e:
            mysql.connection.rollback()
            flash(f'DB 연결 오류: {str(e)}', 'error')
        finally:
            cur.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        try:
            cur = mysql.connection.cursor()
            cur.execute("SELECT id, username, password_hash FROM users WHERE email = %s", [email])
            user = cur.fetchone()
            if user and bcrypt.check_password_hash(user['password_hash'], password):
                session['user_id'] = user['id']
                session['username'] = user['username']
                logger.debug(f"User logged in: id={user['id']}, username={user['username']}")
                flash('로그인 성공!', 'success')
                return redirect(url_for('home'))
            else:
                flash('이메일 또는 비밀번호가 잘못되었습니다.', 'error')
        except MySQLdb.Error as e:
            flash(f'DB 연결 오류: {str(e)}', 'error')
        finally:
            cur.close()
    return render_template('login.html')

@app.route('/logout')
def logout():
    user_id = session.get('user_id')
    session.pop('user_id', None)
    session.pop('username', None)
    logger.debug(f"User logged out: id={user_id}")
    flash('로그아웃되었습니다.', 'success')
    return redirect(url_for('login'))

@app.route('/search_news', methods=['GET'])
def search_news():
    if 'user_id' not in session:
        flash('로그인이 필요합니다.', 'error')
        return redirect(url_for('login'))
    query = request.args.get('query')
    articles_results = []
    username = session.get('username', '사용자')
    if query:
        try:
            cur = mysql.connection.cursor()
            cur.execute("INSERT INTO user_searches (user_id, search_term) VALUES (%s, %s)",
                        (session['user_id'], query))
            mysql.connection.commit()
            search_term = f"%{query}%"
            sql_query = """
                SELECT DISTINCT
                    a.id, a.title, a.summary, a.category, a.published_at, a.url
                FROM articles a
                LEFT JOIN article_keywords ak ON a.id = ak.article_id
                LEFT JOIN keywords k ON ak.keyword_id = k.id
                WHERE a.title LIKE %s
                   OR a.summary LIKE %s
                   OR k.keyword_text LIKE %s
                ORDER BY a.published_at DESC
                LIMIT 50
            """
            cur.execute(sql_query, (search_term, search_term, search_term))
            articles_results = cur.fetchall()
        except MySQLdb.Error as e:
            mysql.connection.rollback()
            flash(f"검색 중 오류 발생: {str(e)}", "error")
            logger.error(f"Search error for query '{query}': {str(e)}")
        finally:
            cur.close()
    return render_template('home.html', articles=articles_results, username=username,
                           keyword_articles=[])  # lightfm_articles 제거

@app.route('/article/<int:article_id>')
def article_detail(article_id):
    if 'user_id' not in session:
        flash('로그인이 필요합니다.', 'error')
        return redirect(url_for('login'))
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT id, title, summary, category, published_at, url, full_content FROM articles WHERE id = %s", (article_id,))
        article = cur.fetchone()
        if not article:
            flash('존재하지 않는 기사입니다.', 'error')
            return redirect(url_for('home'))
        log_user_action(session['user_id'], article_id, 'view')
    except MySQLdb.Error as e:
        flash(f"기사 로딩 중 오류 발생: {str(e)}", "error")
        logger.error(f"Article load error {article_id}: {str(e)}")
        return redirect(url_for('home'))
    finally:
        cur.close()
    return render_template('article_detail.html', article=article)

@app.route('/article/<int:article_id>/view')
def view_article(article_id):
    if 'user_id' not in session:
        flash('로그인이 필요합니다.', 'error')
        return redirect(url_for('login'))
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT url FROM articles WHERE id = %s", (article_id,))
        article = cur.fetchone()
        if not article:
            flash('존재하지 않는 기사입니다.', 'error')
            return redirect(url_for('home'))
        log_user_action(session['user_id'], article_id, 'click_external_link')
        article_url = article['url']
    except MySQLdb.Error as e:
        flash(f"기사 로딩 중 오류 발생: {str(e)}", "error")
        logger.error(f"View article error {article_id}: {str(e)}")
        return redirect(url_for('home'))
    finally:
        cur.close()
    return redirect(article_url)

@app.route('/log_action', methods=['POST'])
def log_action():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': '로그인이 필요합니다.'}), 401
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        if str(user_id) != str(session['user_id']):
            return jsonify({'status': 'error', 'message': '유효하지 않은 사용자 ID입니다.'}), 403
        article_id = data.get('article_id')
        action_type = data.get('action_type')
        read_time = data.get('read_time')
        scroll_depth = data.get('scroll_depth')
        log_user_action(user_id, article_id, action_type, read_time, scroll_depth)
        return jsonify({'status': 'success', 'message': '액션 로깅 완료'}), 200
    except Exception as e:
        logger.error(f"Log action error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/feedback', methods=['POST'])
def feedback():
    data = request.get_json()
    user_id = data.get('user_id') or session.get('user_id')
    if not user_id:
        return jsonify({'status': 'error', 'message': '로그인이 필요합니다.'}), 401
    if str(user_id) != str(session['user_id']):
        return jsonify({'status': 'error', 'message': '유효하지 않은 사용자 ID입니다.'}), 403
    article_id = data.get('article_id')
    feedback_type = data.get('feedback_type')
    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT feedback_type
            FROM user_feedback
            WHERE user_id = %s AND article_id = %s
        """, (user_id, article_id))
        existing_feedback = cur.fetchone()

        if feedback_type in ['like', 'dislike']:
            log_user_action(user_id, article_id, f'feedback_{feedback_type}')

        if feedback_type == 'cancel':
            if existing_feedback:
                cur.execute("""
                    DELETE FROM user_feedback
                    WHERE user_id = %s AND article_id = %s
                """, (user_id, article_id))
                mysql.connection.commit()
                return jsonify({'status': 'success', 'message': '피드백 취소 완료'}), 200
            return jsonify({'status': 'error', 'message': '취소할 피드백 없음'}), 400

        if existing_feedback:
            return jsonify({'status': 'error', 'message': '이미 피드백 제출됨'}), 400

        if feedback_type in ['like', 'dislike']:
            cur.execute("""
                INSERT INTO user_feedback (user_id, article_id, feedback_type)
            VALUES (%s, %s, %s)
            """, (user_id, article_id, feedback_type))
            mysql.connection.commit()
            return jsonify({'status': 'success', 'message': f'{feedback_type} 피드백 저장'}), 200

        return jsonify({'status': 'error', 'message': '유효하지 않은 피드백'}), 400
    except MySQLdb.Error as e:
        mysql.connection.rollback()
        logger.error(f"Feedback error for user {user_id}, article {article_id}: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cur.close()

@app.route('/feedback_status', methods=['POST'])
def feedback_status():
    data = request.get_json()
    user_id = data.get('user_id') or session.get('user_id')
    if not user_id:
        return jsonify({'status': 'error', 'message': '로그인이 필요합니다.'}), 401
    if str(user_id) != str(session['user_id']):
        return jsonify({'status': 'error', 'message': '유효하지 않은 사용자 ID입니다.'}), 403
    article_id = data.get('article_id')
    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT feedback_type
            FROM user_feedback
            WHERE user_id = %s AND article_id = %s
        """, (user_id, article_id))
        feedback = cur.fetchone()
        return jsonify({
            'status': 'success',
            'feedback_type': feedback['feedback_type'] if feedback else None
        }), 200
    except MySQLdb.Error as e:
        logger.error(f"Feedback status error for user {user_id}, article {article_id}: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cur.close()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)