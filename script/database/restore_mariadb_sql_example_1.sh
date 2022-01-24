#!/usr/bin/env bash

SQL_PATH=./script/database/mariadb_sql_example_1.sql

# You need to set no password to mysql root user
# SET PASSWORD FOR root@localhost='';
# FLUSH PRIVILEGES;

# Second solution
# ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '';
# FLUSH PRIVILEGES;

echo "Create database and user"
mysql -u root << EOF
DROP DATABASE IF EXISTS mariadb_sql_example_1;
CREATE USER IF NOT EXISTS 'organization'@'localhost' IDENTIFIED BY 'organization';
GRANT ALL PRIVILEGES ON *.* TO 'organization'@'localhost' IDENTIFIED BY 'organization';
FLUSH PRIVILEGES;
CREATE DATABASE mariadb_sql_example_1;
EOF

echo "Fix SQL file"
sed -i "s/'0000-00-00'/NULL/g" ${SQL_PATH}

echo "Import SQL file"
mysql -u organization -porganization mariadb_sql_example_1 < ${SQL_PATH}

echo "Fix SQL in database"
./.venv/bin/python ./script/database/fix_mariadb_sql_example_1.py
