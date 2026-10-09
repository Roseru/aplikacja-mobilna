#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname postgres --set ON_ERROR_STOP=1 <<'SQL'
\getenv migrator_password APP_MIGRATOR_PASSWORD
\getenv api_password APP_API_PASSWORD
\getenv worker_password APP_WORKER_PASSWORD
\getenv keycloak_password KEYCLOAK_DB_PASSWORD
CREATE ROLE calorie_app_migrator LOGIN PASSWORD :'migrator_password';
CREATE ROLE calorie_app_api LOGIN PASSWORD :'api_password';
CREATE ROLE calorie_app_worker LOGIN PASSWORD :'worker_password';
CREATE ROLE keycloak LOGIN PASSWORD :'keycloak_password';
CREATE DATABASE calorie_app OWNER calorie_app_migrator;
CREATE DATABASE calorie_test OWNER calorie_app_migrator;
CREATE DATABASE keycloak OWNER keycloak;
REVOKE ALL ON DATABASE calorie_app FROM PUBLIC;
REVOKE ALL ON DATABASE keycloak FROM PUBLIC;
GRANT CONNECT ON DATABASE calorie_app TO calorie_app_api, calorie_app_worker;
\connect calorie_app
SET ROLE calorie_app_migrator;
CREATE SCHEMA app;
GRANT USAGE ON SCHEMA app TO calorie_app_api, calorie_app_worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO calorie_app_api, calorie_app_worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT USAGE, SELECT ON SEQUENCES TO calorie_app_api, calorie_app_worker;
SQL
