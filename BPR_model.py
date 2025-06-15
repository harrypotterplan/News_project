import pandas as pd
from surprise import Dataset, Reader
from surprise.prediction_algorithms.matrix_factorization import SVDpp as BPR  # SVDpp를 BPR로 사용
from surprise.model_selection import train_test_split  # train_test_split 임포트 추가
from sqlalchemy import create_engine
import joblib
import logging
import os
from dotenv import load_dotenv

logging.basicConfig(filename='bpr_model.log', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

def get_db_engine():
    db_host = os.getenv('DB_HOST')
    db_user = os.getenv('DB_USER')
    db_pass = os.getenv('DB_PASS')
    db_name = os.getenv('DB_NAME')
    db_port = int(os.getenv('DB_PORT', 3306))

    logger.debug(f"DB_HOST: {db_host}, DB_USER: {db_user}, DB_NAME: {db_name}, DB_PORT: {db_port}")

    if not all([db_host, db_user, db_pass, db_name]):
        logger.error("환경 변수가 설정되지 않았습니다. .env 파일을 확인하세요.")
        raise ValueError("Missing environment variables.")

    return create_engine(f"mysql+pymysql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}?charset=utf8mb4")

def prepare_data():
    try:
        engine = get_db_engine()
        logger.info("DB에서 데이터 로드 중...")

        df_feedback = pd.read_sql("SELECT user_id, article_id, feedback_type FROM user_feedback", engine)
        df_log = pd.read_sql("SELECT user_id, article_id, action_type FROM user_article_log", engine)
        logger.info(f"피드백 수: {len(df_feedback)}, 로그 수: {len(df_log)}")

        rating_map_feedback = {'dislike': 0.1, 'view': 1.0, 'click_external_link': 2.5, 'read': 5.0, 'like': 10.0}
        rating_map_log = {'view': 1.0, 'read': 5.0, 'click_external_link': 2.5, 'feedback_like': 10.0}

        df_feedback['rating'] = df_feedback['feedback_type'].map(rating_map_feedback)
        df_feedback = df_feedback[['user_id', 'article_id', 'rating']].dropna()
        df_log['rating'] = df_log['action_type'].map(rating_map_log)
        df_log = df_log[['user_id', 'article_id', 'rating']].dropna()

        df_combined = pd.concat([df_feedback, df_log], ignore_index=True)
        df_final = df_combined.groupby(['user_id', 'article_id'])['rating'].max().reset_index()

        logger.info(f"최종 데이터 수: {len(df_final)}, 고유 사용자: {df_final['user_id'].nunique()}, 고유 기사: {df_final['article_id'].nunique()}")
        logger.debug(f"Rating 분포:\n{df_final['rating'].value_counts()}")

        reader = Reader(rating_scale=(0.1, 10.0))
        data = Dataset.load_from_df(df_final[['user_id', 'article_id', 'rating']], reader)
        trainset, testset = train_test_split(data, test_size=0.1, random_state=42)
        logger.info(f"Train 데이터: {trainset.n_ratings}, Test 데이터: {len(testset)}")

        train_users = {trainset.to_raw_uid(uid) for uid in trainset.all_users()}
        train_articles = {trainset.to_raw_iid(iid) for iid in trainset.all_items()}
        cold_start_users = sum(1 for uid, _, _ in testset if uid not in train_users)
        cold_start_articles = sum(1 for _, iid, _ in testset if iid not in train_articles)
        logger.info(f"Testset 콜드스타트 사용자: {cold_start_users}, 기사: {cold_start_articles}")

        return trainset, testset
    except Exception as e:
        logger.error(f"데이터 준비 실패: {str(e)}", exc_info=True)
        raise

def train_bpr_model():
    try:
        logger.info("BPR 모델 학습 시작")
        trainset, testset = prepare_data()

        model = BPR(n_factors=20, n_epochs=50, lr_all=0.01, reg_all=0.01, random_state=42)
        logger.info("모델 학습 중...")
        model.fit(trainset)

        predictions = model.test(testset)
        logger.info(f"Testset 예측 수: {len(predictions)}")

        impossible_predictions = sum(1 for pred in predictions if pred.details['was_impossible'])
        valid_predictions = [pred for pred in predictions if not pred.details['was_impossible']]
        if valid_predictions:
            rmse = ((sum((pred.r_ui - pred.est)**2 for pred in valid_predictions) / len(valid_predictions))**0.5)
            logger.info(f"Testset RMSE: {rmse:.4f}")
        else:
            logger.info("유효한 예측이 없어 RMSE 계산 불가")

        logger.info(f"불가능한 예측 수: {impossible_predictions}")
        for i, pred in enumerate(predictions[:5]):
            logger.info(f"User: {pred.uid}, Article: {pred.iid}, Actual: {pred.r_ui:.2f}, Predicted: {pred.est:.2f}, Impossible: {pred.details['was_impossible']}")

        save_dir = os.path.join(os.getcwd(), "model_data")
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, "bpr_model.pkl")
        joblib.dump(model, save_path)
        logger.info(f"BPR 모델 저장: {save_path}")
        return model
    except Exception as e:
        logger.error(f"BPR 학습 실패: {str(e)}", exc_info=True)
        raise

if __name__ == "__main__":
    train_bpr_model()