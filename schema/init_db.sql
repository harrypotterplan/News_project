-- 데이터베이스가 이미 존재하면 삭제하여 초기화합니다. (개발 환경에서 유용)
DROP DATABASE IF EXISTS AI_master;

-- AI_master 데이터베이스를 생성합니다.
-- utf8mb4 문자 집합과 utf8mb4_unicode_ci 콜레이션을 사용하여 다양한 언어 (한글 포함)를 지원합니다.
CREATE DATABASE AI_master CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 이후의 모든 SQL 명령은 AI_master 데이터베이스 내에서 실행됩니다.
USE AI_master;

-- 1. users 테이블: 사용자 정보 저장
-- 웹 서비스 사용자의 계정 정보를 관리합니다.
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,             -- 사용자 고유 ID (자동 증가, 기본 키)
    username VARCHAR(50) NOT NULL UNIQUE,         -- 사용자 이름 (고유해야 함)
    email VARCHAR(100) NOT NULL UNIQUE,          -- 사용자 이메일 (고유해야 함, 로그인에 활용)
    password_hash VARCHAR(255) NOT NULL,          -- 비밀번호의 해시 값 (보안을 위해 원문 저장 안 함)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP, -- 사용자 계정 생성 일시 (기본값: 현재 시간)

    -- 인덱스 추가: 검색 성능 최적화
    INDEX idx_username (username),                 -- username으로 사용자 조회 시 효율적
    INDEX idx_email (email)                        -- email로 사용자 조회 시 효율적
) ENGINE=InnoDB; -- InnoDB 엔진은 트랜잭션과 외래 키를 지원합니다.

-- 2. articles 테이블: 기사 정보 저장
-- 크롤링 또는 외부 API를 통해 수집된 뉴스 기사 정보를 저장합니다.
CREATE TABLE articles (
    id INT AUTO_INCREMENT PRIMARY KEY,             -- 기사 고유 ID (자동 증가, 기본 키)
    title VARCHAR(255) NOT NULL,                   -- 기사 제목 (필수)
    summary TEXT,                                  -- 기사 요약 (긴 텍스트를 위해 TEXT 타입 사용, NULL 허용)
    content TEXT,                                  -- 기사 본문 (매우 긴 텍스트를 위해 TEXT 타입 사용, NULL 허용)
    category VARCHAR(50),                          -- 기사 카테고리 (예: 정치, 경제, IT 등, NULL 허용)
    published_at DATETIME,                         -- 기사 발행 일시
    url VARCHAR(255) NOT NULL UNIQUE,              -- 기사 원본 URL (고유해야 함)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP, -- 기사 레코드 생성 일시 (DB에 저장된 시간)

    -- 인덱스 추가: 검색 및 정렬 성능 최적화
    INDEX idx_category (category),                 -- 카테고리별 기사 조회 시 효율적
    INDEX idx_published_at (published_at)          -- 발행 일시 기준으로 정렬하거나 범위 조회 시 효율적
) ENGINE=InnoDB;

-- 3. keywords 테이블: 추출된 키워드 저장
-- 기사 본문 또는 메타데이터에서 추출된 고유한 키워드를 저장합니다.
-- 이는 키워드 기반 추천 시스템의 핵심 요소입니다.
CREATE TABLE keywords (
    id INT AUTO_INCREMENT PRIMARY KEY,             -- 키워드 고유 ID (자동 증가, 기본 키)
    keyword_text VARCHAR(255) NOT NULL UNIQUE      -- 키워드 텍스트 (중복되지 않아야 함, 고유 인덱스)
) ENGINE=InnoDB;

-- 4. article_keywords 테이블: 기사와 키워드 간의 관계 매핑
-- 각 기사가 어떤 키워드들과 연관되어 있는지를 다대다(N:M) 관계로 연결합니다.
-- `get_keyword_recommendations` 함수에서 사용됩니다.
CREATE TABLE article_keywords (
    article_id INT NOT NULL,                       -- 기사 ID (articles 테이블 참조)
    keyword_id INT NOT NULL,                       -- 키워드 ID (keywords 테이블 참조)
    PRIMARY KEY (article_id, keyword_id),          -- 기사와 키워드 쌍의 복합 기본 키 (중복 연결 방지)

    -- 외래 키 제약 조건: 참조 무결성 유지
    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE, -- 기사 삭제 시 관련 키워드 연결 자동 삭제
    FOREIGN KEY (keyword_id) REFERENCES keywords(id) ON DELETE CASCADE, -- 키워드 삭제 시 관련 기사 연결 자동 삭제

    -- 인덱스 추가: 관계 조회 성능 최적화
    INDEX idx_article_id (article_id),             -- 특정 기사와 연관된 키워드 조회 시 효율적
    INDEX idx_keyword_id (keyword_id)              -- 특정 키워드와 연관된 기사 조회 시 효율적
) ENGINE=InnoDB;

-- 5. user_feedback 테이블: 사용자 피드백(좋아요/싫어요/읽음 등) 저장
-- 사용자가 특정 기사에 대해 남긴 명시적/암묵적 피드백을 기록합니다.
CREATE TABLE user_feedback (
    id INT AUTO_INCREMENT PRIMARY KEY,             -- 피드백 레코드 고유 ID
    user_id INT NOT NULL,                          -- 피드백을 남긴 사용자 ID
    article_id INT NOT NULL,                       -- 피드백이 발생한 기사 ID
    -- 피드백의 종류를 정의합니다. (예: 'like', 'dislike', 'read', 'click_external_link')
    feedback_type ENUM('like', 'dislike', 'read', 'click_external_link') NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP, -- 피드백 발생 일시

    -- 외래 키 제약 조건: 참조 무결성 유지
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,     -- user 삭제 시 관련 피드백 자동 삭제
    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE, -- article 삭제 시 관련 피드백 자동 삭제

    -- 인덱스 추가: 관련 피드백 조회 성능 최적화
    INDEX idx_user_id (user_id),                   -- 특정 사용자의 피드백 조회 시 효율적
    INDEX idx_article_id (article_id),             -- 특정 기사에 대한 피드백 조회 시 효율적
    INDEX idx_feedback_type (feedback_type)        -- 특정 타입의 피드백 조회 시 효율적
) ENGINE=InnoDB;

-- 6. user_searches 테이블: 사용자 검색어 저장
-- 사용자가 시스템 내에서 검색한 검색어 이력을 기록합니다.
CREATE TABLE user_searches (
    id INT AUTO_INCREMENT PRIMARY KEY,             -- 검색 기록 고유 ID
    user_id INT NOT NULL,                          -- 검색을 수행한 사용자 ID
    search_term VARCHAR(255) NOT NULL,             -- 사용자가 입력한 검색어
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,  -- 검색이 발생한 일시

    -- 외래 키 제약 조건
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE, -- user 삭제 시 관련 검색 기록 자동 삭제

    -- 인덱스 추가: 검색 이력 조회 및 분석 성능 최적화
    INDEX idx_user_id (user_id),                   -- 특정 사용자의 검색 기록 조회 시 효율적
    -- search_term(50)은 검색어의 앞 50자만 인덱싱하여 인덱스 크기 및 성능 최적화
    INDEX idx_search_term (search_term(50)),
    INDEX idx_timestamp (timestamp)                -- 시간대별 검색어 트렌드 분석 시 효율적
) ENGINE=InnoDB;

-- 7. user_article_log 테이블: 사용자 기사 행동 로그(조회, 클릭 등) 저장
-- 사용자가 기사에 대해 수행한 다양한 행동(조회, 외부 링크 클릭 등)을 기록합니다.
CREATE TABLE user_article_log (
    id INT AUTO_INCREMENT PRIMARY KEY,             -- 행동 로그 고유 ID
    user_id INT NOT NULL,                          -- 행동을 수행한 사용자 ID
    article_id INT NOT NULL,                       -- 행동이 발생한 기사 ID
    -- 행동의 종류를 정의합니다. (예: 'view' - 기사 조회, 'click_external_link' - 외부 링크 클릭, 'read' - 기사 완독)
    action_type ENUM('view', 'click_external_link', 'read') NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,  -- 행동이 발생한 일시

    -- 외래 키 제약 조건
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,     -- user 삭제 시 관련 행동 로그 자동 삭제
    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE, -- article 삭제 시 관련 행동 로그 자동 삭제

    -- 인덱스 추가: 사용자 행동 분석 및 추천 모델 학습 데이터 조회 성능 최적화
    INDEX idx_user_id (user_id),                   -- 특정 사용자의 행동 로그 조회 시 효율적
    INDEX idx_article_id (article_id),             -- 특정 기사에 대한 행동 로그 조회 시 효율적
    INDEX idx_action_type (action_type),           -- 특정 행동 타입의 로그 조회 시 효율적
    INDEX idx_timestamp (timestamp)                -- 시간대별 행동 트렌드 분석 시 효율적
) ENGINE=InnoDB;

-- 8. recommended_articles 테이블: 추천 기사 저장
-- 사용자에게 추천된 기사 목록과 관련 메타데이터를 영구적으로 저장합니다.
-- 이는 추천 시스템의 평가, 이력 관리, A/B 테스트 등에 핵심적으로 사용됩니다.
CREATE TABLE recommended_articles (
    id INT AUTO_INCREMENT PRIMARY KEY,               -- 추천 기록 고유 ID
    user_id INT NOT NULL,                            -- 추천을 받은 사용자 ID
    article_id INT NOT NULL,                         -- 추천된 기사 ID
    recommendation_rank INT NOT NULL,                -- 해당 추천 세션 내에서 기사의 추천 순위 (1부터 시작, 1이 가장 높음)
    recommendation_score FLOAT,                      -- 해당 추천 기사에 대한 모델의 내부 점수 (예: 1/rank, 확률 값 등)
    recommended_at DATETIME DEFAULT CURRENT_TIMESTAMP, -- 추천이 사용자에게 생성/제공된 일시 (기본값: 현재 시간)
    batch_id VARCHAR(50) NULL,                       -- 추천이 생성된 배치 작업의 고유 ID (예: 'daily_run_20250611', NULL 허용)
    recommendation_algorithm_version VARCHAR(50) DEFAULT 'keyword_v1', -- 추천을 생성한 알고리즘 또는 모델의 버전 (기본값 'keyword_v1')
    recommendation_session_id VARCHAR(100) NULL,     -- 특정 사용자에게 추천이 생성된 단일 요청/세션의 고유 ID (NULL 허용)

    -- 외래 키 제약 조건
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,     -- user 삭제 시 관련 추천 기록 자동 삭제
    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE, -- article 삭제 시 관련 추천 기록 자동 삭제

    -- 인덱스 추가: 추천 이력 조회 및 분석 성능 최적화
    INDEX idx_user_id (user_id),                     -- 특정 사용자의 모든 추천 기록 조회 시 효율적
    INDEX idx_recommended_at (recommended_at),       -- 특정 기간에 생성된 추천 기록 조회 시 효율적
    INDEX idx_user_batch (user_id, batch_id),        -- 특정 사용자의 특정 배치 추천 기록 조회 시 효율적
    INDEX idx_user_session (user_id, recommendation_session_id), -- 특정 사용자의 특정 세션 추천 기록 조회 시 효율적

    -- 고유 인덱스: 동일 사용자가 동일 기사를 동일 시각에 중복 추천받는 것을 방지
    -- 이는 주로 데이터 무결성을 위한 제약이며, 실제 애플리케이션 로직에서 중복 삽입을 처리해야 합니다.
    UNIQUE INDEX idx_user_article_time (user_id, article_id, recommended_at)
) ENGINE=InnoDB;