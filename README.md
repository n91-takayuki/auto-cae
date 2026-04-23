# Auto-CAE

STEP ファイルを読み込んで面クリックで境界条件を設定するだけで、Gmsh + CalculiX によるメッシュ化と線形静解析を自動実行し、結果を 3D ビュー上に色マップ表示する Web アプリ。

## 機能

- **STEP 読込 + 面別可視化** — OCP (cadquery-ocp) で STEP をロードし面ごとにテッセレーション表示
- **直感的な境界条件設定** — 3D ビューで面をクリック → 右パネルから「拘束 (X/Y/Z 任意)」「荷重 (合力 N / 圧力 MPa, 法線 or XYZ)」を追加。Shift/Ctrl で複数面選択
- **材料プリセット帳** — 構造用鋼 S45C / SUS304 / アルミ A5052 / 銅 C1020 / Ti-6Al-4V + カスタム値編集
- **メッシュサイズ指定** — 細かい〜粗い (0.3×〜3.0×) のスライダ。実 mm 概算をリアルタイム表示
- **複雑形状対応の自動フォールバック** — Frontal-Delaunay → HXT 3D → OCC 補修 (`healShapes` / `removeAllDuplicates` / 退化要素修正) → 二次要素昇格方式 (tet4 → setOrder 2) と段階的に試行し、最初に成功した戦略で続行
- **WebSocket 進捗表示** — `meshing → solving → postprocess → done` をリアルタイムで進捗バー表示
- **結果の 3D 可視化** — von Mises 応力を **jet (青⇄赤)** カラーマップ + 対数変位倍率スライダ (0.01×〜100×、bbox 対角の 5% を auto)
- **メッシュエッジ表示トグル** — 結果メッシュの 3 角形エッジを重ね描き / 非表示切替
- **ジョブ履歴** — プロジェクトごとに過去ジョブを左パネルに一覧表示。完了ジョブのクリックで結果を再表示
- **CSV / INP ダウンロード** — 結果凡例下部から
  - CSV: ノード ID / 座標 / 変位 / 応力テンソル (Sxx〜Sxy) + von Mises (mm-N-MPa)
  - INP: CalculiX 入力ファイル (再実行 / 別ソルバ流用可)
- **エラートースト** — 失敗時に右上に自動通知 (6 秒で消滅、手動 X 閉じも可)
- **ガラス UI** — ダーク + radial gradient 背景 + バックドロップブラー + cyan→violet グラデーションアクセント

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

```
apps/
  web/                              # Vite + React + TS フロントエンド
    src/
      scene/{Viewer,FaceMesh,ResultOverlay}.tsx
      panels/{Toolbar,LeftTree,RightProps,BottomLog,ResultLegend,Toasts}.tsx
      store/useProject.ts           # zustand
      api/client.ts                 # 型付き API クライアント
      data/materials.ts             # 材料プリセット帳
  api/
    app/
      main.py                       # FastAPI エントリ
      cad/step_loader.py            # STEP → 面別三角メッシュ
      mesh/gmsh_runner.py           # gmsh + 6段フォールバック + .inp 生成
      solve/{ccx_runner,pipeline}.py# ccx 実行 + ジョブパイプライン
      frd/parser.py                 # FRD → DISP / STRESS
      routers/{projects,jobs}.py    # REST
      ws/jobs_ws.py                 # WebSocket 進捗
      schemas/{geometry,jobs}.py    # Pydantic
scripts/
  doctor.py                         # 依存診断
workdir/                            # ジョブ成果物 (gitignore)
```

## スタック

- Frontend: React / Vite / TypeScript / react-three-fiber / drei / Tailwind / zustand
- Backend: Python 3.11 / FastAPI / uvicorn / websockets / **cadquery-ocp** (OCP) / **gmsh** / CalculiX (ccx)

## API

| Method | Path | 内容 |
|---|---|---|
| POST | `/api/projects` | STEP アップロード → 面別ジオメトリ生成 |
| GET  | `/api/projects/{id}/geometry` | 面別三角メッシュ取得 |
| POST | `/api/jobs` | 解析ジョブ投入 (BC / 材料 / メッシュサイズ) |
| GET  | `/api/jobs?projectId=...` | プロジェクト別ジョブ履歴 |
| GET  | `/api/jobs/{id}` | ジョブ状態 |
| GET  | `/api/jobs/{id}/result` | 結果サマリ (ノード/変位/von Mises) |
| GET  | `/api/jobs/{id}/csv` | ノード単位 CSV (座標+変位+応力テンソル+von Mises) |
| GET  | `/api/jobs/{id}/inp` | CalculiX 入力ファイル |
| WS   | `/ws/jobs/{id}` | 進捗ストリーム (250ms ポーリング) |

## 単位系

**mm-N-MPa で統一**。入力時に強制バリデーション。

## 操作フロー

1. ツールバー「STEP 読込」でファイルを選択
2. 3D ビューで面をクリック (Shift/Ctrl で追加選択) → 右パネルで拘束 / 荷重を追加
3. 右パネルで材料プリセット選択 + メッシュサイズ調整
4. ツールバー「解析実行」 → 進捗バーで状態を確認
5. 完了すると自動で結果表示に切替 (jet カラーマップ + 変形)
6. 凡例の下部から CSV / INP をダウンロード
7. 左パネル「ジョブ履歴」から過去解析を再表示可
