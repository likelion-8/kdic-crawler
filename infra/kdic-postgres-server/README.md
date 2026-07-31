# KDIC PostgreSQL 16 + pgvector development environment

## Purpose

This repository lets every team member reproduce the same local PostgreSQL development environment after cloning it. It contains only environment configuration and helper scripts: no real KDIC data, personal data, database dump, backup, or password is committed.

## Configuration

- PostgreSQL: 16 (the current `pg16` image build is 16.12)
- pgvector: 0.8.1
- Docker image: `pgvector/pgvector:0.8.1-pg16`
- Container: `kdic-postgres16`
- Database: `kdic`
- Initial administrator: `kdic_admin`
- Host port: `5433` (container port `5432`)
- Docker named volume: `kdic-postgres16-data`
- Shared development role: `kdic_team_admin`

The Windows PostgreSQL 18 service remains on port 5432 and is not changed. This project uses port 5433 specifically to avoid that conflict.

The default port binding is `127.0.0.1:5433`. Do not change `POSTGRES_BIND_ADDRESS` to `0.0.0.0` by default, and do not expose port 5433 on public Wi-Fi.

## Requirements

- Git
- Docker Desktop (running)
- PowerShell
- Optional: DBeaver

## Reproduce locally

```powershell
git clone <REPOSITORY_URL>
cd kdic-crawler\infra\kdic-postgres-server

Copy-Item .env.example .env
notepad .env
```

In `.env`, change only the placeholder below to a password you choose. Never commit `.env`.

```dotenv
POSTGRES_PASSWORD=CHANGE_ME
```

Start the container:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

The start script requires an existing `.env`, checks that Docker Desktop is available, starts the compose service, and waits for a healthy container. It never deletes an existing volume.

Verify the environment:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

Verification checks the healthy container, TCP connection to `127.0.0.1:5433`, PostgreSQL major version 16, pgvector 0.8.1, and a temporary vector create/insert/distance-query/drop test. The verification object is temporary and is removed before completion. No password is printed.

## DBeaver connection

Create a PostgreSQL connection with these settings:

| Setting | Value |
| --- | --- |
| Host | `127.0.0.1` |
| Port | `5433` |
| Database | `kdic` |
| Username | `kdic_admin` |
| Password | The password in your own `.env` |

Each developer should use their own local password; do not share the administrator password in source control, chat, or a connection URL.

## Shared team role and member accounts

`kdic_team_admin` is a shared `NOLOGIN` development role. It has the development privileges needed for the `kdic` database and `public` schema, but it is not a superuser and cannot create databases, create roles, replicate, or bypass RLS.

For a newly initialized volume, `db/init/03_team_role.sql` creates this role. Docker runs initialization SQL only on the first creation of `kdic-postgres16-data`. To apply or reapply the same idempotent role and privileges to an existing database without deleting tables or data, run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\configure-team-access.ps1
```

Create one individual account at a time (for example `kdic_member1` through `kdic_member4`):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\create-team-member.ps1
```

The script asks for the account name, which must begin with `kdic_` and use only lowercase letters, digits, and underscores. It asks for the password twice as a `SecureString`, uses SCRAM-SHA-256, adds the account to `kdic_team_admin`, and verifies its login. If the account already exists, it makes no password or attribute change.

For shared schema objects that every team member must be able to alter or drop, connect as a team account and run this before the DDL:

```sql
SET ROLE kdic_team_admin;
```

## Stop and restart

Stop without deleting the container or data volume:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop.ps1
```

Restart later with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

## Full reset (destructive)

`reset.ps1` permanently deletes the `kdic-postgres16-data` Docker volume and every database object in it. It is only for a full local development reset. It is never run automatically and requires you to type `RESET` exactly.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\reset.ps1
```

Back up anything important before using it. Deleted volume data cannot be recovered by this repository.

## What Git contains

Git tracks the Compose definition, `.env.example`, scripts, and idempotent initialization SQL only. It must not track `.env`, real passwords, PostgreSQL Docker volumes, actual database data, dumps, backups, logs, server IP addresses, team passwords, or PostgreSQL URLs containing passwords.

The initialization SQL creates only pgvector, a minimal empty verification table, and the shared role. If all developers need the same application tables or sample data, add reviewed migrations and seed data separately; do not export a live database into this repository.
