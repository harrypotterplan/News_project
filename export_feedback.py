import os
import csv
import MySQLdb
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# MySQL 연결 설정
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
        print("DB 연결 성공!")
        return conn
    except MySQLdb.Error as e:
        print(f"DB 연결 실패: {str(e)}")
        return None

# CSV로 내보내기
def export_feedback_to_csv():
    conn = get_db_connection()
    if not conn:
        return

    try:
        cur = conn.cursor(MySQLdb.cursors.DictCursor)
        # 전체 행 수 계산
        cur.execute("SELECT COUNT(*) AS total_rows FROM user_feedback")
        total_rows = cur.fetchone()['total_rows']
        print(f"총 행 수: {total_rows}")

        # 80% 지점과 20% 개수 계산
        offset = int(total_rows * 0.8)
        limit = int(total_rows * 0.2)
        print(f"Offset: {offset}, Limit: {limit}")

        # 20% 데이터 쿼리
        cur.execute("""
            SELECT user_id, article_id, feedback_type
            FROM user_feedback
            ORDER BY created_at
            LIMIT %s, %s
        """, (offset, limit))
        rows = cur.fetchall()

        # CSV 파일 저장 (프로젝트 폴더에 저장)
        output_file = 'test_feedback.csv'  # 상대 경로
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            writer.writerow(['user_id', 'article_id', 'feedback_type'])  # 헤더
            writer.writerows([[row['user_id'], row['article_id'], row['feedback_type']] for row in rows])

        print(f"데이터가 {os.path.abspath(output_file)}에 저장되었습니다!")

    except MySQLdb.Error as e:
        print(f"쿼리 실행 오류: {str(e)}")
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    export_feedback_to_csv()