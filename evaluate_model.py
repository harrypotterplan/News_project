import os
import logging
import MySQLdb
import numpy as np
from lightfm import LightFM
from lightfm.data import Dataset
from lightfm.evaluation import precision_at_k, recall_at_k
from dotenv import load_dotenv
from tqdm import tqdm
import traceback

# 로깅 설정
logging.basicConfig(filename='crawler.log', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_db_connection():
    """MySQL 데이터베이스 연결 설정"""
    try:
        load_dotenv()
        if not os.getenv('DB_HOST'):
            raise ValueError("DB_HOST not found in .env")
        conn = MySQLdb.connect(
            host=os.getenv('DB_HOST'),
            user=os.getenv('DB_USER'),
            passwd=os.getenv('DB_PASS'),
            db=os.getenv('DB_NAME'),
            port=int(os.getenv('DB_PORT', 3306)),
            charset='utf8mb4'
        )
        logger.debug("DB 연결 성공")
        return conn
    except (MySQLdb.Error, ValueError) as e:
        logger.error(f"DB 연결 실패: {str(e)}")
        return None

def prepare_data(conn, user_ids, item_ids):
    """LightFM 모델 학습을 위한 데이터 준비"""
    logger.debug("데이터 준비 시작...")
    dataset = Dataset()
    dataset.fit(users=user_ids, items=item_ids)

    interactions, weights = [], []
    try:
        cur = conn.cursor()
        # user_article_log
        cur.execute("""
            SELECT user_id, article_id, action_type
            FROM user_article_log
            WHERE action_type IN ('view', 'read', 'click_external_link')
            AND user_id IN (%s) AND article_id IN (%s)
        """ % (','.join(['%s'] * len(user_ids)), ','.join(['%s'] * len(item_ids))), user_ids + item_ids)
        action_counts = {'view': 0, 'read': 0, 'click_external_link': 0}
        for row in cur.fetchall():
            interactions.append((row[0], row[1]))
            action = row[2]
            action_counts[action] += 1
            weights.append(0.5 if action == 'view' else 2.0 if action == 'read' else 3.0)
        logger.debug(f"Action counts: {action_counts}")

        # user_feedback
        cur.execute("""
            SELECT user_id, article_id, feedback_type
            FROM user_feedback
            WHERE feedback_type IN ('like', 'dislike')
            AND user_id IN (%s) AND article_id IN (%s)
        """ % (','.join(['%s'] * len(user_ids)), ','.join(['%s'] * len(item_ids))), user_ids + item_ids)
        feedback_counts = {'like': 0, 'dislike': 0}
        for row in cur.fetchall():
            interactions.append((row[0], row[1]))
            feedback = row[2]
            feedback_counts[feedback] += 1
            weights.append(5.0 if feedback == 'like' else -5.0)
        logger.debug(f"Feedback counts: {feedback_counts}")

        logger.info(f"Total interactions: {len(interactions)}")
        if not interactions:
            logger.warning("No valid interactions found")
            return dataset, None, None

        interactions_matrix = dataset.build_interactions(interactions)[1]
        weights_matrix = dataset.build_interactions([(x[0], x[1], w) for x, w in zip(interactions, weights)])[1]
        logger.debug(f"interactions_matrix shape: {interactions_matrix.shape}")
        return dataset, interactions_matrix, weights_matrix
    except MySQLdb.Error as e:
        logger.error(f"Error preparing data: {str(e)}")
        return dataset, None, None
    finally:
        if 'cur' in locals():
            cur.close()

def train_and_recommend(dataset, interactions_matrix, weights_matrix, user_ids_to_recommend):
    """LightFM 모델 학습 및 추천 생성"""
    if interactions_matrix is None or weights_matrix is None:
        logger.warning("No interaction matrix, cannot generate recommendations")
        return {user_id: [] for user_id in user_ids_to_recommend}

    model = LightFM(loss='warp', no_components=5, learning_rate=0.05, random_state=42)
    logger.debug("LightFM 모델 학습 시작...")
    try:
        print(f"DEBUG: Starting model.fit() with interactions_matrix shape: {interactions_matrix.shape}")
        print(f"DEBUG: Weights matrix shape: {weights_matrix.shape}")
        for epoch in tqdm(range(5), desc="Training epochs"):
            model.fit_partial(
                interactions_matrix,
                sample_weight=weights_matrix,
                epochs=1,
                num_threads=1,
                verbose=True
            )
            logger.debug(f"Completed epoch {epoch + 1}")
        logger.info("Model trained successfully")
        print("DEBUG: model.fit() completed")
    except Exception as e:
        logger.error(f"Error in model training: {str(e)}")
        print(f"Error during LightFM model training: {str(e)}")
        traceback.print_exc()
        return {user_id: [] for user_id in user_ids_to_recommend}

    recommendations = {}
    user_id_map = dataset.mapping()[0]
    item_id_map = dataset.mapping()[2]
    for user_db_id in user_ids_to_recommend:
        try:
            if user_db_id not in user_id_map:
                logger.warning(f"User ID {user_db_id} not found in LightFM dataset mapping")
                recommendations[user_db_id] = []
                continue
            user_lightfm_id = user_id_map[user_db_id]
            known_positive_items = interactions_matrix.tocsr()[user_lightfm_id].indices if user_lightfm_id < interactions_matrix.shape[0] else np.array([])
            scores = model.predict(user_lightfm_id, np.arange(interactions_matrix.shape[1]))
            top_items_lightfm_ids = np.argsort(-scores)
            recommended_article_db_ids = [
                item_id_map[item_lightfm_id]
                for item_lightfm_id in top_items_lightfm_ids
                if item_lightfm_id not in known_positive_items and item_lightfm_id in item_id_map
            ][:10]
            recommendations[user_db_id] = recommended_article_db_ids
            logger.debug(f"User {user_db_id}: {len(recommended_article_db_ids)} recommendations generated")
        except Exception as e:
            logger.error(f"Error generating recommendations for user {user_db_id}: {str(e)}")
            recommendations[user_db_id] = []
    logger.info(f"Generated recommendations for {len(recommendations)} users")
    return recommendations

def store_recommendations(conn, recommendations):
    """추천 결과를 데이터베이스에 저장"""
    try:
        cur = conn.cursor()
        cur.execute("TRUNCATE TABLE recommended_articles")
        valid_articles = set()
        cur.execute("SELECT id FROM articles")
        for row in cur.fetchall():
            valid_articles.add(row[0])
        
        inserted = 0
        for user_id, article_ids in recommendations.items():
            for rank, article_id in enumerate(article_ids, 1):
                if article_id not in valid_articles:
                    logger.warning(f"Invalid article_id {article_id} for user {user_id}, skipping")
                    continue
                cur.execute("""
                    INSERT INTO recommended_articles (user_id, article_id, recommendation_rank, recommendation_score)
                    VALUES (%s, %s, %s, %s)
                """, (user_id, article_id, rank, 1.0 / rank))
                inserted += 1
                logger.debug(f"Stored recommendation: user_id={user_id}, article_id={article_id}, rank={rank}")
        conn.commit()
        logger.info(f"Stored {inserted} recommendations successfully")
    except MySQLdb.Error as e:
        conn.rollback()
        logger.error(f"Error storing recommendations: {str(e)}")
    finally:
        if 'cur' in locals():
            cur.close()

def evaluate_model():
    """LightFM 모델 평가 및 추천 생성"""
    logger.info("Starting model evaluation...")
    conn = get_db_connection()
    if not conn:
        logger.error("DB connection failed, aborting evaluation")
        return {'error': 'DB connection failed'}

    try:
        cur = conn.cursor(MySQLdb.cursors.DictCursor)
        cur.execute("SELECT id FROM users")
        all_user_ids = [row['id'] for row in cur.fetchall()]
        cur.execute("SELECT DISTINCT article_id FROM user_article_log")
        all_item_ids = [row['article_id'] for row in cur.fetchall()]
        cur.close()

        logger.debug(f"Users: {len(all_user_ids)}, Articles: {len(all_item_ids)}")
        if not all_user_ids or not all_item_ids:
            logger.warning("No users or articles found")
            return {'status': 'No sufficient data'}

        dataset, interactions_matrix, weights_matrix = prepare_data(conn, all_user_ids, all_item_ids)
        if interactions_matrix is None:
            logger.warning("No interaction data found")
            return {'status': 'No interactions data'}

        recommendations = train_and_recommend(dataset, interactions_matrix, weights_matrix, all_user_ids)
        store_recommendations(conn, recommendations)

        results = {}
        model = LightFM(loss='warp', no_components=5, learning_rate=0.05, random_state=42)
        for epoch in tqdm(range(5), desc="Evaluation epochs"):
            model.fit_partial(interactions_matrix, sample_weight=weights_matrix, epochs=1, num_threads=1)
        precision = precision_at_k(model, interactions_matrix, k=10).mean()
        recall = recall_at_k(model, interactions_matrix, k=10).mean()

        for user_id in all_user_ids:
            results[user_id] = {
                'recommended_items': recommendations.get(user_id, []),
                'precision': round(precision, 4),
                'recall': round(recall, 4)
            }
            logger.debug(f"User {user_id} - Precision@10: {precision:.4f}, Recall@10: {recall:.4f}")

        logger.info(f"Evaluation completed: {len(results)} users processed")
        return results
    except Exception as e:
        logger.error(f"Error evaluating model: {str(e)}")
        return {'error': str(e)}
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    load_dotenv()
    evaluation_results = evaluate_model()
    print(f"Evaluation results: {evaluation_results}")