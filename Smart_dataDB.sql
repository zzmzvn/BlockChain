-- Main database schema
DROP TABLE IF EXISTS polls;
DROP TABLE IF EXISTS votes;
DROP TABLE IF EXISTS results;
DROP TABLE IF EXISTS vote_history;

CREATE TABLE polls (
    id INTEGER PRIMARY KEY,
    title TEXT,
    start_time DATETIME,
    end_time DATETIME,
    options TEXT,
    created_by TEXT,
    poll_hash TEXT,
    status TEXT DEFAULT 'active',
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
    total_votes INTEGER DEFAULT 0,
    is_archived BOOLEAN DEFAULT 0
);

CREATE TABLE votes (
    id INTEGER PRIMARY KEY,
    poll_id INTEGER,
    voter_address TEXT,
    voter_name TEXT,
    option_index INTEGER,
    option_text TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    tx_hash TEXT,
    vote_hash TEXT,
    vote_status TEXT DEFAULT 'valid',
    FOREIGN KEY(poll_id) REFERENCES polls(id)
);

CREATE TABLE results (
    id INTEGER PRIMARY KEY,
    poll_id INTEGER,
    final_results TEXT,
    total_votes INTEGER,
    winner_option TEXT,
    winner_votes INTEGER,
    completion_time DATETIME,
    verification_hash TEXT,
    is_final BOOLEAN DEFAULT 0,
    FOREIGN KEY(poll_id) REFERENCES polls(id)
);

CREATE TABLE vote_history (
    id INTEGER PRIMARY KEY,
    poll_id INTEGER,
    action_type TEXT,
    action_data TEXT,
    action_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    actor_address TEXT,
    tx_hash TEXT,
    FOREIGN KEY(poll_id) REFERENCES polls(id)
);

-- Add status column to polls table if it doesn't exist
ALTER TABLE polls ADD COLUMN status TEXT DEFAULT 'active';

-- Add new columns to polls table
ALTER TABLE polls ADD COLUMN last_updated DATETIME DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE polls ADD COLUMN total_votes INTEGER DEFAULT 0;
ALTER TABLE polls ADD COLUMN is_archived BOOLEAN DEFAULT 0;

-- Add new columns to votes table
ALTER TABLE votes ADD COLUMN vote_status TEXT DEFAULT 'valid';

-- Add new columns to results table
ALTER TABLE results ADD COLUMN verification_hash TEXT;
ALTER TABLE results ADD COLUMN is_final BOOLEAN DEFAULT 0;

-- Create results table if it doesn't exist
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY,
    poll_id INTEGER,
    final_results TEXT,
    total_votes INTEGER,
    winner_option TEXT,
    winner_votes INTEGER,
    completion_time DATETIME,
    FOREIGN KEY(poll_id) REFERENCES polls(id)
);

-- Create vote history table if not exists
CREATE TABLE IF NOT EXISTS vote_history (
    id INTEGER PRIMARY KEY,
    poll_id INTEGER,
    action_type TEXT,
    action_data TEXT,
    action_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    actor_address TEXT,
    tx_hash TEXT,
    FOREIGN KEY(poll_id) REFERENCES polls(id)
);

-- Update existing polls based on end time
UPDATE polls 
SET status = CASE 
    WHEN datetime(end_time) <= datetime('now') THEN 'completed'
    ELSE 'active'
END,
last_updated = datetime('now');

-- Update total votes count for each poll
UPDATE polls
SET total_votes = (
    SELECT COUNT(*) 
    FROM votes 
    WHERE votes.poll_id = polls.id 
    AND votes.vote_status = 'valid'
);

-- Calculate and store final results for completed polls
INSERT OR REPLACE INTO results (
    poll_id, 
    final_results, 
    total_votes, 
    winner_option, 
    winner_votes, 
    completion_time,
    verification_hash,
    is_final
)
SELECT 
    p.id,
    json_group_array(
        json_object(
            'option_text', v.option_text,
            'votes', COUNT(*),
            'percentage', ROUND(CAST(COUNT(*) AS FLOAT) * 100 / p.total_votes, 2)
        )
    ) as final_results,
    p.total_votes,
    first_value(v.option_text) OVER (
        PARTITION BY p.id 
        ORDER BY COUNT(*) DESC
    ) as winner_option,
    first_value(COUNT(*)) OVER (
        PARTITION BY p.id 
        ORDER BY COUNT(*) DESC
    ) as winner_votes,
    datetime('now') as completion_time,
    hex(randomblob(16)) as verification_hash,
    1 as is_final
FROM polls p
JOIN votes v ON p.id = v.poll_id
WHERE p.status = 'completed' 
AND v.vote_status = 'valid'
GROUP BY p.id, v.option_text;

-- Create trigger to update last_updated timestamp
CREATE TRIGGER IF NOT EXISTS update_poll_timestamp
AFTER UPDATE ON polls
BEGIN
    UPDATE polls 
    SET last_updated = datetime('now')
    WHERE id = NEW.id;
END;

-- Create trigger to update total_votes
CREATE TRIGGER IF NOT EXISTS update_total_votes
AFTER INSERT ON votes
BEGIN
    UPDATE polls 
    SET total_votes = (
        SELECT COUNT(*) 
        FROM votes 
        WHERE poll_id = NEW.poll_id 
        AND vote_status = 'valid'
    )
    WHERE id = NEW.poll_id;
END; 