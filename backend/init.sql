-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Create enum types
DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('admin', 'manager', 'member', 'viewer');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE document_status AS ENUM ('pending', 'processing', 'indexed', 'failed');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;
