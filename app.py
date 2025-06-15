import os
import logging
import MySQLdb
from flask import Flask, request, render_template, session, redirect, url_for, flash, jsonify
from flask_mysqldb import MySQL
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
import random
import uuid
import joblib
from surprise import Dataset, Reader
import pandas as pd

# 로깅 설정
logging.basicConfig(filename='app.log', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
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

# SVD 모델 로드 함수
def load_svd_model():
    try:
        model_path = os.path.join(os.getcwd(), 'model_data', 'svd_model.pkl')
        if not os.path.exists(model_path):
            logger.error(f"SVD model not found at {model_path}. Please train the SVD model first by running svd_model.py.")
            return None
        model = joblib.load(model_path)
        logger.info(f"SVD model loaded from {model_path}")
        return model
    except Exception as e:
        logger.error(f"Error loading SVD model: {str(e)}", exc_info=True)
        return None

# BPR(SVDpp) 모델 로드 함수
def load_bpr_model():
    try:
        model_path = os.path.join(os.getcwd(), 'model_data', 'bpr_model.pkl')
        if not os.path.exists(model_path):
            logger.error(f"BPR model not found at {model_path}. Please train the BPR model first by running BPR_model.py.")
            return None
        model = joblib.load(model_path)
        logger.info(f"BPR model loaded from {model_path}")
        return model
    except Exception as e:
        logger.error(f"Error loading BPR model: {str(e)}", exc_info=True)
        return None

# 전역 변수로 SVD 및 BPR 모델 로드
svd_model = load_svd_model()
bpr_model = load_bpr_model()

def store_recommendations(user_id, article_ids, batch_id=None, algorithm_version='keyword_v1'):
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
                if "1062" in str(e):
                    logger.debug(f"Recommendation already exists for user {user_id}, article {article_id}. Skipping.")
                else:
                    raise e
        conn.commit()
        logger.info(f"Stored {len(article_ids)} recommendations for user {user_id}, batch_id={batch_id}, session_id={session_id}")
    except MySQLdb.Error as e:
        logger.error(f"Error storing recommendations for user {user_id}: {str(e)}", exc_info=True)
        if conn:
            conn.rollback()
    finally:
        if cur:
            cur.close()

def get_recommended_articles(user_id):
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
        logger.error(f"Error getting recommended articles: {str(e)}", exc_info=True)
        return []
    finally:
        if cur:
            cur.close()

def get_keyword_recommendations(user_id, user_article_log=None, user_feedback=None, top_n=10, batch_id=None):
    cur = None
    try:
        cur = mysql.connection.cursor()

        if user_article_log is None:
            cur.execute("SELECT article_id FROM user_article_log WHERE user_id = %s", (user_id,))
            user_article_log = [row['article_id'] for row in cur.fetchall()]
        
        if user_feedback is None:
            cur.execute("SELECT article_id, feedback_type FROM user_feedback WHERE user_id = %s", (user_id,))
            user_feedback = [(row['article_id'], row['feedback_type']) for row in cur.fetchall()]
        
        cur.execute("SELECT search_term, COUNT(*) as frequency FROM user_searches WHERE user_id = %s GROUP BY search_term ORDER BY frequency DESC LIMIT 5", (user_id,))
        search_keywords = [(row['search_term'], row['frequency']) for row in cur.fetchall()]
        
        search_count = len(search_keywords)
        action_count = len(user_article_log)
        logger.debug(f"User {user_id}: searches={search_count}, actions={action_count}")

        if search_count < 3 and action_count < 3:
            logger.debug(f"Insufficient data for user {user_id}, returning popular articles (keyword fallback)")
            cur.execute(f"""
                SELECT a.id, a.title, a.summary, a.category, a.published_at, a.url
                FROM articles a
                LEFT JOIN user_article_log ual ON a.id = ual.article_id
                GROUP BY a.id
                ORDER BY COUNT(ual.id) DESC, a.published_at DESC
                LIMIT {top_n}
            """)  # description -> summary
            articles = cur.fetchall()
            logger.debug(f"Popular articles returned by keyword fallback: {len(articles)}")
            return articles

        action_keywords_temp = {}
        for article_id_log in user_article_log:
            cur.execute("""
                SELECT k.keyword_text
                FROM article_keywords ak
                JOIN keywords k ON ak.keyword_id = k.id
                WHERE ak.article_id = %s
            """, (article_id_log,))
            for row in cur.fetchall():
                action_keywords_temp[row['keyword_text']] = action_keywords_temp.get(row['keyword_text'], 0) + 0.5

        action_keywords = [(k, v) for k, v in action_keywords_temp.items()]
        logger.debug(f"Action keywords: {action_keywords}")

        feedback_keywords_temp = {}
        for article_id_fb, feedback_type_fb in user_feedback:
            cur.execute("""
                SELECT k.keyword_text
                FROM article_keywords ak
                JOIN keywords k ON ak.keyword_id = k.id
                WHERE ak.article_id = %s
            """, (article_id_fb,))
            for row in cur.fetchall():
                weight = 0
                if feedback_type_fb == 'like':
                    weight = 2.0
                elif feedback_type_fb == 'dislike':
                    weight = -2.0
                elif feedback_type_fb == 'read':
                    weight = 1.0
                elif feedback_type_fb == 'click_external_link':
                    weight = 1.5
                feedback_keywords_temp[row['keyword_text']] = feedback_keywords_temp.get(row['keyword_text'], 0) + weight
        feedback_keywords = [(k, v) for k, v in feedback_keywords_temp.items()]
        logger.debug(f"Feedback keywords count: {len(feedback_keywords)}")

        keyword_weights = {}
        for keyword, weight in search_keywords:
            keyword_weights[keyword] = keyword_weights.get(keyword, 0) + weight
        for keyword, weight in action_keywords:
            keyword_weights[keyword] = keyword_weights.get(keyword, 0) + weight
        for keyword, weight in feedback_keywords:
            keyword_weights[keyword] = keyword_weights.get(keyword, 0) + weight

        keywords = sorted([(k, w) for k, w in keyword_weights.items() if w > 0], key=lambda x: x[1], reverse=True)[:5]
        logger.debug(f"Final keywords: {keywords}")

        if not keywords:
            logger.debug(f"No positive keywords, returning popular articles (keyword fallback)")
            cur.execute(f"""
                SELECT a.id, a.title, a.summary, a.category, a.published_at, a.url
                FROM articles a
                LEFT JOIN user_article_log ual ON a.id = ual.article_id
                GROUP BY a.id
                ORDER BY COUNT(ual.id) DESC, a.published_at DESC
                LIMIT {top_n}
            """)  # description -> summary
            articles = cur.fetchall()
            logger.debug(f"Popular articles returned by keyword fallback: {len(articles)}")
            return articles

        selected_keywords = random.choices([k for k, w in keywords], weights=[w for k, w in keywords], k=min(len(keywords), 3))
        
        cur.execute("SELECT article_id FROM user_feedback WHERE user_id = %s AND feedback_type = 'dislike'", (user_id,))
        disliked_article_ids = [row['article_id'] for row in cur.fetchall()]

        recommended_articles = []
        seen_ids = set()
        disliked_ids_str = ','.join(map(str, disliked_article_ids)) if disliked_article_ids else 'NULL'

        for keyword in selected_keywords:
            if len(recommended_articles) >= top_n:
                break
            limit_per_keyword = max(1, top_n // len(selected_keywords)) + 2
            cur.execute(f"""
                SELECT a.id, a.title, a.summary, a.category, a.published_at, a.url
                FROM articles a
                JOIN article_keywords ak ON a.id = ak.article_id
                JOIN keywords k ON ak.keyword_id = k.id
                WHERE k.keyword_text = %s 
                  AND a.id NOT IN ({disliked_ids_str})
                ORDER BY a.published_at DESC
                LIMIT %s
            """, (keyword, limit_per_keyword))  # description -> summary
            articles = cur.fetchall()
            for article in articles:
                if article['id'] not in seen_ids:
                    recommended_articles.append(article)
                    seen_ids.add(article['id'])
                if len(recommended_articles) >= top_n:
                    break

        unique_articles = recommended_articles[:top_n]
        logger.debug(f"Keyword recommendations generated: {len(unique_articles)}")
        logger.info(f"Keyword recommendations for user {user_id}: {len(unique_articles)} articles")
        return unique_articles
    except MySQLdb.Error as e:
        logger.error(f"Error getting keyword recommendations for user {user_id}: {str(e)}", exc_info=True)
        return []
    finally:
        if cur:
            cur.close()

def get_svd_recommendations(user_id, top_n=10, batch_id=None):
    global svd_model
    if svd_model is None:
        logger.warning("SVD model is not loaded. Attempting to reload...")
        svd_model = load_svd_model()
        if svd_model is None:
            logger.error("Failed to load SVD model. Cannot provide SVD recommendations.")
            return []

    cur = None
    try:
        cur = mysql.connection.cursor()

        cur.execute("""
            SELECT article_id FROM user_article_log WHERE user_id = %s
            UNION
            SELECT article_id FROM user_feedback WHERE user_id = %s
            UNION
            SELECT article_id FROM recommended_articles WHERE user_id = %s
        """, (user_id, user_id, user_id))
        interacted_article_ids = {row['article_id'] for row in cur.fetchall()}
        logger.debug(f"User {user_id} has interacted with {len(interacted_article_ids)} articles.")

        cur.execute("SELECT id FROM articles")
        all_article_ids = {row['id'] for row in cur.fetchall()}
        logger.debug(f"Total articles in DB: {len(all_article_ids)}")

        candidate_article_ids = list(all_article_ids - interacted_article_ids)
        if not candidate_article_ids:
            logger.warning(f"No unseen articles for user {user_id} for SVD. Returning popular articles.")
            cur.execute(f"""
                SELECT a.id, a.title, a.summary, a.category, a.published_at, a.url
                FROM articles a
                LEFT JOIN user_article_log ual ON a.id = ual.article_id
                GROUP BY a.id
                ORDER BY COUNT(ual.id) DESC, a.published_at DESC
                LIMIT {top_n}
            """)  # description -> summary
            articles = cur.fetchall()
            return articles
            
        logger.debug(f"Candidate articles for user {user_id}: {len(candidate_article_ids)}")

        predictions = []
        for article_id in candidate_article_ids:
            _, _, _, estimated_rating, _ = svd_model.predict(user_id, article_id, r_ui=None)
            predictions.append((article_id, estimated_rating))

        predictions.sort(key=lambda x: x[1], reverse=True)
        top_recommendations = predictions[:top_n]
        recommended_article_ids = [item[0] for item in top_recommendations]
        
        if recommended_article_ids:
            placeholders = ','.join(['%s'] * len(recommended_article_ids))
            cur.execute(f"""
                SELECT id, title, summary, category, published_at, url
                FROM articles
                WHERE id IN ({placeholders})
                ORDER BY FIELD(id, {placeholders})
            """, recommended_article_ids + recommended_article_ids)  # description -> summary
            articles = cur.fetchall()
            final_ordered_articles = []
            article_map = {article['id']: article for article in articles}
            for article_id in recommended_article_ids:
                if article_id in article_map:
                    final_ordered_articles.append(article_map[article_id])
            logger.debug(f"SVD raw recommended article IDs for user {user_id}: {[rec[0] for rec in top_recommendations]}")
            logger.debug(f"SVD final ordered article IDs for user {user_id}: {[art['id'] for art in final_ordered_articles]}")
            logger.info(f"SVD recommendations for user {user_id}: {len(final_ordered_articles)} articles")
            return final_ordered_articles
        else:
            logger.warning(f"SVD model produced no recommendations for user {user_id}.")
            return []

    except Exception as e:
        logger.error(f"Error getting SVD recommendations for user {user_id}: {str(e)}", exc_info=True)
        return []
    finally:
        if cur:
            cur.close()

def get_bpr_recommendations(user_id, top_n=10, batch_id=None):
    global bpr_model
    if bpr_model is None:
        logger.warning("BPR model is not loaded. Attempting to reload...")
        bpr_model = load_bpr_model()
        if bpr_model is None:
            logger.error(f"Failed to load BPR model for user {user_id}. Cannot provide BPR recommendations.")
            return []

    cur = None
    try:
        cur = mysql.connection.cursor()

        cur.execute("""
            SELECT article_id FROM user_article_log WHERE user_id = %s
            UNION
            SELECT article_id FROM user_feedback WHERE user_id = %s
            UNION
            SELECT article_id FROM recommended_articles WHERE user_id = %s
        """, (user_id, user_id, user_id))
        interacted_article_ids = {row['article_id'] for row in cur.fetchall()}
        logger.debug(f"User {user_id} has interacted with {len(interacted_article_ids)} articles.")

        cur.execute("SELECT id FROM articles")
        all_article_ids = {row['id'] for row in cur.fetchall()}
        logger.debug(f"Total articles in DB: {len(all_article_ids)}")

        candidate_article_ids = list(all_article_ids - interacted_article_ids)
        if not candidate_article_ids:
            logger.warning(f"No unseen articles for user {user_id} for BPR. Returning popular articles.")
            cur.execute(f"""
                SELECT a.id, a.title, a.summary, a.category, a.published_at, a.url
                FROM articles a
                LEFT JOIN user_article_log ual ON a.id = ual.article_id
                GROUP BY a.id
                ORDER BY COUNT(ual.id) DESC, a.published_at DESC
                LIMIT {top_n}
            """)
            articles = cur.fetchall()
            return articles

        logger.debug(f"Candidate articles for user {user_id}: {len(candidate_article_ids)}")

        predictions = []
        for article_id in candidate_article_ids:
            _, _, _, est_rating, _ = bpr_model.predict(str(user_id), str(article_id))
            predictions.append((article_id, est_rating))

        predictions.sort(key=lambda x: x[1], reverse=True)
        recommended_article_ids = [item[0] for item in predictions[:top_n]]

        if recommended_article_ids:
            placeholders = ','.join(['%s'] * len(recommended_article_ids))
            cur.execute(f"""
                SELECT id, title, summary, category, published_at, url
                FROM articles
                WHERE id IN ({placeholders})
                ORDER BY FIELD(id, {placeholders})
            """, recommended_article_ids + recommended_article_ids)
            articles = cur.fetchall()
            final_ordered_articles = []
            article_map = {article['id']: article for article in articles}
            for article_id in recommended_article_ids:
                if article_id in article_map:
                    final_ordered_articles.append(article_map[article_id])
            logger.debug(f"BPR raw recommended article IDs for user {user_id}: {recommended_article_ids}")
            logger.debug(f"BPR final ordered article IDs for user {user_id}: {[art['id'] for art in final_ordered_articles]}")
            logger.info(f"BPR recommendations for user {user_id}: {len(final_ordered_articles)} articles")
            return final_ordered_articles
        else:
            logger.warning(f"BPR model produced no recommendations for user {user_id}.")
            return []

    except Exception as e:
        logger.error(f"Error getting BPR recommendations for user {user_id}: {str(e)}", exc_info=True)
        return []
    finally:
        if cur:
            cur.close()

def log_user_action(user_id, article_id, action_type, read_time=None, scroll_depth=None):
    logger.debug(f"Logging action: user_id={user_id}, article_id={article_id}, action_type={action_type}")
    try:
        cur = mysql.connection.cursor()
        if read_time is not None or scroll_depth is not None:
            cur.execute("""
                INSERT INTO user_article_log (user_id, article_id, action_type, read_time, scroll_depth)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, article_id, action_type, read_time, scroll_depth))
        else:
            cur.execute("""
                INSERT INTO user_article_log (user_id, article_id, action_type)
                VALUES (%s, %s, %s)
            """, (user_id, article_id, action_type))
        mysql.connection.commit()
        logger.debug(f"Action logged: {action_type}")
    except MySQLdb.Error as e:
        mysql.connection.rollback()
        logger.error(f"Error logging action: {str(e)}", exc_info=True)
    finally:
        if cur:
            cur.close()

@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    username = session.get('username', '사용자')
    
    keyword_articles = get_keyword_recommendations(user_id, top_n=10, batch_id='keyword_batch_20250615')
    svd_articles = get_svd_recommendations(user_id, top_n=10, batch_id='svd_batch_20250615')
    bpr_articles = get_bpr_recommendations(user_id, top_n=10, batch_id='bpr_batch_20250615')
    
    if keyword_articles:
        keyword_article_ids = [article['id'] for article in keyword_articles]
        store_recommendations(user_id, keyword_article_ids, batch_id='keyword_batch_20250615', algorithm_version='keyword_v1')
    if svd_articles:
        svd_article_ids = [article['id'] for article in svd_articles]
        store_recommendations(user_id, svd_article_ids, batch_id='svd_batch_20250615', algorithm_version='svd_v1')
    if bpr_articles:
        bpr_article_ids = [article['id'] for article in bpr_articles]
        store_recommendations(user_id, bpr_article_ids, batch_id='bpr_batch_20250615', algorithm_version='bpr_v1')

    return render_template('home.html', username=username, articles=[],
                           keyword_articles=keyword_articles, svd_articles=svd_articles, bpr_articles=bpr_articles)

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
            if cur:
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
            if cur:
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
            logger.debug(f"Search query '{query}' logged for user {session['user_id']}")

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
            """  # description -> summary
            cur.execute(sql_query, (search_term, search_term, search_term))
            articles_results = cur.fetchall()
            logger.info(f"Search query '{query}' returned {len(articles_results)} results for user {session['user_id']}")
        except MySQLdb.Error as e:
            mysql.connection.rollback()
            flash(f"검색 중 오류 발생: {str(e)}", "error")
            logger.error(f"Search error for query '{query}': {str(e)}", exc_info=True)
            return render_template('home.html', articles=[], username=username,
                                   keyword_articles=[], svd_articles=[], bpr_articles=[])
        finally:
            if cur:
                cur.close()
    else:
        logger.debug(f"No search query provided for user {session['user_id']}")
    return render_template('home.html', articles=articles_results, username=username,
                           keyword_articles=[], svd_articles=[], bpr_articles=[])

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
        return render_template('article_detail.html', article=article, user_id=session['user_id'])
    except MySQLdb.Error as e:
        flash(f"기사 로딩 중 오류 발생: {str(e)}", "error")
        logger.error(f"Article load error {article_id}: {str(e)}", exc_info=True)
        return redirect(url_for('home'))
    finally:
        if cur:
            cur.close()

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
        logger.error(f"View article error {article_id}: {str(e)}", exc_info=True)
        return redirect(url_for('home'))
    finally:
        if cur:
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
        logger.error(f"Log action error: {str(e)}", exc_info=True)
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

        if feedback_type in ['like', 'dislike', 'read', 'click_external_link']:
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
            if existing_feedback['feedback_type'] == feedback_type:
                return jsonify({'status': 'success', 'message': f'이미 {feedback_type} 피드백이 제출되었거나 처리되었습니다.'}), 200
            else:
                cur.execute("""
                    UPDATE user_feedback SET feedback_type = %s, created_at = NOW()
                    WHERE user_id = %s AND article_id = %s
                """, (feedback_type, user_id, article_id))
                mysql.connection.commit()
                return jsonify({'status': 'success', 'message': f'피드백을 {feedback_type}로 업데이트 완료'}), 200

        if feedback_type in ['like', 'dislike', 'read', 'click_external_link']:
            cur.execute("""
                INSERT INTO user_feedback (user_id, article_id, feedback_type)
                VALUES (%s, %s, %s)
            """, (user_id, article_id, feedback_type))
            mysql.connection.commit()
            return jsonify({'status': 'success', 'message': f'{feedback_type} 피드백 저장'}), 200

        return jsonify({'status': 'error', 'message': '유효하지 않은 피드백'}), 400
    except MySQLdb.Error as e:
        mysql.connection.rollback()
        logger.error(f"Feedback error for user {user_id}, article {article_id}: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if cur:
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
        logger.error(f"Feedback status error for user {user_id}, article {article_id}: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        if cur:
            cur.close()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)