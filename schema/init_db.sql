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
    url TEXT NOT NULL,                        -- 기사 원본 URL
    full_content TEXT,                        -- 기사 본문 저장
    INDEX idx_published_at (published_at),    -- 검색/정렬 최적화
    INDEX idx_category (category),            -- 카테고리별 검색 최적화
    INDEX idx_api_article_id (api_article_id) -- API 기사 ID 검색 최적화
);

-- 3. `keywords` 테이블 생성
-- 기사에서 추출된 키워드를 저장 (중복 방지)
CREATE TABLE keywords (
    id INT AUTO_INCREMENT PRIMARY KEY,
    keyword_text VARCHAR(255) NOT NULL UNIQUE -- 키워드 텍스트 (중복되지 않아야 함)
);

-- 4. `article_keywords` 테이블 생성
-- 기사와 키워드 간의 다대다 관계를 연결
CREATE TABLE article_keywords (
    article_id INT NOT NULL,                 -- 기사 ID (articles 테이블 참조)
    keyword_id INT NOT NULL,                 -- 키워드 ID (keywords 테이블 참조)
    PRIMARY KEY (article_id, keyword_id),    -- 복합 기본 키로 중복 연결 방지
    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE, -- 기사 삭제 시 연결된 키워드도 삭제
    FOREIGN KEY (keyword_id) REFERENCES keywords(id) ON DELETE CASCADE, -- 키워드 삭제 시 연결된 기사도 삭제
    INDEX idx_article_id (article_id),       -- 기사별 키워드 조회 최적화
    INDEX idx_keyword_id (keyword_id)        -- 키워드별 기사 조회 최적화
);

-- 5. `user_article_log` 테이블 생성
-- 사용자의 기사 조회, 클릭 등 행동을 기록
CREATE TABLE user_article_log (
    id INT AUTO_INCREMENT PRIMARY KEY,          -- 로그의 고유 식별자 (자동 증가)
    user_id INT NOT NULL,                       -- 행동을 수행한 사용자의 ID (users 테이블 참조)
    article_id INT NOT NULL,                    -- 행동이 발생한 기사의 ID (articles 테이블 참조)
    action_type VARCHAR(50) NOT NULL,           -- 행동의 종류 (예: 'read', 'click', 'share' 등)
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, -- 행동이 발생한 시간 (기본값: 현재 시간)
    read_time INT,                            -- 기사를 읽은 시간 (초 단위, NULL 허용)
    scroll_depth FLOAT,                       -- 기사 스크롤 정도 (0.0 ~ 1.0, NULL 허용)
    -- 외래 키 제약 조건
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),              -- 사용자별 로그 조회 최적화
    INDEX idx_article_id (article_id)         -- 기사별 로그 조회 최적화
);

-- 6. 사용자 검색 기록을 저장하는 테이블 생성
CREATE TABLE user_searches (
    id INT AUTO_INCREMENT PRIMARY KEY,           -- 검색 기록의 고유 식별자 (자동 증가)
    user_id INT NOT NULL,                       -- 검색을 수행한 사용자의 ID (users 테이블 참조)
    search_term VARCHAR(255) NOT NULL,          -- 사용자가 입력한 검색어 (최대 255자)
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, -- 검색이 이루어진 시간 (기본값: 현재 시간)
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE, -- users 테이블의 id를 참조, 사용자 삭제 시 검색 기록도 삭제
    INDEX idx_user_id (user_id),                -- user_id에 인덱스 추가로 검색 쿼리 성능 최적화
    INDEX idx_search_term (search_term)         -- search_term에 인덱스 추가로 검색어 분석 쿼리 최적화
);

-- 7. 사용자 피드백을 저장하는 테이블 (좋아요, 싫어요 등)
CREATE TABLE user_feedback (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    article_id INT NOT NULL,
    feedback_type VARCHAR(50) NOT NULL, -- 'like' 또는 'dislike'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, article_id), -- 사용자는 한 기사에 대해 하나의 피드백만 남길 수 있음
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE,
    INDEX idx_user_article (user_id, article_id)
);

-- 8. 추천된 기사들을 저장하는 테이블
CREATE TABLE recommended_articles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    article_id INT NOT NULL,
    recommendation_score FLOAT, -- 추천 점수 (모델이 부여한 가중치 등)
    recommended_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE,
    UNIQUE (user_id, article_id), -- 특정 사용자에게 특정 기사가 한 번만 추천되도록
    INDEX idx_user_recommended (user_id)
);