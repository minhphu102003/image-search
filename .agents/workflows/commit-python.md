# commit-python workflow

Mục tiêu: chuẩn hoá quy trình commit cho project Python (Beekid Image Search Service), đảm bảo code sạch, test pass, message đúng convention (`feat:`, `fix:`, `chore:`...).

## 0) Kiểm tra thay đổi hiện tại (trước khi tạo branch mới)

```bash
git status
git diff
```

## 2) Đồng bộ môi trường

```bash
uv sync --extra dev
```

## 3) Chạy quality gate trước commit

```bash
uv run pytest
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
```

## 4) Soát nhanh trước khi commit

```bash
git status
```

Checklist nhanh:
- Không commit `.env`, secret, file tạm
- Không có debug code thừa
- Test liên quan đã cập nhật
- Tuân thủ Clean Architecture: domain không depend vào infrastructure

## 5) Commit theo convention

```bash
git add <specific-files>
git commit -m "feat: <mo-ta-ngan-gon>"
```

Ví dụ:
- `feat: add Redis event bus with dead-letter handling`
- `fix: handle empty embedding search results safely`
- `chore: add structlog structured logging`

## 6) Push

```bash
git push -u origin <branch-name>
```

