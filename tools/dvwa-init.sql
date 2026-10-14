-- Fresh local lab only: create/seed without DROP, DELETE or resetting existing data.
USE dvwa;
CREATE TABLE IF NOT EXISTS users (
 user_id INT NOT NULL PRIMARY KEY, first_name VARCHAR(15), last_name VARCHAR(15),
 user VARCHAR(15), password VARCHAR(32), avatar VARCHAR(70), last_login TIMESTAMP,
 failed_login INT DEFAULT 0
);
INSERT IGNORE INTO users VALUES
 (1,'admin','admin','admin',MD5('password'),'/hackable/users/admin.jpg',CURRENT_TIMESTAMP,0),
 (2,'Gordon','Brown','gordonb',MD5('abc123'),'/hackable/users/gordonb.jpg',CURRENT_TIMESTAMP,0);
CREATE TABLE IF NOT EXISTS guestbook (
 comment_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, comment VARCHAR(300), name VARCHAR(100)
);
