-- Runs once on first container start. Creates a separate database for the integration tests.
CREATE DATABASE supportpilot_test OWNER supportpilot;

\connect supportpilot
CREATE EXTENSION IF NOT EXISTS vector;

\connect supportpilot_test
CREATE EXTENSION IF NOT EXISTS vector;
