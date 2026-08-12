# Tsunagi - IMPLEMENTATION.md

# Project Overview

Tsunagi is an open-source, self-hosted SMS synchronization platform for Android.

Its purpose is to synchronize SMS messages from Android devices to a central server and provide secure APIs for accessing those messages across devices and applications.

The project is designed around synchronization, developer APIs, self-hosting, and multi-device support.

---

# Vision

Provide an open-source alternative for:

- SMS synchronization
- Message archiving
- Device message aggregation
- Real-time message delivery
- Self-hosted messaging infrastructure

---

# Repository Structure

```text
tsunagi/
├── android-app/
├── backend/
├── frontend/
├── docs/
├── deployment/
├── scripts/
├── README.md
├── ROADMAP.md
├── CONTRIBUTING.md
└── IMPLEMENTATION.md
```

---

# Phase 1: MVP

## Objective

Create a working end-to-end message synchronization system.

### Flow

```text
Android Device
      |
      v
 FastAPI Backend
      |
      +------> PostgreSQL
      |
      +------> Redis
```

---

# Android Application

## Technology

- Kotlin
- Jetpack Compose
- Room Database
- Retrofit
- WorkManager

## Modules

### SMS Receiver

Responsibilities:

- Listen for incoming SMS
- Parse SMS metadata
- Store locally
- Queue for synchronization

Data captured:

```json
{
  "id": "uuid",
  "sender": "string",
  "body": "string",
  "received_at": "timestamp"
}
```

---

### Local Storage

Room entities:

#### DeviceEntity

```text
id
device_name
token
created_at
```

#### MessageEntity

```text
id
sender
body
received_at
sync_status
```

---

### Sync Engine

Responsibilities:

- Upload unsynchronized messages
- Retry failed uploads
- Handle connectivity changes
- Maintain sync state

---

### Settings Screen

Features:

- Server URL
- Device name
- API token
- Sync status
- Last synchronization

---

# Backend

## Technology

- FastAPI
- PostgreSQL
- Redis
- SQLAlchemy
- Alembic

---

# Database Design

## devices

```sql
id UUID PRIMARY KEY
name VARCHAR
token VARCHAR
created_at TIMESTAMP
last_seen TIMESTAMP
status BOOLEAN
```

## messages

```sql
id UUID PRIMARY KEY
device_id UUID
sender TEXT
body TEXT
received_at TIMESTAMP
created_at TIMESTAMP
```

## api_keys

```sql
id UUID PRIMARY KEY
name TEXT
key TEXT
created_at TIMESTAMP
```

---

# API Design

## Authentication

Header:

```http
Authorization: Bearer <token>
```

---

## Register Device

```http
POST /api/v1/devices/register
```

Request:

```json
{
  "device_name": "Office Phone"
}
```

Response:

```json
{
  "device_id": "uuid",
  "token": "token"
}
```

---

## Upload Message

```http
POST /api/v1/messages
```

Request:

```json
{
  "id": "uuid",
  "sender": "sender",
  "body": "message body",
  "received_at": "timestamp"
}
```

---

## List Messages

```http
GET /api/v1/messages
```

Filters:

```text
limit
offset
sender
after
before
```

---

## Search Messages

```http
GET /api/v1/messages/search
```

Filters:

```text
query
sender
```

---

## Wait For New Message

```http
GET /api/v1/messages/wait
```

Purpose:

Return newly received messages in real time.

---

# Redis Usage

Redis is used only for:

- Real-time events
- Pub/Sub
- Active subscriptions
- WebSocket delivery

PostgreSQL remains source of truth.

---

# WebSocket Layer

Endpoint:

```text
/ws/messages
```

Features:

- Push new messages
- Device status updates
- Synchronization events

---

# Frontend Dashboard

## Technology

- React
- Vite
- TailwindCSS

## Features

### Inbox

- View messages
- Search messages
- Filter messages

### Devices

- Online devices
- Offline devices
- Last seen

### API Keys

- Create key
- Revoke key

### Statistics

- Messages received
- Active devices
- Storage usage

---

# Security

## Transport

- HTTPS only
- TLS certificates

## Authentication

- Device tokens
- User API keys

## Permissions

- Device scope
- User scope
- Admin scope

---

# Docker Deployment

## Containers

```text
api
postgres
redis
frontend
nginx
```

---

# Development Milestones

## Milestone 1

Android:

- SMS receiver
- Room database

Backend:

- FastAPI
- PostgreSQL

---

## Milestone 2

Android:

- Sync service

Backend:

- Device registration
- Message ingestion

---

## Milestone 3

Backend:

- Search APIs
- Filtering APIs

Frontend:

- Inbox

---

## Milestone 4

Backend:

- Redis pub/sub
- WebSocket support

Frontend:

- Real-time updates

---

## Milestone 5

Multi-device synchronization

---

# Coding Standards

## Android

- MVVM
- Repository pattern
- Dependency Injection

## Backend

- Service layer
- Repository layer
- Typed schemas
- OpenAPI documentation

---

# Non-Goals for MVP

Do not implement:

- MMS
- Desktop client
- Browser extension
- Multi-user organizations
- Message sending
- Contact synchronization

Focus only on reliable message synchronization.

---

# Success Criteria

Version 1.0 is complete when:

- Android device can capture SMS
- Messages are stored locally
- Messages synchronize to server
- Messages are persisted in PostgreSQL
- APIs return synchronized messages
- Dashboard displays messages
- Docker deployment works
- Documentation is complete
