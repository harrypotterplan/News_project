import pandas as pd
import numpy as np
from sklearn.metrics import ndcg_score
import logging
import MySQLdb
from flask import Flask
from flask_mysqldb import MySQL
from dotenv import load_dotenv
import os

# app.py에서 필요한 함수만 임포트 (get_db_connection은 이 파일에서 정의하므로 제외)
from app import get_keyword_recommendations, get_bpr_recommendations

# 로깅 설정: 파일명도 좀 더 일반적인 evaluate_models.log로 변경
logging.basicConfig(filename='evaluate_models.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Flask 앱 설정
app = Flask(__name__)
load_dotenv()

# MySQL 설정 (이 파일 내에서 직접 설정)
app.config['MYSQL_HOST'] = os.getenv('DB_HOST')
app.config['MYSQL_USER'] = os.getenv('DB_USER')
app.config['MYSQL_PASSWORD'] = os.getenv('DB_PASS')
app.config['MYSQL_DB'] = os.getenv('DB_NAME')
app.config['MYSQL_PORT'] = int(os.getenv('DB_PORT', 3306))
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'
mysql = MySQL(app)

# 이 파일 내에서 DB 연결 함수 정의 (app.py에서 가져올 필요 없음)
def get_db_connection():
    try:
        conn = MySQLdb.connect(
            host=os.getenv('DB_HOST'),
            user=os.getenv('DB_USER'),
            passwd=os.getenv('DB_PASS'),
            db=os.getenv('DB_NAME'),
            port=int(os.getenv('DB_PORT', 3306)),
            charset='utf8mb4'
        )
        # logger.debug("DB 연결 성공!") # 너무 많은 로그 방지를 위해 debug 레벨로 변경
        return conn
    except MySQLdb.Error as e:
        logger.error(f"DB 연결 실패: {str(e)}", exc_info=True)
        return None


def calculate_extended_metrics(predicted_ranks, actual_liked_articles, actual_interacted_articles, k=10):
    ap_sum = 0.0
    ndcg_sum = 0.0
    hit_rate_sum = 0.0
    num_users_evaluated = 0

    for user_id, predicted_list in predicted_ranks.items():
        if user_id not in actual_liked_articles or not actual_liked_articles[user_id]:
            # logger.debug(f"User {user_id} has no liked articles. Skipping evaluation for this user.")
            continue # 해당 사용자에 대해 실제로 좋아한 기사가 없으면 평가에서 제외

        num_users_evaluated += 1
        actual_relevant = set(actual_liked_articles[user_id])
        actual_interacted = set(actual_interacted_articles.get(user_id, []))

        # Calculate Average Precision (AP)
        precision_at_k = []
        hits = 0
        for i, article_id in enumerate(predicted_list[:k], 1):
            if article_id in actual_relevant:
                hits += 1
                precision_at_k.append(hits / i) # Precision@i
        ap = sum(precision_at_k) / len(actual_relevant) if actual_relevant else 0.0 # 실제 관련 항목 수로 나눔 (MAP 정의에 따라)
        ap_sum += ap

        # Calculate Normalized Discounted Cumulative Gain (NDCG)
        dcg = 0.0
        idcg = 0.0
        
        # DCG calculation (using 2^relevance-1 / log2(i+1))
        # BPR은 예측 점수 자체가 절대적인 관련성이 아니므로, 이진 관련성(1 또는 0)을 사용
        # true_relevance를 1 (관련) 또는 0 (비관련)으로 단순화
        for i, article_id in enumerate(predicted_list[:k]):
            if article_id in actual_relevant:
                dcg += 1.0 / np.log2(i + 2) # i+1이 0이 될 수 없으므로 i+2 (log2(1)부터 시작)
            
        # Ideal DCG: 모든 관련 항목이 상위에 있다고 가정
        # 실제 관련 항목 수만큼 1/log2(i+1)을 더함
        for i in range(min(k, len(actual_relevant))): # 실제 relevant 한 아이템 수 만큼 idcg 계산
            idcg += 1.0 / np.log2(i + 2)
            
        ndcg = dcg / idcg if idcg > 0 else 0.0
        ndcg_sum += ndcg

        # Calculate HitRate (At least one liked item is in top-K)
        if any(pred in actual_relevant for pred in predicted_list[:k]):
            hit_rate_sum += 1

    map_score = ap_sum / num_users_evaluated if num_users_evaluated > 0 else 0.0
    ndcg_score = ndcg_sum / num_users_evaluated if num_users_evaluated > 0 else 0.0
    hit_rate = hit_rate_sum / num_users_evaluated if num_users_evaluated > 0 else 0.0
    
    return map_score, ndcg_score, hit_rate

def evaluate_recommendation_model(user_id, model_type='keyword', batch_id=None, k=10):
    with app.app_context():
        conn = None
        cur = None
        try:
            conn = get_db_connection() # 이 파일의 get_db_connection 사용
            cur = conn.cursor(MySQLdb.cursors.DictCursor)
            logger.info(f"Evaluating {model_type} model for user {user_id}, k={k}")

            # 'like' 피드백만 실제 정답(Ground Truth)으로 사용
            cur.execute("SELECT article_id FROM user_feedback WHERE user_id = %s AND feedback_type = 'like'", (user_id,))
            actual_liked_articles_ids = [row['article_id'] for row in cur.fetchall()]
            
            # 모든 상호작용 기록 (HitRate 계산용)
            cur.execute("SELECT article_id FROM user_article_log WHERE user_id = %s", (user_id,))
            actual_interacted_articles_ids_log = [row['article_id'] for row in cur.fetchall()]
            cur.execute("SELECT article_id FROM user_feedback WHERE user_id = %s", (user_id,))
            actual_interacted_articles_ids_feedback = [row['article_id'] for row in cur.fetchall()]
            actual_interacted_articles_ids = list(set(actual_interacted_articles_ids_log + actual_interacted_articles_ids_feedback))


            predicted_recommendations_info = []
            if model_type == 'keyword':
                predicted_recommendations_info = get_keyword_recommendations(user_id, top_n=k, batch_id=batch_id)
            elif model_type == 'bpr':
                predicted_recommendations_info = get_bpr_recommendations(user_id, top_n=k, batch_id=batch_id)
            else:
                logger.error(f"Unknown model type: {model_type}")
                return {'map': 0, 'ndcg': 0, 'hit_rate': 0}

            predicted_article_ids = [article['id'] for article in predicted_recommendations_info]
            logger.debug(f"User {user_id} - Predicted: {predicted_article_ids}")
            logger.debug(f"User {user_id} - Actual Liked: {actual_liked_articles_ids}")
            # logger.debug(f"User {user_id} - Intersection Liked: {set(predicted_article_ids) & set(actual_liked_articles_ids)}")
            # logger.debug(f"User {user_id} - Actual Interacted: {actual_interacted_articles_ids[:5]}... (total {len(actual_interacted_articles_ids)})")

            map_score, ndcg_score, hit_rate = calculate_extended_metrics(
                {user_id: predicted_article_ids},
                {user_id: actual_liked_articles_ids},
                {user_id: actual_interacted_articles_ids},
                k=k
            )
            logger.info(f"User {user_id} - {model_type} Model - MAP@{k}={map_score:.3f}, NDCG@{k}={ndcg_score:.3f}, HitRate@{k}={hit_rate:.3f}")
            return {'map': map_score, 'ndcg': ndcg_score, 'hit_rate': hit_rate}

        except MySQLdb.Error as e:
            logger.error(f"Error evaluating {model_type} model for user {user_id}: {str(e)}", exc_info=True)
            return {'map': 0, 'ndcg': 0, 'hit_rate': 0}
        except Exception as e:
            logger.error(f"Unexpected error evaluating {model_type} model for user {user_id}: {str(e)}", exc_info=True)
            return {'map': 0, 'ndcg': 0, 'hit_rate': 0}
        finally:
            if cur:
                cur.close()
            # if conn: # evaluate_recommendation_model 에서는 connection을 닫지 않음 (Flask context에서 관리)
            #     conn.close()

def evaluate_all_users(model_type='bpr', k=10):
    logger.info(f"--- {model_type.upper()} Model Evaluation Started ---")
    conn = None
    cur = None
    try:
        conn = get_db_connection() # 이 파일의 get_db_connection 사용
        cur = conn.cursor()
        # 'like' 피드백을 가진 사용자만 평가 대상에 포함
        cur.execute("SELECT DISTINCT user_id FROM user_feedback WHERE feedback_type = 'like'")
        user_ids = [row[0] for row in cur.fetchall()]
        logger.info(f"평가 대상 사용자 수 (liked articles 기준): {len(user_ids)}")

        if not user_ids:
            logger.warning(f"No users with 'like' feedback found for {model_type} model evaluation.")
            return {'avg_map': 0, 'avg_ndcg': 0, 'avg_hit_rate': 0}

        map_scores = []
        ndcg_scores = []
        hit_rates = []
        for user_id in user_ids:
            metrics = evaluate_recommendation_model(user_id, model_type=model_type, k=k)
            map_scores.append(metrics['map'])
            ndcg_scores.append(metrics['ndcg'])
            hit_rates.append(metrics['hit_rate'])

        avg_map = sum(map_scores) / len(map_scores) if map_scores else 0
        avg_ndcg = sum(ndcg_scores) / len(ndcg_scores) if ndcg_scores else 0
        avg_hit_rate = sum(hit_rates) / len(hit_rates) if hit_rates else 0
        logger.info(f"--- {model_type.upper()} Model Average Results ---")
        logger.info(f"MAP@{k}={avg_map:.4f}, NDCG@{k}={avg_ndcg:.4f}, HitRate@{k}={avg_hit_rate:.4f}")
        print(f"--- {model_type.upper()} Model Average Results ---")
        print(f"MAP@{k}={avg_map:.4f}, NDCG@{k}={avg_ndcg:.4f}, HitRate@{k}={avg_hit_rate:.4f}")

        return {'avg_map': avg_map, 'avg_ndcg': avg_ndcg, 'avg_hit_rate': avg_hit_rate}

    except Exception as e:
        logger.error(f"전체 사용자 평가 오류 ({model_type} 모델): {str(e)}", exc_info=True)
        return {'avg_map': 0, 'avg_ndcg': 0, 'avg_hit_rate': 0}
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

if __name__ == "__main__":
    with app.app_context():
        # 키워드 모델 평가 실행
        evaluate_all_users(model_type='keyword', k=10)
        print("\n") # 구분선
        # BPR 모델 평가 실행
        evaluate_all_users(model_type='bpr', k=10)
