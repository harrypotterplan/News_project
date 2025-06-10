import os
import logging
import MySQLdb
import csv
import pandas as pd
from sklearn.metrics import precision_score, recall_score, f1_score
from app import app, get_keyword_recommendations
from dotenv import load_dotenv

# 로깅 설정
logging.basicConfig(filename='crawler.log', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_db_connection():
    """MySQL 데이터베이스 연결 설정"""
    load_dotenv()
    return MySQLdb.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER'),
        passwd=os.getenv('DB_PASS'),
        db=os.getenv('DB_NAME', 'AI_master'),
        port=int(os.getenv('DB_PORT', 3306)),
        charset='utf8mb4'
    )

def evaluate_keyword_model(batch_id, feedback_file='test_feedback.csv'):
    """키워드 추천 모델 평가. batch_id로 추천 세션 고정."""
    with app.app_context():
        conn = None
        cur = None
        try:
            # DB 연결
            conn = get_db_connection()
            cur = conn.cursor(MySQLdb.cursors.DictCursor)
            logger.info(f"Connected to database for evaluation with batch_id={batch_id}")

            # 피드백 데이터 로드
            feedback_df = pd.read_csv(feedback_file)
            users = feedback_df['user_id'].unique()
            logger.info(f"Evaluating for {len(users)} users: {users}")

            # 평가 메트릭 초기화
            precisions, recalls, f1s = [], [], []

            for user_id in users:
                # 추천 생성 (이미 저장된 경우 DB에서 조회)
                cur.execute(
                    """
                    SELECT article_id 
                    FROM recommended_articles 
                    WHERE user_id = %s AND batch_id = %s
                    ORDER BY recommendation_rank
                    """,
                    (user_id, batch_id)
                )
                stored_article_ids = [row['article_id'] for row in cur.fetchall()]

                if not stored_article_ids:
                    # 추천이 없으면 새로 생성
                    recommendations = get_keyword_recommendations(user_id, batch_id=batch_id)
                    stored_article_ids = [rec['id'] for rec in recommendations]
                    logger.debug(f"Generated {len(stored_article_ids)} recommendations for user {user_id}")

                # 피드백 데이터 필터링
                user_feedback = feedback_df[feedback_df['user_id'] == user_id]
                positive_feedback = user_feedback[user_feedback['feedback_type'] == 'like']['article_id'].tolist()

                # 실제/예측 레이블 생성
                y_true = [1 if aid in positive_feedback else 0 for aid in stored_article_ids]
                y_pred = [1] * len(stored_article_ids)  # 추천된 기사는 모두 긍정으로 가정

                # 메트릭 계산
                if len(y_true) > 0:
                    precision = precision_score(y_true, y_pred, zero_division=0)
                    recall = recall_score(y_true, y_pred, zero_division=0)
                    f1 = f1_score(y_true, y_pred, zero_division=0)
                    precisions.append(precision)
                    recalls.append(recall)
                    f1s.append(f1)
                    logger.info(f"User {user_id}: Precision={precision:.3f}, Recall={recall:.3f}, F1={f1:.3f}")

            # 평균 메트릭
            avg_precision = sum(precisions) / len(precisions) if precisions else 0
            avg_recall = sum(recalls) / len(recalls) if recalls else 0
            avg_f1 = sum(f1s) / len(f1s) if f1s else 0
            logger.info(f"Average: Precision={avg_precision:.3f}, Recall={avg_recall:.3f}, F1={avg_f1:.3f}")

            return {
                'precision': avg_precision,
                'recall': avg_recall,
                'f1': avg_f1
            }

        except Exception as e:
            logger.error(f"Evaluation error: {str(e)}")
            raise e
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

if __name__ == "__main__":
    results = evaluate_keyword_model(batch_id="test_batch_20250611")
    print(f"Evaluation Results: {results}")