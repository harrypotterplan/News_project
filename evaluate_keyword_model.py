import os
import logging
import MySQLdb
import csv
from app import app, get_keyword_recommendations  # app과 함수 임포트
from dotenv import load_dotenv

# 로깅 설정
logging.basicConfig(filename='crawler.log', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_db_connection():
    """MySQL 데이터베이스 연결 설정"""
    load_dotenv()
    return MySQLdb.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        passwd=os.getenv('DB_PASS'),
        db=os.getenv('DB_NAME'),
        port=int(os.getenv('DB_PORT', 3306)),
        charset='utf8mb4'
    )

def load_test_data(file_path):
    """테스트 데이터 로드"""
    test_data = {}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or 'user_id' not in reader.fieldnames or 'article_id' not in reader.fieldnames:
                logger.error(f"Invalid CSV format in {file_path}: missing required columns")
                return {}
            for row in reader:
                user_id = int(row['user_id'])
                article_id = int(row['article_id'])
                if user_id not in test_data:
                    test_data[user_id] = set()
                test_data[user_id].add(article_id)
        logger.debug(f"Loaded test data for {len(test_data)} users from {file_path}")
        return test_data
    except FileNotFoundError:
        logger.error(f"Test data file not found: {file_path}")
        return {}
    except Exception as e:
        logger.error(f"Error loading test data: {str(e)}")
        return {}

def evaluate_keyword_model():
    """키워드 추천 모델의 성능 평가
    - 정밀도, 재현율, F1 스코어를 계산"""
    with app.app_context():  # Flask 앱 컨텍스트 생성
        conn = get_db_connection()
        try:
            cur = conn.cursor(MySQLdb.cursors.DictCursor)
            cur.execute("SELECT DISTINCT id FROM users LIMIT 5")  # 사용자 ID 조회
            user_ids = [row['id'] for row in cur.fetchall()]
            logger.debug(f"Retrieved user IDs: {user_ids}")
            
            # 테스트 데이터 로드 (프로젝트 폴더 기준)
            test_data = load_test_data('test_feedback.csv')
            if not test_data:
                logger.warning("No test data loaded")
                print("No test data loaded.")
                return

            total_precision = 0
            total_recall = 0
            num_users = 0

            for user_id in user_ids:
                # 실제 관심 기사 (테스트 데이터)
                true_positives = test_data.get(user_id, set())
                logger.debug(f"User {user_id} true positives: {true_positives}")

                # 추천 기사
                recommended = get_keyword_recommendations(user_id)
                recommended_ids = set(article['id'] for article in recommended)
                logger.debug(f"User {user_id} recommended IDs: {recommended_ids}")

                if not true_positives or not recommended_ids:
                    logger.debug(f"Skipping user {user_id}: no true positives or recommendations")
                    continue

                # 정밀도 계산 (추천 중 맞는 비율)
                precision = len(true_positives & recommended_ids) / len(recommended_ids) if recommended_ids else 0
                # 재현율 계산 (실제 중 추천된 비율)
                recall = len(true_positives & recommended_ids) / len(true_positives) if true_positives else 0

                total_precision += precision
                total_recall += recall
                num_users += 1
                logger.debug(f"User {user_id}: Precision={precision:.4f}, Recall={recall:.4f}")

            if num_users > 0:
                avg_precision = total_precision / num_users
                avg_recall = total_recall / num_users
                avg_f1 = 2 * (avg_precision * avg_recall) / (avg_precision + avg_recall) if (avg_precision + avg_recall) > 0 else 0
                logger.info(f"Average Precision: {avg_precision:.4f}, Recall: {avg_recall:.4f}, F1: {avg_f1:.4f}")
                print(f"Average Precision: {avg_precision:.4f}, Recall: {avg_recall:.4f}, F1: {avg_f1:.4f}")
            else:
                logger.warning("No users with sufficient data for evaluation")
                print("No users with sufficient data for evaluation")

        except MySQLdb.Error as e:
            logger.error(f"Evaluation error: {str(e)}")
            print(f"Evaluation error: {str(e)}")
        finally:
            cur.close()
            conn.close()

if __name__ == "__main__":
    evaluate_keyword_model()