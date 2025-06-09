import os
import logging
import MySQLdb
import numpy as np
from lightfm import LightFM
from lightfm.data import Dataset
from lightfm.evaluation import precision_at_k, recall_at_k

# 로깅 설정: 디버깅 및 오류 추적을 위해 로그 레벨을 INFO로 설정
logging.basicConfig(filename='crawler.log', level=logging.INFO)
logger = logging.getLogger(__name__)

def get_db_connection():
    """MySQL 데이터베이스 연결 설정"""
    try:
        conn = MySQLdb.connect(
            host= os.getenv('DB_HOST'),
            user=os.getenv('DB_USER'),
            passwd=os.getenv('DB_PASS'),
            db=os.getenv('DB_NAME'),
            port=int(os.getenv('DB_PORT', 3306)),
            charset='utf8mb4'
        )


        logger.info("DB 연결 성공")
        return conn
    except MySQLdb.Error as e:
        logger.error(f"DB 연결 실패: {str(e)}")
        return None

def prepare_data(conn, user_ids, item_ids):
    """
    LightFM 모델 학습을 위한 데이터 준비
    Args:
        conn: MySQL 연결 객체
        user_ids: 사용자 ID 리스트
        item_ids: 기사 ID 리스트
    Returns:
        dataset: LightFM Dataset 객체
        interactions_matrix: 사용자-기사 상호작용 행렬
        weights_matrix: 가중치 행렬
    """
    logger.info("데이터 준비 시작...")
    dataset = Dataset()
    dataset.fit(users=user_ids, items=item_ids)

    # 상호작용 데이터 수집
    interactions, weights = [], []
    try:
        cur = conn.cursor(MySQLdb.cursors.DictCursor)
        # user_article_log에서 조회 및 클릭 데이터 수집
        cur.execute("""
            SELECT user_id, article_id, action_type
            FROM user_article_log
            WHERE action_type IN ('read', 'click_external_link')
        """)
        for row in cur.fetchall():
            interactions.append((row['user_id'], row['article_id']))
            weights.append(1.0)  # 기본 가중치

        # user_feedback에서 좋아요/싫어요 데이터 수집
        cur.execute("""
            SELECT user_id, article_id, feedback_type
            FROM user_feedback
            WHERE feedback_type IN ('like', 'dislike')
        """)
        for row in cur.fetchall():
            interactions.append((row['user_id'], row['article_id']))
            weights.append(2.0 if row['feedback_type'] == 'like' else -1.0)

        logger.debug(f"Interactions collected: {len(interactions)}")
        if not interactions:
            logger.warning("상호작용 데이터가 없습니다.")
            return dataset, None, None

        # 상호작용 행렬 생성
        interactions_matrix = dataset.build_interactions(interactions)[1]
        weights_matrix = dataset.build_interactions([(x[0], x[1], w) for x, w in zip(interactions, weights)])[1]
        logger.debug(f"interactions_matrix shape: {interactions_matrix.shape}")
        logger.debug(f"weights_matrix shape: {weights_matrix.shape}")
        logger.debug(f"num_users: {len(user_ids)}, num_items: {len(item_ids)}")
        return dataset, interactions_matrix, weights_matrix
    except MySQLdb.Error as e:
        logger.error(f"데이터 준비 중 오류: {str(e)}")
        return dataset, None, None
    finally:
        cur.close()

def train_and_recommend(dataset, interactions_matrix, weights_matrix, user_ids_to_recommend):
    """
    LightFM 모델 학습 및 추천 생성
    Args:
        dataset: LightFM Dataset 객체
        interactions_matrix: 상호작용 행렬
        weights_matrix: 가중치 행렬
        user_ids_to_recommend: 추천 대상 사용자 ID 리스트
    Returns:
        recommendations: 사용자별 추천 기사 ID 딕셔너리
    """
    if interactions_matrix is None or weights_matrix is None:
        logger.warning("상호작용 행렬이 없어 추천을 생성할 수 없습니다.")
        return {user_id: [] for user_id in user_ids_to_recommend}

    model = LightFM(loss='warp', no_components=30, learning_rate=0.05)
    logger.info("LightFM 모델 학습 시작...")
    try:
        # 모델 학습
        print("DEBUG: Starting model.fit() with interactions_matrix shape:", interactions_matrix.shape)
        model.fit(interactions_matrix, sample_weight=weights_matrix, epochs=10, num_threads=os.cpu_count() or 1)
        logger.info("LightFM 모델 학습 완료.")
        print("DEBUG: model.fit() 완료")
    except Exception as e:
        logger.error(f"Error in model.fit(): {str(e)}")
        print(f"DEBUG: Error in model.fit(): {str(e)}")
        return {user_id: [] for user_id in user_ids_to_recommend}

    recommendations = {}
    user_id_map = dataset.mapping()[0]  # 사용자 ID 매핑
    item_id_map = dataset.mapping()[2]  # 기사 ID 매핑
    for user_db_id in user_ids_to_recommend:
        try:
            if user_db_id not in user_id_map:
                logger.warning(f"User ID {user_db_id} not found in LightFM dataset mapping. Skipping recommendations for this user.")
                recommendations[user_db_id] = []
                continue
            user_lightfm_id = user_id_map[user_db_id]
            # 이미 상호작용한 기사 제외
            known_positive_items = interactions_matrix.tocsr()[user_lightfm_id].indices if user_lightfm_id < interactions_matrix.shape[0] else np.array([])
            scores = model.predict(user_lightfm_id, np.arange(interactions_matrix.shape[1]))
            top_items_lightfm_ids = np.argsort(-scores)
            # LightFM ID를 DB ID로 변환
            recommended_article_db_ids = [
                item_id_map[item_lightfm_id]
                for item_lightfm_id in top_items_lightfm_ids
                if item_lightfm_id not in known_positive_items and item_lightfm_id in item_id_map
            ][:20]
            recommendations[user_db_id] = recommended_article_db_ids
            logger.info(f"User {user_db_id}: {len(recommended_article_db_ids)} recommendations generated.")
        except Exception as e:
            logger.error(f"Error generating recommendations for user {user_db_id}: {str(e)}", exc_info=True)
            recommendations[user_db_id] = []
    return recommendations

def store_recommendations(conn, recommendations):
    """
    추천 결과를 데이터베이스에 저장
    Args:
        conn: MySQL 연결 객체
        recommendations: 사용자별 추천 기사 ID 딕셔너리
    """
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM recommended_articles")  # 기존 추천 삭제
        for user_id, article_ids in recommendations.items():
            for rank, article_id in enumerate(article_ids, 1):
                cur.execute("""
                    INSERT INTO recommended_articles (user_id, article_id, recommendation_rank)
                    VALUES (%s, %s, %s)
                """, (user_id, article_id, rank))
        conn.commit()
        logger.info("추천 결과가 성공적으로 저장되었습니다.")
    except MySQLdb.Error as e:
        conn.rollback()
        logger.error(f"추천 결과 저장 중 오류: {str(e)}")
    finally:
        cur.close()

def evaluate_model():
    """
    LightFM 모델 평가 및 추천 생성
    Returns:
        results: 사용자별 평가 결과 (precision, recall)
    """
    logger.info("모델 평가 프로세스 시작...")
    conn = get_db_connection()
    if not conn:
        logger.error("DB 연결 실패로 인해 평가 중단")
        return {'error': 'DB 연결 실패'}

    try:
        cur = conn.cursor(MySQLdb.cursors.DictCursor)
        # 사용자 및 기사 ID 수집
        cur.execute("SELECT id FROM users")
        all_user_ids = [row['id'] for row in cur.fetchall()]
        cur.execute("SELECT id FROM articles")
        all_item_ids = [row['id'] for row in cur.fetchall()]
        cur.close()

        if not all_user_ids or not all_item_ids:
            logger.warning("사용자 또는 기사 데이터 부족.")
            return {'status': 'No sufficient data'}

        # 데이터 준비
        dataset, interactions_matrix, weights_matrix = prepare_data(conn, all_user_ids, all_item_ids)
        if interactions_matrix is None:
            logger.warning("상호작용 데이터 부족으로 평가 중단")
            return {'status': 'No interactions data'}

        # 추천 생성
        recommendations = train_and_recommend(dataset, interactions_matrix, weights_matrix, all_user_ids)
        store_recommendations(conn, recommendations)

        # 평가 결과 계산
        results = {}
        for user_id, recommended_items_list in recommendations.items():
            cur = conn.cursor(MySQLdb.cursors.DictCursor)
            recommended_items = np.array(recommended_items_list[:10])
            # 관심 기사: 좋아요 또는 외부 링크 클릭
            cur.execute("""
                SELECT article_id
                FROM user_feedback WHERE user_id = %s AND feedback_type = 'like'
                UNION
                SELECT article_id
                FROM user_article_log WHERE user_id = %s AND action_type = 'click_external_link'
            """, (user_id, user_id))
            interested_items = set(row['article_id'] for row in cur.fetchall())
            cur.close()

            # Precision@10 및 Recall@10 계산
            recommended_set = set(recommended_items)
            precision = len(interested_items & recommended_set) / len(recommended_set) if recommended_set else 0
            recall = len(interested_items & recommended_set) / len(interested_items) if interested_items else 0
            results[user_id] = {
                'recommended_items': recommended_items.tolist(),
                'precision': round(precision, 4),
                'recall': round(recall, 4)
            }
            logger.info(f"User {user_id} - Precision@10: {precision:.4f}, Recall@10: {recall:.4f}, Recommended items: {recommended_items.tolist()}")
        
        logger.info(f"Evaluation results: {results}")
        return results
    except Exception as e:
        logger.error(f"Error evaluating model: {str(e)}", exc_info=True)
        return {'error': str(e)}
    finally:
        conn.close()

if __name__ == "__main__":
    # 환경 변수 로드
    from dotenv import load_dotenv
    load_dotenv()
    # 모델 평가 실행
    evaluation_results = evaluate_model()
    print(f"Evaluation results: {evaluation_results}")