-- 0001: Eklentiler
-- pg_trgm: bulanık (yazım hatasına dayanıklı) arama
-- vector (pgvector): 16 boyutlu özellik vektörleri ve benzerlik
create schema if not exists extensions;
create extension if not exists pg_trgm with schema extensions;
create extension if not exists vector with schema extensions;
create extension if not exists pgcrypto with schema extensions; -- gen_random_uuid() için (Postgres 13+ zaten içerir)
