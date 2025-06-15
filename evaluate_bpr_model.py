import pandas as pd
import numpy as np
from sklearn.metrics import ndcg_score
import logging
import MySQLdb
from flask import Flask
from flask_mysqldb import MySQL
from dotenv import load_dotenv
import os
from app import get_bpr_recommendations, get_keyword_recommendations

# 로깅 설정
logging.basicConfig(filename='evaluate_bpr.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Flask 앱 설정
app = Flask(__name__)
load_dotenv()

# MySQL 설정 (.env에서 가져옴)
app.config['MYSQL_HOST'] = os.getenv('DB_HOST')
app.config['MYSQL_USER'] = os.getenv('DB_USER')
app.config['MYSQL_PASSWORD'] = os.getenv('DB_PASS')
app.config['MYSQL_DB'] = os.getenv('DB_NAME')
app.config['MYSQL_PORT'] = int(os.getenv('DB_PORT', 3306))
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'
mysql = MySQL(app)

def calculate_map_at_k(y_true, y_pred, k=10):
    """MAP@K 계산"""
    ap_scores = []
    for true_items, pred_items in zip(y_true, y_pred):
        if not true_items or not pred_items:
            continue
        hits = 0
        score = 0.0
        for i, pred in enumerate(pred_items[:k], 1):
            if pred in true_items:
                hits += 1
                score += hits / i
        ap_scores.append(score / min(len(true_items), k) if true_items else 0.0)
    return np.mean(ap_scores) if ap_scores else 0.0

def calculate_hit_rate_at_k(y_true, y_pred, k=10):
    """HitRate@K 계산"""
    hits = 0
    total = 0
    for true_items, pred_items in zip(y_true, y_pred):
        if not true_items:
            continue
        total += 1
        if any(pred in true_items for pred in pred_items[:k]):
            hits += 1
    return hits / total if total > 0 else 0.0

def evaluate_model(model_name, get_recommendations_func):
    """모델 평가"""
    try:
        cur = mysql.connection.cursor()
        # user_feedback에서 'like' 피드백 가져오기
        cur.execute("SELECT user_id, article_id FROM user_feedback WHERE feedback_type = 'like'")
        feedback = cur.fetchall()
        logger.info(f"Retrieved {len(feedback)} 'like' feedbacks from user_feedback")
        cur.close()

        # 사용자별 정답 레이블 생성
        y_true = {}
        for row in feedback:
            user_id = row['user_id']
            article_id = row['article_id']
            if user_id not in y_true:
                y_true[user_id] = []
            y_true[user_id].append(article_id)
        logger.info(f"Users with 'like' feedback: {len(y_true)}")

        # 추천 생성 및 평가
        y_pred = {}
        for user_id in y_true:
            articles = get_recommendations_func(user_id, top_n=10)
            y_pred[user_id] = [article['id'] for article in articles]
            logger.debug(f"User {user_id}: True={y_true.get(user_id, [])} Pred={y_pred.get(user_id, [])}")

        # 메트릭 계산
        map_at_10 = calculate_map_at_k([y_true.get(u, []) for u in y_true], [y_pred.get(u, []) for u in y_true], k=10)
        hit_rate_at_10 = calculate_hit_rate_at_k([y_true.get(u, []) for u in y_true], [y_pred.get(u, []) for u in y_true], k=10)

        # NDCG@10 계산
        ndcg_scores = []
        for user_id in y_true:
            true_relevance = [1 if item in y_true[user_id] else 0 for item in y_pred.get(user_id, [])]
            if true_relevance:
                ndcg_scores.append(ndcg_score([true_relevance], [list(range(len(true_relevance), 0, -1))], k=10))
        ndcg_at_10 = np.mean(ndcg_scores) if ndcg_scores else 0.0

        logger.info(f"{model_name} Evaluation: MAP@10={map_at_10:.4f}, NDCG@10={ndcg_at_10:.4f}, HitRate@10={hit_rate_at_10:.4f}")
        print(f"{model_name} Evaluation: MAP@10={map_at_10:.4f}, NDCG@10={ndcg_at_10:.4f}, HitRate@10={hit_rate_at_10:.4f}")
        return map_at_10, ndcg_at_10, hit_rate_at_10

    except MySQLdb.Error as e:
        logger.error(f"Error evaluating {model_name}: {str(e)}", exc_info=True)
        return 0.0, 0.0, 0.0
    except Exception as e:
        logger.error(f"Unexpected error evaluating {model_name}: {str(e)}", exc_info=True)
        return 0.0, 0.0, 0.0

if __name__ == "__main__":
    with app.app_context():
        # 키워드 기반 모델 평가
        evaluate_model("Keyword", get_keyword_recommendations)
        # BPR 모델 평가
        evaluate_model("BPR", get_bpr_recommendations)