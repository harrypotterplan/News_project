-- 데이터베이스 생성 (이미 존재하면 건너뜀)
CREATE DATABASE IF NOT EXISTS AI_master;

-- 데이터베이스 사용
USE AI_master;

-- 1. `users` 테이블 생성
-- 사용자 계정 정보를 저장
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(100) NOT NULL UNIQUE,      -- 이메일은 중복되지 않아야 함
    username VARCHAR(50) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,     -- 비밀번호는 해시된 형태로 저장
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- 사용자 계정 생성 시간
);

-- 2. `articles` 테이블 생성
-- 네이버 API에서 크롤링한 뉴스 기사 정보를 저장
CREATE TABLE articles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    api_article_id VARCHAR(255) UNIQUE,       -- 네이버 API 등에서 받아온 기사 고유 ID (중복 방지)
    title TEXT NOT NULL,                      -- 기사 제목
    summary TEXT,                             -- 네이버 API에서 받아온 요약문 (없을 경우 NULL 허용)
    category VARCHAR(50),                     -- 기사 분류 (예: 정치, 경제, IT 등)
    published_at DATETIME,                    -- 기사 발행 시간
    url TEXT NOT NULL                         -- 기사 원본 URL
);

-- 3. `keywords` 테이블 생성
-- 기사와 연결될 키워드들을 저장
CREATE TABLE keywords (
    id INT AUTO_INCREMENT PRIMARY KEY,
    keyword VARCHAR(255) NOT NULL UNIQUE      -- 키워드 자체 (중복 방지)
);

-- 4. `article_keywords` 테이블 생성
-- `articles`와 `keywords` 테이블 간의 다대다(N:M) 관계를 정의
CREATE TABLE article_keywords (
    article_id INT NOT NULL,                  -- articles 테이블의 ID 참조
    keyword_id INT NOT NULL,                  -- keywords 테이블의 ID 참조
    PRIMARY KEY (article_id, keyword_id),     -- 두 컬럼의 조합이 고유해야 함 (복합 기본 키)
    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE, -- 기사 삭제 시 연결된 키워드 정보도 삭제
    FOREIGN KEY (keyword_id) REFERENCES keywords(id) ON DELETE CASCADE  -- 키워드 삭제 시 연결된 기사-키워드 관계도 삭제
);

-- 5. `user_article_log` 테이블 생성
-- 사용자들의 뉴스 기사 상호작용 로그를 저장
CREATE TABLE user_article_log (
    log_id INT AUTO_INCREMENT PRIMARY KEY,     -- 로그 기록의 고유 식별자
    user_id INT NOT NULL,                     -- 어떤 사용자가 행동했는지 (users 테이블 참조)
    article_id INT NOT NULL,                  -- 어떤 기사에 대해 행동했는지 (articles 테이블 참조)
    action_type VARCHAR(50) NOT NULL,         -- 행동 유형 (예: 'click', 'scroll', 'like', 'dislike', 'bookmark', 'share')
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, -- 사용자가 해당 행동을 취한 시간
    read_time INT,                            -- 기사를 읽은 시간 (초 단위, NULL 허용)
    scroll_depth FLOAT,                       -- 기사 스크롤 정도 (0.0 ~ 1.0, NULL 허용)

    -- 외래 키 제약 조건
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
);