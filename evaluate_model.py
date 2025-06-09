import asyncio
import platform
import numpy as np
from lightfm import LightFM
from lightfm.data import Dataset
import MySQLdb
from dotenv import load_dotenv
import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('evaluation.log'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

load_dotenv()

def get_db_connection():
    try:
        conn = MySQLdb.connect(
            host=os.getenv('DB_HOST'),
            user=os.getenv('DB_USER'),
            passwd=os.getenv('DB_PASS'),
            db=os.getenv('DB_NAME'),
            charset='utf8mb4'
        )
        return conn
    except MySQLdb.Error as e:
        logger.error(f"Database connection error: {str(e)}")
        return None

def prepare_data(conn, user_ids, item_ids):
    dataset = Dataset()
    dataset.fit(users=user_ids, items=item_ids)

    interactions = []
    weights = []
    cur = conn.cursor(MySQLdb.cursors.DictCursor)

    cur.execute("""
        SELECT user_id, article_id, COUNT(*) as interaction_count
        FROM user_article_log
        WHERE action_type = 'read' OR action_type = 'click_external_link'
        GROUP BY user_id, article_id
    """)
    for row in cur.fetchall():
        interactions.append((row['user_id'], row['article_id']))
        weights.append(1.0)

    cur.execute("""
        SELECT user_id, article_id, feedback_type
        FROM user_feedback
    """)
    for row in cur.fetchall():
        if row['feedback_type'] == 'like':
            interactions.append((row['user_id'], row['article_id']))
            weights.append(2.0)
        elif row['feedback_type'] == 'dislike':
            interactions.append((row['user_id'], row['article_id']))
            weights.append(-1.0)

    cur.close()
    
    (interactions_matrix, weights_matrix) = dataset.build_interactions(
        ((user_id, item_id, weight) for (user_id, item_id), weight in zip(interactions, weights))
    )
    
    # --- DEBUGGING PRINTS (최종 수정 부분) ---
    print(f"DEBUG: prepare_data - Interactions collected: {len(interactions)}")
    print(f"DEBUG: interactions_matrix shape: {interactions_matrix.shape}")
    print(f"DEBUG: weights_matrix shape: {weights_matrix.shape}")
    print(f"DEBUG: num_users: {interactions_matrix.shape[0]}, num_items: {interactions_matrix.shape[1]}") # <--- 여기 수정
    # --- END DEBUGGING PRINTS ---

    return dataset, interactions_matrix, weights_matrix

def train_and_recommend(dataset, interactions_matrix, weights_matrix, user_ids_to_recommend):
    model = LightFM(loss='warp', no_components=30)
    logger.info("LightFM 모델 학습 시작...")
    
    # --- DEBUGGING PRINT ---
    print("DEBUG: model.fit()을 호출하기 직전입니다.")
    # --- END DEBUGGING PRINT ---
    
    # 변경 후:
    model.fit(interactions_matrix, sample_weight=weights_matrix, epochs=5, num_threads=os.cpu_count() or 1) 
    logger.info("LightFM 모델 학습 완료.")
    
    # --- DEBUGGING PRINT ---
    print("DEBUG: model.fit() 함수가 끝났습니다.")
    # --- END DEBUGGING PRINT ---

    recommendations = {}
    for user_db_id in user_ids_to_recommend:
        try:
            # LightFM ID 매핑이 없을 경우 KeyError 방지
            if user_db_id not in dataset.mapping()[0]:
                logger.warning(f"User ID {user_db_id} not found in LightFM dataset mapping. Skipping recommendations for this user.")
                recommendations[user_db_id] = []
                continue

            user_lightfm_id = dataset.mapping()[0][user_db_id]
            
            # known_positive_items가 비어있을 경우를 대비
            known_positive_items = interactions_matrix.tocsr()[user_lightfm_id].indices if user_lightfm_id < interactions_matrix.shape[0] else np.array([])
            
            # scores 계산 부분 (최종 수정)
            scores = model.predict(user_lightfm_id, np.arange(interactions_matrix.shape[1])) # <--- 여기 수정
            
            top_items_lightfm_ids = np.argsort(-scores)
            
            item_id_map = {v: k for k, v in dataset.mapping()[2].items()}
            
            # 추천 아이템 필터링 및 슬라이싱
            recommended_article_db_ids = [
                item_id_map[item_lightfm_id] 
                for item_lightfm_id in top_items_lightfm_ids 
                if item_lightfm_id not in known_positive_items and item_lightfm_id in item_id_map
            ][:20]
            recommendations[user_db_id] = recommended_article_db_ids
            logger.info(f"User {user_db_id}: {len(recommended_article_db_ids)} recommendations generated.")
        except KeyError:
            logger.warning(f"User ID {user_db_id} not found in LightFM dataset mapping. (Already checked, but secondary catch)")
            recommendations[user_db_id] = []
        except Exception as e:
            logger.error(f"Error generating recommendations for user {user_db_id}: {str(e)}", exc_info=True)
            recommendations[user_db_id] = []

    return recommendations

def store_recommendations(conn, recommendations):
    cur = conn.cursor()
    cur.execute("DELETE FROM recommended_articles")
    conn.commit()
    logger.info("기존 추천 데이터 삭제 완료.")

    for user_id, article_ids in recommendations.items():
        for rank, article_id in enumerate(article_ids):
            try:
                cur.execute("""
                    INSERT INTO recommended_articles (user_id, article_id, recommendation_score, recommended_at)
                    VALUES (%s, %s, %s, NOW())
                """, (user_id, article_id, len(article_ids) - rank))
                conn.commit()
            except MySQLdb.Error as e:
                logger.error(f"추천 저장 중 오류 발생 (User: {user_id}, Article: {article_id}): {str(e)}")
                conn.rollback()
    cur.close()
    logger.info(f"총 {len(recommendations)}명의 사용자에 대한 추천 저장 완료.")

def evaluate_model():
    conn = get_db_connection()
    if not conn:
        return {'error': 'DB 연결 실패'}

    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users")
        all_user_ids = [row[0] for row in cur.fetchall()]
        cur.execute("SELECT id FROM articles")
        all_item_ids = [row[0] for row in cur.fetchall()]
        cur.close()
        
        if not all_user_ids or not all_item_ids:
            logger.warning("사용자 또는 기사 데이터 부족.")
            return {'status': 'No sufficient data'}

        dataset, interactions_matrix, weights_matrix = prepare_data(conn, all_user_ids, all_item_ids)
        recommendations = train_and_recommend(dataset, interactions_matrix, weights_matrix, all_user_ids)
        store_recommendations(conn, recommendations)

        results = {}
        for user_id, recommended_items_list in recommendations.items():
            cur = conn.cursor(MySQLdb.cursors.DictCursor)
            recommended_items = np.array(recommended_items_list[:10])
            cur.execute("""
                SELECT article_id
                FROM user_feedback WHERE user_id = %s AND feedback_type = 'like'
                UNION
                SELECT article_id
                FROM user_article_log WHERE user_id = %s AND action_type = 'click_external_link'
            """, (user_id, user_id))
            interested_items = set(row['article_id'] for row in cur.fetchall())
            cur.close()

            recommended_set = set(recommended_items)
            precision = len(interested_items & recommended_set) / len(recommended_set) if recommended_set else 0
            recall = len(interested_items & recommended_set) / len(interested_items) if interested_items else 0

            results[user_id] = {
                'recommended_items': recommended_items.tolist(),
                'precision': round(precision, 2),
                'recall': round(recall, 2)
            }
            logger.info(f"User {user_id} - Precision: {precision:.2f}, Recall: {recall:.2f}")

        return results
    except Exception as e:
        logger.error(f"Error evaluating model: {str(e)}")
        return {'error': str(e)}
    finally:
        conn.close()

if __name__ == '__main__':
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    logger.info("모델 평가 프로세스 시작...")
    evaluation_results = evaluate_model()
    logger.info("모델 평가 프로세스 완료.")
    logger.info(f"평가 결과: {evaluation_results}")