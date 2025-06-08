import os
from flask import Flask, request, render_template, session, redirect, url_for, flash, jsonify
from flask_mysqldb import MySQL
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
import logging
import MySQLdb

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# .env 파일 로드
load_dotenv()

# Flask 앱 설정
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

def log_user_action(user_id, article_id, action_type, read_time=None, scroll_depth=None):
    """사용자 행동을 user_article_log 테이블에 기록"""
    cur = None
    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            INSERT INTO user_article_log (user_id, article_id, action_type, read_time, scroll_depth)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, article_id, action_type, read_time, scroll_depth))
        mysql.connection.commit()
        logger.info(f"User {user_id} performed action '{action_type}' on article {article_id}")
    except MySQLdb.Error as e:
        mysql.connection.rollback()
        logger.error(f"Error logging user action for user {user_id}, article {article_id}: {str(e)}")
    finally:
        if cur is not None:
            cur.close()

def get_recommended_articles(user_id):
    """사용자 관심 키워드를 기반으로 추천 기사 제공"""
    cur = None
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT COUNT(*) AS count FROM user_searches WHERE user_id = %s", (user_id,))
        search_count = cur.fetchone()['count']
        cur.execute("SELECT COUNT(*) AS count FROM user_article_log WHERE user_id = %s", (user_id,))
        action_count = cur.fetchone()['count']
        if search_count < 5 and action_count < 5:
            return []

        cur.execute("""
            SELECT search_term, COUNT(*) as frequency
            FROM user_searches
            WHERE user_id = %s
            GROUP BY search_term
            ORDER BY frequency DESC
            LIMIT 5
        """, (user_id,))
        search_keywords = [(row['search_term'], row['frequency']) for row in cur.fetchall()]
        
        cur.execute("""
            SELECT k.keyword, COUNT(*) as weight
            FROM user_article_log ual
            JOIN article_keywords ak ON ual.article_id = ak.article_id
            JOIN keywords k ON ak.keyword_id = k.id
            WHERE ual.user_id = %s AND ual.action_type IN ('view', 'click_external_link')
            GROUP BY k.keyword
            ORDER BY weight DESC
            LIMIT 5
        """, (user_id,))
        action_keywords = [(row['keyword'], row['weight'] * 0.5) for row in cur.fetchall()]
        
        cur.execute("""
            SELECT k.keyword, uf.feedback_type
            FROM user_feedback uf
            JOIN article_keywords ak ON uf.article_id = ak.article_id
            JOIN keywords k ON ak.keyword_id = k.id
            WHERE uf.user_id = %s
        """, (user_id,))
        feedback_keywords = cur.fetchall()
        
        keyword_weights = {}
        for keyword, weight in search_keywords:
            keyword_weights[keyword] = keyword_weights.get(keyword, 0) + weight
        for keyword, weight in action_keywords:
            keyword_weights[keyword] = keyword_weights.get(keyword, 0) + weight
        for row in feedback_keywords:
            keyword = row['keyword']
            weight = 2 if row['feedback_type'] == 'like' else -2
            keyword_weights[keyword] = keyword_weights.get(keyword, 0) + weight
        
        keywords = sorted(
            [(k, w) for k, w in keyword_weights.items() if w > 0],
            key=lambda x: x[1], reverse=True
        )[:5]
        keywords = [k for k, w in keywords]
        if not keywords:
            return []
        
        cur.execute("""
            SELECT article_id
            FROM user_feedback
            WHERE user_id = %s AND feedback_type = 'dislike'
        """, (user_id,))
        disliked_article_ids = [row['article_id'] for row in cur.fetchall()]
        
        recommended_articles = []
        for keyword in keywords:
            cur.execute("""
                SELECT a.id, a.title, a.summary, a.category, a.published_at, a.url
                FROM articles a
                JOIN article_keywords ak ON a.id = ak.article_id
                JOIN keywords k ON ak.keyword_id = k.id
                WHERE k.keyword = %s AND a.id NOT IN (%s)
                ORDER BY a.published_at DESC
                LIMIT 2
            """, (keyword, ','.join(map(str, disliked_article_ids)) if disliked_article_ids else '0'))
            recommended_articles.extend(cur.fetchall())
        
        seen_ids = set()
        unique_articles = []
        for article in recommended_articles:
            if article['id'] not in seen_ids:
                unique_articles.append(article)
                seen_ids.add(article['id'])
            if len(unique_articles) >= 10:
                break
                
        return unique_articles
    except MySQLdb.Error as e:
        logger.error(f"Error getting recommended articles for user {user_id}: {str(e)}")
        return []
    finally:
        if cur is not None:
            cur.close()

@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    recommended_articles = get_recommended_articles(session['user_id'])
    return render_template('home.html', username=session['username'], articles=[], search_query=None, recommended_articles=recommended_articles)

@app.route('/register', methods=['GET', 'POST'])
def register():
    cur = None
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
            if cur is not None:
                cur.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    cur = None
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
                flash('로그인 성공!', 'success')
                return redirect(url_for('home'))
            else:
                flash('이메일 또는 비밀번호가 잘못되었습니다.', 'error')
                return redirect(url_for('login'))
        except MySQLdb.Error as e:
            flash(f'DB 연결 오류: {str(e)}', 'error')
            return redirect(url_for('login'))
        finally:
            if cur is not None:
                cur.close()
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    flash('로그아웃되었습니다.', 'success')
    return redirect(url_for('login'))

@app.route('/search_news', methods=['GET'])
def search_news():
    cur = None
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
                   OR k.keyword LIKE %s
                ORDER BY a.published_at DESC
                LIMIT 50
            """
            cur.execute(sql_query, (search_term, search_term, search_term))
            articles_results = cur.fetchall()
        except MySQLdb.Error as e:
            mysql.connection.rollback()
            flash(f"검색 중 오류 발생: {str(e)}", "error")
            logger.error(f"Error during news search for query '{query}': {str(e)}")
        finally:
            if cur is not None:
                cur.close()
    return render_template('home.html', articles=articles_results, username=username, search_query=query, recommended_articles=[])

@app.route('/article/<int:article_id>')
def article_detail(article_id):
    cur = None
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
        logger.error(f"Error loading article {article_id}: {str(e)}")
        return redirect(url_for('home'))
    finally:
        if cur is not None:
            cur.close()
    return render_template('article_detail.html', article=article)

@app.route('/article/<int:article_id>/view')
def view_article(article_id):
    cur = None
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
        logger.error(f"Error viewing article {article_id} for user {session['user_id']}: {str(e)}")
        return redirect(url_for('home'))
    finally:
        if cur is not None:
            cur.close()
    return redirect(article_url)

@app.route('/log_action', methods=['POST'])
def log_action():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': '로그인이 필요합니다.'}), 401
    data = request.get_json()
    article_id = data.get('article_id')
    action_type = data.get('action_type')
    read_time = data.get('read_time')
    scroll_depth = data.get('scroll_depth')
    try:
        log_user_action(session['user_id'], article_id, action_type, read_time, scroll_depth)
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        logger.error(f"Error logging action: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/feedback', methods=['POST'])
def feedback():
    """좋아요/싫어요 피드백 저장 또는 취소"""
    cur = None
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': '로그인이 필요합니다.'}), 401
    data = request.get_json()
    article_id = data.get('article_id')
    feedback_type = data.get('feedback_type')  # 'like', 'dislike', 'cancel'
    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT feedback_type
            FROM user_feedback
            WHERE user_id = %s AND article_id = %s
        """, (session['user_id'], article_id))
        existing_feedback = cur.fetchone()
        
        if feedback_type == 'cancel':
            if existing_feedback:
                cur.execute("""
                    DELETE FROM user_feedback
                    WHERE user_id = %s AND article_id = %s
                """, (session['user_id'], article_id))
                mysql.connection.commit()
                return jsonify({'status': 'success', 'message': '피드백이 취소되었습니다.'}), 200
            else:
                return jsonify({'status': 'error', 'message': '취소할 피드백이 없습니다.'}), 400
        
        if existing_feedback:
            return jsonify({'status': 'error', 'message': '이미 피드백을 제출했습니다.'}), 400
        
        if feedback_type in ['like', 'dislike']:
            cur.execute("""
                INSERT INTO user_feedback (user_id, article_id, feedback_type)
                VALUES (%s, %s, %s)
            """, (session['user_id'], article_id, feedback_type))
            mysql.connection.commit()
            return jsonify({'status': 'success', 'message': f'{feedback_type} 피드백이 저장되었습니다.'}), 200
        
        return jsonify({'status': 'error', 'message': '유효하지 않은 피드백 유형입니다.'}), 400
    except MySQLdb.IntegrityError:
        mysql.connection.rollback()
        return jsonify({'status': 'error', 'message': '이미 피드백을 제출했습니다.'}), 400
    except MySQLdb.Error as e:
        mysql.connection.rollback()
        logger.error(f"Error processing feedback for user {session['user_id']}, article {article_id}: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if cur is not None:
            cur.close()

@app.route('/feedback_status', methods=['POST'])
def feedback_status():
    """특정 기사에 대한 사용자의 피드백 상태 반환"""
    cur = None
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': '로그인이 필요합니다.'}), 401
    data = request.get_json()
    article_id = data.get('article_id')
    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT feedback_type
            FROM user_feedback
            WHERE user_id = %s AND article_id = %s
        """, (session['user_id'], article_id))
        feedback = cur.fetchone()
        return jsonify({
            'status': 'success',
            'feedback_type': feedback['feedback_type'] if feedback else None
        }), 200
    except MySQLdb.Error as e:
        logger.error(f"Error fetching feedback status for user {session['user_id']}, article {article_id}: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if cur is not None:
            cur.close()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)