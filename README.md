# Auto-CAE

STEP ファイルを読み込んで面クリックで境界条件を設定するだけで、Gmsh + CalculiX によるメッシュ化と線形静解析を自動実行し、結果を 3D ビュー上に色マップ表示する Web アプリ。

## 動作確認済み環境

- Windows 11
- Node.js **v20+** (v24 LTS 確認済み)
- Python **3.11+** (`pyproject.toml` で強制)
- pnpm 9
- CalculiX (ccx) Windows バイナリ

---

## 手動セットアップ手順 (Windows)

以下は実際にゼロから構築した手順です。`scripts\install-deps.ps1` は古い conda 前提の自動化で参考扱い、**実運用は下記の手動手順** を推奨します。

### 1. Node.js と pnpm

1. <https://nodejs.org/> から **Node.js LTS (v20 以降)** の Windows Installer をダウンロードして実行
2. PowerShell を新規に開き、バージョン確認
   ```powershell
   node -v
   ```
3. pnpm を corepack で有効化
   ```powershell
   corepack enable
   corepack prepare pnpm@9.12.0 --activate
   pnpm -v
   ```

### 2. Python 3.11+ と venv

1. <https://www.python.org/downloads/windows/> から **Python 3.11 以上** の installer を入手してインストール
   - インストーラで「Add python.exe to PATH」を必ずチェック
2. リポジトリ直下で仮想環境を作成し有効化
   ```powershell
   cd d:\ML\auto_cae\data
   python -m venv .venv
   .\.venv\Scripts\activate
   python -m pip install --upgrade pip
   ```
3. バックエンド依存をインストール
   ```powershell
   pip install -e apps\api
   ```
   これで `apps/api/pyproject.toml` に書かれた fastapi, uvicorn, pydantic, numpy, **cadquery-ocp** (OCP/OpenCascade), **gmsh**, websockets, python-multipart が入ります。

> **注**: 以前は `pythonocc-core` (conda 専用) を使っていましたが、pip 環境では `cadquery-ocp` (同じ OCP バインディング) に置き換えています。

### 3. CalculiX (ccx) の導入

CalculiX はソルバ本体。Windows バイナリは手動配置が必要です。

1. ~~<http://www.dhondt.de/> または <https://bconverged.com/> から **ccx の Windows 版** (zip) を入手
   bConverged のフリービルドがお手軽 (MKL 同梱)~~
   - PrePoMaxの公式サイト（prepomax.fs.um.si）から、最新版のzipファイルをダウンロードします。
   - zipファイルの中に Solver というフォルダがあり、そこにCalculiXの実行ファイルccx.exeとDLLが入っています。
2. zip を展開して `C:\cae\ccx\` に配置。以下の構成を想定:
   ```
   C:\cae\ccx\
     ccx.exe
     libiomp5md.dll
     mkl_core.2.dll
     mkl_def.2.dll
     mkl_intel_thread.2.dll
     mkl_rt.2.dll
   ```
3. 環境変数 `CCX_PATH` に ccx.exe のフルパスを登録
   ```powershell
   setx CCX_PATH "C:\cae\ccx\ccx.exe"
   ```
   PowerShell を一度閉じて開き直すと反映されます。
4. 単体動作確認 (引数なしで起動し、USAGE が表示されれば OK)
   ```powershell
   & $env:CCX_PATH
   ```

> **トラブル**: `STATUS_DLL_NOT_FOUND (0xC0000135)` で落ちる場合は、同梱の MKL DLL が ccx.exe と同じフォルダにないのが原因。必ず一式を同じフォルダに置くこと。

### 4. フロントエンド依存

```powershell
cd d:\ML\auto_cae\data
pnpm install
```

### 5. 依存診断

venv を有効化した状態で:

```powershell
python scripts\doctor.py
```

`fastapi` `uvicorn` `numpy` `ocp` `gmsh` `ccx` すべて `[ok]` になれば完了です。

---

## 起動

### ワンクリック起動 (推奨)

```powershell
start.bat
```

- ダブルクリック可
- venv を自動で有効化
- API (`http://127.0.0.1:8000`) と Web (`http://127.0.0.1:5173`) を別ウィンドウで起動
- Vite が準備できた時点でブラウザを自動オープン
- 各ウィンドウで Ctrl+C すると個別停止

### 手動起動 (ターミナル2つ)

```powershell
.\.venv\Scripts\activate
pnpm dev:api      # http://127.0.0.1:8000
pnpm dev:web      # http://127.0.0.1:5173
```

---

## 構成

- `apps/web` — React + Vite + R3F フロントエンド
- `apps/api` — FastAPI バックエンド (CAD 読込・メッシュ・解析)
- `scripts/` — 診断スクリプト (`doctor.py`) とセットアップ参考
- `workdir/` — ジョブ成果物 (自動生成、gitignore)

## スタック

- Frontend: React / Vite / TypeScript / react-three-fiber / drei / Tailwind / zustand
- Backend: Python 3.11 / FastAPI / uvicorn / **cadquery-ocp** (OCP) / **gmsh** / CalculiX (ccx)

## 単位系

**mm-N-MPa で統一**。入力時に強制バリデーション。
