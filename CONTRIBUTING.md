# Contributing to Heritage AI Services

Cảm ơn bạn đã quan tâm đóng góp cho dự án Heritage AI Services!

## Yêu cầu hệ thống

| Công cụ    | Phiên bản  | Mục đích                          |
|------------|------------|-----------------------------------|
| Python     | 3.11 – 3.12| Backend runtime                   |
| Node.js    | 20+        | Frontend (Next.js)                |
| PostgreSQL | 16+        | Database chính (với pgvector)     |
| Redis      | 7+         | Hàng đợi job nền                  |
| MinIO      | Latest     | Lưu trữ file (S3-compatible)      |

## Cài đặt môi trường phát triển

```bash
git clone <your-fork>
cd Heritage-KLTN-AI-Services

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# Chỉnh sửa .env

alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 5055 --reload
```

## Cấu trúc project

```
Heritage-KLTN-AI-Services/
├── app/
│   ├── ai/                 # AI providers (Google, OpenAI, Anthropic)
│   ├── database/           # SQLAlchemy models & DB init
│   ├── mcp/                # MCP server (Claude Desktop integration)
│   ├── routers/            # API route handlers
│   │   └── heritage_bridge.py  # Bridge endpoints cho NestJS BE
│   ├── services/           # Business logic
│   ├── config.py           # Pydantic settings
│   ├── main.py             # FastAPI app entry point
│   └── worker.py           # ARQ background worker
├── alembic/                # Database migrations
├── frontend/               # Admin portal (Next.js)
├── docs/                   # Documentation
├── skills/                 # MCP skill definitions
└── docker-compose.yml
```

## Quy ước commit

Sử dụng [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(api): add bulk delete endpoint for sources
fix(worker): handle empty PDF files during ingestion
docs: update HOW_TO_RUN
refactor(ui): extract reusable component
```

## Tiêu chuẩn code

### Backend (Python)
- Formatter/Linter: Ruff
- Type hints bắt buộc cho parameters và return types
- Tất cả DB/IO operations phải là async

### Frontend (TypeScript)
- Framework: Next.js 15 với App Router
- Không dùng `any` trừ khi thực sự cần thiết

## License

MIT License — xem file [LICENSE](LICENSE).
