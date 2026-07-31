\set ON_ERROR_STOP on

-- This contains no KDIC data. It only proves that the vector type is usable.
CREATE TABLE IF NOT EXISTS public.kdic_pgvector_verify (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    embedding vector(3) NOT NULL
);

COMMENT ON TABLE public.kdic_pgvector_verify IS
    'Minimal pgvector environment verification object; no application data.';
