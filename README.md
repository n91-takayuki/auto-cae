# Auto-CAE

STEP ファイルを読み込んで面クリックで境界条件を設定するだけで、Gmsh + CalculiX によるメッシュ化と線形静解析を自動実行し、結果を 3D ビュー上に色マップ表示する Web アプリ。

## Quick start (Windows)

```powershell
# 1. 依存セットアップ (Miniconda, pythonocc, gmsh, CalculiX, Node, pnpm)
.\scripts\install-deps.ps1

# 2. 依存診断
python scripts\doctor.py

# 3. 開発サーバ起動 (別ターミナル2つ)
conda activate cae
pnpm dev:api      # http://127.0.0.1:8000
pnpm dev:web      # http://127.0.0.1:5173
```

## 構成

- `apps/web` — React + Vite + R3F フロントエンド
- `apps/api` — FastAPI バックエンド(CAD読込・メッシュ・解析)
- `scripts/` — Windows セットアップと診断
- `workdir/` — ジョブ成果物(自動生成、gitignore)

## スタック

Frontend: React / Vite / TypeScript / react-three-fiber / drei / Tailwind / shadcn/ui / zustand
Backend:  Python 3.11 / FastAPI / uvicorn / pythonocc-core / gmsh / CalculiX (ccx)

## 単位系

**mm-N-MPa で統一**。入力時に強制バリデーション。
